"""Produce a continuous normal-A calendar for1000 worlds, then derive10000 cases."""
import argparse
import collections
import copy
import math
import shutil
from concurrent.futures import ProcessPoolExecutor
from common import *
from design import resource_world,continuous_A


TIME_KEYS=('start_min','end_min','release_min','deadline_min','delivery_deadline_min','connection_start_min','departure_min','actual_charge_end_min','load_min','unload_min')
def relative(item,base):
    result=copy.deepcopy(item)
    for key in TIME_KEYS:
        if key in result:result[key]-=base
    return result

def episode(w,year,date,year_path,year_sha):
    base=origin(date);lo=base-1440;hi=base+3*1440
    controls=[c for day in year['days'].values()for c in day['controls']if c['start_min']<hi and c['end_min']>lo]
    ops=[o for o in year['operations']if lo<=o['start_min']<hi]
    tasks=[t for t in year['tasks']if t['start_min']<hi and t['end_min']>lo]
    ids={x['need_id']for x in tasks+ops+controls if 'need_id'in x}
    needs=[n for day in year['days'].values()for n in day['needs']if n['need_id']in ids or lo<=n['release_min']<hi]
    contexts=[copy.deepcopy(year['days'][str(date+dt.timedelta(days=i))])for i in range(-1,3)]
    for d in contexts:
        d['needs']=[relative(n,base)for n in d['needs']];d['controls']=[relative(c,base)for c in d['controls']]
    target=year['days'][str(date)];owned=target['needs'];counts=collections.Counter(n['kind']for n in owned)
    signature={'task_counts':{k:counts[k]for k in ('washer','dryer','dishwasher','water_heater')},
        'laundry_kg':round(target['textiles']['washed_kg'],1),
        'trip_kWh':target['activity']['transport']['traction_kWh']if target['activity']['transport']else 0.,
        'HVAC_mode_counts':dict(collections.Counter(n['mode']for n in owned if n['kind']=='ac')),
        'HVAC_room_minutes_30min_bins':round(sum(n['quantity']for n in owned if n['kind']=='ac')/30),
        'program_two_hour_phase_bins':sorted((t['kind'],(t['start_min']-base)//120)for t in year['tasks']if t['need_id']in{n['need_id']for n in owned}),
        'outside_person_hours':round(sum(i['end_min']-i['start_min']for seq in target['activity']['member_calendars'].values()for i in seq if i['location']=='outside')/60)}
    signals={}
    for device in w['parameter_pack']['devices']:
        if'ac'not in device['types']:continue
        relevant=[c for c in controls if c['asset_id']==device['asset_id']and c['kind']=='ac_setpoint']
        channels={'available':[],'heat_sp':[],'cool_sp':[],'fan_mode':[]}
        for minute in range(lo,hi,10):
            control=next((c for c in relevant if c['start_min']<=minute<c['end_min']),None)
            channels['available'].append(int(control is not None));channels['fan_mode'].append(control['fan_operating_mode']if control else 0)
            channels['heat_sp'].append(control['heating_setpoint_C']if control else 5.)
            channels['cool_sp'].append(control['cooling_setpoint_C']if control else 50.)
        signals[device['asset_id']]=channels
    return {'schema':'eb.normal_A_case.v40','case_id':w['household_id']+'__'+str(date),'household_id':w['household_id'],'date':str(date),
            'timeline_origin':'local midnight of case date;display/evaluation08:00 through next08:00;negative and>1440 timestamps retained',
            'source_world_content_sha256':w['world_content_sha256'],'parameter_pack_sha256':w['parameter_pack_sha256'],
            'year_A_path':year_path,'year_A_sha256':year_sha,'common_history_start_date':str(date-dt.timedelta(days=7)),
            'HVAC_signal_start_min':-1440,'HVAC_signal_step_min':10,'HVAC_signals':signals,
            'days':contexts,'needs_A':[relative(n,base)for n in needs],
            'A':{'tasks':[relative(t,base)for t in tasks],'operations':[relative(o,base)for o in ops],
                 'controls':[relative(c,base)for c in controls],'changed_controls':[]},
            'substantive_service_signature':signature,'normal_A_before_B':True,'B_generated':False,'physical_delivery_validated':False}


from functools import lru_cache
@lru_cache(maxsize=1)
def parent_records():return {r['household_id']:r for r in read(OUT.parent/'normal_A_v38_20261016/A_BINDINGS10000.json')['records']}

def one(job):
    row,run,signature=job;run=Path(run);hid=row['household_id'];record=run/'records'/(hid+'.json')
    if record.exists():return read(record)
    try:
        path=MASTER/row['world_path']
        if sha(path)!=row['world_sha256']:raise ValueError('MASTER_WORLD_CHANGED')
        source=parent_records()[hid]
        parent=OUT.parent/'normal_A_v38_20261016'
        w=resource_world(read(parent/source['A_world_path']));wp=run/'worlds'/(hid+'.json');save(wp,w)
        hp=run/'HVAC_components'/(hid+'.json');hp.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(parent/source['HVAC_components_path'],hp)
        year=continuous_A(w);journal={'upstream_calendar_rebuilt':True,'parent_annual_A_read':False,'stable_joint_habits':w['living_habits']}
        year['schema']='eb.continuous_normal_A.v40'
        year['previous_A_annual_sha256_for_comparison_only']=source['annual_A_sha256']
        jp=run/'regeneration'/(hid+'.json');save(jp,{'household_id':hid,'parent_annual_A_sha256':source['annual_A_sha256'],'changes':journal,'family_and_hardware_preserved':True,'dated_calendars_needs_visits_and_programs_rebuilt':True,'physical_acceptance':False})
        yp=run/'annual_A'/(hid+'.json');save(yp,year);ys=sha(yp)
        cases=[]
        for selected in w['random10_date_selection']['dates']:
            date=dt.date.fromisoformat(selected['date']);case=episode(w,year,date,str(yp.relative_to(OUT)),ys)
            cp=run/'cases'/(case['case_id']+'.json');save(cp,case)
            cases.append({'case_id':case['case_id'],'date':str(date),'path':str(cp.relative_to(OUT)),'sha256':sha(cp),
                          'service_signature':case['substantive_service_signature']})
        result={'household_id':hid,'passed':True,'type':row['type'],'master_world_path':row['world_path'],'master_world_sha256':row['world_sha256'],
                'A_world_path':str(wp.relative_to(OUT)),'A_world_sha256':sha(wp),'HVAC_components_path':str(hp.relative_to(OUT)),'HVAC_components_sha256':sha(hp),
                'annual_A_path':str(yp.relative_to(OUT)),'annual_A_sha256':ys,'cases':cases,
                'unique_substantive_days':len({digest(c['service_signature'])for c in cases}),
                'deferred_laundry_count':len(year['deferred_laundry']),'max_dirty_wait_days':max(d['textiles']['oldest_days']for d in year['days'].values())}
    except Exception as error:
        result={'household_id':hid,'passed':False,'error':str(error),'rules_sha256':signature}
    save(record,result);return result


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--workers',type=int,default=4);parser.add_argument('--limit',type=int,default=1000);args=parser.parse_args()
    verify_inputs();signature=rules_id();root=OUT/'runs'/signature[:16]
    for source in list((OUT/'code').glob('*.py'))+[OUT/'GENERATION_RULES.json',OUT/'INPUT_LOCK.json',OUT/'USER_DECISIONS.json']:
        target=root/'source_snapshot'/source.name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,target)
    save(root/'RUN.json',{'rules_sha256':signature,'household_limit':args.limit,'B_generated':False,'EP_started':0})
    rows=read(MASTER/'WORLD_BINDINGS1000.json')['records'][:args.limit];records=[]
    with ProcessPoolExecutor(max_workers=args.workers)as pool:
        for r in pool.map(one,[(r,str(root),signature)for r in rows]):
            records.append(r)
            if len(records)%10==0:print({'processed':len(records),'passed':sum(r['passed']for r in records)},flush=True)
    if rules_id()!=signature:raise RuntimeError('GENERATOR_CHANGED_DURING_RUN')
    failed=[r for r in records if not r['passed']]
    report={'households':len(records),'passed':len(records)-len(failed),'failures':failed,'rules_sha256':signature,
            'cases_written':sum(len(r.get('cases',[]))for r in records),'records':records,'EP_started':0}
    save(root/'BUILD_REVIEW.json',report)
    print(canonical({k:v for k,v in report.items()if k!='records'}),flush=True)
    if failed:raise SystemExit(2)
    if len(records)==1000 and not read(OUT/'GENERATION_RULES.json').get('date_mobility_decision_pending',False):
        save(OUT/'A_BINDINGS10000.json',{'schema':'eb.normal_A_bindings.v40','rules_sha256':signature,'households':1000,'cases':10000,'records':records})
        ids={r['household_id']for r in read(MASTER/'SUBSET50.json')['records']}
        subset=[r for r in records if r['household_id']in ids]
        save(OUT/'SUBSET50.json',{'schema':'eb.normal_A_subset.v40','records':subset,'type_counts':dict(collections.Counter(r['type']for r in subset)),
                                'same_master_household_ids':True,'same_A_files_and_hashes':True,'separate_generation':False})

if __name__=='__main__':main()
