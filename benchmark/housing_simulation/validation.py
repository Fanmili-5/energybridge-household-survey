"""Construction gates and physical readback checks for the public reference profile."""
import copy
import datetime as dt
import math
from pathlib import Path

from .kernel.execution import execute
from .pipeline import HERE, build_shell, compile_pairs, fresh, read, run_pairs, save, seal, sha, verify


def check_baseline(pack, pairs, settings):
    anchor=dt.date.fromisoformat(pack['anchor']);end=dt.date.fromisoformat(pack['end_exclusive']);hi=(end-anchor).days*1440
    plan={k:copy.deepcopy(pack[k])for k in ('tasks','operations')}
    plan['operations']=[o for o in plan['operations']if 0<=o['start_min']<o['end_min']<=hi]
    pair={'date':str(anchor),'needs_A':pack['service_needs']}
    result=execute(pack,pair,plan,0,hi)
    if result['operation_failures'] or result['dropped_program_ids'] or any(not b['collected'] for b in result['batches']):
        raise ValueError('BASELINE_NOT_EXECUTABLE:'+str({'operations':list(result['operation_failures'].items())[:4], 'batches':[b for b in result['batches']if not b['collected']][:2]}))
    needs={n['need_id']:n for n in pack['service_needs']}
    for op in plan['operations']:
        if op['kind']=='unload' and op['end_min']>needs[op['need_id']]['deadline_min']:
            raise ValueError('baseline retrieval misses service deadline')
    history=settings['history_days'];tail=settings['tail_days']
    if type(history)is not int or history<1 or type(tail)is not int or tail<1:raise ValueError('positive history/tail required')
    for p in pairs:
        date=dt.date.fromisoformat(p['date'])
        # Current input profile permits changes only within the target day.
        start=date-dt.timedelta(days=history);finish=date+dt.timedelta(days=max(tail,9))
        if start<anchor or finish>end:raise ValueError('history or recovery outside supplied calendar')
        dates=[start+dt.timedelta(days=i)for i in range((finish-start).days)]
        if len(dates)>365 or any(d.month==2 and d.day==29 for d in dates):raise ValueError('nonleap replay interval at most365days required')


