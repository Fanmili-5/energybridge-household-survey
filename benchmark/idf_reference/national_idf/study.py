"""Registered reference experiments, separate from eventual A/B strategy evaluation."""
from __future__ import annotations
import copy
import datetime as dt
from pathlib import Path
import numpy as np
from .common import ROOT,read,save,require,sha,digest
from .compiler import compile_case
from .runtime import execute,audit,SQL


def grid(series,step_min=10):
    groups={}
    for row,v in zip(series['rows'],series['values']):
        _,month,day,hour,minute,interval,_=row
        # SQLite Time uses civil hour 0..24 plus minute 0..59, unlike EPW's
        # hour-ending 1..24 convention. Every value labels an interval END.
        total=hour*60+minute
        key=(month,day,(total-1)//step_min)
        groups.setdefault(key,[]).append((float(v),interval))
    if series['type'].lower()=='sum':return {k:sum(v for v,t in vs)for k,vs in groups.items()}
    return {k:sum(v*t for v,t in vs)/sum(t for v,t in vs)for k,vs in groups.items()}


def compare(left,right,criteria):
    checks={};differences={}
    for arm in ('reference','exercise'):
        la=read(left/arm/'AUDIT.json');ra=read(right/arm/'AUDIT.json')
        lw=la['metrics']['mixed_water'];rw=ra['metrics']['mixed_water']
        checks[arm+'_water_service_conclusion']=(lw['service_failure_intervals']>0)==(rw['service_failure_intervals']>0)
        if lw['minimum_report_interval_C']is not None and rw['minimum_report_interval_C']is not None:
            difference=abs(lw['minimum_report_interval_C']-rw['minimum_report_interval_C'])
            differences[arm+'_minimum_water_C']=difference
            checks[arm+'_minimum_water_temperature']=difference<=criteria['tank_mean_absolute_C']
        le=read(left/arm/'compiled/execution_ledger.json')['ev']['failures']
        re=read(right/arm/'compiled/execution_ledger.json')['ev']['failures']
        checks[arm+'_ev_service_conclusion']=bool(le)==bool(re)
        a=SQL(left/arm/'run/eplusout.sql');b=SQL(right/arm/'run/eplusout.sql')
        try:
            ga=grid(a.series('Electricity:Facility'));gb=grid(b.series('Electricity:Facility'))
            common=ga.keys()&gb.keys();require(common,'COMPARISON_EMPTY_ENERGY_GRID')
            ea=sum(ga[k]for k in common)/3600000;eb=sum(gb[k]for k in common)/3600000
            checks[arm+'_energy']=abs(eb-ea)<=criteria['per_arm_energy_relative']*max(abs(eb),1e-9)
            differences[arm+'_kWh']=eb-ea
            channels=[d for d in a.dictionary if d[1]=='Zone Mean Air Temperature' or d[1]=='Water Heater Temperature Node 1']
            for d in channels:
                ga=grid(a.series(d[1],d[2]));gb=grid(b.series(d[1],d[2]));common=sorted(ga.keys()&gb.keys())
                require(common,'COMPARISON_EMPTY_GRID')
                mae=float(np.mean([abs(ga[k]-gb[k])for k in common]))
                limit=criteria['zone_mean_absolute_C']if d[1]=='Zone Mean Air Temperature'else criteria['tank_mean_absolute_C']
                checks[arm+':'+d[1]+':'+d[2]]=mae<=limit
                differences[arm+':'+d[1]+':'+d[2]]=mae
        finally:a.close();b.close()
    def effect(folder):
        x=SQL(folder/'exercise/run/eplusout.sql');y=SQL(folder/'reference/run/eplusout.sql')
        try:return x.energy('Electricity:Facility')-y.energy('Electricity:Facility')
        finally:x.close();y.close()
    e1,e2=effect(left),effect(right)
    checks['paired_effect']=abs(e2-e1)<=max(criteria['effect_absolute_kWh'],criteria['effect_relative']*abs(e2))
    return {'passed':all(checks.values()),'checks':checks,'differences':differences,
            'effects_kWh':[e1,e2],'effect_sign_changed':e1*e2<0}


def run_pair(case,selection,folder,engine,protocol,*,mode='formal'):
    from .governance import reference_only
    reference_only(mode)
    folder.mkdir(parents=True,exist_ok=False);outputs={}
    for arm in ('reference','exercise'):
        c=copy.deepcopy(case);c['case_id']+='-'+arm
        if arm=='exercise':
            event=dt.date.fromisoformat(c['run']['start_date'])+dt.timedelta(days=protocol['intervention']['relative_day'])
            for field,delta in [('heat_sp',-2),('cool_sp',2)]:
                c['controls'].setdefault('dated_overrides',[]).append({'date':event.isoformat(),'field':field,
                  'start_min':1080,'end_min':1140,'value':c['controls']['heating_C'if field=='heat_sp'else'cooling_C']+delta})
        dest=folder/arm;dest.mkdir()
        try:
            # Selection remains frozen during sensitivity; bind the changed physical context explicitly.
            s=copy.deepcopy(selection)
            s['design_environment_hash']=digest({'environment':c['environment'],'design':c['design']})
            s['held_fixed_for_registered_sensitivity']=True
            compiled=dest/'compiled';run=dest/'run'
            compile_case(c,compiled,engine,s,mode=mode);r=execute(compiled,run,engine,mode=mode)
            if r['passed_numerical_execution']:
                a=audit(compiled,run);save(dest/'AUDIT.json',a)
                outputs[arm]={'passed':a['engineering_passed'],'run_sha256':sha(run/'RUN.json'),
                              'facility_kWh':a['metrics']['facility_kWh']}
            else:outputs[arm]={'passed':False,'native':r}
        except Exception as e:outputs[arm]={'passed':False,'error':str(e)}
    passed=all(r['passed']for r in outputs.values())
    # Future controls cannot affect the common pre-intervention thermal history.
    prefix={}
    if passed:
        left=SQL(folder/'reference/run/eplusout.sql');right=SQL(folder/'exercise/run/eplusout.sql')
        try:
            event=dt.date.fromisoformat(case['run']['start_date'])+dt.timedelta(days=2)
            for z in case['environment']['unit_zones']:
                a=grid(left.series('Zone Mean Air Temperature',z));b=grid(right.series('Zone Mean Air Temperature',z))
                ks=[k for k in a if (k[0],k[1],k[2])<(event.month,event.day,108)]
                prefix[z]=bool(ks)and all(abs(a[k]-b[k])<1e-8 for k in ks)
        finally:left.close();right.close()
    result={'arms':outputs,'passed':passed and all(prefix.values()),'common_prefix':prefix,
      'execution_mode':'engineering_reference','formal_admitted':False,
      'protocol_sha256':sha(ROOT/'configs/study_protocol.json'),'not_final_AB_strategy':True}
    save(folder/'PAIR.json',result);return result


def run_study(case_path,selection_path,out,engine,*,seasons=None,full=True,mode='formal'):
    from .governance import reference_only
    reference_only(mode)
    require(not out.exists(),'OUTPUT_EXISTS');out.mkdir(parents=True)
    protocol=read(ROOT/'configs/study_protocol.json');base=read(case_path);selection=read(selection_path)
    save(out/'REGISTERED_PROTOCOL.json',protocol)
    results=[]
    for season,start in protocol['seasons'].items():
        if seasons and season not in seasons:continue
        c=copy.deepcopy(base);c['run'].update(start_date=start,
          end_date=(dt.date.fromisoformat(start)+dt.timedelta(days=6)).isoformat(),reporting='Timestep',purpose='registered_sensitivity')
        season_results={}
        comparisons={};selected_step=None
        def execute_config(name,settings):
            variant=copy.deepcopy(c);variant['run'].update(settings)
            r=run_pair(variant,selection,out/season/name,engine,protocol,mode=mode);season_results[name]=r
            print(base['case_id'],season,name,r['passed'],flush=True)
            return r
        for coarse,fine in [(5,2),(2,1)]:
            for step in (coarse,fine):
                if 'step'+str(step)not in season_results:execute_config('step'+str(step),{'solver_step_min':step})
            if not all(season_results['step'+str(s)]['passed']for s in (coarse,fine)):continue
            comparison=compare(out/season/f'step{coarse}',out/season/f'step{fine}',protocol['numerical_criteria'])
            comparisons[f'step{coarse}_vs{fine}']=comparison
            if not comparison['passed']:continue
            if full:
                name=f'warmup28_step{coarse}'
                r=execute_config(name,{'solver_step_min':coarse,'warmup_min_days':28,'warmup_max_days':84})
                if not r['passed']:continue
                warm=compare(out/season/f'step{coarse}',out/season/name,protocol['numerical_criteria'])
                comparisons[name]=warm
                name=f'tail14_step{coarse}'
                r=execute_config(name,{'solver_step_min':coarse,
                  'end_date':(dt.date.fromisoformat(start)+dt.timedelta(days=13)).isoformat()})
                if not r['passed']:continue
                tail=compare(out/season/f'step{coarse}',out/season/name,protocol['numerical_criteria'])
                comparisons[name]=tail
                if not(warm['passed']and tail['passed']):continue
            selected_step=coarse;break
        save(out/season/'NUMERICAL_COMPARISONS.json',{'selected_solver_step_min':selected_step,
          'comparisons':comparisons,'complete_warmup_and_tail_confirmation':full and selected_step is not None})
        c['run']['solver_step_min']=selected_step or 1
        if full:
            for parameter,values in protocol['parameter_stresses'].items():
                for value in values:
                    variant=copy.deepcopy(c)
                    if parameter=='reference_ach':variant['environment'][parameter]=value
                    elif parameter=='neighbor_C_shift':
                        for key in ['winter_C','summer_C','shoulder_C']:variant['environment']['neighbors'][key]+=value
                    else:variant['environment']['parameter_stress']={parameter:value}
                    name=f'{parameter}-{value}';r=run_pair(variant,selection,out/season/name,engine,protocol,mode=mode)
                    season_results[name]=r;print(base['case_id'],season,name,r['passed'],flush=True)
            variant=copy.deepcopy(c);variant['environment']['airflow_model']='pressure_network'
            season_results['pressure_network']=run_pair(variant,selection,out/season/'pressure_network',engine,protocol,mode=mode)
            comparisons['parameter_stresses']={}
            baseline_name='step'+str(selected_step or 1)
            for name,r in season_results.items():
                if name==baseline_name or not r['passed']or name.startswith(('step','warmup','tail')):continue
                comparisons['parameter_stresses'][name]=compare(out/season/baseline_name,out/season/name,protocol['numerical_criteria'])
            save(out/season/'SENSITIVITY_COMPARISONS.json',comparisons['parameter_stresses'])
        results.append({'season':season,'configurations':season_results,'selected_solver_step_min':selected_step,
                        'numerical_admitted':full and selected_step is not None})
    report={'schema':'national_idf.registered_study_results.v1','case_sha256':sha(case_path),
      'execution_mode':'engineering_reference','formal_admitted':False,
      'selection_sha256':sha(selection_path),'protocol_sha256':sha(ROOT/'configs/study_protocol.json'),
      'full_matrix_requested':full,'results':results,'empirical_calibration':False,
      'all_planned_execution_checks_passed':all(r['passed']for s in results for r in s['configurations'].values()),
      'numerical_admitted':full and all(s['numerical_admitted']for s in results),
      'numerical_convergence_not_inferred_from_execution_only':True}
    save(out/'STUDY.json',report);return report
