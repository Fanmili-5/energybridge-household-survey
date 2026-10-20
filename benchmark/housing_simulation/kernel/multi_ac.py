"""Co-located native PTHPs: per-device coil gates, one physical zone.

EnergyPlus has one zone thermostat. Its envelope requests the strongest active
heating/cooling setpoint; each unit's own thermostat independently gates its
coils. Native SequentialLoad dispatch and all component performance curves stay
in force. This is an explicit cycling/reference control approximation, not a
calibrated manufacturer controller. No rooms, devices or requested plans change.
"""

HYSTERESIS_C = .2


def thermostat_state(temperature, heating, cooling, available, prior=(0, 0)):
    """Symmetric 0.2 C switching band; pure reference used in regression tests."""
    if not available:
        return 0, 0
    half = HYSTERESIS_C / 2
    heat, cool = prior
    if temperature <= heating-half: heat = 1
    elif temperature >= heating+half: heat = 0
    if temperature >= cooling+half: cool = 1
    elif temperature <= cooling-half: cool = 0
    return heat, cool


def add_controls(rows, room, packages, prefix, fields, put):
    """Gate the actual DX/supplemental coils, preserving fan/permission schedules."""
    sensor = prefix+'_temperature'
    rows.append(['EnergyManagementSystem:Sensor',sensor,room,'Zone Mean Air Temperature'])
    lines=[];initial=[];mappings=[]
    for p in packages:
        name=p['schedule_names']['available']+'_independent'
        variables={key:name+'_'+key for key in ('available','heat_sp','cool_sp')}
        for key,var in variables.items():
            rows.append(['EnergyManagementSystem:Sensor',var,p['schedule_names'][key],'Schedule Value'])
        gates={key:name+'_'+key for key in ('heating','cooling')}
        for key,gate in gates.items():
            rows.extend([['Schedule:Constant',gate,'any',0],
                         ['EnergyManagementSystem:Actuator',gate+'_act',gate,'Schedule:Constant','Schedule Value'],
                         ['Output:Variable',gate,'Schedule Value','Timestep','report_target_and_recovery']])
            initial.append('SET '+gate+'_act = 0')
        for r in rows:
            if r[1] not in {x[1] for x in p['rows']}:
                continue
            kind=r[0]
            if kind.startswith('Coil:Heating:'):
                put(r,'availability_schedule_name',gates['heating'])
            elif kind.startswith('Coil:Cooling:'):
                put(r,'availability_schedule_name',gates['cooling'])
        h,c=gates['heating']+'_act',gates['cooling']+'_act'
        av,hs,cs=(variables[k] for k in ('available','heat_sp','cool_sp'))
        lines.extend([f'IF {av} < 0.5',f'SET {h} = 0',f'SET {c} = 0','ELSE',
            f'IF {sensor} <= {hs} - 0.1',f'SET {h} = 1',f'ELSEIF {sensor} >= {hs} + 0.1',f'SET {h} = 0','ENDIF',
            f'IF {sensor} >= {cs} + 0.1',f'SET {c} = 1',f'ELSEIF {sensor} <= {cs} - 0.1',f'SET {c} = 0','ENDIF','ENDIF'])
        mappings.append({'asset_id':p['asset_id'],'coil_gate_schedules':gates,
                         'requested_schedules':p['schedule_names']})
    rows.extend([['EnergyManagementSystem:Program',prefix+'_initialize',*initial],
                 ['EnergyManagementSystem:ProgramCallingManager',prefix+'_initialization','BeginNewEnvironment',prefix+'_initialize'],
                 ['EnergyManagementSystem:Program',prefix+'_control',*lines],
                 ['EnergyManagementSystem:ProgramCallingManager',prefix+'_controller','BeginTimestepBeforePredictor',prefix+'_control']])
    return {'room_id':room,'model':'per_device_coil_thermostat_gates_native_sequential_load',
            'zone_thermostat':'active_max_heating_min_cooling_envelope',
            'hysteresis_C':HYSTERESIS_C,'sampled_at':'BeginTimestepBeforePredictor',
            'fan_requests_preserved':True,'device_priority':[p['asset_id'] for p in packages],
            'limitations':'ideal mixed room;fixed native dispatch priority;sampled cycling control,not manufacturer calibration',
            'devices':mappings}
