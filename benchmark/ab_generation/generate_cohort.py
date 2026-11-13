"""Batch the native daily-plan generator; no physics or labels are created."""
import argparse,datetime as dt,gzip,hashlib,json,time
from pathlib import Path
from collections import Counter,defaultdict
from concurrent.futures import ProcessPoolExecutor,as_completed
from .common import digest
from .generate_native import generate,implementation
from .unified.contract import entry_config

def save(path,value):
    part=path.with_suffix(path.suffix+'.part')
    part.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n');part.replace(path)

def summarize(case,folder,index):
    counts=Counter();orders=Counter();signs=Counter();meals=Counter();conflicts=0;pair_index=[]
    for path in sorted(folder.glob('*_PAIR.json.gz')):
        if path.name.endswith('_INITIAL_PAIR.json.gz'):continue
        with gzip.open(path,'rt') as stream:pair=json.load(stream)
        counts.update({c['family'] for c in pair['selected_proposal']['components']})
        orders[len(pair['selected_proposal']['components'])]+=1
        value=pair['selected_proposal']['nominal_whole_plan_event_reduction_kWh']
        signs['thermal_unknown' if value is None else 'positive' if value>1e-8 else 'negative' if value<-1e-8 else 'zero']+=1
        low,high=case['household']['comfort']['preferred_cooling_c']
        conflicts+=any(c['kind']=='ac_setpoint' and not low<=c['cooling_setpoint_C']<=high for c in pair['B']['controls'])
        with gzip.open(folder/(pair['date']+'_A.json.gz'),'rt') as stream:baseline=json.load(stream)
        for job in baseline['problem']['jobs']:
            if job['kind']=='dishwasher':
                load=job['A_reference_dish_load'];meals[load['meal_kind']]+=1
                task=next(t for t in pair['A']['tasks'] if t['need_id']==job['need_id'])
                if task['start_min']<load['meal_end_min']:raise ValueError('A_DISH_LOAD_PRECEDES_MEAL')
        pair_index.append(dict(index=index,case_id=case['case_id'],date=pair['date'],relative_path=str(path.relative_to(folder.parent)),A_sha256=pair['A_sha256'],B_sha256=pair['B_sha256'],pair_file_sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    names=dict(AC='ac',WM='washer',DR='dryer',DW='dishwasher',WH='water_heater',EV='ev')
    required={names[k] for k in case['household']['controlled_function_ids']}
    return dict(index=index,country=case['household']['country'],role=case['household']['role_id'],status='passed',pairs=len(pair_index),selected_family_counts=dict(counts),component_orders=dict(orders),family_gaps=sorted(required-set(counts)),meal_load_counts=dict(meals),preference_conflict_pairs=conflicts,nominal_event_effects=dict(signs),source_household_sha256=digest(case),pair_index=pair_index)

def worker(item):
    index,case,dates,reference,manifest,out,native,cfg=item;folder=Path(out)/str(index).zfill(4);started=time.monotonic()
    try:
        generate(case,dates,reference,manifest,folder,native,cfg)
        row=summarize(case,folder,index)
    except Exception as error:
        folder.mkdir(exist_ok=True)
        row=dict(index=index,country=case['household']['country'],role=case['household']['role_id'],status='failed',error_type=type(error).__name__,error=str(error))
        save(folder/'FAILURE.json',row)
    row['seconds']=round(time.monotonic()-started,3);return row

def aggregate(rows,target,source_ok,implementation_ok,summary):
    counters={k:Counter() for k in ['selected_family_counts','component_orders','meal_load_counts','nominal_event_effects']}
    countries=Counter();roles=Counter();role_families=defaultdict(Counter)
    for row in rows:
        if row['status']!='passed':continue
        for key,count in counters.items():count.update(row[key])
        countries[row['country']]+=1;roles[row['role']]+=1;role_families[row['role']].update(row['selected_family_counts'])
    return dict(summary=summary,native_plan_generation_passed=summary['passed']==target and summary['failed']==0,
        source_unchanged=source_ok,implementation_unchanged=implementation_ok,countries=dict(countries),roles=dict(roles),
        appliance_component_counts=dict(counters['selected_family_counts']),component_orders=dict(counters['component_orders']),
        meal_load_counts=dict(counters['meal_load_counts']),nominal_event_effects=dict(counters['nominal_event_effects']),
        role_family_counts={k:dict(v) for k,v in role_families.items()},household_family_gaps=sum(bool(x.get('family_gaps')) for x in rows),
        soft_cooling_preference_conflict_pairs=sum(x.get('preference_conflict_pairs',0) for x in rows),
        selected_pair_native_replays=summary['pairs']*2,formal_questionnaire_release=False,all_10000_physics_qualified=False,human_answers_generated=False)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ['households','reference','native-source','out']:parser.add_argument('--'+name,required=True,type=Path)
    parser.add_argument('--start-date',required=True);parser.add_argument('--days',type=int,default=10)
    parser.add_argument('--workers',type=int,default=4);parser.add_argument('--configuration',type=Path)
    args=parser.parse_args()
    if min(args.days,args.workers)<1:parser.error('days and workers must be positive')
    raw=args.households.read_bytes();reference_raw=args.reference.read_bytes()
    cases=[json.loads(line) for line in raw.splitlines() if line.strip()]
    if not cases or len({case['case_id'] for case in cases})!=len(cases):parser.error('nonempty unique household case IDs required')
    cases.sort(key=lambda c:(c['household']['country'],c['household']['role_id'],c['case_id']))
    reference=json.loads(reference_raw);manifest=hashlib.sha256(raw).hexdigest();frozen=implementation()
    cfg=entry_config(args.configuration or Path(__file__).with_name('GENERATION_REPAIR_CONFIG.json'))
    start=dt.date.fromisoformat(args.start_date);dates=[(start+dt.timedelta(days=i)).isoformat() for i in range(args.days)]
    args.out.mkdir(parents=True,exist_ok=False);started=time.monotonic()
    save(args.out/'PRE_RUN.json',dict(schema='eb.native_cohort.pre_run.v1',source_sha256=manifest,reference_sha256=digest(reference),configuration=cfg,implementation=frozen,dates=dates,workers=args.workers,target_households=len(cases),target_pairs=len(cases)*args.days,old_10000_overwritten=False,physics_results_inherited=False,human_labels_generated=False))
    rows=[]
    items=[(i,c,dates,reference,manifest,str(args.out),str(args.native_source),cfg) for i,c in enumerate(cases)]
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        futures=[pool.submit(worker,item) for item in items]
        for future in as_completed(futures):
            row=future.result();rows.append(row)
            summary=dict(completed=len(rows),passed=sum(v['status']=='passed' for v in rows),failed=sum(v['status']!='passed' for v in rows),pairs=sum(v.get('pairs',0) for v in rows),seconds=round(time.monotonic()-started,2))
            save(args.out/'STATUS.json',dict(summary=summary,rows=[{k:v for k,v in x.items() if k!='pair_index'} for x in sorted(rows,key=lambda v:v['index'])]))
    with (args.out/'PAIR_INDEX.jsonl').open('w') as stream:
        for x in sorted((p for row in rows for p in row.get('pair_index',[])),key=lambda p:(p['index'],p['date'])):stream.write(json.dumps(x,ensure_ascii=False)+'\n')
    source_ok=args.households.read_bytes()==raw and args.reference.read_bytes()==reference_raw
    result=aggregate(rows,len(cases),source_ok,implementation()==frozen,summary)
    if not source_ok or not result['implementation_unchanged']:result['native_plan_generation_passed']=False
    save(args.out/'RESULT.json',result);print(json.dumps(result))
    return 0 if result['native_plan_generation_passed'] else 1
if __name__=='__main__':raise SystemExit(main())
