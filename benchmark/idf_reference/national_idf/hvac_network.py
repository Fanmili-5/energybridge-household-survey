"""Source-closed ductless HVAC import with explicit room and observer ports.

Public source numeric fields are retained, including declared autosizing rules.
This checks installation topology; it never certifies target capacity selection.
"""
import copy
import re

from .common import ROOT, digest, read, require
from .idf import Fields, objects, parse
from .source_adapter import housing_fingerprint, protected, selected, selector, source_file
from .supply_network import ZONE_REFS, items


def node_field(name, meta):
    return meta.get('type') == 'string' and 'node' in name and name.endswith(('_name', '_names'))


def empty_enclosure(rows, target, pack, *, root):
    """No dummy ideal system is required to install into a declared bare source."""
    scope = read(source_file(pack['source_operation_replacement'], root))
    require(scope.get('schema') == 'national_idf.native_operation_replacement.v1'
        and scope.get('target_model') == pack['target_model']
        and scope.get('source_operational_reproduction') is False
        and scope.get('formal_admitted') is False and scope.get('excluded_source_tables'),
        'HVAC_EMPTY_SOURCE_OPERATION_NOT_DECLARED')
    for evidence in scope['excluded_source_tables'].values(): source_file(evidence, root)
    require(not pack['retire_objects'] and not pack['rewrite_source_observers']
        and not pack.get('retained_ideal_context'), 'HVAC_EMPTY_SOURCE_CANNOT_RETIRE_OBJECTS')
    prefixes = ('airloophvac', 'zonehvac:', 'hvactemplate:', 'coil:', 'fan:', 'airterminal:',
        'zonecontrol:', 'thermostatsetpoint:', 'boiler:', 'district', 'evaporativecooler:')
    require(not any(r[0].casefold().startswith(prefixes) for r in target+rows),
        'HVAC_EMPTY_ENCLOSURE_CONTAINS_OLD_SYSTEM')


def closure(rows, schema, roots):
    refs = {}
    for i, row in enumerate(rows):
        for label in schema['properties'][row[0]].get('name', {}).get('reference', []):
            refs.setdefault((label, row[1].casefold()), set()).add(i)
    chosen = {item['index'] for item in roots}
    for item in roots: selected(rows, item)
    ems = {row[1].casefold(): i for i, row in enumerate(rows) if row[0].startswith('EnergyManagementSystem:')
        and row[0] != 'EnergyManagementSystem:ProgramCallingManager'}
    while True:
        previous = chosen.copy()
        for i in list(chosen):
            require(not protected(rows[i]), 'HVAC_CLOSURE_REACHED_HOUSING', rows[i][:2])
            for p, name, meta in items(rows[i], schema):
                value, labels = rows[i][p], meta.get('object_list', [])
                if not value or not labels or set(labels) & ZONE_REFS: continue
                if value in schema['properties']: continue  # IDD object type, not an instance
                found = set().union(*(refs.get((label, value.casefold()), set()) for label in labels))
                require(len(found) == 1, 'HVAC_REFERENCE_NOT_CLOSED', [rows[i][:2], name, value, labels])
                chosen |= found
        names = {rows[i][1].casefold() for i in chosen}
        nodes = {rows[i][p].casefold() for i in chosen for p, name, meta in items(rows[i], schema)
                 if node_field(name, meta) and rows[i][p]}
        for i, row in enumerate(rows):
            if row[0] == 'NodeList' and row[1].casefold() in nodes: chosen.add(i)
            if row[0] in ('AirLoopHVAC:SupplyPath', 'AirLoopHVAC:ReturnPath') and any(
                    row[p].casefold() in nodes for p, name, meta in items(row, schema) if node_field(name, meta)):
                chosen.add(i)
            if row[0] == 'Sizing:System' and row[1].casefold() in names: chosen.add(i)
            if row[0] == 'EnergyManagementSystem:Actuator' and row[2].casefold() in names: chosen.add(i)
        actuators = [rows[i][1] for i in chosen if rows[i][0] == 'EnergyManagementSystem:Actuator']
        for i, row in enumerate(rows):
            if row[0] in ('EnergyManagementSystem:Program', 'EnergyManagementSystem:Subroutine') and any(
                    re.search(r'\bset\s+'+re.escape(name)+r'\s*=', ' '.join(row[2:]), re.I) for name in actuators):
                chosen.add(i)
        text = ' '.join(' '.join(rows[i][2:]) for i in chosen if rows[i][0] in (
            'EnergyManagementSystem:Program', 'EnergyManagementSystem:Subroutine'))
        for symbol, i in ems.items():
            if re.search(r'\b'+re.escape(symbol)+r'\b', text, re.I): chosen.add(i)
        programs = {rows[i][1].casefold() for i in chosen if rows[i][0] == 'EnergyManagementSystem:Program'}
        for i, row in enumerate(rows):
            if row[0] == 'EnergyManagementSystem:ProgramCallingManager' and any(v.casefold() in programs for v in row[3:]):
                require(all(v.casefold() in programs for v in row[3:]), 'HVAC_SHARED_PROGRAM_MANAGER_REQUIRES_REVIEW')
                chosen.add(i)
        if chosen == previous: break
    require(not any(rows[i][0] in ('ZoneInfiltration:DesignFlowRate', 'ZoneVentilation:DesignFlowRate',
        'Site:WaterMainsTemperature', 'Sizing:Zone', 'ZoneHVAC:IdealLoadsAirSystem') for i in chosen), 'HVAC_FOREIGN_HOUSING_BOUNDARY_IMPORTED')
    return sorted(chosen)


