"""Instantiate the pinned official PTHP topology; no household data imports."""
import copy

from .pipeline import HERE, digest, read


def field_object(kind, values, fields):
    names = fields[kind]
    unknown = set(values) - set(names)
    if unknown:
        raise ValueError(f'unknown {kind} fields: {sorted(unknown)}')
    last = max(names.index(k) for k in values)
    return [kind] + [values.get(k, '') for k in names[:last + 1]]


def heat_pump(device, fields):
    """Scale Zone1 from the official example, preserving its performance curves."""
    source = read(HERE / 'resources/heat_pump.json')
    prefix = 'hp_' + digest(device['asset_id'])[:12]
    schedules = {k: prefix + '_' + k for k in ('available', 'fan_mode', 'heat_sp', 'cool_sp')}
    rows = copy.deepcopy(source['rows'])
    names = {r[1]: prefix + '_' + r[1] for r in rows}
    # Node names are not all standalone objects; namespace every Zone1 node too.
    for row in rows:
        for i, value in enumerate(row[1:], 1):
            if value in names:
                row[i] = names[value]
            elif isinstance(value, str) and value.startswith('Zone1'):
                row[i] = prefix + '_' + value
    def put(row, key, value):
        i = fields[row[0]].index(key) + 1
        row.extend([''] * max(0, i + 1 - len(row)))
        row[i] = value
    p = device['parameters']
    for r in rows:
        k = r[0]
        if k.startswith('Curve:'):
            continue
        if 'availability_schedule_name' in fields[k]:
            put(r, 'availability_schedule_name', schedules['available'] if k in ('ZoneHVAC:PackagedTerminalHeatPump', 'Fan:SystemModel') else 'always')
        if k == 'ZoneHVAC:PackagedTerminalHeatPump':
            for key in ('cooling_supply_air_flow_rate', 'heating_supply_air_flow_rate', 'no_load_supply_air_flow_rate'):
                put(r, key, p['air_flow_m3_s'])
            for key in ('cooling_outdoor_air_flow_rate', 'heating_outdoor_air_flow_rate', 'no_load_outdoor_air_flow_rate'):
                put(r, key, 0)
            put(r, 'supply_air_fan_operating_mode_schedule_name', schedules['fan_mode'])
        elif k == 'Fan:SystemModel':
            put(r, 'design_maximum_air_flow_rate', p['air_flow_m3_s'])
            put(r, 'design_electric_power_consumption', p['fan_power_W'])
            put(r, 'design_pressure_rise', p['fan_pressure_Pa'])
        elif k == 'Coil:Cooling:DX:SingleSpeed':
            for key, value in {'gross_rated_total_cooling_capacity': p['cooling_capacity_W'],
                               'gross_rated_cooling_cop': p['cooling_COP'],
                               'gross_rated_sensible_heat_ratio': p['sensible_heat_ratio'],
                               'rated_air_flow_rate': p['air_flow_m3_s']}.items():
                put(r, key, value)
        elif k == 'Coil:Heating:DX:SingleSpeed':
            for key, value in {'gross_rated_heating_capacity': p['heating_capacity_W'],
                               'gross_rated_heating_cop': p['heating_COP'],
                               'rated_air_flow_rate': p['air_flow_m3_s'],
                               'minimum_outdoor_dry_bulb_temperature_for_compressor_operation': -15,
                               'crankcase_heater_capacity': 0,
                               'resistive_defrost_heater_capacity': p['defrost_capacity_W']}.items():
                put(r, key, value)
        elif k == 'Coil:Heating:Electric':
            put(r, 'nominal_capacity', p['supplemental_capacity_W'])
    unit = next(r for r in rows if r[0] == 'ZoneHVAC:PackagedTerminalHeatPump')
    # Zero dedicated outdoor-air flow: dwelling infiltration/exhaust is modeled separately.
    rows.append(['OutdoorAir:NodeList', prefix + '_Zone1PTHPOAInNode'])
    return {'asset_id': device['asset_id'], 'room_id': device['room_id'], 'rows': rows,
            'equipment_name': unit[1], 'zone_return_node': prefix + '_Zone1PTHPAirInletNode',
            'zone_supply_node': prefix + '_Zone1PTHPAirOutletNode', 'schedule_names': schedules,
            'source_idf_sha256': source['source_idf_sha256']}


def standalone_tank(device, obj, peak):
    """Direct hot-outlet draw, with no invented mixing valve or plant pump."""
    p = device['parameters']
    return obj('WaterHeater:Stratified', {
        'name': 'reference_storage_tank', 'end_use_subcategory': 'target_electric_hot_water',
        'tank_volume': p['volume_m3'], 'tank_height': p['height_m'], 'tank_shape': 'VerticalCylinder',
        'maximum_temperature_limit': p['maximum_C'], 'heater_priority_control': 'MasterSlave',
        'heater_1_setpoint_temperature_schedule_name': 'tank_target',
        'heater_1_deadband_temperature_difference': p['deadband_C'],
        'heater_1_capacity': p['heater_capacity_W'], 'heater_1_height': p['height_m'] * .1,
        'heater_2_setpoint_temperature_schedule_name': 'tank_target',
        'heater_2_capacity': 0, 'heater_2_height': 0,
        'heater_fuel_type': 'Electricity', 'heater_thermal_efficiency': p['efficiency'],
        'ambient_temperature_indicator': 'Zone', 'ambient_temperature_zone_name': device['room_id'],
        'uniform_skin_loss_coefficient_per_unit_area_to_ambient_temperature': p['skin_loss_W_m2K'],
        'skin_loss_fraction_to_zone': 1, 'peak_use_flow_rate': peak,
        'use_flow_rate_fraction_schedule_name': 'water_draw', 'use_side_effectiveness': 1,
        'use_side_inlet_height': 0, 'use_side_outlet_height': p['height_m'],
        'number_of_nodes': p['number_of_nodes']})
