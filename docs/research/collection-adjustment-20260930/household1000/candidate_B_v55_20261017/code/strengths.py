"""Construct B from A and the existing request objects, using native device units.

Device grades are independently assigned before B. Four input vectors rotate
each device's own grade; vector number is not an overall household severity.
"""
import collections, math
from common import *
from proposals import operation_slot, command_signature
from planning import contexts, ev_window, program_delta, FACTORS

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
                           'base_grade_index': rank('independent-device-strength-v53', source['case_id'], key) % 4}
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
    return {'required_charge_time_multiplier': (.25,.5,1.,2.)[grade], 'minimum_request_step_min': 10,
            'reserve_budget_factor_is_separate_from_draft_grade': True,'event_target_scale':FACTORS[grade],
            'basis':'EB_required_energy_and_real_connection;benchmark_time_dose_and_independent_reserve_budget'}


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


def thermal_values(source,kind,aid,lo,hi,av,load_direction,axis,table):
    ref=av or control_reference(source['A'],kind,aid,lo,hi)
    if kind=='tank_setpoint':
        value=ref['value_C']+(1 if load_direction=='up'else -1)*table['target_delta_C']
        return {'value_C':max(table['request_target_floor_C'],min(table['request_target_ceiling_C'],value))}
    heat=ref['heating_setpoint_C'];cool=ref['cooling_setpoint_C'];delta=table['setpoint_delta_C'];up=load_direction=='up'
    if axis=='heating':heat+=delta if up else -delta;cool=max(cool,heat+2.)
    else:cool+=-delta if up else delta;heat=min(heat,cool-2.)
    return {'heating_setpoint_C':heat,'cooling_setpoint_C':cool,'fan_operating_mode':ref.get('fan_operating_mode',0)}


def build_controls(w,source,plan,defs,levels):
    """Form prepare/event/restore requests once per actual thermal controller.

    A preparation interval always has its own direction. A future down request
    cannot accidentally turn its storage phase into the down action itself.
    All patches are bounded; the original A controller resumes afterward.
    """
    assets={x['asset_id']:x for x in w['parameter_pack']['devices']};ctxs=contexts(w,source,defs)
    grouped=collections.defaultdict(list)
    for kind,aid,phase,rows in control_blocks(source):grouped[kind,aid].append((phase,rows))
    phases=[]
    for (kind,aid),blocks in sorted(grouped.items()):
        d=assets[aid];key=controller_key(d);family=defs[key]['family'];ctx=ctxs[key];e=ctx['event'];table=grade_table(family,levels[key],d)
        behavior=ctx['behavior'];wanted=e['direction']
        if behavior=='opposing_request':wanted='up'if wanted=='down'else'down'
        has_prepare=any(phase=='add_permission'for phase,_ in blocks)
        has_withdraw=any(phase=='withdraw_permission'for phase,_ in blocks)
        routine=[x for x in source['A']['controls']if x['kind']==kind and x['asset_id']==aid]
        event_start=e['start_min'];event_end=e['end_min'];axis=ctx['thermal_axis_reference']
        def apply_phase(lo,hi,phase,load_direction,withdraw=False,allow_add=False):
            lo=max(DECISION,lo);hi=min(1920,hi)
            if lo>=hi:return
            bounds=sorted({lo,hi}|{max(lo,min(hi,x[k]))for x in routine for k in('start_min','end_min')})
            for aa,bb in zip(bounds,bounds[1:]):
                av=next((x for x in routine if x['start_min']<=aa<bb<=x['end_min']),None)
                if av is None and (withdraw or not allow_add):continue
                if withdraw:
                    rest=sum(max(0,min(x['end_min'],1920)-max(x['start_min'],480))for x in plan['controls']if x['kind']==kind and x['asset_id']==aid)
                    if rest<=bb-aa:bb=max(aa,bb-10)
                    if aa>=bb:continue
                    values=None
                else:values=thermal_values(source,kind,aid,aa,bb,av,load_direction,axis,table)
                patch_control(plan,source,kind,aid,aa,bb,values)
                phases.append({'controller_key':key,'asset_id':aid,'kind':kind,'phase':phase,'start_min':aa,'end_min':bb,'load_direction_requested':load_direction,'selected_event_id':e['event_id'],'event_interval_min':[event_start,event_end],'behavior':behavior,'A_permission_present':av is not None,'withdraw_permission':withdraw,'restore_A_at_min':hi,'B_physical_success_required':False})
        # Storage before a down event raises thermal energy (heat/tank up or
        # cooling down). An up event uses the extra permission inside its window.
        if has_prepare and wanted=='down':
            lead=table['preconditioning_lead_cap_min']if family=='ac'else table['preheat_lead_cap_min']
            apply_phase(event_start-lead,event_start,'preparation','up',allow_add=True)
        cap=table['exposure_cap_min']
        if behavior in('normal_response','partial_response','opposing_request'):
            reference_kw=max(.1,d.get('max_electric_kw',e['target_kw']))
            cap=min(cap,max(10,ceil10((event_end-event_start)*min(1.,e['target_kw']/reference_kw*FACTORS[levels[key]]))))
        # Anchor down exposure on A active time, rather than always the first
        # ten minutes of an event whose heater/coil may activate much later.
        st=e.get('native_A_event_state',{});profile=st.get('timestep_profile',{})
        keys=('heater_W',)if family=='water_heater'else('heat_J','supplement_J','cool_J')
        active=sorted({t for k in keys for t,v in profile.get(k,[])if v>1 and event_start<=t<event_end})
        start=active[0]if wanted=='down'and active else event_start
        end=min(event_end,start+cap)
        event_permissions=[(max(start,x['start_min']),min(end,x['end_min']))for x in routine if max(start,x['start_min'])<min(end,x['end_min'])]
        if event_permissions or (has_prepare and wanted=='up'):
            apply_phase(start,end,'event',wanted,withdraw=has_withdraw and wanted=='down',allow_add=has_prepare and wanted=='up')
        else:
            # The explicit limited/pressure request may still be ineffective or
            # uncomfortable. Use its given original service interval, not noise.
            original=sorted((x['start_min'],x['end_min'])for phase,rs in blocks for x in rs)
            lo,hi=next(((a,z)for a,z in original if z>DECISION),(start,end))
            apply_phase(max(lo,DECISION),min(hi,max(lo,DECISION)+cap),'service_boundary',wanted,withdraw=has_withdraw and wanted=='down',allow_add=has_prepare)
    plan['thermal_phase_requests']=phases


