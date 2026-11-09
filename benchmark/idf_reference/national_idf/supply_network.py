"""Import a dependency-closed public water loop with explicit thermal ports.

Numeric source fields are copied verbatim. Node/object identifiers, zone ports
and file locations are the only rewrites; the local inlet is supplied separately.
"""
import copy
import re

from .common import ROOT, digest, read, require, sha
from .idf import Fields, objects, parse
from .parameter_pack import field_definitions
from .source_adapter import equipment_zone, housing_fingerprint, selector, source_file

ZONE_REFS = {'ZoneNames', 'SpaceNames', 'ZoneAndZoneListNames', 'ZoneAndZoneListAndSpaceAndSpaceListNames'}


def node_field(name, meta):
    # Stratified tank node counts and node loss coefficients are numeric, not
    # graph identifiers. Only actual IDD string node ports may be renamed.
    return 'node' in name and meta.get('type') == 'string' and name.endswith('_name')


def items(row, schema):
    fixed, extension = field_definitions(schema, row[0])
    for position in range(1, len(row)):
        if position <= len(fixed): name, meta = fixed[position-1]
        else:
            require(extension, 'SUPPLY_EXTRA_FIELD_WITHOUT_SCHEMA', row[0])
            name, meta = extension[(position-len(fixed)-1) % len(extension)]
        yield position, name, meta


def closure(rows, schema, loop_name, auxiliaries):
    refs = {}
    for i, row in enumerate(rows):
        definition = schema['properties'][row[0]]
        for label in definition.get('name', {}).get('reference', []):
            refs.setdefault((label, row[1].casefold()), set()).add(i)
    seeds = [i for i, row in enumerate(rows) if row[:2] == ['PlantLoop', loop_name]]
    require(len(seeds) == 1, 'SUPPLY_LOOP_NOT_UNIQUE')
    seeds += [i for i, row in enumerate(rows) if row[0] == 'Sizing:Plant' and row[1] == loop_name]
    for name in auxiliaries:
        found = [i for i, row in enumerate(rows) if row[:2] == ['OtherEquipment', name]]
        require(len(found) == 1, 'SUPPLY_AUXILIARY_MISSING', name); seeds += found
    chosen = set(seeds)
    while True:
        previous = chosen.copy()
        for i in list(chosen):
            for position, name, meta in items(rows[i], schema):
                value = rows[i][position]
                labels = meta.get('object_list', [])
                if not value or not labels or set(labels) & ZONE_REFS: continue
                if any(label.endswith('Types') for label in labels) and value in schema['properties']: continue
                found = set().union(*(refs.get((label, value.casefold()), set()) for label in labels))
                require(len(found) == 1, 'SUPPLY_REFERENCE_NOT_UNIQUE_OR_CLOSED', [rows[i][0], name, value, labels])
                chosen |= found
        names = {rows[i][1].casefold() for i in chosen}
        nodes = {rows[i][p].casefold() for i in chosen for p, name, meta in items(rows[i], schema)
                 if node_field(name, meta) and rows[i][p]}
        for i, row in enumerate(rows):
            if row[0] == 'WaterHeater:Sizing' and row[1].casefold() in names:
                chosen.add(i)
            if row[0].startswith('SetpointManager:'):
                if any(row[p].casefold() in nodes for p, name, meta in items(row, schema) if node_field(name, meta)): chosen.add(i)
            if row[0] in ('EnergyManagementSystem:Sensor', 'EnergyManagementSystem:InternalVariable', 'EnergyManagementSystem:Actuator'):
                if len(row) > 2 and row[2].casefold() in names: chosen.add(i)
        variables = {rows[i][1] for i in chosen if rows[i][0].startswith('EnergyManagementSystem:')}
        for i, row in enumerate(rows):
            if row[0] in ('EnergyManagementSystem:Program', 'EnergyManagementSystem:Subroutine'):
                if any(re.search(r'\b'+re.escape(variable)+r'\b', ' '.join(row[2:]), re.I) for variable in variables): chosen.add(i)
        text = ' '.join(' '.join(rows[i][2:]) for i in chosen if rows[i][0] in ('EnergyManagementSystem:Program', 'EnergyManagementSystem:Subroutine'))
        for i, row in enumerate(rows):
            if row[0].startswith('EnergyManagementSystem:') and any(re.search(r'\b'+re.escape(v)+r'\b', text, re.I) for v in row[1:2]): chosen.add(i)
            if row[0] == 'EnergyManagementSystem:ProgramCallingManager' and any(p.casefold() in names for p in row[3:]): chosen.add(i)
        if chosen == previous: break
    require(not any(rows[i][0] in ('Zone', 'Space', 'Building', 'Site:WaterMainsTemperature') for i in chosen), 'SUPPLY_IMPORTED_HOUSING_OR_FOREIGN_MAINS')
    return sorted(chosen)


