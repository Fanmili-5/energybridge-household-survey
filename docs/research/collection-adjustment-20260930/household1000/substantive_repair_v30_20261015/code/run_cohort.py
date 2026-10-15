"""Execute and independently read every expected pair; original50 then other950."""
import argparse,collections,concurrent.futures,copy,os,shutil,time
from common import *
from cohort_gate import scoped_rows,require_reviewed_ep,guard_job,ENGINE
import physics
V28=BASE/'contrast_repair_v29_20261015'

def old_arm(c,side,lease):
    source=V28/'runs'/c['variant']/c['household_id']/f'{c["round_index"]:02d}_{side}'
    path=source/'RUN_RECORD.json'
    if not path.is_file():return None
    r=read(path);signature={'IDF_sha256':c[side]['IDF_sha256'],'weather_sha256':c['weather']['sha256'],'engine_sha256':sha(ENGINE)}
    if r.get('signature')!=signature or not r.get('runtime_pass')or not(source/'eplusout.sql').is_file()or sha(source/'eplusout.sql')!=r['SQL_sha256']:
        source=BASE/'formal50_950_production_v28_20261014/runs'/c['variant']/c['household_id']/f'{c["round_index"]:02d}_{side}'
        path=source/'RUN_RECORD.json'
        if not path.is_file():return None
        r=read(path)
        if r.get('signature')!=signature or not r.get('runtime_pass')or not(source/'eplusout.sql').is_file()or sha(source/'eplusout.sql')!=r['SQL_sha256']:return None
    guard_job(c,side,lease);destination=OUT/'runs'/c['variant']/c['household_id']/source.name;destination.mkdir(parents=True,exist_ok=True)
    for name in('eplusout.sql','eplusout.err','engine.log'):
        if(source/name).exists():
            target=destination/name
            if target.exists():assert sha(target)==sha(source/name)
            else:os.link(source/name,target)
    result={**r,'SQL_path':str((destination/'eplusout.sql').relative_to(OUT)),
        'exact_output_reuse':{'source_run_record_sha256':sha(path),'source_SQL_sha256':r['SQL_sha256'],'source_run_path':str(source),'same_IDF_weather_engine_bytes':True,'old_acceptance_report_reused':False}}
    save(destination/'RUN_RECORD.json',result);return result

def hard_failures(result):
    s=result['services']['A'];return {'A_hot_water_target_failures':sum(not x['temperature_pass']for x in s.get('hot_water',[])),
     'A_EV_access_target_failures':sum(not x['target_pass']for x in s.get('EV',{}).get('goals',[])),
     'A_EV_undelivered_trips':sum(not x['trip_departed']for x in s.get('EV',{}).get('trips',[])),
     'A_EV_reserve_failures':sum(not x['reference_reserve_pass']for x in s.get('EV',{}).get('trips',[])),
     'A_circuit_exceeded_pairs':int(bool(s['power_limits']['circuit_exceeded'])),'A_home_exceeded_pairs':int(s['power_limits']['home_exceeded'])}

_WORKER_LEASE=None
def worker_init(lease):
    global _WORKER_LEASE
    _WORKER_LEASE=lease;physics._READBACK_LEASE=lease

def one(c,lease=None):
    lease=lease or _WORKER_LEASE
    runs={s:old_arm(c,s,lease)or physics.run_job((c,s),lease)for s in('A','B')}
    if not all(r['runtime_pass']for r in runs.values()):raise RuntimeError('EP severe/fatal failure')
    physics._READBACK_LEASE=lease;result=physics.pair_readback(c,runs)
    return {'compiled':c,'runs':runs,'readback':result,'hard':hard_failures(result)}