def audit(compiled, runs, output):
    compiled=Path(compiled).resolve();runs=Path(runs).resolve()
    cm,rm=verify(compiled),verify(runs)
    if rm['compiled_manifest_sha256']!=sha(compiled/'MANIFEST.json'):raise ValueError('run/compiler binding mismatch')
    out=fresh(output);records=[]
    for item in cm['records']:
        rid=item['id'];checks={};details={};metas={};traces={}
        try:
            for side in ('A','B'):
                result=read(runs/rid/side/'RESULT.json')
                if result['status']!='completed':raise ValueError('arm did not complete:'+side)
                meta=read(compiled/rid/side/'INPUT.json.gz');trace=read(runs/rid/side/'TRACE.json.gz')
                if result['idf_sha256']!=meta['idf_sha256']:raise ValueError('model/result binding mismatch')
                metas[side]=meta;traces[side]=trace
                hi=meta['run_interval_min'][1];expected=list(range(0,hi,10))
                checks[side+'_complete_finite_timeline']=bool(trace) and all([t for t,v in c['values']]==expected and all(math.isfinite(v)for t,v in c['values'])for c in trace.values())
                def values(name,key=''):
                    channel=trace.get(name+'|'+key)
                    if channel is None:raise ValueError('required physical channel missing:'+name+'|'+key)
                    return dict(channel['values'])
                facility=values('Electricity:Facility')
                supply=meta.get('world_assembly',{}).get('electrical_supply_W')
                if supply:
                    checks[side+'_electrical_supply']=max(facility.values())/600<=supply+1e-6
                    details[side+'_facility_peak_timestep_W']=max(facility.values())/600
                parts=['Electricity:HVAC','InteriorEquipment:Electricity','InteriorLights:Electricity']
                if meta['tank_name']:parts.append('WaterSystems:Electricity')
                if meta['EV']['installed']:parts.append('ExteriorEquipment:Electricity')
                subtotals=[values(n)for n in parts]
                error=max(abs(facility[t]-sum(p[t]for p in subtotals))for t in expected)
                checks[side+'_meter_closure']=error<=max(1e-3,max(facility.values())*1e-8)
                details[side+'_meter_max_error_J']=error
                program_errors={}
                for key,mapping in meta['equipment_meter_mapping'].items():
                    actual=values('Electric Equipment Electricity Energy',key)
                    tasks=[t for t in meta['execution']['tasks']if t['asset_id']==mapping['asset_id'] and t['kind']==mapping['kind']]
                    wanted={t:mapping['watts']*600*int(any(x['start_min']<=t<x['end_min']for x in tasks))for t in expected}
                    program_errors[mapping['asset_id']]=max(abs(actual[t]-wanted[t])for t in expected)
                checks[side+'_program_energy']=all(e<1e-3 for e in program_errors.values())
                details[side+'_program_max_error_J']=program_errors
                details[side+'_HVAC_energy_kWh']={aid:sum(values('Zone Packaged Terminal Heat Pump Electricity Energy',key).values())/3600000
                                                for aid,key in meta['HVAC_equipment_mapping'].items()}
                needs={n['need_id']:n for n in meta.get('service_needs',[])}
                relevant=[b for b in meta['execution']['batches']if 480<=b['requested_program_end_min']<hi]
                checks[side+'_service_execution']=not meta['execution']['operation_failures'] and not meta['execution']['dropped_program_ids'] and all(b['program_executed'] and b['collected'] and (b['need_id']not in needs or b['requested_retrieval_end_min']<=needs[b['need_id']]['deadline_min'])for b in relevant)
                details[side+'_service_batches']=len(relevant)
                if meta['EV']['installed']:
                    ev=meta['EV'];actual=values('Exterior Equipment Electricity Energy','EXTERNAL_EV')
                    requested=dict(meta['EV_grid_steps'])
                    checks[side+'_EV_meter']=all(abs(actual[t]/3600000-requested.get(t,0))<1e-7 for t in expected if t>=480)
                    checks[side+'_EV_balance']=abs(ev['energy_balance_error_kWh'])<1e-8 and ev['stop_at_unexecutable_trip_min']is None and all(x['unserved_traction_kWh']<1e-8 and x['minimum_reserve_shortfall_kWh']<1e-8 for x in ev['trips'])
                    details[side+'_EV_balance_error_kWh']=ev['energy_balance_error_kWh']
                if meta['tank_name'] and meta.get('hot_water_model')=='standalone_hot_outlet':
                    temp=values('Water Heater Use Side Outlet Temperature',meta['tank_name'])
                    flow=values('Water Heater Use Side Mass Flow Rate',meta['tank_name'])
                    water=[]
                    for n in meta['water_needs']:
                        times=[t for t in expected if n['release_min']<=t<n['deadline_min']]
                        if not times:continue
                        minimum=min(temp[t]for t in times);mass=sum(flow[t]*600 for t in times)
                        water.append({'need_id':n['need_id'],'minimum_outlet_C':minimum,'delivered_mass_kg':mass,'requested_hot_outlet_liters':n['quantity'],
                                      'temperature_met':minimum+1e-5>=n['minimum_C'],'quantity_met_with_density_tolerance':abs(mass/n['quantity']-1)<.03})
                    checks[side+'_hot_water_service']=all(w['temperature_met'] and w['quantity_met_with_density_tolerance']for w in water)
                    details[side+'_water_services']=water
                details[side+'_facility_kWh']=sum(facility.values())/3600000
            # Every reported variable and meter must share the same pre-notice physical trajectory.
            ta,tb=traces['A'],traces['B'];checks['same_channel_set']=ta.keys()==tb.keys()
            pre=max((abs(a[1]-b[1])for k in ta.keys()&tb.keys()for a,b in zip(ta[k]['values'],tb[k]['values'])if a[0]<480),default=0)
            checks['pre_notice_trajectory_equal']=pre<1e-6;details['pre_notice_max_absolute_error']=pre
            checks['shared_shell_weather']=all(metas['A'][k]==metas['B'][k]for k in ('source_shell_sha256','weather_sha256','history_days','run_interval_min'))
            checks['recovery_horizon']=metas['A']['run_interval_min'][1]-max(metas['A']['intervention_last_request_min'],metas['B']['intervention_last_request_min'])>=7*1440
            recovery={}
            for key in sorted(ta.keys()&tb.keys()):
                if key.startswith(('Zone Mean Air Temperature|','Water Heater Tank Temperature|','Water Heater Final Temperature Node ')):
                    aa=dict(ta[key]['values']);bb=dict(tb[key]['values']);hi=metas['A']['run_interval_min'][1]
                    recovery[key]={'terminal_difference_C':bb[hi-10]-aa[hi-10],
                      'last24h_mean_absolute_difference_C':sum(abs(bb[t]-aa[t])for t in range(hi-1440,hi,10))/144}
            details['recovery_state_differences']=recovery
            checks['recovery_observable_residuals']=bool(recovery) and all(v['last24h_mean_absolute_difference_C']<=(.1 if key.startswith('Zone')else .5)
                                              and abs(v['terminal_difference_C'])<=(.1 if key.startswith('Zone')else .5)for key,v in recovery.items())
            if metas['A']['EV']['installed']:
                checks['EV_terminal_state_equal']=abs(metas['A']['EV']['end_energy_kWh']-metas['B']['EV']['end_energy_kWh'])<1e-8
            details['energy_comparison_scope']='paired interval electricity; recovery residuals reported; no human acceptance inferred'
        except (ValueError,KeyError,OSError,ZeroDivisionError)as e:
            checks['readback_complete']=False;details['reason']=str(e)
        records.append({'id':rid,'status':'passed'if checks and all(checks.values())else 'failed','checks':checks,'details':details})
    verify(compiled);verify(runs)
    return seal(out,{'schema':'eb.housing_physics.audit.v1','passed':bool(records) and all(r['status']=='passed'for r in records),
                     'compiled_manifest_sha256':sha(compiled/'MANIFEST.json'),'runs_manifest_sha256':sha(runs/'MANIFEST.json'),
                     'records':records,'recovery_tolerances_C':{'zone_air':.1,'tank_and_nodes':.5},
                     'empirical_calibration_claimed':False,'human_acceptance_inferred':False})


