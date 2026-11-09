"""Apply frozen criteria, with actual EV service fields and explicit water scope."""
import argparse

from national_idf.common import ROOT, read, require, save
from scripts import analyze_multicountry_numerics as numerical
from scripts.validate_multicountry_life import OUT, validate

PAIRS=[('2_vs_1min',(2,14,7),(1,14,7)),('5_vs_2min',(5,14,7),(2,14,7)),
       ('warmup_14_vs_28days',(2,14,7),(2,28,7)),('tail_7_vs_14days',(2,14,7),(2,14,14))]


def actual_ev_service(runtime):
    rows=runtime['EV']['departure_service'][:7]
    required=('departure_SOC_requirement_met','trip_executed','missing_traction_kWh')
    require(rows and all(all(k in r for k in required) for r in rows),'NUMERICAL_EV_SERVICE_FIELDS_MISSING')
    return [(r['departure_SOC_requirement_met'],r['trip_executed'],r['missing_traction_kWh']>0) for r in rows]


def compare_paths(left_paths, right_paths):
    """Same registered grid and criteria; include absent-EV inventories."""
    criteria=read(ROOT/'configs/study_protocol.json')['numerical_criteria']
    checks={};values={};effects=[]
    for paths in (left_paths,right_paths):
        energy=[]
        for p in paths:
            runtime=read(p/'RUNTIME.json')
            require(runtime['exit_code']==0 and not runtime['progress']['errors'],'NUMERICAL_RUN_FAILED')
            energy.append(sum(numerical.series(p,'Electricity:Facility').values())/3.6e6)
        effects.append(energy[1]-energy[0])
    for i,arm in enumerate(('baseline','intervention')):
        a,b=left_paths[i],right_paths[i]
        ga,gb=[numerical.series(p,'Electricity:Facility') for p in (a,b)]
        common=sorted(ga.keys()&gb.keys());require(common,'NUMERICAL_COMPARISON_EMPTY')
        ea,eb=[sum(g[k] for k in common)/3.6e6 for g in (ga,gb)]
        checks[arm+'_facility_energy']=abs(ea-eb)<=criteria['per_arm_energy_relative']*max(abs(eb),1e-9)
        values[arm+'_facility_kWh']={'left':ea,'right':eb,'relative_difference':abs(ea-eb)/max(abs(eb),1e-9)}
        for name,key,limit in [('Zone Mean Air Temperature','conditioned space',criteria['zone_mean_absolute_C']),
            ('Water Heater Tank Temperature','EB_WATER_water heater',criteria['tank_mean_absolute_C'])]:
            ga,gb=[numerical.series(p,name,key) for p in (a,b)];ks=sorted(ga.keys()&gb.keys())
            require(ks,'NUMERICAL_STATE_COMPARISON_EMPTY')
            mae=sum(abs(ga[k]-gb[k]) for k in ks)/len(ks)
            checks[arm+'_'+name]=mae<=limit;values[arm+'_'+name]={'MAE_C':mae,'limit_C':limit}
        ra,rb=[read(p/'RUNTIME.json') for p in (a,b)]
        if ra['EV'] is None or rb['EV'] is None:
            require(ra['EV'] is rb['EV'] is None,'NUMERICAL_EV_INVENTORY_CHANGED')
            checks[arm+'_EV_absent_not_simulated']=True
        else:checks[arm+'_EV_departure_conclusions']=actual_ev_service(ra)==actual_ev_service(rb)
        # Diagnostics do not silently introduce another accuracy criterion.
        for name in ('WaterSystems:Electricity','Cooling:Electricity','Heating:Electricity','Fans:Electricity'):
            ga,gb=[numerical.series(p,name) for p in (a,b)];ks=sorted(ga.keys()&gb.keys())
            aa,bb=[sum(g[k] for k in ks)/3.6e6 for g in (ga,gb)]
            values[arm+'_'+name]={'left_kWh':aa,'right_kWh':bb,'diagnostic_not_new_acceptance_threshold':True}
    limit=max(criteria['effect_absolute_kWh'],criteria['effect_relative']*abs(effects[1]))
    checks['paired_control_effect']=abs(effects[0]-effects[1])<=limit
    values['paired_effect_kWh']={'left':effects[0],'right':effects[1],'absolute_difference':abs(effects[0]-effects[1]),
                                'limit_kWh':limit,'sign_changed':effects[0]*effects[1]<0}
    return {'passed':all(checks.values()),'checks':checks,'values':values,
            'mixed_water_service_convergence_complete':False}


def execute(label, count=6):
    numerical.OUT=OUT;numerical.VARIANT='life'
    results={}
    for name,left,right in PAIRS:
        def paths(args):
            runs=[numerical.path(label,*args,arm) for arm in ('baseline','intervention')]
            if count!=6:runs=[p.parent/('four' if count==4 else 'five')/'run_v2' for p in runs]
            return runs
        result=compare_paths(paths(left),paths(right))
        result.update(left_variant=left,right_variant=right)
        result['water_service_convergence_not_inferred_from_tank_temperature']=True
        results[name]=result
    report={'schema':'national_idf.multicountry_life_numerical_checks.v1','results':results,
        'criteria':read(ROOT/'configs/study_protocol.json')['numerical_criteria'],
        'all_registered_energy_temperature_and_EV_checks_pass':all(r['passed'] for r in results.values()),
        'accuracy_thresholds_changed':False,'water_service_convergence_review_complete':False,
        'scope':'Same life and control instructions at fixed source dates;not a repair/waiver of old source-demand failures',
        'formal_admitted':False}
    report['installed_function_count']=count
    save(OUT/label/('NUMERICAL_COMPARISONS.json' if count==6 else f'NUMERICAL_COMPARISONS_{count}.json'),report)
    print(label,count,{name:r['passed'] for name,r in results.items()},flush=True)
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--labels',nargs='+',default=['US','ES','US_apartment'])
    p.add_argument('--inventories',nargs='+',type=int,choices=[4,5,6],default=[6]);args=p.parse_args()
    for label in args.labels:
        for count in args.inventories:execute(label,count)
