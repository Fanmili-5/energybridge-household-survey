"""Full-population phase, service-anchor and independent EV energy-ledger audit."""
import sys,collections,math
from pathlib import Path
STAGE=Path(__file__).resolve().parents[1];sys.path.insert(0,str(STAGE/'code'))
from common import *

def audit(row):
    errors=[];counts=collections.Counter();program=collections.Counter();examples={};world=None;y=None
    def fail(case,code):errors.append([case,code])
    for rr in row['rounds']:
        p=read(OUT/rr['path']);case=p['case_id'];counts['cases']+=1
        if world is None:world=read(A_STAGE/p['A_source']['world_path'])
        assets={x['asset_id']:x for x in world['parameter_pack']['devices']}
        parent=p['revision_parent'];prior=read(PARENT_B/parent['case_path'])
        if sha(PARENT_B/parent['case_path'])!=parent['case_sha256']or prior['A']!=p['A']or prior['needs_A']!=p['needs_A']:fail(case,'PARENT_OR_A46_CHANGED')
        def literal_programs(plan):return sorted((z['task_id'],z['asset_id'],z['kind'],z['start_min'],z['end_min'])for z in plan['tasks']),sorted((z['operation_id'],z['asset_id'],z['kind'],z['start_min'],z['end_min'])for z in plan['operations'])
        counts['B55_program_or_handling_changed_cases']+=literal_programs(p['B'])!=literal_programs(prior['B'])
        def ev_commands(plan):return sorted((z['asset_id'],z['need_id'],z['start_min'],z['end_min'],z['stop_at_target_soc'])for z in plan['controls']if z['kind']=='ev_charge_window')
        if ev_commands(p['B'])!=ev_commands(prior['B']):fail(case,'B55_EV_PERMISSION_CHANGED')
        counts['B55_EV_permission_preserved_cases']+=ev_commands(p['B'])==ev_commands(prior['B'])
        for phase in p['B'].get('thermal_phase_requests',[]):
            counts['thermal_phase:'+phase['phase']]+=1
            lo,hi=phase['start_min'],phase['end_min'];e0,e1=phase['event_interval_min'];aid=phase['asset_id'];kind=phase['kind']
            if phase['phase']=='preparation'and (hi>e0 or phase['load_direction_requested']!='up'):fail(case,'PREPARATION_PHASE_DIRECTION_OR_TIME')
            if phase['phase']=='event'and not e0<=lo<hi<=e1:fail(case,'EVENT_PHASE_TIME')
            for t in range(lo,hi,10):
                a=next((x for x in p['A']['controls']if x['kind']==kind and x['asset_id']==aid and x['start_min']<=t<x['end_min']),None)
                b=next((x for x in p['B']['controls']if x['kind']==kind and x['asset_id']==aid and x['start_min']<=t<x['end_min']),None)
                if phase['phase']=='preparation'and b and a:
                    if kind=='tank_setpoint'and b['value_C']<a['value_C']-1e-8:fail(case,'PREPARATION_LOWERED_TANK_TARGET')
                    if kind=='ac_setpoint':
                        req=next(q for q in p['proposal']['requested_device_strengths']if q['controller_key']==phase['controller_key']);axis=req['input_state_plan']['thermal_axis_reference']
                        if (axis=='heating'and b['heating_setpoint_C']<a['heating_setpoint_C']-1e-8)or(axis=='cooling'and b['cooling_setpoint_C']>a['cooling_setpoint_C']+1e-8):fail(case,'PREPARATION_RELAXED_ACTIVE_AC_AXIS')
                        if b['cooling_setpoint_C']-b['heating_setpoint_C']<2-1e-8:fail(case,'PREPARATION_AC_DEADBAND')
        # B is identical to A outside the explicitly formed thermal phase intervals.
        if p['B'].get('thermal_phase_requests'):
            for aid in {z['asset_id']for z in p['B']['thermal_phase_requests']}:
                rows=[z for z in p['B']['thermal_phase_requests']if z['asset_id']==aid];kind=rows[0]['kind'];fields=['value_C']if kind=='tank_setpoint'else['heating_setpoint_C','cooling_setpoint_C','fan_operating_mode']
                arows=[z for z in p['A']['controls']if z['asset_id']==aid and z['kind']==kind];brows=[z for z in p['B']['controls']if z['asset_id']==aid and z['kind']==kind]
                for t in range(480,4320,10):
                    if any(z['start_min']<=t<z['end_min']for z in rows):continue
                    def val(xs):
                        x=next((z for z in xs if z['start_min']<=t<z['end_min']),None);return tuple(x[k]for k in fields)if x else None
                    if val(arows)!=val(brows):fail(case,'THERMAL_A_RECOVERY_NOT_RESTORED');break
        # Independently compare declared plans with literal B commands and all
        # other A batches' full [load start, retrieval end) occupation.
        for f in p['B'].get('program_request_plans',[]):
            counts['program_plans']+=1;basis=f['request_basis'];pol=f['service_fallback_policy']
            task=next(x for x in p['B']['tasks']if x['need_id']==f['need_id']and x['kind']in('washer','dishwasher'))
            atask=next(x for x in p['A']['tasks']if x['task_id']==task['task_id'])
            load=next(x for x in p['B']['operations']if x['need_id']==f['need_id']and x['kind']=='load');unload=next(x for x in p['B']['operations']if x['need_id']==f['need_id']and x['kind']=='unload')
            finish=max(x['end_min']for x in p['B']['tasks']if x['need_id']in(f['need_id'],f['need_id']+':dry'))
            values={'load_min':load['start_min'],'unload_min':unload['start_min'],'finish_min':finish,'program_start_min':task['start_min']}
            if [task['start_min'],load['start_min'],unload['start_min'],finish,task['start_min']-atask['start_min']]!=[f['B_start_min'],f['B_load_min'],f['B_unload_min'],f['B_chain_finish_min'],f['actual_shift_min']]:fail(case,'PROGRAM_METADATA_NOT_LITERAL_COMMAND')
            bad=[]
            for other in p['A']['operations']:
                if other['asset_id']!=f['asset_id']or other['kind']!='load'or other['need_id']==f['need_id']:continue
                clear=next((x['end_min']for x in p['A']['operations']if x['need_id']==other['need_id']and x['kind']=='unload'),4320)
                if max(load['start_min'],other['start_min'])<min(unload['end_min'],clear):bad.append(other['need_id'])
            if sorted(bad)!=sorted(f['asset_hold_conflicts_A']):fail(case,'WHOLE_ASSET_HOLD_METADATA')
            if f['individual_A_context_feasible']and bad:fail(case,'FALSE_FEASIBILITY_WITH_OCCUPIED_ASSET')
            counts['full_hold_feasible_claims']+=f['individual_A_context_feasible'];counts['explicit_infeasible_program_requests']+=not f['individual_A_context_feasible']
            req=next(x for x in p['proposal']['requested_device_strengths']if x['controller_key']==f['controller_key']);ctx=next(x for x in req['input_state_plan']['program_service_candidates']if x['need_id']==f['need_id'])
            if basis=='life_node_request':
                node=f['selected_node'];counts['exact_life_nodes']+=1
                if not node or node not in ctx['life_nodes']or values[node['field']]!=node['minute']:fail(case,'UNREACHED_LIFE_NODE')
                if not f['individual_A_context_feasible']:fail(case,'INFEASIBLE_REPORTED_AS_LIFE_NODE')
                need=next(x for x in p['needs_A']if x['need_id']==f['need_id']);kind=node['kind'];ref=node['reference'];valid=False
                if kind=='service_release':valid=node['minute']==need['release_min']
                elif kind=='decision_ready':valid=node['minute']==480
                elif kind=='service_deadline':valid=node['minute']==need['deadline_min']-10
                elif kind=='previous_batch_cleared':valid=any(x['need_id']==ref and x['asset_id']==f['asset_id']and x['kind']=='unload'and x['end_min']==node['minute']for x in p['A']['operations'])
                elif kind in('prior_commitment_ends','existing_room_visit','before_next_use','original_loading_complete','original_retrieval','finish_at_original_retrieval'):
                    op=next((x for x in p['A']['operations']if x['operation_id']==ref),None)
                    expected=op['start_min']-10 if kind=='before_next_use'else op['start_min']if kind in('original_retrieval','finish_at_original_retrieval')else op['end_min']if op else None
                    valid=op is not None and expected==node['minute']
                    if kind=='existing_room_visit':valid=valid and op['operator_id']==unload['operator_id']and op['room_id']==unload['room_id']
                elif kind in('operator_available','operator_return','before_operator_leaves','room_reservation_ends'):
                    operation=load if node['field']=='load_min'else unload
                    for day in p['days']:
                        base=(dt.date.fromisoformat(day['date'])-dt.date.fromisoformat(p['date'])).days*1440
                        if kind=='room_reservation_ends':valid=valid or any(x['room_id']==operation['room_id']and base+x['end_min']==node['minute']for x in day['shared']['facility_reservations'])
                        else:valid=valid or any(base+(hi-10 if kind=='before_operator_leaves'else lo)==node['minute']for lo,hi in day['activity']['operator_windows_min'].get(operation['operator_id'],[]))
                if not valid:fail(case,'LIFE_NODE_NOT_GROUNDED_IN_ORIGINAL_INPUT')

                # A static original retrieval/load alone is not a new life-node action.
                aa=next(x for x in p['A']['operations']if x['operation_id']==load['operation_id']);au=next(x for x in p['A']['operations']if x['operation_id']==unload['operation_id'])
                if (node['field']=='load_min'and load['start_min']==aa['start_min'])or(node['field']=='unload_min'and unload['start_min']==au['start_min'])or(node['field']in('program_start_min','finish_min')and f['actual_shift_min']==0):fail(case,'UNCHANGED_NODE_USED_TO_JUSTIFY_ARBITRARY_TIMER')
            elif f['selected_node']is not None or f['life_node_reached']:fail(case,'DOSE_OR_VPP_REQUEST_MISLABELLED_LIFE_NODE')
            counts['program_basis:'+basis]+=1
            direction='advance'if f['actual_shift_min']<0 else'delay'if f['actual_shift_min']>0 else'handling_only'
            program[(task['kind'],basis,pol,direction)]+=1
        # Main impact and event classification share the very same EV trajectory.
        ev=p['EV_continuous_reference'];impact=p['VPP_response_reference'];summary=impact['EV_continuous_impact']
        if summary['continuous_reference_sha256']!=digest(ev):fail(case,'EV_IMPACT_TRAJECTORY_BINDING')
        def grid(side,lo,hi):
            return sum(x['grid_kWh']*max(0,min(x['end_min'],hi)-max(x['start_min'],lo))/10 for x in ev[side]['charging_steps'])if ev['status']!='not_installed'else 0.
        def prog(plan,lo,hi):
            result=0.
            for x in plan['tasks']:
                par=assets[x['asset_id']]['parameters'];result+=max(0,min(x['end_min'],hi)-max(x['start_min'],lo))/60*par.get(x['kind'],par)['power_kw']
            return result
        for name,lo,hi in [('primary',480,1920),('after_primary_to_tail',1920,4320),('to_tail',480,4320)]:
            expected=prog(p['B'],lo,hi)-prog(p['A'],lo,hi)+grid('B',lo,hi)-grid('A',lo,hi)
            if abs(expected-impact['known_load_requested_'+name+'_delta_kWh'])>1e-7:fail(case,'MAIN_IMPACT_USES_STALE_EV_ENERGY')
        for e,er,cr in zip(p['VPP_events'],impact['events'],p['classification']['actual_actions']['events']):
            lo,hi=e['start_min'],e['end_min'];ar=grid('A',lo,hi);br=grid('B',lo,hi)
            if abs(ar-er['EV_A_grid_kWh'])>1e-7 or abs(br-er['EV_B_grid_kWh'])>1e-7:fail(case,'EVENT_SUMMARY_EV_TRAJECTORY')
            expected=(prog(p['A'],lo,hi)+ar-prog(p['B'],lo,hi)-br)*60/(hi-lo)*(1 if e['direction']=='down'else-1)
            if abs(expected-er['requested_known_response_average_kw'])>1e-7:fail(case,'EVENT_TOTAL_SUMMARY_EV_TRAJECTORY')
            cond={'tasks':p['assessment_B']['conditional_recovery_reference']['realized_tasks']}
            expected=(prog(p['A'],lo,hi)+ar-prog(cond,lo,hi)-br)*60/(hi-lo)*(1 if e['direction']=='down'else-1)
            if abs(expected-er['conditional_known_response_average_kw'])>1e-7:fail(case,'CONDITIONAL_SUMMARY_EV_TRAJECTORY')
            for label,aa,zz in [('post2h',hi,hi+120),('pre2h',max(480,lo-120),lo)]:
                expected=prog(p['B'],aa,zz)-prog(p['A'],aa,zz)+grid('B',aa,zz)-grid('A',aa,zz)
                if abs(expected-er['requested_'+label+'_extra_kWh'])>1e-7:fail(case,'PRE_POST_SUMMARY_EV_TRAJECTORY')
            if cr['EV_event_state_reference']['continuous_reference_sha256']!=digest(ev):fail(case,'CLASSIFICATION_EV_TRAJECTORY')
        counts['continuous_impact_summary_verified_cases']+=1
        ev=p['EV_continuous_reference']
        if ev['status']=='not_installed':continue
        for name,r in summary['periods'].items():
            lo,hi=r['interval_min'];aa=grid('A',lo,hi);bb=grid('B',lo,hi)
            if max(abs(r['A_grid_kWh']-aa),abs(r['B_grid_kWh']-bb),abs(r['delta_grid_kWh']-bb+aa))>1e-7:fail(case,'EV_PERIOD_ENERGY_SUMMARY')
        legacy={}
        for side in('A','B'):
            total=0.
            for z in prior[side]['controls']:
                if z['kind']!='ev_charge_window':continue
                for m in range(z['start_min'],z['actual_charge_end_min'],10):
                    if 480<=m<4320:total+=ev['charger_kW']/6*(z['last_step_power_fraction']if m==z['actual_charge_end_min']-10 else 1)
            legacy[side]=total
        counts['legacy_EV_tail_energy_discrepancy_corrected_cases']+=abs(legacy['B']-legacy['A']-(grid('B',480,4320)-grid('A',480,4320)))>1e-7
        expected_last=max([x['end_min']for x in p['A']['controls']+p['B']['controls']if x.get('need_id')in ev['changed_need_ids']and x['kind']=='ev_charge_window'],default=1920)
        if expected_last!=ev['last_changed_permission_end_min']:fail(case,'EV_RECOVERY_ENDPOINT_IS_NOT_ACTUAL_INTERVENTION_END')
        last=ev['last_changed_permission_end_min'];expected=grid('B',last,ev['interval_min'][1])-grid('A',last,ev['interval_min'][1])
        if abs(summary['after_request_extra_grid_kWh']-expected)>1e-7 or summary['recovery_status']!=ev['recovery_status']or summary['common_SOC_restored_min']!=ev['common_SOC_restored_after_request_min']:fail(case,'EV_RECOVERY_ENERGY_OR_STATUS_SUMMARY')
        if len(summary['target_unmet_departures'])!=sum(x['target_SOC_unmet']or not x['trip_executable_in_reference']for x in ev['B']['trips']):fail(case,'EV_FAILURE_HIDDEN_IN_SUMMARY')
        counts['EV_installed_cases']+=1
        if y is None:y=read(A_STAGE/p['A_source']['annual_A_path'])
        offset=(dt.date.fromisoformat(p['date'])-dt.date.fromisoformat(y['anchor'])).days*1440;cap=ev['capacity_kWh'];start,end=ev['interval_min']
        expected_initial=y['initial_states']['EV_SOC']*cap
        for x in y['EV_battery_energy_events']:
            lo,z=x['start_min'],x['end_min'];point=offset+start
            if z==lo:expected_initial+=x['battery_kWh']if lo<point else 0
            elif lo<point:expected_initial+=x['battery_kWh']*min(1.,(point-lo)/(z-lo))
        if abs(expected_initial-ev['initial_energy_kWh'])>1e-7:fail(case,'EV_COMMON_INITIAL_STATE')
        aw=[{**z,'start_min':z['start_min']-offset,'end_min':z['end_min']-offset}for d in y['days'].values()for z in d['controls']if z['kind']=='ev_charge_window'and z['start_min']<offset+end and z['end_min']>offset+start]
        bwcase=[z for z in p['B']['controls']if z['kind']=='ev_charge_window'];ids={z['need_id']for z in bwcase};bw=[z for z in aw if z['need_id']not in ids]+bwcase
        operations={z['operation_id']:z for z in y['operations']if z['kind'].startswith('EV_')};connections={}
        for z in operations.values():
            if z['kind']=='EV_plug':
                unplug=operations[z['need_id']+':EV_unplug'];connections[z['need_id']]=(z['end_min']-offset,unplug['start_min']-offset)
        for side,windows in [('A',aw),('B',bw)]:
            r=ev[side];events=[]
            if abs(r['energy_balance_error_kWh'])>1e-6:fail(case,'EV_ENERGY_BALANCE')
            for c in r['charging_steps']:
                t=c['start_min'];active=[z for z in windows if z['need_id']==c['need_id']and z['start_min']<=t<t+10<=z['end_min']];conn=connections[c['need_id']]
                if len(active)!=1 or not conn[0]<=t<t+10<=conn[1]:fail(case,'EV_CHARGE_OUTSIDE_ORIGINAL_PERMISSION_CONNECTION')
                if c['battery_kWh']>ev['charger_kW']*ev['efficiency']/6+1e-7 or abs(c['grid_kWh']*ev['efficiency']-c['battery_kWh'])>1e-7:fail(case,'EV_CHARGE_RATE_OR_EFFICIENCY')
                events.append((c['end_min'],0,'charge',c))
            expected_trips=[z for z in y['journeys']if start+offset<=z['absolute_departure_min']<=end+offset and(r['stop_at_unexecutable_trip_min']is None or z['absolute_departure_min']<=r['stop_at_unexecutable_trip_min']+offset)]
            if [z['absolute_departure_min']-offset for z in expected_trips]!=[z['departure_min']for z in r['trips']]:fail(case,'EV_TRIP_CALENDAR_CHANGED')
            for q,raw in zip(r['trips'],expected_trips):
                if q['traction_kWh']!=raw['traction_kWh']:fail(case,'EV_TRIP_ENERGY_CHANGED')
                if side=='A':
                    point=raw['absolute_departure_min'];expected=y['initial_states']['EV_SOC']*cap
                    for item in y['EV_battery_energy_events']:
                        lo,z=item['start_min'],item['end_min']
                        if z==lo:expected+=item['battery_kWh']if lo<point else 0
                        elif lo<point:expected+=item['battery_kWh']*min(1.,(point-lo)/(z-lo))
                    if abs(expected-q['pre_trip_kWh'])>1e-6:fail(case,'A_CONTINUOUS_SOC_DIFFERS_FROM_FROZEN_ANNUAL_LEDGER')
                events.append((q['departure_min'],1,'trip',q))
            energy=ev['initial_energy_kWh']
            for t,_,kind,x in sorted(events,key=lambda z:(z[0],z[1])):
                if kind=='charge':
                    energy+=x['battery_kWh']
                    if abs(energy-x['SOC_after']*cap)>1e-6:fail(case,'EV_UNRECORDED_SOC_RESET')
                else:
                    if abs(energy-x['pre_trip_kWh'])>1e-6:fail(case,'EV_PRE_TRIP_CONTINUITY')
                    energy=max(0,energy-x['traction_kWh'])
                    if abs(energy-x['post_trip_kWh'])>1e-6:fail(case,'EV_POST_TRIP_CONTINUITY')
                if energy< -1e-7 or energy>cap+1e-7:fail(case,'EV_SOC_HARDWARE_BOUND')
            if abs(energy-r['end_energy_kWh'])>1e-6:fail(case,'EV_FINAL_CONTINUITY')
        counts['EV_changed_request_cases']+=bool(ev['changed_need_ids']);counts['EV_recovery:'+ev['recovery_status']]+=1
        for q in ev['B']['trips']:
            counts['EV_B_target_unmet_departures']+=q['target_SOC_unmet'];counts['EV_B_minimum_reserve_unmet_departures']+=q['minimum_reserve_unmet_after_trip'];counts['EV_B_unexecutable_departures']+=not q['trip_executable_in_reference']
        if case in('ordinary-v6-0001__2025-09-30','ordinary-v6-0048__2025-04-02','ordinary-v6-1000__2025-07-23','ordinary-v6-0454__2025-10-08','ordinary-v6-0001__2025-03-22'):examples[case]={'path':rr['path'],'EV_continuous_reference':ev,'impact_summary':impact,'program_plans':p['B'].get('program_request_plans',[]),'thermal_phases':p['B'].get('thermal_phase_requests',[]),'actual':p['proposal']['actual_device_strengths']}
    return errors,dict(counts),[(list(k),v)for k,v in program.items()],examples