def reproduce(energyplus_dir, weather, output):
    """Public nonempty reference cases, built using only this package and EnergyPlus."""
    from .assembly import assemble
    ep=Path(energyplus_dir).resolve();weather=Path(weather).resolve()if weather else ep/'WeatherData/USA_IL_Chicago-OHare.Intl.AP.725300_TMY3.epw'
    if not weather.is_file():raise ValueError('EPW file required')
    out=fresh(output)
    stages=[]
    def gate(name,result,expected):
        stages.append({'stage':name,'records':len(result['records'])})
        if not result['records'] or any(r['status']!=expected for r in result['records']):raise ValueError('reproduction failed at '+name+'; inspect '+str(out/name))
    gate('shells',build_shell(HERE/'examples/shell_batch.json',out/'shells'),'shell_compiled')
    gate('worlds',assemble(HERE/'examples/world_batch.json',out/'shells',weather,out/'worlds'),'assembled')
    gate('compiled',compile_pairs(out/'worlds/physics_job.json',out/'compiled'),'compiled')
    gate('runs',run_pairs(out/'compiled',out/'runs',ep/'energyplus',sha(ep/'energyplus'),300),'completed')
    result=audit(out/'compiled',out/'runs',out/'audit')
    return seal(out,{'schema':'eb.housing_simulation.public_reproduction.v1','passed':result['passed'],'records':result['records'],
        'stages':stages,'historical_cohort_required':False,'engine_sha256':sha(ep/'energyplus'),'weather_sha256':sha(weather),
        'package_code_sha256':sha(HERE/'assembly.py')})
