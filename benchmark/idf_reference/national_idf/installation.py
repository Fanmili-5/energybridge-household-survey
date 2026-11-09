"""Evidence-bound installation ports and legacy-load ownership.

The component assembler supplies sourced physical objects. This layer wires
their named ports, checks the water/air context and rejects unallocated loads.
It cannot create pipe temperatures, airflow coefficients or residual loads.
"""
import copy

from .common import ROOT, digest, read, require
from .idf import Fields, objects
from .source_adapter import equipment_zone, housing_fingerprint, selected, source_file

DEVICES = ('washer', 'dryer', 'dishwasher')
LOADS = {'ElectricEquipment', 'GasEquipment', 'OtherEquipment', 'HotWaterEquipment', 'SteamEquipment'}


def named(rows, kind, name):
    found = [row for row in objects(rows, kind) if row[1].casefold() == name.casefold()]
    require(len(found) == 1, 'INSTALLATION_OBJECT_MISSING_OR_DUPLICATE', [kind, name])
    return found[0]


def component_branches(rows, kind, name):
    return [row for row in objects(rows, 'Branch') if any(row[i:i+2] == [kind, name] for i in range(3, len(row), 4))]


def check_water(rows, fields, device, binding):
    equipment = named(rows, 'WaterUse:Equipment', binding['equipment'])
    require(fields.get(equipment, 'flow_rate_fraction_schedule_name') == binding['flow_schedule'], 'INSTALLATION_WATER_SCHEDULE', device)
    connections = [row for row in objects(rows, 'WaterUse:Connections') if binding['equipment'] in row[11:]]
    require(len(connections) == 1 and sum(row[11:].count(binding['equipment']) for row in connections) == 1,
            'INSTALLATION_WATER_NOT_CONNECTED_EXACTLY_ONCE', device)
    connection = connections[0]
    require(connection[1] == binding['connection'] and binding['mode'] == 'native_plant_connected', 'INSTALLATION_WATER_CONNECTION', device)
    require(fields.get(connection, 'inlet_node_name') and fields.get(connection, 'outlet_node_name'), 'INSTALLATION_WATER_NO_PLANT_NODES')
    require(binding['heater_grid_meter_owner'] == binding['heater']['name']
            and binding['water_use_heating_energy_added_to_grid'] is False, 'INSTALLATION_WATER_ENERGY_DOUBLE_COUNT')
    heater = named(rows, binding['heater']['kind'], binding['heater']['name'])
    demand = component_branches(rows, 'WaterUse:Connections', connection[1])
    supply = component_branches(rows, heater[0], heater[1])
    require(len(demand) == len(supply) == 1, 'INSTALLATION_WATER_BRANCH_AMBIGUOUS')
    loop = named(rows, 'PlantLoop', binding['plant_loop'])
    demand_list = named(rows, 'BranchList', fields.get(loop, 'demand_side_branch_list_name'))
    supply_list = named(rows, 'BranchList', fields.get(loop, 'plant_side_branch_list_name'))
    require(demand[0][1] in demand_list[2:] and supply[0][1] in supply_list[2:], 'INSTALLATION_WATER_DIFFERENT_LOOPS')
    require(binding['cold_supply'] == 'retained_source_Site_WaterMainsTemperature'
            and len(objects(rows, 'Site:WaterMainsTemperature')) == 1
            and not fields.get(connection, 'cold_water_supply_temperature_schedule_name')
            and not fields.get(connection, 'supply_water_storage_tank_name'), 'INSTALLATION_MAINS_NOT_BOUND')
    require(binding['target_temperature'] == 'retained_source_native_inheritance'
            and not fields.get(equipment, 'target_temperature_schedule_name'), 'INSTALLATION_TARGET_TEMPERATURE_NOT_BOUND')
    return {'equipment': equipment[1], 'connection': connection[1], 'plant_loop': loop[1],
            'heater_grid_meter_owner': heater[1], 'demand_branch': demand[0][1], 'supply_branch': supply[0][1],
            'water_use_heating_energy_is_not_an_extra_grid_load': True}