def materialize(pack_ref, schema_ref, *, root=ROOT):
    pack = read(source_file(pack_ref, root)); schema = read(source_file(schema_ref, root))
    require(pack.get('schema') == 'national_idf.sourced_supply_network.v1', 'SUPPLY_PACK_SCHEMA')
    rows = parse(source_file(pack['source_model'], root).read_text())
    chosen = closure(rows, schema, pack['source_loop'], pack['source_auxiliary_equipment'])
    require([selector(rows, i) for i in chosen] == pack['source_objects'], 'SUPPLY_DEPENDENCY_CLOSURE_CHANGED')
    prefix = pack['prefix']; require(re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*', prefix), 'SUPPLY_NAMESPACE')
    names = {rows[i][1].casefold(): prefix+rows[i][1] for i in chosen if
             schema['properties'][rows[i][0]].get('name')}
    nodes = {rows[i][p].casefold(): prefix+rows[i][p] for i in chosen for p, name, meta in items(rows[i], schema)
             if node_field(name, meta) and rows[i][p]}
    erls = {rows[i][1].casefold(): prefix+rows[i][1] for i in chosen if rows[i][0].startswith('EnergyManagementSystem:')}
    token = re.compile(r'\b('+'|'.join(map(re.escape, sorted(erls, key=len, reverse=True)))+r')\b', re.I) if erls else None
    result, changes, dependencies = [], [], {}
    for i in chosen:
        before, row = rows[i], copy.deepcopy(rows[i])
        for p, name, meta in items(before, schema):
            value = before[p]
            if not value: continue
            key = value.casefold()
            if p == 1 and schema['properties'][row[0]].get('name'):
                row[p] = names[key]
            elif row[0] in ('EnergyManagementSystem:Program', 'EnergyManagementSystem:Subroutine'):
                row[p] = token.sub(lambda m: erls[m[0].casefold()], value) if token else value
            elif row[0] == 'Schedule:File' and name == 'file_name':
                file = (source_file(pack['source_model'], root).parent / value).resolve()
                require(file.is_relative_to(root.resolve()) and file.is_file(), 'SUPPLY_SCHEDULE_FILE_MISSING')
                ref = {'path': str(file.relative_to(root)), 'sha256': sha(file)}
                target = 'assets/'+ref['sha256']+file.suffix
                row[p] = target; dependencies[target] = {'source': ref, 'output_path': target}
            elif set(meta.get('object_list', [])) & ZONE_REFS:
                require(key in {v.casefold() for v in pack['source_thermal_ports']}, 'SUPPLY_UNBOUND_THERMAL_PORT', value)
                row[p] = pack['installation_zone']
            elif row[0].startswith('EnergyManagementSystem:') and p == 2 and key in names:
                row[p] = names[key]
            elif row[0].startswith('EnergyManagementSystem:') and p == 2 and key in {v.casefold() for v in pack['source_thermal_ports']}:
                row[p] = pack['installation_zone']
            elif node_field(name, meta) and key in nodes: row[p] = nodes[key]
            elif meta.get('object_list') and key in names: row[p] = names[key]
        changes.append({'source': selector(rows, i), 'before': before, 'after': row})
        result.append(row)
    return pack, result, changes, list(dependencies.values())


def apply(rows, pack_ref, schema_ref, *, root=ROOT):
    pack, additions, changes, dependencies = materialize(pack_ref, schema_ref, root=root)
    fields = Fields(source_file(schema_ref, root))
    require(equipment_zone(rows, pack['installation_zone'], fields) == pack['installation_zone'], 'SUPPLY_TARGET_ZONE_MISSING')
    require(len(objects(rows, 'Site:WaterMainsTemperature')) == 1, 'SUPPLY_LOCAL_INLET_NOT_BOUND')
    require(not any(row[0] in ('WaterUse:Equipment', 'WaterUse:Connections', 'WaterHeater:Mixed', 'WaterHeater:Stratified') for row in rows),
            'SUPPLY_TARGET_HAS_UNRETIRED_WATER_SYSTEM')
    result = copy.deepcopy(rows)+additions
    require(housing_fingerprint(result) == housing_fingerprint(rows), 'SUPPLY_CHANGED_HOUSING')
    names = [(row[0], row[1].casefold()) for row in result if fields.names(row[0]) and fields.names(row[0])[0] == 'name']
    require(len(names) == len(set(names)), 'SUPPLY_NAMESPACE_COLLISION')
    tanks = objects(additions, 'WaterHeater:Stratified')
    require(len(tanks) == 1 and not objects(additions, 'WaterHeater:Mixed'), 'SUPPLY_SOURCE_NOT_SINGLE_STRATIFIED_TANK')
    connections = objects(additions, 'WaterUse:Connections'); uses = objects(additions, 'WaterUse:Equipment')
    for use in uses:
        require(sum(row[11:].count(use[1]) for row in connections) == 1, 'SUPPLY_DEMAND_NOT_CONNECTED_ONCE')
    require(pack['water_use_heating_energy_added_to_grid'] is False and pack['Python_heater_electricity_added'] is False,
            'SUPPLY_DOUBLE_ELECTRICITY_ACCOUNT')
    return result, {'schema': 'national_idf.supply_import_receipt.v1', 'pack': pack_ref,
        'source_loop': pack['source_loop'], 'target_loop': pack['prefix']+pack['source_loop'],
        'source_objects': changes, 'source_object_count': len(additions), 'water_use_objects': [row[1] for row in uses],
        'native_tank': tanks[0][1], 'heater_grid_owner': 'native tank + native parasitics; adjustment sink separately attributed',
        'water_use_heating_energy_is_nonadditive_thermal_output': True, 'Python_heater_electricity_added': False,
        'source_adiabatic_pipe_and_zero_pump_simplifications_retained': True, 'formal_admitted': False}, dependencies
