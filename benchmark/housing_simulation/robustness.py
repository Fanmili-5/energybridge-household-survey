"""Registered convergence and Morris screening on cohort-free reference worlds."""
import concurrent.futures
import copy
import math
from pathlib import Path
import random
import statistics

from .pipeline import HERE, read, save, sha, digest, fresh, build_shell, compile_pairs, run_pairs, seal


def airflow_balance(trace,environment,rooms):
    limits=read(HERE/'STUDY_PLAN.json')['pressure_network']
    expected=next(iter(trace.values()))['values'];axis=[t for t,v in expected]
    net={r:{t:0. for t in axis}for r in rooms};through=copy.deepcopy(net)
    for link in environment['links']:
        channels=[]
        for direction in ('1 to Node 2','2 to Node 1'):
            c=trace.get('AFN Linkage Node '+direction+' Mass Flow Rate|'+link['surface'])
            if c is None or c['unit']!='kg/s' or [t for t,v in c['values']]!=axis:raise ValueError('missing AFN flow channel:'+link['surface'])
            channels.append(dict(c['values']))
        for t in axis:
            a,b=(c[t]for c in channels)
            if min(a,b)<-1e-10:raise ValueError('negative directional AFN flow')
            for room,sign in ((link['from'],1),(link['to'],-1)):
                if room:
                    net[room][t]+=sign*(a-b);through[room][t]+=a+b
    residuals={r:max(abs(v)for v in n.values())for r,n in net.items()}
    passed=all(abs(v)<=limits['AFN_zone_balance_absolute_kg_s']+limits['AFN_zone_balance_relative']*through[r][t]for r,n in net.items()for t,v in n.items())
    return {'passed':passed,'maximum_absolute_residual_kg_s_by_zone':residuals,'links_checked':len(environment['links']),
            'absolute_tolerance_kg_s':limits['AFN_zone_balance_absolute_kg_s'],'relative_tolerance':limits['AFN_zone_balance_relative']}


def morris_design(plan):
    p=plan['morris'];rng=random.Random(p['seed']);names=sorted(p['parameters']);states=[];edges=[]
    delta=p['normalized_step']
    for trajectory in range(p['trajectories']):
        signs={n:rng.choice((-1,1))for n in names}
        x={n:rng.choice((0.,1/3))+(delta if signs[n]<0 else 0)for n in names}
        order=names[:];rng.shuffle(order);previous=None
        for step in range(len(names)+1):
            sid=f'morris_{trajectory}_{step}'
            settings={n:p['parameters'][n][0]+x[n]*(p['parameters'][n][1]-p['parameters'][n][0])for n in names}
            states.append({'id':sid,'normalized':dict(x),'settings':settings})
            if previous:edges.append({'from':previous,'to':sid,'parameter':order[step-1],'normalized_delta':signs[order[step-1]]*delta})
            previous=sid
            if step<len(names):x[order[step]]=round(x[order[step]]+signs[order[step]]*delta,14)
    return states,edges


def convergence(left,right,tail=False):
    """Paired effect B-A; common9day electricity/state interval for refinements."""
    criteria=read(HERE/'STUDY_PLAN.json')['comparison'];details={};passed=True
    for case in left:
        a,b=left[case],right[case];checks={}
        for side in ('A','B'):
            energy_a=a[side+'_kWh'];energy_b=b[side+'_kWh']
            if not tail:checks[side+'_energy']=abs(energy_b-energy_a)<=criteria['per_arm_energy_relative']*max(abs(energy_b),1e-9)
        effect_a=a['B_minus_A_kWh'];effect_b=b['B_minus_A_kWh']
        checks['paired_effect']=abs(effect_b-effect_a)<=max(criteria['effect_absolute_kWh'],criteria['effect_relative']*abs(effect_b))
        state_errors={}
        if not tail:
            for key,values in a['states'].items():
                other=b['states'][key]
                if len(values)!=len(other):raise ValueError('comparison interval mismatch')
                error=sum(abs(x-y)for x,y in zip(values,other))/len(values);state_errors[key]=error
                checks['state:'+key]=error<=(criteria['zone_mean_absolute_C']if key.startswith('Zone')else criteria['tank_mean_absolute_C'])
        ok=all(checks.values());passed=passed and ok
        details[case]={'passed':ok,'checks':checks,'effect_difference_kWh':effect_b-effect_a,'mean_absolute_state_difference_C':state_errors,
                       'per_arm_energy_difference_kWh':{s:b[s+'_kWh']-a[s+'_kWh']for s in ('A','B')}}
    return {'passed':passed,'cases':details}


