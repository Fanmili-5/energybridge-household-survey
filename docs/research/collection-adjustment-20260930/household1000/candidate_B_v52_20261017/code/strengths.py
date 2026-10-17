"""Construct B from A and the existing request objects, using native device units.

Device grades are independently assigned before B. Four input vectors rotate
each device's own grade; vector number is not an overall household severity.
"""
import collections, math
from common import *
from proposals import operation_slot, command_signature

AC_DELTA_C = (.5, 1., 1.5, 2.)       # Exact EB onboarding anchors.
AC_EXPOSURE_MIN = (20, 30, 60, 90)  # Benchmark exposure grid; VPP windows30-90min.
PREHEAT_LEAD_MIN = (20, 40, 60, 120)
PROGRAM_CYCLE_MULTIPLIER = (.25, .5, 1., 2.)
TANK_DELTA_C = (1., 2., 3., 5.)      # Benchmark grid, not an EB published scale.
EV_SLACK_FRACTION = (.25, .5, 1., 1.25)
FAMILY_ORDER = ('washer', 'dishwasher', 'ac', 'water_heater', 'ev')


def ceil10(value): return int(math.ceil(value / 10 - 1e-9) * 10)
def sign(value): return 1 if value > 1e-8 else -1 if value < -1e-8 else 0


def controller_key(device):
    family = next(x for x in FAMILY_ORDER if x in device['types'])
    return family + ':' + (device['room_id'] if family == 'ac' else device['asset_id'])


def definitions(w, source):
    assets = {x['asset_id']: x for x in w['parameter_pack']['devices']}
    actual = source['classification']['actual_actions']
    touched = {x['asset_id'] for key in ('program_changes', 'manual_operation_changes', 'control_changes') for x in actual[key]}
    result = {}
    for aid in sorted(touched):
        d = assets[aid]; key = controller_key(d)
        if key not in result:
            result[key] = {'controller_key': key, 'family': key.split(':')[0], 'asset_ids': [],
                           'base_grade_index': rank('independent-device-strength-v52', source['case_id'], key) % 4}
        result[key]['asset_ids'].append(aid)
    return result


def grade_table(family, grade, device):
    if family == 'ac':
        return {'setpoint_delta_C': AC_DELTA_C[grade], 'exposure_cap_min': AC_EXPOSURE_MIN[grade],
                'preconditioning_lead_cap_min': PREHEAT_LEAD_MIN[grade],
                'basis': 'EB_onboarding_0.5_1_1.5_2C;benchmark_time_grid;actual_deadband_cap_reported'}
    if family == 'water_heater':
        return {'target_delta_C': TANK_DELTA_C[grade], 'exposure_cap_min': AC_EXPOSURE_MIN[grade],
                'preheat_lead_cap_min': PREHEAT_LEAD_MIN[grade],
                'request_target_floor_C': 45., 'request_target_ceiling_C': min(65., device['parameters']['maximum_C']),
                'basis': 'EB_preheat_and_temperature_interface;45C_EB_request_floor;bound_hardware_ceiling;benchmark_1_2_3_5C_grid'}
    if family in ('washer', 'dishwasher'):
        p = device['parameters']; duration = p.get(family, p)['duration_h'] * 60
        return {'program_duration_min': duration, 'cycle_multiplier': PROGRAM_CYCLE_MULTIPLIER[grade],
                'requested_shift_min': ceil10(duration * PROGRAM_CYCLE_MULTIPLIER[grade]),
                'basis': 'EB_noninterruptible_task_duration_and_service_window;benchmark_quarter_half_one_two_cycles',
                'linked_auto_dryer_has_no_independent_start_request': 'dryer' in device['types']}
    return {'connection_slack_removal_fraction': EV_SLACK_FRACTION[grade], 'minimum_request_step_min': 10,
            'basis': 'EB_required_energy_charger_efficiency_departure_slack;benchmark_fraction_grid;1.25_is_explicit_stress_request'}


def selected_levels(defs, vector=0):
    return {key: (d['base_grade_index'] + vector) % 4 for key, d in defs.items()}


def same_control(a, b):
    keys = ('start_min', 'end_min', 'stop_at_target_soc')
    return all(a[k] == b[k] for k in keys)


def control_reference(plan, kind, aid, lo, hi):
    xs = [x for x in plan['controls'] if x['kind'] == kind and x['asset_id'] == aid]
    return min(xs, key=lambda x: (0 if x['start_min'] <= lo < x['end_min'] else
                                 min(abs(x['start_min']-lo), abs(x['end_min']-hi)), x['start_min']))