def build_programs(w, source, plan, defs, levels):
    assets={x['asset_id']:x for x in w['parameter_pack']['devices']};ctxs=contexts(w,source,defs)
    oldtasks={x['task_id']:x for x in source['B']['tasks']};covered=set()
    for a in source['A']['tasks']:
        if a['kind']=='dryer' or a['start_min']==oldtasks[a['task_id']]['start_min']:continue
        aid=a['asset_id'];nid=a['need_id'];covered.add(nid);d=assets[aid];key=controller_key(d)
        table=grade_table(a['kind'],levels[key],d);delta=sign(oldtasks[a['task_id']]['start_min']-a['start_min'])*table['requested_shift_min']
        delta=program_delta(source,a,table['requested_shift_min'],delta,ctxs[key],d['parameters'])
        oldload=next(o for o in source['A']['operations']if o['kind']=='load'and o['need_id']==nid)
        load=next(o for o in plan['operations']if o['kind']=='load'and o['need_id']==nid)
        unload=next(o for o in plan['operations']if o['kind']=='unload'and o['need_id']==nid)
        src_load=next(o for o in source['B']['operations']if o['operation_id']==load['operation_id'])
        handling=src_load['start_min']!=oldload['start_min'];need=next(n for n in source['needs_A']if n['need_id']==nid)
        minimum=max(DECISION-a['start_min'],need['release_min']-oldload['start_min'],DECISION-oldload['start_min']) if handling else max(DECISION,oldload['end_min'])-a['start_min']
        delta=max(delta,minimum)
        group=[t for t in plan['tasks']if t['need_id']in(nid,nid+':dry')]
        ctx=ctxs[key];e=ctx['event'];direction=e['direction']
        if ctx['behavior']=='opposing_request':direction='up'if direction=='down'else'down'
        intent_gain=sum((max(0,min(t['end_min']+delta,e['end_min'])-max(t['start_min']+delta,e['start_min']))-max(0,min(t['end_min'],e['end_min'])-max(t['start_min'],e['start_min'])))/60*d['parameters'].get(t['kind'],d['parameters'])['power_kw']*(1 if direction=='up'else-1)for t in group)
        candidate_input=next(c for c in ctx['program_service_candidates']if c['need_id']==nid)
        feasible_delta=any(q['delta_min']==delta for q in candidate_input['feasible_candidates'])
        formation={'service_fallback_policy':ctx['service_fallback_policy'],'fallback_anchors':'release/loading readiness;existing retrieval visit;next service/deadline;pressure explicit','input_behavior':ctx['behavior'],'request_basis':'feasible_VPP_candidate'if ctx['behavior']in('normal_response','partial_response','opposing_request')and intent_gain>0 and feasible_delta else 'service_boundary_request'if feasible_delta else'boundary_pressure_request','release_min':need['release_min'],'deadline_min':need['deadline_min'],'requested_shift_cap_min':table['requested_shift_min'],'actual_shift_min':delta,'fixed_chain_intent_gain_kWh':intent_gain,'individual_A_context_feasible':feasible_delta,'joint_B_constraints_checked_separately':True,'selected_event_id':e['event_id'],'no_response_claim':not(intent_gain>0 and feasible_delta)}
        for t in group:
            t['start_min']+=delta;t['end_min']+=delta;t['request_formation']=formation
        finish=max(t['end_min']for t in group)
        candidate=next((q for c in ctxs[key]['program_service_candidates']if c['need_id']==nid for q in c['feasible_candidates']if q['delta_min']==delta),None)
        if candidate is not None:
            for op,field in [(load,'load_min'),(unload,'unload_min')]:op['start_min']=candidate[field];op['end_min']=op['start_min']+10
        elif handling:
            for op in(load,unload):op['start_min']+=delta;op['end_min']+=delta
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
        # Existing retrieval/load only: use actual operator/service boundaries,
        # with dose as a cap. Never add a visit or offset it just for diversity.
        cap=table['requested_shift_min'];lo=max(minimum,a['start_min']-cap);hi=min(need['deadline_min']-10,a['start_min']+cap)
        from planning import operation_allowed
        options=[t for t in range(ceil10(lo),int(hi)+1,10)if t!=a['start_min']and operation_allowed(source,a,t,{a['need_id'],a['need_id']+':dry'})]
        target=max(options)if options else max(minimum,min(a['start_min']+cap,need['deadline_min']-10))
        op=next(o for o in plan['operations']if o['operation_id']==a['operation_id']);op['start_min']=target;op['end_min']=target+10



