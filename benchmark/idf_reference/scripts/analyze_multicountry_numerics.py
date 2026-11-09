"""Apply the existing numerical criteria to native grids and fixed test pairs."""
import argparse
from functools import lru_cache
import sqlite3
from national_idf.common import ROOT, read, save, require
from national_idf.study import grid

OUT=ROOT/'reports/multicountry_idf_20261107'
VARIANT='legacy'


def path(country,step=2,warmup=14,days=7,arm='intervention'):
    return OUT/('numerics_'+VARIANT if VARIANT!='legacy' else 'numerics')/f'{country}_s{step}_w{warmup}_d{days}_{arm}'/'run'


@lru_cache(maxsize=256)
def series(folder,name,key=None):
    # Select only the required native channel, keeping the same registered
    # grid calculation without loading every report series into Python.
    with sqlite3.connect((folder/'output/eplusout.sql').resolve().as_uri()+'?mode=ro',uri=True) as db:
        query='SELECT ReportDataDictionaryIndex,Type FROM ReportDataDictionary WHERE lower(Name)=lower(?)'
        params=[name]
        if key is not None:query+=' AND lower(KeyValue)=lower(?)';params.append(key)
        found=db.execute(query,params).fetchall();require(len(found)==1,'NUMERICAL_CHANNEL_CARDINALITY',[name,key])
        index,kind=found[0]
        rows=db.execute('''SELECT t.TimeIndex,t.Month,t.Day,t.Hour,t.Minute,t.Interval,r.Value
            FROM ReportData r JOIN Time t USING(TimeIndex) JOIN EnvironmentPeriods e USING(EnvironmentPeriodIndex)
            WHERE r.ReportDataDictionaryIndex=? AND COALESCE(t.WarmupFlag,0)=0 AND e.EnvironmentType=3
            ORDER BY t.TimeIndex''',(index,)).fetchall()
    require(rows,'NUMERICAL_CHANNEL_EMPTY',[name,key])
    return grid({'rows':rows,'values':[r[6] for r in rows],'type':kind},read(ROOT/'configs/study_protocol.json')['comparison_grid_min'])


def compare(country,left,right):
    criteria=read(ROOT/'configs/study_protocol.json')['numerical_criteria'];checks={};values={};effects=[]
    for label,args in [('left',left),('right',right)]:
        arm_energy=[]
        for arm in ('baseline','intervention'):
            folder=path(country,*args,arm)
            r=read(folder/'RUNTIME.json');require(r['exit_code']==0 and not r['progress']['errors'],'NUMERICAL_RUN_FAILED')
            arm_energy.append(sum(series(folder,'Electricity:Facility').values())/3.6e6)
        effects.append(arm_energy[1]-arm_energy[0])
    for arm in ('baseline','intervention'):
        a,b=path(country,*left,arm),path(country,*right,arm)
        ga,gb=series(a,'Electricity:Facility'),series(b,'Electricity:Facility');common=sorted(ga.keys()&gb.keys())
        require(common,'NUMERICAL_COMPARISON_EMPTY')
        ea,eb=[sum(g[k] for k in common)/3.6e6 for g in (ga,gb)]
        checks[arm+'_facility_energy']=abs(ea-eb)<=criteria['per_arm_energy_relative']*max(abs(eb),1e-9)
        values[arm+'_facility_kWh']={'left':ea,'right':eb,'relative_difference':abs(ea-eb)/max(abs(eb),1e-9)}
        for name,key,limit in [('Zone Mean Air Temperature','conditioned space',criteria['zone_mean_absolute_C']),
                               ('Water Heater Tank Temperature','EB_WATER_water heater',criteria['tank_mean_absolute_C'])]:
            ga,gb=series(a,name,key),series(b,name,key);ks=sorted(ga.keys()&gb.keys())
            mae=sum(abs(ga[k]-gb[k]) for k in ks)/len(ks)
            checks[arm+'_'+name]=mae<=limit;values[arm+'_'+name]={'MAE_C':mae,'limit_C':limit}
        for name in ('WaterSystems:Electricity','Cooling:Electricity','Heating:Electricity','Fans:Electricity'):
            ga,gb=series(a,name),series(b,name);ks=sorted(ga.keys()&gb.keys());aa,bb=[sum(g[k] for k in ks)/3.6e6 for g in (ga,gb)]
            values[arm+'_'+name]={'left_kWh':aa,'right_kWh':bb,'relative_difference':abs(aa-bb)/max(abs(bb),1e-9),
                                    'diagnostic_not_new_acceptance_threshold':True}
        ra,rb=read(a/'RUNTIME.json'),read(b/'RUNTIME.json')
        aa=ra['EV']['departure_service'];bb=rb['EV']['departure_service']
        checks[arm+'_EV_departure_conclusions']=[v.get('target_reached') for v in aa[:7]]==[v.get('target_reached') for v in bb[:7]]
    limit=max(criteria['effect_absolute_kWh'],criteria['effect_relative']*abs(effects[1]))
    checks['paired_control_effect']=abs(effects[0]-effects[1])<=limit
    values['paired_effect_kWh']={'left':effects[0],'right':effects[1],'absolute_difference':abs(effects[0]-effects[1]),'limit_kWh':limit,'sign_changed':effects[0]*effects[1]<0}
    return {'passed':all(checks.values()),'checks':checks,'values':values,'left_variant':left,'right_variant':right,
            'mixed_water_service_convergence_complete':False}


def main():
    global VARIANT
    parser=argparse.ArgumentParser();parser.add_argument('--variant',choices=['legacy','EB_original','EB_system1','EB_defaults'],default='legacy')
    parser.add_argument('--labels',nargs='+',default=['US','ES']);args=parser.parse_args();VARIANT=args.variant
    results={}
    for country in args.labels:
        results[country]={name:compare(country,a,b) for name,a,b in [
            ('2_vs_1min',(2,14,7),(1,14,7)),('5_vs_2min',(5,14,7),(2,14,7)),
            ('warmup_14_vs_28days',(2,14,7),(2,28,7)),('tail_7_vs_14days',(2,14,7),(2,14,14))]}
        print(country,{name:value['passed'] for name,value in results[country].items()})
    suffix='' if args.labels==['US','ES'] else '__'+'_'.join(args.labels)
    save(OUT/('NUMERICAL_COMPARISONS_'+VARIANT+suffix+'.json' if VARIANT!='legacy' else 'NUMERICAL_COMPARISONS'+suffix+'.json'),{'schema':'national_idf.multicountry_numerical_comparisons.v1',
        'criteria':read(ROOT/'configs/study_protocol.json')['numerical_criteria'],'results':results,
        'accuracy_thresholds_changed':False,'formal_admitted':False,'full_numerical_acceptance_complete':False})


if __name__=='__main__':main()