def summarize(folder,tail=False):
    result={};run=read(folder/'runs/MANIFEST.json')
    for item in read(folder/'compiled/MANIFEST.json')['records']:
        rid=item['id'];case={'states':{}}
        for side in ('A','B'):
            trace=read(folder/'runs'/rid/side/'TRACE.json.gz');limit=math.inf if tail else read(HERE/'STUDY_PLAN.json')['comparison']['common_interval_min']
            case[side+'_kWh']=sum(v for t,v in trace['Electricity:Facility|']['values']if t<limit)/3600000
            for key,c in trace.items():
                if key.startswith(('Zone Mean Air Temperature|','Water Heater Tank Temperature|','Water Heater Final Temperature Node ')):
                    case['states'][key+'|'+side]=[v for t,v in c['values']if t<limit]
        case['B_minus_A_kWh']=case['B_kWh']-case['A_kWh'];result[rid]=case
    return result


def public_study(energyplus_dir,output,workers=3,weather=None,weather_metadata=None):
    from .assembly import assemble
    from .validation import audit
    ep=Path(energyplus_dir).resolve();engine=ep/'energyplus';weather=Path(weather).resolve()if weather else ep/'WeatherData/USA_IL_Chicago-OHare.Intl.AP.725300_TMY3.epw'
    plan=read(HERE/'STUDY_PLAN.json')
    if type(workers)is not int or not 1<=workers<=plan['max_workers']:raise ValueError('workers outside registered limit')
    out=fresh(output);save(out/'REGISTERED_PLAN.json',plan)
    world=read(HERE/'examples/world_batch.json');world['settings'].update(plan['reference'])
    if weather_metadata:world['weather_source']=read(weather_metadata)
    for household in world['households']:
        summer=household['cases'][0];winter=copy.deepcopy(summer);winter['case_id']=summer['case_id'].replace('summer','winter');winter['date']='2025-11-15'
        household['cases']=[summer,winter]
    save(out/'world_input.json',world)
    shells=build_shell(HERE/'examples/shell_batch.json',out/'shells')
    worlds=assemble(out/'world_input.json',out/'shells',weather,out/'worlds')
    if any(r['status']!='shell_compiled'for r in shells['records'])or any(r['status']!='assembled'for r in worlds['records']):raise ValueError('study input construction rejected;inspect manifests')
    job=read(out/'worlds/physics_job.json');job['resource_root']=str(out/'worlds')
    states,edges=morris_design(plan)
    configs=[{'id':'history_'+str(h),'settings':{'history_days':h}}for h in plan['history_days']]
    def run(config):
        folder=out/config['id'];folder.mkdir();current=copy.deepcopy(job);current['settings'].update(config['settings']);save(folder/'job.json',current)
        compiled=compile_pairs(folder/'job.json',folder/'compiled')
        if any(r['status']!='compiled'for r in compiled['records']):raise ValueError('study compilation failed:'+config['id'])
        runs=run_pairs(folder/'compiled',folder/'runs',engine,sha(engine),plan['run_timeout_s'])
        if any(r['status']!='completed'for r in runs['records']):raise ValueError('study execution failed:'+config['id'])
        checked=audit(folder/'compiled',folder/'runs',folder/'audit')
        save(folder/'SUMMARY.json',{'id':config['id'],'passed':checked['passed'],'settings':current['settings'],'audit_manifest_sha256':sha(folder/'audit/MANIFEST.json')})
        print(config['id']+':'+str(checked['passed']),flush=True)
        return config['id'],summarize(folder),checked
    results={};audits={}
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers)as pool:
        for name,result,checked in pool.map(run,configs):results[name]=result;audits[name]=checked
    comparisons={}
    for a,b in zip(plan['history_days'],plan['history_days'][1:]):comparisons[f'history_{a}_vs_{b}']=convergence(results['history_'+str(a)],results['history_'+str(b)])
    step=None;prior='history_112';history=None;tail={'passed':False}
    # A step is admitted only when refinement, history and recovery all pass.
    # If a candidate fails any gate, continue down the registered ladder.
    for a,b in zip(plan['simulation_timestep_min'],plan['simulation_timestep_min'][1:]):
        name,result,checked=run({'id':'timestep_'+str(b),'settings':{'simulation_timestep_min':b}});results[name]=result;audits[name]=checked
        comparison=convergence(results[prior],result);comparisons[f'timestep_{a}_vs_{b}']=comparison
        if comparison['passed']:
            hname='history_168_step_'+str(a)
            hname,hresult,hchecked=run({'id':hname,'settings':{'history_days':168,'simulation_timestep_min':a}});results[hname]=hresult;audits[hname]=hchecked
            confirmed=convergence(results[prior],hresult);comparisons['deployed_history_112_vs_168_step_'+str(a)]=confirmed
            if confirmed['passed']:
                tname,tresult,tchecked=run({'id':'tail_16_step_'+str(a),'settings':{'history_days':112,'simulation_timestep_min':a,'tail_days':16}});results[tname]=tresult;audits[tname]=tchecked
                tail=convergence(summarize(out/prior,tail=True),summarize(out/tname,tail=True),tail=True);comparisons['tail_9_vs_16_step_'+str(a)]=tail
                if tail['passed']:step=a;history=112;ref_name=prior;break
        prior=name
    if step is None:raise ValueError('combined solver/history/recovery ladder did not converge;retain all failed candidate outputs')
    selected={'history_days':112,'simulation_timestep_min':step}
    configurations=[{'id':'pressure_network','settings':{**selected,'airflow_model':'pressure_network'}},
                    *[{**state,'settings':{**selected,**state['settings']}}for state in states]]
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers)as pool:
        for name,result,checked in pool.map(run,configurations):results[name]=result;audits[name]=checked
    elementary={case:{name:{metric:[]for metric in plan['morris']['outputs']}for name in plan['morris']['parameters']}for case in results['history_112']}
    for edge in edges:
        for case,parameters in elementary.items():
            for metric,values in parameters[edge['parameter']].items():values.append((results[edge['to']][case][metric]-results[edge['from']][case][metric])/edge['normalized_delta'])
    screening={case:{name:{metric:{'mu':statistics.mean(v),'mu_star':statistics.mean(map(abs,v)),'sigma':statistics.stdev(v),'n':len(v)}for metric,v in metrics.items()}for name,metrics in parameters.items()}for case,parameters in elementary.items()}
    sensitivity_valid=all(len(v)==plan['morris']['trajectories']and all(math.isfinite(x)for x in v)for p in elementary.values()for m in p.values()for v in m.values())
    effects={case:{name:round(result[case]['B_minus_A_kWh'],9)for name,result in results.items()}for case in results['history_112']}
    records=[{'id':name,'passed':checked['passed'],'case_count':len(checked['records']),'audit_manifest_sha256':sha(out/name/'audit/MANIFEST.json')}for name,checked in audits.items()]
    numerical_ok=history is not None and step is not None and tail['passed']
    report={'schema':'eb.housing_simulation.robustness.v1','passed':all(r['passed']for r in records)and numerical_ok and sensitivity_valid,
        'registered_plan_sha256':sha(out/'REGISTERED_PLAN.json'),'code_tree_sha256':digest({str(p.relative_to(HERE)):sha(p)for p in sorted(HERE.rglob('*.py'))}),
        'weather_sha256':sha(weather),'engine_sha256':sha(engine),'historical_cohort_required':False,'records':records,
        'simulated_arms':sum(2*r['case_count']for r in records),'numerical_convergence_passed':numerical_ok,
        'reference_configuration_id':ref_name,'sensitivity_numeric_settings':selected,'selected_reference':{'history_days':history,'tail_days':9 if tail['passed']else None,'simulation_timestep_min':step},
        'comparisons':comparisons,'morris_design':{'states':states,'edges':edges},'morris_screening':screening,'sensitivity_analysis_complete':sensitivity_valid,
        'paired_effects_B_minus_A_kWh':effects,'effect_sign_changes':{case:min(values.values())<0<max(values.values())for case,values in effects.items()},
        'empirical_Chinese_calibration_claimed':False,'population_generalization_claimed':False}
    save(out/'REPORT.json',report)
    return seal(out,{k:v for k,v in report.items()if k not in ('comparisons','morris_screening','paired_effects_B_minus_A_kWh','morris_design')})