def check_dryer(rows, fields, binding):
    require(binding['technology'] == 'vented_electric_source_model'
            and binding['makeup_mode'] == 'retain_complete_source_EMS_context', 'INSTALLATION_DRYER_AIR_MODEL_UNSUPPORTED')
    equipment = named(rows, 'ElectricEquipment', binding['equipment'])
    zone = equipment_zone(rows, fields.get(equipment, 'zone_or_zonelist_or_space_or_spacelist_name'), fields)
    require(zone == binding['thermal_zone'], 'INSTALLATION_DRYER_ZONE_MISMATCH')
    schedule = fields.get(equipment, 'schedule_name')
    sensor = named(rows, 'EnergyManagementSystem:Sensor', binding['schedule_sensor'])
    require(sensor[2:] == [schedule, 'Schedule Value'], 'INSTALLATION_DRYER_SCHEDULE_NOT_SHARED')
    program = named(rows, 'EnergyManagementSystem:Program', binding['program'])
    require(all(line in program[2:] for line in binding['required_source_statements']), 'INSTALLATION_DRYER_EXHAUST_CHAIN_BROKEN')
    require(any(binding['program'] in row[3:] for row in objects(rows, 'EnergyManagementSystem:ProgramCallingManager')),
            'INSTALLATION_DRYER_EMS_NOT_CALLED')
    for sink in binding['heat_moisture_sinks']:
        actuator = named(rows, 'EnergyManagementSystem:Actuator', sink['actuator'])
        require(actuator[2:] == [sink['equipment'], 'OtherEquipment', 'Power Level'], 'INSTALLATION_DRYER_SINK_ACTUATOR')
        target = named(rows, 'OtherEquipment', sink['equipment'])
        require(equipment_zone(rows, fields.get(target, 'zone_or_zonelist_or_space_or_spacelist_name'), fields) == zone,
                'INSTALLATION_DRYER_SINK_ZONE')
    actuator = named(rows, 'EnergyManagementSystem:Actuator', binding['infiltration_actuator'])
    require(actuator[2:] == [binding['infiltration_object'], 'Zone Infiltration', 'Air Exchange Flow Rate'],
            'INSTALLATION_DRYER_MAKEUP_ACTUATOR')
    named(rows, 'ZoneInfiltration:DesignFlowRate', binding['infiltration_object'])
    require(binding['additional_exhaust_objects'] == [], 'INSTALLATION_DRYER_DUPLICATE_EXHAUST')
    return {'thermal_zone': zone, 'electric_schedule': schedule, 'sensor': sensor[1], 'program': program[1],
            'complete_source_airflow_context_retained': True, 'new_exhaust_coefficient_or_makeup_assumed': False}


