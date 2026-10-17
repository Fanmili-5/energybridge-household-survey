"""Independent meter, common-history, delivery and recovery readback.

Engine completion is distinct from service feasibility, VPP performance and human
acceptance. Opposing, ineffective and unrecovered outcomes are never filtered.
"""
import argparse
import collections
import math
from concurrent.futures import ProcessPoolExecutor
from core import *
from audit_compiled import audit as audit_idf,pack as source_pack

def values(trace,name,key=None):
    matches=[v for k,v in trace['channels'].items()if k.split('|')[0].lower()==name.lower()and(key is None or k.split('|')[1].lower()==key.lower())]
    if not matches:return [0.]*(trace['interval_min'][1]//10)
    if len(matches)!=1:raise ValueError('AMBIGUOUS_OUTPUT:'+name+':'+str(key))
    return [float(x[1])for x in matches[0]]

def energy(trace,name,key=None):return [v/3600000 for v in values(trace,name,key)]
def add(*args):return [sum(v)for v in zip(*args)]
def total(v,lo,hi):return sum(v[max(0,lo//10):hi//10])

def summarize_side(pair,side,folder):
    inputs=read(folder/'INPUT.json.gz');trace=read(folder/'TRACE.json.gz');errors=[];hi=trace['interval_min'][1]
    e={key:energy(trace,name)for key,name in [('facility','Electricity:Facility'),('HVAC','Electricity:HVAC'),('water','WaterSystems:Electricity'),('equipment','InteriorEquipment:Electricity'),('lighting','InteriorLights:Electricity'),('EV','ExteriorEquipment:Electricity')]}
    closure=max(abs(a-b)for a,b in zip(e['facility'],add(e['HVAC'],e['water'],e['equipment'],e['lighting'],e['EV'])))
    if closure>1e-7:errors.append({'code':'FACILITY_METER_NOT_CLOSED','max_kWh':closure})
    program=[0.]*(hi//10);program_checks=[]
    for key,mapping in inputs['equipment_meter_mapping'].items():
        observed=energy(trace,'Electric Equipment Electricity Energy',key)
        expected=[0.]*(hi//10)
        for t in inputs['execution']['tasks']:
            if t['asset_id']==mapping['asset_id']and t['kind']==mapping['kind']:
                for minute in range(max(0,t['start_min']),min(hi,t['end_min']),10):expected[minute//10]+=mapping['watts']/6000
        error=max(abs(a-b)for a,b in zip(observed,expected))
        if error>1e-7:errors.append({'code':'PROGRAM_METER_MISMATCH','asset':mapping['asset_id'],'kind':mapping['kind'],'max_kWh':error})
        program=add(program,observed);program_checks.append({'asset_id':mapping['asset_id'],'kind':mapping['kind'],'primary_kWh':total(observed,480,1920),'full_rollout_kWh':total(observed,480,hi),'max_meter_error_kWh':error})
    if inputs['EV']['installed']:
        expected=dict(inputs['EV_grid_steps']);ev_error=max(abs(e['EV'][t//10]-expected.get(t,0))for t in range(480,hi,10))
        if ev_error>1e-7:errors.append({'code':'EV_GRID_METER_MISMATCH','max_kWh':ev_error})
        if abs(inputs['EV']['energy_balance_error_kWh'])>1e-7:errors.append({'code':'EV_BATTERY_LEDGER_MISMATCH'})
        old=pair['EV_continuous_reference'];old_steps={x['start_min']:x['grid_kWh']for x in old[side]['charging_steps']}
        source_error=max(abs(e['EV'][t//10]-old_steps.get(t,0))for t in range(480,min(hi,old['interval_min'][1]),10))
        if source_error>1e-7:errors.append({'code':'EV_DELIVERY_DIFFERS_FROM_FROZEN_B57_REFERENCE','max_kWh':source_error})
    else:ev_error=0
    e['programs']=program;e['controlled_portfolio']=add(e['HVAC'],e['water'],program,e['EV'])
    e['dwelling_inlet']=[a-b for a,b in zip(e['facility'],e['EV'])]
    world=source_pack(pair['household_id'])['world'];devices={d['asset_id']:d for d in world['parameter_pack']['devices']}
    circuits=collections.defaultdict(lambda:[0.]*(hi//10));hvac=[]
    for aid,key in inputs['HVAC_equipment_mapping'].items():
        v=energy(trace,'Zone Packaged Terminal Heat Pump Electricity Energy',key);hvac.append(v)
        circuit=devices[aid]['circuit'];circuits[circuit]=add(circuits[circuit],v)
    pumps=energy(trace,'Pump Electricity Energy')
    hvac_closure=max(abs(a-b)for a,b in zip(e['HVAC'],add(*hvac,pumps)))
    if hvac_closure>1e-7:errors.append({'code':'INCOMPLETE_HVAC_COMPONENT_METER_COVERAGE','max_kWh':hvac_closure})
    for key,mapping in inputs['equipment_meter_mapping'].items():
        circuit=devices[mapping['asset_id']]['circuit'];circuits[circuit]=add(circuits[circuit],energy(trace,'Electric Equipment Electricity Energy',key))
    for d in devices.values():
        if 'water_heater'in d['types']:circuits[d['circuit']]=add(circuits[d['circuit']],e['water'],pumps)
        if 'ev'in d['types']:circuits[d['circuit']]=add(circuits[d['circuit']],e['EV'])
    supply=[]
    for circuit,v in circuits.items():
        limit=world['parameter_pack']['circuit_limit_kw'][circuit]
        exceed=[t for t in range(480,hi,10)if v[t//10]*6>limit+1e-6]
        if exceed:supply.append({'circuit':circuit,'given_limit_kw':limit,'exceeded_minutes':len(exceed)*10,'first_exceed_min':exceed[0],'peak_average_kw':max(v[48:])*6})
    main_limit=world['parameter_pack']['home_service_limit_kw'];main_over=[t for t in range(480,hi,10)if e['dwelling_inlet'][t//10]*6>main_limit+1e-6]
    if main_over:supply.append({'circuit':'dwelling_inlet','given_limit_kw':main_limit,'exceeded_minutes':len(main_over)*10,'first_exceed_min':main_over[0],'peak_average_kw':max(e['dwelling_inlet'][48:])*6})
    mains=values(trace,'Site Mains Water Temperature');water=[]
    for k,seq in trace['channels'].items():
        if k.startswith('Water Use Equipment Total Volume|'):
            key=k.split('|')[1];temps=values(trace,'Water Use Equipment Mixed Water Temperature',key)
            volume=sum(v for t,v in seq if 480<=t<1920)
            deficit=sum(v*max(0,40.5555555555556-temps[t//10])for t,v in seq if 480<=t<1920)
            if volume>0:water.append({'equipment':key,'mixed_volume_L':volume*1000,'volume_weighted_temperature_shortfall_C':deficit/volume,
                                       'below_target_volume_L':sum(v*1000 for t,v in seq if 480<=t<1920 and temps[t//10]<40.5555555555556-.5)})
    primary_batches=[b for b in inputs['execution']['batches']if b['need_id'].startswith(pair['date'])]
    summary={'primary_energy_kWh':{k:total(v,480,1920)for k,v in e.items()},
             'rollout_energy_kWh':{k:total(v,480,hi)for k,v in e.items()},
             'primary_peak_kw':{k:max(v[48:192])*6 for k,v in e.items()},
             'meter_closure_max_kWh':closure,'EV_meter_max_error_kWh':ev_error,'program_meters':program_checks,
             'HVAC_component_meter_closure_max_kWh':hvac_closure,
             'given_electrical_supply_feasible_at_10min_resolution':not supply,'electrical_supply_violations':supply,
             'supply_violation_scope':'open-loop requested electrical replay,not a claim a real breaker delivers beyond its limit;no invented breaker/reset action',
             'mains_primary_C':mains[48],'mains_rollout_range_C':[min(mains),max(mains)],
             'program_batches':primary_batches,'water_delivery':water,
             'EV_trips':inputs['EV'].get('trips',[]),'EV_stop_at_unexecutable_trip_min':inputs['EV'].get('stop_at_unexecutable_trip_min'),
             'source_schedule_hash':inputs['source_schedule_hash'],'human_acceptance':None,
             'electricity_cost':None,'cost_status':'not computed without a separately frozen tariff scenario',
             'errors':errors}
    return inputs,trace,e,summary

def pair_review(item):
    record,case,label=item;folder=ROOT/'results'/label/record['household_id']/case['date'];pair=read(ROOT/case['path'])
    try:
        run=read(folder/'PAIR_RUN.json')
        if not run['passed']:return {'case_id':case['case_id'],'passed':False,'errors':['ENGINE_NOT_COMPLETED']}
        data={s:summarize_side(pair,s,folder/s)for s in ('A','B')};ai,at,ae,aa=data['A'];bi,bt,be,bb=data['B'];errors=aa['errors']+bb['errors']
        for side in ('A','B'):
            if data[side][0]['source_schedule_hash']!=pair['schedule_hashes'][side]:errors.append({'code':'SOURCE_SCHEDULE_CHANGED','side':side})
            errors.extend(audit_idf(pair,side,folder/side,data[side][0]))
        common=0.
        for key,av in at['channels'].items():
            bv=bt['channels'].get(key)
            if bv is None:errors.append({'code':'PAIRED_CHANNEL_MISSING','key':key});continue
            scale=3600000 if at['metadata'][key]['unit']=='J'else 1
            common=max(common,max(abs(a[1]-b[1])/scale for a,b in zip(av[:48],bv[:48])))
        if common>1e-7:errors.append({'code':'PREDECISION_STATE_OR_ENERGY_DIFFERS','max_normalized_error':common})
        end=bi['actual_intervention_end_min'];hi=bt['interval_min'][1];state_channels=[];temperature_residual=[];restored=None
        for key,meta in bt['metadata'].items():
            if key.startswith(('Zone Mean Air Temperature|','Zone Mean Radiant Temperature|','Water Heater Final Temperature Node ')):
                state_channels.append((key,.1))
            elif key.startswith('Zone Air Relative Humidity|'):state_channels.append((key,.2))
        joint_ok=[]
        ast=dict(ai['EV']['trace'])if ai['EV']['installed']else {}
        bst=dict(bi['EV']['trace'])if bi['EV']['installed']else {}
        for ix in range(48,hi//10):
            okay=all(abs(bt['channels'][key][ix][1]-at['channels'][key][ix][1])<=tol for key,tol in state_channels)
            if ai['EV']['installed']:
                okay=okay and ix*10 in ast and ix*10 in bst and abs(ast[ix*10]-bst[ix*10])<=1e-6
            joint_ok.append(okay)
        if end is None:
            status='no_executable_request_difference';restored=None
            if any(abs(a-b)>1e-8 for a,b in zip(ae['facility'],be['facility'])):errors.append({'code':'IDENTICAL_REQUESTS_DIFFERENT_OUTPUTS'})
        else:
            # Six consecutive hours within tolerance, with no later excursion in
            # this observation horizon. Not a claim about unobserved deep walls.
            last_bad=max((480+i*10 for i,ok in enumerate(joint_ok)if not ok),default=470)
            first=max(end,last_bad+10,480)
            if hi-first>=360:restored=first;status='within_declared_tolerances_to_horizon'
            else:status='not_restored_within_horizon'
        for key,tol in state_channels:
            temperature_residual.append({'channel':key,'end_delta':bt['channels'][key][-1][1]-at['channels'][key][-1][1],'tolerance':tol})
        events=[]
        for ev in pair['VPP_events']:
            a=ev['start_min'];z=ev['end_min'];ek={s:total(e['controlled_portfolio'],a,z)for s,e in [('A',ae),('B',be)]}
            delta=(ek['B']-ek['A'])*60/(z-a);requested=delta if ev['direction']=='up'else-delta
            events.append({'event_id':ev['event_id'],'direction':ev['direction'],'target_kw':ev['target_kw'],
                           'A_controlled_kWh':ek['A'],'B_controlled_kWh':ek['B'],'delta_kw':delta,'requested_direction_response_kw':requested,
                           'relation':'unchanged'if abs(delta)<1e-6 else'aligned'if requested>0 else'opposing',
                           'target_met':requested>=ev['target_kw']-1e-6,'meter_scope':'target HVAC+water system+executed target programs+external EV;background excluded'})
        exposure=[]
        for key,av in at['channels'].items():
            if not key.startswith('Zone Mean Air Temperature|'):continue
            rid=key.split('|')[1];counts=values(at,'Zone People Occupant Count',rid);bv=bt['channels'][key]
            occupied=[i for i in range(48,192)if counts[i]>0]
            if occupied:
                exposure.append({'room':rid,'A_occupied_temperature_range_C':[min(av[i][1]for i in occupied),max(av[i][1]for i in occupied)],
                                 'B_occupied_temperature_range_C':[min(bv[i][1]for i in occupied),max(bv[i][1]for i in occupied)],
                                 'occupied_absolute_delta_degree_hours':sum(counts[i]*abs(bv[i][1]-av[i][1])/6 for i in occupied),
                                 'human_comfort_or_acceptance':None})
        summary={'schema':VERSION,'case_id':case['case_id'],'source_pair_sha256':pair['source_pair_sha256'],
                 'A':aa,'B':bb,'VPP_events':events,'temperature_exposure':exposure,
                 'delta_primary_kWh':{k:bb['primary_energy_kWh'][k]-aa['primary_energy_kWh'][k]for k in ae},
                 'delta_rollout_kWh':{k:bb['rollout_energy_kWh'][k]-aa['rollout_energy_kWh'][k]for k in ae},
                 'recovery':{'status':status,'actual_intervention_end_min':end,'observed_state_match_min':restored,'end_min':hi,
                             'criteria':{'air_and_radiant_and_tank_node_C':.1,'RH_percentage_points':.2,'EV_battery_kWh':1e-6,'minimum_stable_minutes':360},
                             'end_residuals':temperature_residual,'exact_deep_wall_state_equality_claimed':False,'state_reset_or_extra_recovery_actions':False},
                 'source_B_constraint_flags':pair['assessment_B']['constraint_flags'],'source_B_failures_retained':True,
                 'common_history_max_normalized_error':common,'given_constraints_feasible':pair['assessment_B']['given_constraints_feasible'],
                 'engine_completion_is_not_service_success':True,'human_acceptance':None,'passed':not errors,'errors':errors}
        save(folder/'PHYSICAL_SUMMARY.json',summary)
        return {'case_id':case['case_id'],'household_id':record['household_id'],'type':record['type'],'date':case['date'],'path':str((folder/'PHYSICAL_SUMMARY.json').relative_to(ROOT)),
                'sha256':sha(folder/'PHYSICAL_SUMMARY.json'),'source_pair_sha256':pair['source_pair_sha256'],'passed':not errors,'errors':errors,
                'B_constraint_conflict':bool(summary['source_B_constraint_flags']),'recovery_status':status,
                'B_unexecuted_batches':sum(not x['program_executed']for x in bb['program_batches']),
                'A_unexecuted_batches':sum(not x['program_executed']for x in aa['program_batches']),
                'B_EV_target_shortfall_departures':sum(x['target_shortfall_kWh']>1e-7 for x in bb['EV_trips']),
                'B_water_below_target':any(x['below_target_volume_L']>0 for x in bb['water_delivery']),
                'A_supply_violation':not aa['given_electrical_supply_feasible_at_10min_resolution'],
                'B_supply_violation':not bb['given_electrical_supply_feasible_at_10min_resolution'],
                'whole_event_relations':[e['relation']for e in events],
                'delta_primary_controlled_kWh':summary['delta_primary_kWh']['controlled_portfolio'],
                'delta_rollout_controlled_kWh':summary['delta_rollout_kWh']['controlled_portfolio'],
                'meter_closure_max_kWh':max(aa['meter_closure_max_kWh'],bb['meter_closure_max_kWh'])}
    except Exception as exc:
        import traceback
        return {'case_id':case['case_id'],'passed':False,'errors':[str(exc)],'traceback':traceback.format_exc()}

def main():
    p=argparse.ArgumentParser();p.add_argument('--label',default='pilot50');p.add_argument('--workers',type=int,default=4)
    args=p.parse_args();runs=read(ROOT/'results'/args.label/'RUN_BINDINGS.json');manifest=read(ROOT/'INPUT_MANIFEST.json')
    ids={r['case_id']for r in runs['records']};jobs=[(r,c,args.label)for r in manifest['records']for c in r['cases']if c['case_id']in ids]
    results=[]
    with ProcessPoolExecutor(max_workers=args.workers)as pool:
        for r in pool.map(pair_review,jobs,chunksize=1):
            results.append(r)
            if len(results)%100==0:print(canonical({'analyzed_pairs':len(results),'errors':sum(not x['passed']for x in results)}),flush=True)
    counts=collections.Counter();events=collections.Counter()
    for r in results:
        counts['cases']+=1;counts['passed']+=r['passed']
        if r['passed']:
            counts['source_constraint_conflict_cases']+=r['B_constraint_conflict'];counts['B_unexecuted_batches']+=r['B_unexecuted_batches'];counts['A_unexecuted_batches']+=r['A_unexecuted_batches']
            counts['B_EV_target_shortfall_departures']+=r['B_EV_target_shortfall_departures'];counts['B_water_below_target_cases']+=r['B_water_below_target']
            counts['A_supply_violation_cases']+=r['A_supply_violation'];counts['B_supply_violation_cases']+=r['B_supply_violation']
            counts[r['recovery_status']]+=1;events.update(r['whole_event_relations'])
    report={'schema':VERSION,'scope':args.label,'passed':all(r['passed']for r in results),'counts':dict(counts),'whole_VPP_event_relations':dict(events),
            'records':results,'errors':[r for r in results if not r['passed']],'run_bindings_sha256':sha(ROOT/'results'/args.label/'RUN_BINDINGS.json'),
            'one_dataset':True,'human_acceptance_labels_created':0,'schedules_modified':False,'code_sha256':code_hash()}
    save(ROOT/'results'/args.label/'REVIEW.json',report);print(canonical({k:v for k,v in report.items()if k not in('records','errors')}))
    if not report['passed']:raise SystemExit(2)

if __name__=='__main__':main()
