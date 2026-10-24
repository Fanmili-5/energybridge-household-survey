"""Six fixed public horizons: conditional preference targets, then new A only."""
import argparse
from collections import Counter
from pathlib import Path
import time

from benchmark.ab_generation.common import read,save,sha,digest
from benchmark.ab_generation.unified.a_solver import solve
from benchmark.ab_generation.unified.dated_target_context import VERSION,derive
from .a_review import inspect


def run(prior,profiles,out):
    prior,profiles,out=map(Path,(prior,profiles,out));out.mkdir(parents=True,exist_ok=False)
    inputs=[]
    for f in sorted((prior/'source').glob('*/PARALLEL_PROBLEM.json.gz')):
        p=read(f);pp=profiles/(p['household_id']+'.json')
        inputs.append(dict(household_id=p['household_id'],problem_path=str(f.resolve()),
                           portrait_path=str(pp.resolve()),problem_sha256=sha(f),portrait_sha256=sha(pp)))
    if len(inputs)!=6:raise ValueError('EXPECTED_SIX_PREDECLARED_PUBLIC_INPUTS')
    code=Path(__file__).parents[1]/'ab_generation/unified'
    pins={str(p):sha(p) for p in [code/'a_solver.py',code/'dated_target_context.py',Path(__file__),Path(__file__).with_name('a_review.py')]}
    protocol=dict(version=VERSION,seed=20261022,deterministic_time=20,inputs=inputs,source_pins=pins,
                  no_B_generated=True,physical_runs=0,comparison='same_frozen_portrait_and_life;explicit_conditional_target_mapping_only')
    save(out/'PROTOCOL.json',protocol);summary=[]
    for r in inputs:
        problem,portrait=read(r['problem_path']),read(r['portrait_path']);before=digest([problem,portrait])
        context=derive(problem,portrait);save(out/r['household_id']/'TARGET_CONTEXT.json',context)
        started=time.perf_counter()
        result=solve(problem,portrait,seed=protocol['seed'],deterministic_time=protocol['deterministic_time'],target_mode=VERSION)
        elapsed=time.perf_counter()-started
        check=inspect(problem,result['A'],result['ev_charging_steps']) if result['status']=='feasible' else None
        save(out/r['household_id']/'A.json.gz',result)
        save(out/r['household_id']/'INDEPENDENT_CHECK.json',check)
        consumed={r['need_id']:r['target_min'] for r in result['service_ledger']}
        mismatch=[r['need_id'] for r in context['rows'] if r['target_min'] is not None and consumed.get(r['need_id'])!=r['target_min']]
        row=dict(household_id=r['household_id'],targets=len(context['rows']),
                 retained_v3=sum(not x['source_v3_target_missing'] for x in context['rows']),
                 conditional_targets=sum(x['source_v3_target_missing'] and x['target_min'] is not None for x in context['rows']),
                 unresolved=sum(x['target_min'] is None for x in context['rows']),
                 origins=dict(Counter(x['origin'] for x in context['rows'])),A_status=result['status'],
                 optimal=result.get('optimal'),independent_check=check,target_input_mismatch=mismatch,
                 target_realized=sum(x['target_realized'] for x in result['service_ledger']),
                 elapsed_seconds=elapsed,inputs_unchanged=before==digest([problem,portrait]))
        summary.append(row);print(row['household_id'],row['A_status'],row['conditional_targets'],check and check['passed'],flush=True)
        save(out/'SUMMARY.json',dict(rows=summary,complete=len(summary)==len(inputs),coverage_accepted=False,
             prior_v3_missing_personal_owner_not_fabricated=True,physical_runs=0))
    changed=[p for r in inputs for p,h in [(r['problem_path'],r['problem_sha256']),(r['portrait_path'],r['portrait_sha256'])] if sha(p)!=h]
    save(out/'SOURCE_INTEGRITY.json',dict(changed=changed,passed=not changed,files=len(inputs)*2))
    return summary


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--prior',required=True);p.add_argument('--profiles',required=True);p.add_argument('--out',required=True)
    a=p.parse_args();run(a.prior,a.profiles,a.out)