def plan_installation(pack_ref, source_model, source_rows, rows, schema_ref, *, root=ROOT):
    pack = read(source_file(pack_ref, root))
    require(pack.get('schema') == 'national_idf.whitegoods_installation.v1'
            and pack.get('target_model') == source_model and pack.get('engine_schema') == schema_ref,
            'INSTALLATION_TARGET_OR_SCHEMA_MISMATCH')
    require(set(pack['devices']) == set(DEVICES) and pack['formal_admitted'] is False, 'INSTALLATION_SCOPE')
    for ref in pack['evidence']:
        source_file(ref, root)
    gaps = copy.deepcopy(pack['unresolved'])
    source_loads = {i for i, row in enumerate(source_rows) if row[0] in LOADS}
    claims = pack['legacy_loads']
    require(len({row['object']['index'] for row in claims}) == len(claims)
            and {row['object']['index'] for row in claims} == source_loads, 'INSTALLATION_LEGACY_INVENTORY_INCOMPLETE')
    for item in claims:
        selected(source_rows, item['object'])
        require(item['disposition'] in ('replace_owned_device', 'retain_source_context', 'unresolved_aggregate'),
                'INSTALLATION_LEGACY_DISPOSITION')
        require(item['evidence'], 'INSTALLATION_LEGACY_EVIDENCE_MISSING')
        for ref in item['evidence']:
            source_file(ref, root)
        if item['disposition'] == 'unresolved_aggregate':
            gaps.append({'code': 'INSTALLATION_AGGREGATE_LOAD_OWNERSHIP_UNKNOWN', 'object': item['object']})
    for device in ('washer', 'dishwasher'):
        if pack['water'][device] is None:
            gaps.append({'code': 'INSTALLATION_WATER_PORT_MISSING', 'device': device})
    if pack['dryer_air'] is None:
        gaps.append({'code': 'INSTALLATION_DRYER_AIR_PATH_MISSING'})
    result = {'schema': 'national_idf.whitegoods_installation_plan.v1', 'pack': pack_ref,
        'id': pack['id'], 'scope': pack['scope'], 'ready': not gaps, 'gaps': gaps, 'modifications': [],
        'legacy_loads': claims, 'water': None, 'dryer_air': None, 'formal_admitted': False,
        'physical_values_invented': False, 'new_model_rows': copy.deepcopy(rows)}
    if gaps:
        require(not pack['port_edits'], 'INCOMPLETE_INSTALLATION_MUST_NOT_EDIT')
        return result
    fields = Fields(source_file(schema_ref, root))
    after, seen = result['new_model_rows'], set()
    for edit in pack['port_edits']:
        before = selected(source_rows, edit['object'])
        candidates = [i for i, row in enumerate(after) if row == before]
        # Group edits by source object, then apply only declared string ports.
        if edit['object']['index'] not in seen:
            require(len(candidates) == 1, 'INSTALLATION_CONFLICT_WITH_OTHER_EDITS', edit['object'])
            seen.add(edit['object']['index'])
            index = candidates[0]
            result['modifications'].append({'source_object': edit['object'], 'before': before[:], 'after': after[index],
                                            'reason': 'Explicit installation name/reference ports; source numeric fields unchanged'})
        else:
            change = next(v for v in result['modifications'] if v['source_object'] == edit['object'])
            index = next(i for i, row in enumerate(after) if row is change['after'])
        row, position = after[index], edit['field_index']
        require(type(position) is int and 1 <= position < len(row) and row[position] == edit['before']
                and isinstance(edit['after'], str) and edit['after'].strip(), 'INSTALLATION_PORT_PRECONDITION')
        role = edit['role']
        allowed = (role == 'object_name' and row[0] in ('ElectricEquipment', 'WaterUse:Equipment') and position == 1
            or role == 'water_connection_reference' and row[0] == 'WaterUse:Connections' and position >= 11
            or role == 'reporting_key' and row[0] == 'Output:Variable' and position == 1
                and row[2].startswith(('Electric Equipment ', 'Water Use Equipment ')))
        require(allowed, 'INSTALLATION_PHYSICAL_PARAMETER_EDIT_FORBIDDEN', edit)
        row[position] = edit['after']
    require(housing_fingerprint(after) == housing_fingerprint(rows), 'INSTALLATION_HOUSING_CHANGED')
    # A kept context row includes its exact values and referenced network. The
    # complete source EMS is guarded, not extracted as a portable flow scalar.
    for guard in pack['retained_context_guards']:
        old = selected(source_rows, guard)
        require(after.count(old) == 1, 'INSTALLATION_CONTEXT_GUARD_CHANGED', guard)
    # The source air balance already contains mechanical exhaust. Neither a
    # second ventilation object nor an extra EMS path may be added alongside it.
    airflow = lambda data: sorted(digest(row) for row in data if row[0].startswith(
        ('ZoneInfiltration:', 'ZoneVentilation:', 'ZoneMixing', 'ZoneCrossMixing', 'AirflowNetwork:',
         'EnergyManagementSystem:')))
    require(airflow(after) == airflow(source_rows), 'INSTALLATION_ADDITIONAL_OR_CHANGED_AIRFLOW_PATH')
    # Account for every old load, including zero auxiliaries and unrelated
    # background. An unlisted additional load cannot bypass the ownership map.
    expected_loads = [change['after'] if (change := next((c for c in result['modifications']
        if c['source_object'] == item['object']), None)) else selected(source_rows, item['object']) for item in claims]
    require(sorted(map(digest, expected_loads)) == sorted(digest(row) for row in after if row[0] in LOADS),
            'INSTALLATION_UNALLOCATED_OR_DUPLICATE_LOAD')
    names = [(r[0].casefold(), r[1].casefold()) for r in after if fields.names(r[0]) and fields.names(r[0])[0] == 'name']
    require(len(names) == len(set(names)), 'INSTALLATION_DUPLICATE_NAMED_LOAD_OR_OBJECT')
    for device, definition in pack['devices'].items():
        equipment = named(after, 'ElectricEquipment', definition['equipment'])
        require(fields.get(equipment, 'schedule_name') == definition['schedule'], 'INSTALLATION_ELECTRIC_SCHEDULE', device)
        old = selected(source_rows, definition['replaced_equipment'])
        require(not any(r[1].casefold() == old[1].casefold() for r in objects(after, 'ElectricEquipment')),
                'INSTALLATION_OLD_DEVICE_NOT_RETIRED', device)
        require(any(c['object'] == definition['replaced_equipment'] and c['disposition'] == 'replace_owned_device'
                    and c['owner'] == device for c in claims), 'INSTALLATION_LOAD_OWNER_NOT_BOUND', device)
    result['water'] = {device: check_water(after, fields, device, pack['water'][device]) for device in ('washer', 'dishwasher')}
    result['dryer_air'] = check_dryer(after, fields, pack['dryer_air'])
    result['result_model_rows_sha256'] = digest(after)
    return result


def assembly_installation(spec, manifest, source_rows, rows, *, root=ROOT):
    refs = [spec['components'][device].get('installation_pack') for device in DEVICES]
    if not any(refs):
        return None
    require(all(refs) and all(ref == refs[0] for ref in refs), 'INSTALLATION_PACK_NOT_JOINTLY_BOUND')
    return plan_installation(refs[0], manifest['model'], source_rows, rows, spec['engine_schema'], root=root)


def installation_receipt(plan):
    return None if plan is None else {key: value for key, value in plan.items() if key != 'new_model_rows'}