def build_ev(w, source, plan, defs, levels):
    assets={x['asset_id']:x for x in w['parameter_pack']['devices']};ctxs=contexts(w,source,defs)
    for a in source['A']['controls']:
        if a['kind']!='ev_charge_window':continue
        xs=[x for x in source['B']['controls']if x['kind']=='ev_charge_window'and x['asset_id']==a['asset_id']and x['need_id']==a['need_id']]
        src=next((x for x in xs if x['end_min']==a['end_min']),xs[0]if len(xs)==1 else None)
        if src is None:raise ValueError('AMBIGUOUS_EV_SOURCE_WINDOW')
        if same_control(a,src):continue
        d=assets[a['asset_id']];key=controller_key(d);p=d['parameters'];table=grade_table('ev',levels[key],d)
        start,end=ev_window(a,p,table,levels[key],ctxs[key]);x=next(x for x in plan['controls']if x==a)
        available=(end-start)/60*p['charger_kw']*p['efficiency'];delivered=min(a['battery_energy_kWh'],available)
        steps=math.ceil(delivered/(p['charger_kw']*p['efficiency'])*6-1e-10)
        ctx=ctxs[key];pressure=ctx['behavior']in('service_pressure','service_window_request','partial_response');requested_path=ctx['EV_request_path']
        if pressure:
            effective_path=requested_path
            if(requested_path=='event_only_permission'and max(a['start_min'],ctx['event']['start_min'])>=min(a['end_min'],ctx['event']['end_min']))or(requested_path=='event_end_cutoff'and ctx['event']['end_min']<=a['start_min']):effective_path='event_unavailable_departure_budget'
        else:
            effective_path='unused_permission_trim'if start==a['start_min']and end==min(a['end_min'],a['start_min']+ceil10(a['battery_energy_kWh']/(p['charger_kw']*p['efficiency'])*60))else'VPP_timed_permission'
        x.update(start_min=start,end_min=end,actual_charge_end_min=start+steps*10,
            last_step_power_fraction=max(0,min(1,delivered/(p['charger_kw']*p['efficiency'])*6-(steps-1))),
            requested_battery_energy_kWh=a['battery_energy_kWh'],projected_battery_energy_kWh=delivered,
            grid_energy_kWh=delivered/p['efficiency'],projection_basis='same_connection_A_state_fixed_charger_upper_bound;not_continuous_B_SOC',
            formation_path={'requested_path':ctxs[key]['EV_request_path'],'event_connection_overlap_min':max(0,min(a['end_min'],ctxs[key]['event']['end_min'])-max(a['start_min'],ctxs[key]['event']['start_min'])),'request_path':effective_path,'effective_path_read_from_input_branch_and_final_permission':True,
                'A_connection_min':[a['start_min'],a['end_min']],'B_permission_min':[start,end],'required_charge_minutes':a['battery_energy_kWh']/(p['charger_kw']*p['efficiency'])*60,'available_charge_minutes':end-start,'target_deficit_kWh':max(0,a['battery_energy_kWh']-delivered),'deadline_min':a['end_min'],'charging_cutoff_min':a['end_min'],'given_trip_departure_min':next(n['departure_min']for n in source['needs_A']if n['need_id']==a['need_id']),'given_unplug_interval_min':next([o['start_min'],o['end_min']]for o in source['A']['operations']if o['need_id']==a['need_id']and o['kind']=='EV_unplug'),'selected_event_id':ctxs[key]['event']['event_id'],'cause_chain':['given_connection_and_same_A_initial_energy','input_request_path_selected_before_B','available_permission_intersected_with_real_departure','fixed_charger_energy_bound_readback'],'failure_not_forced':True})


def construct(w, source, defs, vector=0):
    if not defs:return copy.deepcopy(source['B'])
    levels=selected_levels(defs,vector);plan=copy.deepcopy(source['A'])
    build_programs(w,source,plan,defs,levels)
    build_controls(w,source,plan,defs,levels)
    build_ev(w,source,plan,defs,levels)
    plan['controls'].sort(key=lambda x:(x['kind'],x['asset_id'],x['start_min'],x['end_min']))
    plan['changed_controls']=[x for x in plan['controls']if x not in source['A']['controls']]
    return plan