def patch_control(plan, source, kind, aid, lo, hi, values):
    """Replace a real interval, preserving A outside it and existing need IDs."""
    old = [x for x in plan['controls'] if x['kind'] == kind and x['asset_id'] == aid and
           overlap((lo, hi), (x['start_min'], x['end_min']))]
    for x in old:
        plan['controls'].remove(x)
        if x['start_min'] < lo: plan['controls'].append({**x, 'end_min': lo})
        if hi < x['end_min']: plan['controls'].append({**x, 'start_min': hi})
    if values is None: return
    bounds = sorted({lo, hi} | {max(lo, min(hi, x[k])) for x in old for k in ('start_min','end_min')})
    for a, b in zip(bounds, bounds[1:]):
        ref = next((x for x in old if x['start_min'] <= a < b <= x['end_min']), None)
        if ref is None: ref = control_reference(source['B'], kind, aid, a, b)
        x = {**ref, 'start_min': a, 'end_min': b, **values}
        if kind == 'ac_setpoint':
            x.update(value_C=x['cooling_setpoint_C'],
                     heating_and_cooling_deadband_C=x['cooling_setpoint_C']-x['heating_setpoint_C'])
        plan['controls'].append(x)


def control_blocks(source):
    groups = collections.defaultdict(list)
    for x in source['classification']['actual_actions']['control_changes']:
        if x['kind'] == 'ev_charge_window': continue
        phase = 'add_permission' if x['A'] is None else 'withdraw_permission' if x['B'] is None else x['control_request_direction']
        groups[x['kind'], x['asset_id'], phase].append(x)
    blocks = []
    for (kind, aid, phase), rows in sorted(groups.items()):
        pending = []
        for x in sorted(rows, key=lambda x: x['start_min']):
            if pending and x['start_min'] != pending[-1]['end_min']:
                blocks.append((kind, aid, phase, pending)); pending=[]
            pending.append(x)
        if pending: blocks.append((kind, aid, phase, pending))
    return blocks


def build_controls(w, source, plan, defs, levels):
    assets = {x['asset_id']: x for x in w['parameter_pack']['devices']}
    for kind, aid, phase, rows in control_blocks(source):
        device = assets[aid]; key = controller_key(device); family = defs[key]['family']
        table = grade_table(family, levels[key], device)
        lo, hi = rows[0]['start_min'], rows[-1]['end_min']
        if phase == 'add_permission':
            cap = table['preconditioning_lead_cap_min'] if family == 'ac' else table['preheat_lead_cap_min']
            lo = max(lo, hi-cap)  # Keep preparation close to the existing service/event.
        else: hi = min(hi, lo+table['exposure_cap_min'])
        for row in rows:
            a, b = max(lo, row['start_min']), min(hi, row['end_min'])
            if a >= b: continue
            av, bv = row['A'], row['B']
            if phase == 'withdraw_permission': values = None
            elif family == 'ac':
                if av is None:
                    z=source['thermal_control_context'][aid]
                    av={'heating_setpoint_C':z['usual_heating_setpoint_C'],
                        'cooling_setpoint_C':z['usual_cooling_setpoint_C'], 'fan_operating_mode':bv['fan_operating_mode']}
                    dh,dc=1,-1
                else:
                    dh=sign(bv['heating_setpoint_C']-av['heating_setpoint_C'])
                    dc=sign(bv['cooling_setpoint_C']-av['cooling_setpoint_C'])
                delta=table['setpoint_delta_C'];narrowing=int(dh>0)+int(dc<0)
                if narrowing:delta=min(delta,max(0.,(av['cooling_setpoint_C']-av['heating_setpoint_C']-2)/narrowing))
                values={'heating_setpoint_C':av['heating_setpoint_C']+dh*delta,
                        'cooling_setpoint_C':av['cooling_setpoint_C']+dc*delta,
                        'fan_operating_mode':bv['fan_operating_mode']}
            else:
                if av is None:
                    ref=control_reference(source['A'],kind,aid,a,b);value=ref['value_C']
                else:value=av['value_C']+sign(bv['value_C']-av['value_C'])*table['target_delta_C']
                values={'value_C':max(table['request_target_floor_C'], min(table['request_target_ceiling_C'],value))}
            patch_control(plan,source,kind,aid,a,b,values)


