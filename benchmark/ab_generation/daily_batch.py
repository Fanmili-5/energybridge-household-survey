"""Reproducible daily A plan-only batch; no B search, physics or human labels."""
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor
import argparse,collections,datetime as dt,gzip,hashlib,importlib.metadata,json,os,subprocess,time,traceback
from .common import read,save,sha,digest
from .v9_date_adapter import generate_day_baseline
from .unified.contract import entry_config,code_hash

_STATE={}
def initialize(reference,cfg,manifest,native,out):
    _STATE.update(reference=reference,cfg=cfg,manifest=manifest,native=Path(native),out=Path(out))

def job(item):
    index,case,date=item;started=time.monotonic()
    folder=_STATE['out']/(str(index).zfill(4)+'_'+date);folder.mkdir()
    row=dict(source_index=index,country=case['household']['country'],role=case['household']['role_id'],date=date)
    try:
        result=generate_day_baseline(case,date,_STATE['reference'],_STATE['cfg'],_STATE['manifest'],
                                    native_appliance_source_path=_STATE['native'])
        with gzip.open(folder/'EVIDENCE.json.gz','wt',encoding='utf-8') as f:json.dump(result,f,ensure_ascii=False,separators=(',',':'))
        row['status']=result['status']
        row['daily_passed']=bool(result.get('daily_acceptance',{}).get('passed')) if result.get('daily_acceptance') else False
        row['native_passed']=bool(result.get('native_acceptance',{}).get('passed')) if result.get('native_acceptance') else False
        if result['status']=='accepted_plan_only':
            plan=result['result']['A']
            row['programmes_by_kind']=dict(collections.Counter(t['kind'] for t in plan['tasks']))
            base=(dt.date.fromisoformat(date)-dt.date.fromisoformat(result['problem']['anchor'])).days*1440
            row['all_programme_starts_on_question_date']=all(base<=t['start_min']<base+1440 for t in plan['tasks'])
            row['all_non_EV_programmes_finish_same_date']=all(t['end_min']<=base+1440 for t in plan['tasks'])
            row['manual_operations']=len(plan['operations'])
            needs={n['need_id']:n for n in result['context']['needs']}
            row['start_window_coordinates_consistent']=all(needs[t['need_id']]['start_window_min'][0]<=t['start_min']-base<needs[t['need_id']]['start_window_min'][1] for t in plan['tasks'])
            row['native_sampler_attempts']=result['result']['native_sampler_attempts']
            row['full_overnight_programmes']=sum(t['start_min']//1440!=(t['end_min']-1)//1440 for t in plan['tasks'])
            row['EV_commands']=sum(r['kind']=='ev_charge_window' for r in plan['controls'])
            row['EV_present']=any(r['function']=='EV' for r in result['problem']['daily_service_contract']['other_daily_services'])
            row['no_service_task_deleted']=len(plan['tasks'])==len(result['problem']['daily_service_contract']['programme_requirements'])
        else:
            row['hard_error_codes']=[r.split(':')[0] for r in (result.get('native_acceptance') or {}).get('hard_errors',[])]
            row['daily_error_codes']=[r['code'] for r in (result.get('daily_acceptance') or {}).get('errors',[])]
    except Exception as error:
        (folder/'ERROR.txt').write_text(traceback.format_exc())
        row.update(status='exception',error_type=type(error).__name__)
    row['seconds']=round(time.monotonic()-started,4)
    return row

def run(args):
    source=Path(args.source).resolve();out=Path(args.output).resolve()
    if out.exists():raise ValueError('OUTPUT_EXISTS_KEEP_PRIOR_EVIDENCE')
    if out.is_relative_to(source.parent):raise ValueError('OUTPUT_INSIDE_FROZEN_SOURCE_DIRECTORY')
    if not 1<=args.workers<=8:raise ValueError('WORKERS_MUST_BE_1_TO_8')
    if len(args.dates)!=10 or len(set(args.dates))!=10:raise ValueError('EXACTLY_TEN_DISTINCT_DATES_REQUIRED')
    for date in args.dates:dt.date.fromisoformat(date)
    manifest=sha(source)
    if manifest!=args.expected_source_sha256:raise ValueError('SOURCE_MANIFEST_MISMATCH')
    reference=read(args.reference);cfg=entry_config(args.config) if args.config else entry_config()
    # This adapter consumes V9's own household reference targets, not a second portrait.
    cfg['A_target_context_mode']='frozen_v3'
    cases=sorted([json.loads(line) for line in source.open() if line.strip()],
                 key=lambda x:(x['household']['country'],x['household']['role_id'],x['case_id']))
    if len({c['case_id'] for c in cases})!=len(cases):raise ValueError('DUPLICATE_SOURCE_HOUSEHOLD')
    out.mkdir(parents=True)
    frozen_code=code_hash();start=time.monotonic()
    pre=dict(schema='eb.daily_A_batch.pre_run.v1',source_sha256=manifest,reference_sha256=sha(args.reference),
             configuration=cfg,code_sha256=frozen_code,households=len(cases),dates=args.dates,
             target=len(cases)*len(args.dates),workers=args.workers,source_households_modified=False,
             scope='original EB native command plans;no manual operations;not physical outcomes or released questions',
             A_method='copied_original_EB_no_DR_routine_on_declared_command_grid',
             physical_runs=0,human_answers_generated=False,training=False,paid_calls=0,
             runtime={k:importlib.metadata.version(k) for k in ('ortools','numpy','scipy')})
    save(out/'PRE_RUN.json',pre)
    rows=[]
    items=((i,c,date) for i,c in enumerate(cases) for date in args.dates)
    with ProcessPoolExecutor(max_workers=args.workers,initializer=initialize,
          initargs=(reference,cfg,manifest,args.native_source,str(out))) as pool:
        for row in pool.map(job,items,buffersize=args.workers*2):
            rows.append(row)
            if len(rows)%100==0 or len(rows)==pre['target']:
                summary=dict(completed=len(rows),target=pre['target'],
                             accepted=sum(r['status']=='accepted_plan_only' for r in rows),
                             status_counts=dict(collections.Counter(r['status'] for r in rows)),
                             elapsed_seconds=round(time.monotonic()-start,2))
                save(out/'STATUS.json',{**summary,'rows':rows})
                print(json.dumps(summary),flush=True)
    source_unchanged=sha(source)==manifest;code_unchanged=code_hash()==frozen_code
    counts=collections.Counter()
    for row in rows:counts.update(row.get('programmes_by_kind',{}))
    accepted=[r for r in rows if r['status']=='accepted_plan_only']
    summary.update(source_unchanged=source_unchanged,code_unchanged=code_unchanged,
        daily_A_plan_acceptance_passed=(len(accepted)==pre['target'] and source_unchanged and code_unchanged),
        completed_households=len({r['source_index'] for r in rows}),
        ten_distinct_dates_per_household=all(len(ds)==10 for ds in
            ({r['date'] for r in rows if r['source_index']==i} for i in range(len(cases)))),
        complete_programmes_by_kind=dict(counts),
        all_programme_starts_on_question_date=all(r.get('all_programme_starts_on_question_date') for r in accepted),
        no_service_task_deleted=all(r.get('no_service_task_deleted') for r in accepted),
        EV_days=sum(r.get('EV_present',False) for r in accepted),
        max_native_EV_permission_intervals=max((r.get('EV_commands',0) for r in accepted),default=0),
        full_overnight_programmes=sum(r.get('full_overnight_programmes',0) for r in accepted),
        all_non_EV_programmes_finish_same_date=all(r.get('all_non_EV_programmes_finish_same_date') for r in accepted),
        manual_operations_generated=sum(r.get('manual_operations',0) for r in accepted),
        start_window_coordinates_consistent=all(r.get('start_window_coordinates_consistent') for r in accepted),
        country_households=dict(collections.Counter(c['household']['country'] for c in cases)),
        role_households=dict(collections.Counter(c['household']['role_id'] for c in cases)),
        physical_outcomes_computed=False,selected_AB_pairs=0,formal_questionnaire_questions=0)
    save(out/'RESULT.json',summary)
    print(json.dumps(summary),flush=True)
    return 0 if summary['daily_A_plan_acceptance_passed'] else 1

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',required=True);p.add_argument('--reference',required=True)
    p.add_argument('--expected-source-sha256',required=True);p.add_argument('--native-source',required=True)
    p.add_argument('--config');p.add_argument('--output',required=True);p.add_argument('--workers',type=int,default=1)
    p.add_argument('--dates',nargs='+',required=True)
    return run(p.parse_args())

if __name__=='__main__':raise SystemExit(main())