def main():
    from concurrent.futures import ProcessPoolExecutor
    verify_inputs();sig=rules_id();bindings=sha(OUT/'PAIR_BINDINGS10000.json');rows=read(OUT/'PAIR_BINDINGS10000.json')['records'];errors=[];counts=collections.Counter();program=collections.Counter();examples={}
    with ProcessPoolExecutor(max_workers=4)as pool:
        for i,(ee,cc,pp,xx)in enumerate(pool.map(audit,rows),1):
            errors.extend(ee);counts.update(cc);program.update({tuple(k):v for k,v in pp});examples.update(xx)
            if i%100==0:print({'phase_EV_households':i,'errors':len(errors)},flush=True)
    assert sig==rules_id()and bindings==sha(OUT/'PAIR_BINDINGS10000.json')
    report={'passed':not errors,'rules_sha256':sig,'bindings_sha256':bindings,'counts':dict(counts),'program_fallback_distribution':[{'device_family':k[0],'basis':k[1],'policy':k[2],'direction':k[3],'count':v}for k,v in sorted(program.items())],'errors':errors,'all10000_retained':True,'scope':'raw phase direction/time/A restoration and continuous fixed-charger ledger under given trips/permissions;not full B physics or human acceptance'}
    save(OUT/'PHASE_EV_REVIEW.json',report);save(OUT/'review/阶段与连续电量案例.json',examples);print(canonical(report))
    if errors:raise SystemExit(2)
if __name__=='__main__':main()