def build_programs(w, source, plan, defs, levels):
    assets={x['asset_id']:x for x in w['parameter_pack']['devices']}
    oldtasks={x['task_id']:x for x in source['B']['tasks']};covered=set()
    for a in source['A']['tasks']:
        if a['kind']=='dryer' or a['start_min']==oldtasks[a['task_id']]['start_min']:continue
        aid=a['asset_id'];nid=a['need_id'];covered.add(nid);d=assets[aid];key=controller_key(d)
        table=grade_table(a['kind'],levels[key],d);delta=sign(oldtasks[a['task_id']]['start_min']-a['start_min'])*table['requested_shift_min']
        oldload=next(o for o in source['A']['operations']if o['kind']=='load'and o['need_id']==nid)
        load=next(o for o in plan['operations']if o['kind']=='load'and o['need_id']==nid)
        unload=next(o for o in plan['operations']if o['kind']=='unload'and o['need_id']==nid)
        src_load=next(o for o in source['B']['operations']if o['operation_id']==load['operation_id'])
        handling=src_load['start_min']!=oldload['start_min'];need=next(n for n in source['needs_A']if n['need_id']==nid)
        minimum=max(DECISION-a['start_min'],need['release_min']-oldload['start_min'],DECISION-oldload['start_min']) if handling else max(DECISION,oldload['end_min'])-a['start_min']
        delta=max(delta,minimum)
        group=[t for t in plan['tasks']if t['need_id']in(nid,nid+':dry')]
        for t in group:t['start_min']+=delta;t['end_min']+=delta
        finish=max(t['end_min']for t in group)
        if handling:
            for o in(load,unload):o['start_min']+=delta;o['end_min']+=delta
        else:
            probe={**unload,'_bath_room':w['activity_contract']['room_map']['bath']}
            slot=operation_slot(source,plan,probe,finish,min(need['deadline_min'],finish+need['maximum_retrieval_wait_min']+10,4320),max(finish,unload['start_min']))
            if slot is None:slot=finish
            unload['start_min']=slot;unload['end_min']=slot+10
    # A source request can change an existing retrieval without shifting its program.
    source_ops={x['operation_id']:x for x in source['B']['operations']}
    for a in source['A']['operations']:
        if a['kind'].startswith('EV_') or a['need_id']in covered:continue
        src=source_ops[a['operation_id']]
        if src['start_min']==a['start_min']:continue
        d=assets[a['asset_id']];key=controller_key(d);family=defs[key]['family']
        table=grade_table(family,levels[key],d);delta=sign(src['start_min']-a['start_min'])*table['requested_shift_min']
        need=next(n for n in source['needs_A']if n['need_id']==a['need_id'])
        minimum=max(DECISION,need['release_min'])if a['kind']=='load'else max(DECISION,max(t['end_min']for t in plan['tasks']if t['need_id']in(a['need_id'],a['need_id']+':dry')))
        target=max(minimum,a['start_min']+delta)
        op=next(o for o in plan['operations']if o['operation_id']==a['operation_id']);op['start_min']=target;op['end_min']=target+10


def build_ev(w, source, plan, defs, levels):
    assets={x['asset_id']:x for x in w['parameter_pack']['devices']}
    source_controls={(x['asset_id'],x['need_id'],x['end_min']):x for x in source['B']['controls']if x['kind']=='ev_charge_window'}
    for a in source['A']['controls']:
        if a['kind']!='ev_charge_window':continue
        xs=[x for x in source['B']['controls']if x['kind']=='ev_charge_window'and x['asset_id']==a['asset_id']and x['need_id']==a['need_id']]
        src=next((x for x in xs if x['end_min']==a['end_min']),None)
        if src is None:
            # Selected controls are single-window in the frozen generator.
            if len(xs)!=1:raise ValueError('AMBIGUOUS_EV_SOURCE_WINDOW')
            src=xs[0]
        if same_control(a,src):continue
        d=assets[a['asset_id']];key=controller_key(d);p=d['parameters'];table=grade_table('ev',levels[key],d)
        full=ceil10(a['battery_energy_kWh']/(p['charger_kw']*p['efficiency'])*60)
        slack=max(0,a['end_min']-a['start_min']-full)
        pressure=max(10,ceil10(max(10,slack)*table['connection_slack_removal_fraction']))
        delay=src['start_min']!=a['start_min'];cut=src['end_min']!=a['end_min']
        shift=ceil10(pressure/2)if delay and cut else pressure if delay else 0
        removed=pressure-shift if cut else 0
        start=min(a['end_min']-10,a['start_min']+shift);end=max(start+10,a['end_min']-removed)
        if end>a['end_min']:end=a['end_min']
        x=next(x for x in plan['controls']if x==a)
        available=(end-start)/60*p['charger_kw']*p['efficiency'];delivered=min(a['battery_energy_kWh'],available)
        steps=math.ceil(delivered/(p['charger_kw']*p['efficiency'])*6-1e-10)
        x.update(start_min=start,end_min=end,actual_charge_end_min=start+steps*10,
            last_step_power_fraction=max(0,min(1,delivered/(p['charger_kw']*p['efficiency'])*6-(steps-1))),
            requested_battery_energy_kWh=a['battery_energy_kWh'],projected_battery_energy_kWh=delivered,
            grid_energy_kWh=delivered/p['efficiency'],projection_basis='same_connection_A_state_fixed_charger_upper_bound;not_continuous_B_SOC')


def construct(w, source, defs, vector=0):
    if not defs:return copy.deepcopy(source['B'])
    levels=selected_levels(defs,vector);plan=copy.deepcopy(source['A'])
    build_programs(w,source,plan,defs,levels)
    build_controls(w,source,plan,defs,levels)
    build_ev(w,source,plan,defs,levels)
    plan['controls'].sort(key=lambda x:(x['kind'],x['asset_id'],x['start_min'],x['end_min']))
    plan['changed_controls']=[x for x in plan['controls']if x not in source['A']['controls']]
    return plan
