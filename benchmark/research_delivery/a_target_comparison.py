"""Matched targets for the existing serial adapter and CP-SAT, all fixed seeds.

The serial method retains its documented fixed-EV/greedy local ordering. This
is a method comparison, not an isolated solver-speed or behavioral-realism test.
"""
import argparse
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
import time

from benchmark.ab_generation.common import read,save,sha,digest
from benchmark.ab_generation.unified.a_solver import solve
from benchmark.ab_generation.unified.dated_target_context import VERSION,derive
from .a_comparison import Serial
from .a_review import inspect


def score(problem,A,targets):
    by_need={t['need_id']:t for t in A['tasks']};missing=[];deviations=[]
    for job in problem['jobs']:
        if job['need_id'] not in by_need:missing.append(job['need_id']);continue
        deviations.append(abs(by_need[job['need_id']]['start_min']-targets[job['need_id']]))
    return dict(compiled_jobs=len(problem['jobs']),matched_jobs=len(deviations),missing_need_ids=missing,
                absolute_machine_target_deviation_min=sum(deviations),behavioral_validity_inferred=False)


def job(task):
    source,seed,prior,out,pins=task
    p,portrait=read(source['problem_path']),read(source['portrait_path']);before=digest([p,portrait])
    context=derive(p,portrait);s=Serial(p,portrait,seed)
    for row in context['rows']:
        if row['target_min'] is not None:
            s.targets[(row['asset_id'],row['source_date'],row['need_id'])]=row['target_min']
    effective={j['need_id']:s.targets.get((j['asset_id'],j['date'],j['need_id']),s.targets.get((j['asset_id'],j['date'],None),j['preferred_start_min'])) for j in p['jobs']}
    started=time.perf_counter();pending=sorted(p['jobs'],key=lambda j:(j['release_min'],j['need_id']));done=set();ledger=[]
    while pending:
        at=next((i for i,j in enumerate(pending) if not j.get('depends_on_need_id') or j['depends_on_need_id'] in done),None)
        if at is None:raise ValueError('COMPARISON_DEPENDENCY_CYCLE')
        j=pending.pop(at);ledger.append(s.program(j));done.add(j['need_id'])
    greedy=dict(tasks=s.tasks,operations=s.operations,controls=p['controls'])
    serial_seconds=time.perf_counter()-started
    reused=seed==20261022
    started=time.perf_counter()
    cp=read(Path(prior)/p['household_id']/'A.json.gz') if reused else solve(p,portrait,seed=seed,deterministic_time=20,target_mode=VERSION)
    cp_seconds=None if reused else time.perf_counter()-started
    cp_targets={r['need_id']:r['target_min'] for r in cp.get('service_ledger',[])}
    mismatch=[nid for nid,t in effective.items() if cp['status']=='feasible' and cp_targets.get(nid)!=t]
    greedy_check=inspect(p,greedy,s.steps)
    cp_check=inspect(p,cp['A'],cp['ev_charging_steps']) if cp['status']=='feasible' else None
    result=dict(household_id=p['household_id'],seed=seed,target_mode=VERSION,
        problem_sha256=source['problem_sha256'],portrait_sha256=source['portrait_sha256'],
        target_context_sha256=context['sha256'],effective_targets_sha256=digest(effective),
        missing_profile_targets=sum(r['target_min'] is None for r in context['rows']),
        CP_target_mismatch=mismatch,serial=greedy_check,CP=cp_check,CP_status=cp['status'],CP_optimal=cp.get('optimal'),
        CP_objective=cp.get('objective'),CP_best_bound=cp.get('best_bound'),
        serial_score=score(p,greedy,effective),CP_score=score(p,cp['A'],effective) if cp['status']=='feasible' else None,
        serial_seconds=serial_seconds,CP_seconds=cp_seconds,CP_prior_result_reused=reused,
        input_unchanged=before==digest([p,portrait]),physical_runs=0)
    path=Path(out)/p['household_id']/(str(seed)+'.json.gz')
    save(path,dict(summary=result,serial_A=greedy,serial_EV_steps=s.steps,serial_service_ledger=ledger,CP=cp,
                   target_context=context,effective_targets=effective,source_pins=pins))
    return dict(**result,path=str(path))


def run(prior,out,workers=2):
    prior,out=map(Path,(prior,out));out.mkdir(parents=True,exist_ok=False)
    old=read(prior/'PROTOCOL.json')
    for path,h in old['source_pins'].items():
        if sha(path)!=h:raise ValueError('CANNOT_REUSE_CHANGED_TARGET_SOLVER_SOURCE:'+path)
    for r in old['inputs']:
        for field in ('problem','portrait'):
            if sha(r[field+'_path'])!=r[field+'_sha256']:raise ValueError('FROZEN_COMPARISON_INPUT_CHANGED')
    sources=[Path(__file__),Path(__file__).with_name('a_comparison.py'),Path(__file__).with_name('a_review.py')]
    pins={str(p):sha(p) for p in sources}|old['source_pins']
    tasks=[(r,s,str(prior),str(out),pins) for r in old['inputs'] for s in [20261022]+list(range(8))]
    save(out/'PROTOCOL.json',dict(inputs=old['inputs'],seeds=[20261022]+list(range(8)),target_mode=VERSION,
        deterministic_time=20,workers=workers,source_pins=pins,prior_protocol_sha256=sha(prior/'PROTOCOL.json'),
        methods='serial_greedy_adapter_fixed_EV;CP_joint_household',timing='descriptive_concurrent;not_isolated_speed_benchmark',
        old_A_B_rewritten=False,physical_runs=0))
    records=[]
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for r in pool.map(job,tasks,buffersize=workers*2):
            records.append(r);save(out/'PROGRESS.json',records)
            print(len(records),'/',len(tasks),r['household_id'],r['seed'],r['CP_status'],flush=True)
    changed=[p for p,h in pins.items() if sha(p)!=h]
    result=dict(runs=len(records),expected=len(tasks),all_seeds_retained=len(records)==len(tasks),
        same_target_inputs=not any(r['CP_target_mismatch'] for r in records),
        serial_passed=sum(r['serial']['passed'] for r in records),CP_passed=sum(bool(r['CP'] and r['CP']['passed']) for r in records),
        CP_optimal=sum(bool(r['CP_optimal']) for r in records),CP_reused=sum(r['CP_prior_result_reused'] for r in records),
        serial_deviation_min=sum(r['serial_score']['absolute_machine_target_deviation_min'] for r in records),
        CP_deviation_min=sum(r['CP_score']['absolute_machine_target_deviation_min'] for r in records if r['CP_score']),
        input_unchanged=all(r['input_unchanged'] for r in records),source_changes=changed,
        superiority_or_behavioral_validity_claimed=False,records=records)
    save(out/'SUMMARY.json',result)
    return {k:v for k,v in result.items() if k!='records'}


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--prior',required=True);p.add_argument('--out',required=True);p.add_argument('--workers',type=int,default=2)
    a=p.parse_args();print(run(a.prior,a.out,a.workers))