def run(scope,workers):
    school_guard();lease=require_reviewed_ep(scope);rows=scoped_rows(scope);expected=len(rows);start=time.monotonic();completed=[];fail=[];totals=collections.Counter()
    # Each worker runs A then B, so at most workers EP processes are active.
    stopped=False
    with concurrent.futures.ProcessPoolExecutor(max_workers=workers,initializer=worker_init,initargs=(lease,))as pool:
        futures={pool.submit(one,c):c for c in rows}
        for f in concurrent.futures.as_completed(futures):
            c=futures[f]
            try:
                item=f.result();completed.append(item);totals.update(item['hard'])
                if any(item['hard'].values()):
                    fail.append({'household_id':c['household_id'],'round_index':c['round_index'],'error':'normal_A_service_or_power_gate','details':item['hard']})
            except Exception as e:fail.append({'household_id':c['household_id'],'round_index':c['round_index'],'error':repr(e)})
            if(len(completed)+len(fail))%20==0 or fail:
                progress={'scope':scope,'completed_pairs':len(completed),'expected_pairs':expected,'failed_pairs':len(fail),'A_hard_failures':dict(totals),'elapsed_seconds':round(time.monotonic()-start)}
                save(OUT/f'PROGRESS_{scope}.json',progress);print(progress,flush=True)
            if fail:
                for pending in futures:pending.cancel()
                stopped=True;break
    runs=[r for item in completed for r in item['runs'].values()]
    if not fail:physics.check_run_coverage(rows,runs)
    readbacks=[item['readback']for item in completed]
    report={'schema':'eb.fresh_cohort_physical_review.v28','scope':scope,'requested_pairs':expected,'checked_pairs':len(completed),
        'baseline_pairs_checked':sum(c['variant']=='base7'for item in completed for c in[item['compiled']]),
        'sensitivity_pairs_checked':sum(c['variant']!='base7'for item in completed for c in[item['compiled']]),
        'expected_sides':expected*2,'completed_sides':len(runs),'failures':fail,**dict(totals),
        'maximum_pre_notice_difference':max((r['pre_notice_max_difference']for r in readbacks),default=None),
        'maximum_meter_residual_J':max((max(r['meter_residual_J'].values())for r in readbacks),default=None),
        'maximum_spatial_SQL_difference':max((max(r['spatial_SQL_max_difference'].values())for r in readbacks),default=None),
        'warning_categories':{k:sum(r['warnings'][k]for r in runs)for k in('psychrometric_domain','DX_airflow_domain','AHRI_curve_domain')},
        'B_hot_water_target_failures':sum(not x['temperature_pass']for r in readbacks for x in r['services']['B'].get('hot_water',[])),
        'B_EV_access_target_failures':sum(not x['target_pass']for r in readbacks for x in r['services']['B'].get('EV',{}).get('goals',[])),
        'B_circuit_exceeded_pairs':sum(bool(r['services']['B']['power_limits']['circuit_exceeded'])for r in readbacks),
        'B_home_exceeded_pairs':sum(r['services']['B']['power_limits']['home_exceeded']for r in readbacks),
        'exact_old_SQL_reused_sides':sum('exact_output_reuse'in r for r in runs),'new_EP_sides':sum('exact_output_reuse'not in r for r in runs),
        'input_signature_at_readback':lease['review']['input_signature'],'compiled_scope_sha256':digest(rows),
        'runs_sha256':digest(sorted(runs,key=lambda r:(r['household_id'],r['round_index'],r['variant'],r['arm']))),'old_acceptance_report_reused':False,
        'acceptance_passed':not fail and len(completed)==expected and not any(totals.values()),'human_answers':0,'field_calibration':False,
        'stopped_early_on_normal_A_or_runtime_failure':stopped,'elapsed_seconds':time.monotonic()-start}
    require_reviewed_ep(scope);save(OUT/f'EP_{scope}_RUNS.json',{'records':runs});save(OUT/f'PHYSICS_{scope}_REVIEW.json',report);print(report,flush=True)
    if not report['acceptance_passed']:raise RuntimeError('cohort physical acceptance failed')

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--scope',choices=['original50','other950','weather_sensitivity'],required=True);p.add_argument('--workers',type=int,default=32);a=p.parse_args();run(a.scope,a.workers)