def materialize(pack, schema, source):
    indices = closure(source, schema, pack['roots'])
    require([selector(source, i) for i in indices] == pack['source_objects'], 'HVAC_SOURCE_CLOSURE_CHANGED')
    prefix = pack['prefix']; require(re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*', prefix), 'HVAC_NAMESPACE')
    names = {source[i][1].casefold(): prefix+source[i][1] for i in indices if schema['properties'][source[i][0]].get('name')}
    nodes = {source[i][p].casefold(): prefix+source[i][p] for i in indices for p, name, meta in items(source[i], schema)
             if node_field(name, meta) and source[i][p]}
    erls = {source[i][1].casefold(): prefix+source[i][1] for i in indices if source[i][0].startswith('EnergyManagementSystem:')}
    pattern = re.compile(r'\b('+'|'.join(map(re.escape, sorted(erls, key=len, reverse=True)))+r')\b', re.I)
    def rewrite(before, *, external=False):
        row = copy.deepcopy(before)
        for p, name, meta in items(before, schema):
            value = before[p]; key = value.casefold()
            if not value: continue
            if not external and p == 1 and schema['properties'][row[0]].get('name'): row[p] = names[key]
            elif row[0] in ('EnergyManagementSystem:Program', 'EnergyManagementSystem:Subroutine') and p >= 2:
                row[p] = pattern.sub(lambda m: erls[m[0].casefold()], value)
            elif set(meta.get('object_list', [])) & ZONE_REFS and not external:
                require(key in {v.casefold() for v in pack['source_thermal_ports']}, 'HVAC_UNKNOWN_THERMAL_PORT', value)
                row[p] = pack['installation_zone']
            elif row[0].startswith('EnergyManagementSystem:') and p == 2:
                row[p] = names.get(key, nodes.get(key, erls.get(key, value)))
            elif name == 'ems_program_or_subroutine_name' and key in erls:
                row[p] = erls[key]
            elif row[0] == 'Output:Variable' and p == 1: row[p] = names.get(key, value)
            elif node_field(name, meta) and key in nodes: row[p] = nodes[key]
            elif meta.get('object_list') and key in names: row[p] = names[key]
        return row
    additions = [rewrite(source[i]) for i in indices]
    require(not any(row[0] == 'Schedule:File' for row in additions), 'HVAC_EXTERNAL_SCHEDULE_REQUIRES_DEPENDENCY_PACK')
    return indices, additions, rewrite, {'objects': names, 'nodes': nodes, 'EMS_symbols': erls}


def apply(rows, pack_ref, schema_ref, *, root=ROOT):
    pack = read(source_file(pack_ref, root)); schema = read(source_file(schema_ref, root))
    require(pack.get('schema') == 'national_idf.sourced_ductless_hvac.v1', 'HVAC_PACK_SCHEMA')
    source = parse(source_file(pack['source_model'], root).read_text())
    target = parse(source_file(pack['target_model'], root).read_text())
    require(housing_fingerprint(rows) == housing_fingerprint(target), 'HVAC_TARGET_HOUSING_NOT_BOUND')
    zone = pack['installation_zone']; require(len([r for r in objects(rows, 'Zone') if r[1] == zone]) == 1, 'HVAC_TARGET_ZONE')
    indices, additions, rewrite, maps = materialize(pack, schema, source)
    retired = [selected(target, entry) for entry in pack['retire_objects']]
    result = copy.deepcopy(rows)
    for before in retired:
        require(result.count(before) == 1, 'HVAC_OLD_OBJECT_NOT_RETIRED_EXACTLY_ONCE', before[:2]); result.remove(before)
    observers = []
    if pack['rewrite_source_observers']:
        require(pack['source_model'] == pack['target_model'], 'HVAC_FOREIGN_OBSERVER_REWRITE')
        require({entry['index'] for entry in pack['retire_objects']} == set(indices), 'HVAC_SOURCE_RETIREMENT_INCOMPLETE')
        revised = []
        for before in result:
            after = rewrite(before, external=True)
            if after != before: observers.append({'before': before, 'after': after})
            revised.append(after)
        result = revised
    else:
        if pack.get('retained_ideal_context'):
            from .retained_context import source_scope
            context, _, groups = source_scope(pack['retained_ideal_context'],
                Fields(source_file(schema_ref, root)), root=root)
            require(context['source_model'] == pack['target_model'] and
                    context['target_zone'] == zone and retired == groups[zone.casefold()],
                    'HVAC_SCOPED_TARGET_RETIREMENT_NOT_COMPLETE')
        elif pack.get('source_operation_replacement'):
            empty_enclosure(rows, target, pack, root=root)
        else:
            require({r[0] for r in retired} == {'ZoneHVAC:IdealLoadsAirSystem', 'ZoneHVAC:EquipmentList',
                'ZoneHVAC:EquipmentConnections', 'ZoneControl:Thermostat', 'ThermostatSetpoint:DualSetpoint'}
                and len(retired) == 5, 'HVAC_TARGET_IDEAL_GROUP_NOT_COMPLETE')
    result += additions
    retained = None
    if pack.get('retained_ideal_context'):
        from .retained_context import verify_retained
        retained = verify_retained(result, pack['retained_ideal_context'],
            Fields(source_file(schema_ref, root)), root=root)
    else:
        require(not objects(result, 'ZoneHVAC:IdealLoadsAirSystem'), 'HVAC_OLD_IDEAL_LOAD_REMAINS')
    require(housing_fingerprint(result) == housing_fingerprint(rows), 'HVAC_IMPORT_CHANGED_HOUSING')
    fields = Fields(source_file(schema_ref, root)); keys = [(r[0], r[1].casefold()) for r in result
        if fields.names(r[0]) and fields.names(r[0])[0] == 'name']
    require(len(keys) == len(set(keys)), 'HVAC_NAMESPACE_COLLISION')
    connections = [r for r in objects(result, 'ZoneHVAC:EquipmentConnections') if r[1] == zone]
    require(len(connections) == 1, 'HVAC_ZONE_CONNECTED_MORE_THAN_ONCE')
    changes = [{'source': selector(source, i), 'before': source[i], 'after': after} for i, after in zip(indices, additions)]
    return result, {'schema': 'national_idf.hvac_network_import_receipt.v1', 'pack': pack_ref,
        'source_object_count': len(additions), 'source_objects': changes, 'retired_objects': retired,
        'source_observer_rewrites': observers, 'namespace_maps': maps, 'target_zone': zone,
        'structural_installation_complete': True, 'numeric_source_parameters_changed': False,
        'foreign_infiltration_or_housing_imported': False,
        'old_ideal_loads_removed': not objects(result, 'ZoneHVAC:IdealLoadsAirSystem'),
        **({'target_old_ideal_loads_removed': True} if retained is not None else {}),
        **({'retained_ideal_context': retained} if retained is not None else {}),
        'independent_target_load_sizing_approved': False, 'formal_admitted': False}


def apply_group(rows, pack_refs, schema_ref, *, root=ROOT):
    """Install independent closed systems into one explicitly empty enclosure.

    Each port is first checked against the same unmodified enclosure. This
    avoids weakening the old-system check to allow arbitrary existing HVAC.
    This is installation validation, never a capacity or service certificate.
    """
    require(isinstance(pack_refs, list) and pack_refs, 'HVAC_GROUP_EMPTY')
    packs = [read(source_file(ref, root)) for ref in pack_refs]
    require(all(p.get('source_operation_replacement') and not p['retire_objects']
        and not p['rewrite_source_observers'] and not p.get('retained_ideal_context')
        for p in packs), 'HVAC_GROUP_REQUIRES_EMPTY_SOURCE')
    require(all(p['target_model'] == packs[0]['target_model']
        and p['source_operation_replacement'] == packs[0]['source_operation_replacement']
        for p in packs), 'HVAC_GROUP_TARGET_CONFLICT')
    zones = [p['installation_zone'].casefold() for p in packs]
    prefixes = [p['prefix'].casefold() for p in packs]
    require(len(set(zones)) == len(zones), 'HVAC_GROUP_ZONE_REPEATED')
    require(len(set(prefixes)) == len(prefixes), 'HVAC_GROUP_NAMESPACE_REPEATED')
    result, receipts = copy.deepcopy(rows), []
    for ref in pack_refs:
        installed, receipt = apply(rows, ref, schema_ref, root=root)
        require(installed[:len(rows)] == rows, 'HVAC_GROUP_MUTATED_SOURCE')
        result.extend(installed[len(rows):]); receipts.append(receipt)
    fields = Fields(source_file(schema_ref, root))
    keys = [(r[0].casefold(), r[1].casefold()) for r in result
        if fields.names(r[0]) and fields.names(r[0])[0] == 'name']
    require(len(keys) == len(set(keys)), 'HVAC_NAMESPACE_COLLISION')
    connections = [r[1].casefold() for r in objects(result, 'ZoneHVAC:EquipmentConnections')]
    require(sorted(connections) == sorted(zones), 'HVAC_GROUP_CONNECTION_SCOPE')
    require(housing_fingerprint(result) == housing_fingerprint(rows), 'HVAC_IMPORT_CHANGED_HOUSING')
    return result, receipts
