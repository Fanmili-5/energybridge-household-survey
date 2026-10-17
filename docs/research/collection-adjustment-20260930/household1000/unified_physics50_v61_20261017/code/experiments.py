"""Bounded original50 production and preselected seasonal sensitivity runs."""
import argparse
import collections
import time
from concurrent.futures import ProcessPoolExecutor
from core import *
from run_physics import job
from check_initialization import compare_contrasts


def inputs():
    manifest=read(ROOT/'INPUT_MANIFEST.json')
    assert len(manifest['records'])==50 and sum(len(r['cases'])for r in manifest['records'])==500
    assert {r['household_id']for r in manifest['records']}==set(manifest['subset50_ids'])
    return manifest


def run(label,engine,workers):
    manifest=inputs();selection=read(ROOT/'SENSITIVITY_SELECTION.json')
    selected={r['case_id']for r in selection['records']}
    if label=='history7':selected={r['case_id']for r in selection['records']if not r['different_history_possible']}
    if label=='history224':selected={r['case_id']for r in selection['records']if r['different_history_possible']}
    if label.startswith('leakage_'):selected=set(selection['leakage_cases'])
    setting=selection['groups'].get(label,{'history':112,'portal_scale':1.,'ACH':.35})
    os.environ['EB_PORTAL_FLOW_SCALE']=str(setting['portal_scale']);os.environ['EB_REFERENCE_ACH']=str(setting['ACH'])
    work=[(r,c,engine,setting['history'],label)for r in manifest['records']for c in r['cases']if label=='pilot50'or c['case_id']in selected]
    assert len(work)==500 if label=='pilot50'else len(work)==len(selected)
    config={'scope':'original50_only','label':label,'jobs':len(work),'settings':setting,'physics_sha256':physics_hash(),
            'input_manifest_sha256':sha(ROOT/'INPUT_MANIFEST.json'),'selection_sha256':sha(ROOT/'SENSITIVITY_SELECTION.json'),
            'engine_sha256':sha(engine),'full1000_deferred_by_user':True}
    save(ROOT/'results'/label/'RUN_CONFIG.json',config);started=time.monotonic();records=[]
    with ProcessPoolExecutor(max_workers=workers)as pool:
        for r in pool.map(job,work,chunksize=1):
            records.append(r)
            if len(records)%10==0 or not r['passed']:
                progress={'label':label,'completed_pairs':len(records),'planned_pairs':len(work),
                          'failed_pairs':sum(not x['passed']for x in records),'elapsed_seconds':round(time.monotonic()-started)}
                save(ROOT/'results'/label/'PROGRESS.json',progress);print(canonical(progress),flush=True)
    report={'schema':VERSION,'scope':'original50_only','label':label,'cases':len(records),'records':records,
            'passed':all(r['passed']for r in records),'physics_sha256':physics_hash(),
            'code_sha256':code_hash(),'input_manifest_sha256':sha(ROOT/'INPUT_MANIFEST.json'),
            'elapsed_seconds':time.monotonic()-started}
    save(ROOT/'results'/label/'RUN_BINDINGS.json',report)
    if not report['passed']:raise RuntimeError('ENGINE_FAILURES_KEPT:'+label)


def sensitivity_record(item):
    label,setting,cid,row,case=item
    pair=read(ROOT/case['path'])
    base=ROOT/'results/pilot50'/row['household_id']/case['date']/'A'
    alternate=ROOT/'results'/label/row['household_id']/case['date']/'A'
    data=compare_contrasts({'reference':base,label:alternate},pair)
    short=read(base/'INPUT.json.gz')['history_days'];long=read(alternate/'INPUT.json.gz')['history_days']
    return {'case_id':cid,'alternative':label,'settings':setting,
            'reference_effective_history_days':short,'alternative_effective_history_days':long,
            'contrast_sensitivity':data}


def review(workers=8):
    manifest=inputs();selection=read(ROOT/'SENSITIVITY_SELECTION.json');byid={c['case_id']:(r,c)for r in manifest['records']for c in r['cases']}
    jobs=[];coverage=collections.defaultdict(list)
    for label in selection['groups']:
        result=read(ROOT/'results'/label/'RUN_BINDINGS.json');assert result['passed']
        assert result['physics_sha256']==physics_hash()
        for item in result['records']:
            cid=item['case_id'];row,case=byid[cid]
            jobs.append((label,selection['groups'][label],cid,row,case));coverage[cid].append(label)
    with ProcessPoolExecutor(max_workers=min(8,workers))as pool:
        records=[]
        for record in pool.map(sensitivity_record,jobs,chunksize=4):
            records.append(record)
            if len(records)%100==0:print(canonical({'sensitivity_readbacks':len(records),'total':len(jobs)}),flush=True)
    selected={r['case_id']:r for r in selection['records']}
    for record in records:
        if record['alternative'].startswith('history'):
            assert record['reference_effective_history_days']!=record['alternative_effective_history_days'], 'IDENTICAL_HISTORY_IS_NOT_A_SENSITIVITY_TEST'
    report={'schema':VERSION,'passed':True,'meaning':'diagnostic execution and readback completed;not all comparisons robust',
            'physics_sha256':physics_hash(),'selection_sha256':sha(ROOT/'SENSITIVITY_SELECTION.json'),
            'cases':len(coverage),'comparisons':len(records),'total_cases':500,'cases_not_individually_assessed':500-len(coverage),
            'coverage':dict(coverage),'season_reason_counts':dict(collections.Counter(reason for cid in coverage for reason in selected[cid]['reasons'])),
            'records':records,'sensitive_comparisons':sum(not r['contrast_sensitivity']['conditional_comparison_robust_under_tested_scenarios']for r in records),
            'sensitive_case_ids':sorted({r['case_id']for r in records if not r['contrast_sensitivity']['conditional_comparison_robust_under_tested_scenarios']}),
            'absolute_occupied_temperature_sensitive_case_ids':sorted({r['case_id']for r in records if r['contrast_sensitivity']['own_occupied_absolute_air_temperature_sensitivity_C']>.2}),
            'source_requests_modified':False,'field_calibration_claimed':False,'full1000_deferred_by_user':True}
    save(ROOT/'SENSITIVITY_REVIEW.json',report)
    print(canonical({k:v for k,v in report.items()if k not in('records','coverage','sensitive_case_ids','absolute_occupied_temperature_sensitive_case_ids')}),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('phase',choices=['production','sensitivity','review']);p.add_argument('--workers',type=int,default=8)
    p.add_argument('--engine',default='/root/autodl-tmp/eb-ab57-physics/runtime/ep24_1/energyplus');args=p.parse_args()
    if args.phase=='production':run('pilot50',args.engine,min(8,args.workers))
    elif args.phase=='sensitivity':
        for label in read(ROOT/'SENSITIVITY_SELECTION.json')['groups']:run(label,args.engine,min(8,args.workers))
    else:review(args.workers)
