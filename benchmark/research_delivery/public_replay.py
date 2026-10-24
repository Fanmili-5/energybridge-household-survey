"""Portable replay from frozen public portraits and original life inputs.

Compile demands again; expected compiled problems and A results are inspected
only after the corresponding computation. Never read simulation or answer data.
This is the frozen-v3-to-new-A/B route, not a new population/profile sampler.
"""
import argparse
import copy
import datetime as dt
from pathlib import Path

from benchmark.ab_generation.common import read,save,sha,digest,bound
from benchmark.ab_generation.unified.a_solver import compile_life,solve
from benchmark.ab_generation.unified.pipeline import fresh_context
from benchmark.ab_generation.unified.contract import config
from .a_review import inspect
from .production import audited_build


def original_problem(spec,world,dates):
    if len(dates)!=10 or dates!=sorted(set(dates)):raise ValueError('EXACT_TEN_GIVEN_DATES_REQUIRED')
    end=(dt.date.fromisoformat(dates[-1])+dt.timedelta(days=3)).isoformat()
    if end>spec['end_exclusive']:raise ValueError('ORIGINAL_LOOKAHEAD_MISSING;NO_CALENDAR_FABRICATED')
    if dates[0]<spec['anchor']:raise ValueError('GIVEN_DATE_BEFORE_ORIGINAL_ANCHOR')
    local=copy.deepcopy(spec);local['end_exclusive']=end
    problem=compile_life(local,world)
    problem['jobs']=[j for j in problem['jobs'] if j['date'] in dates]
    problem['validation_horizon']='ten original dates;two original-calendar lookahead days;no extra program demands'
    return problem


def checked_file(root,reference):
    path=bound(root,reference['path'])
    if sha(path)!=reference['sha256']:raise ValueError('PUBLIC_REPLAY_SOURCE_HASH_MISMATCH:'+reference['path'])
    return read(path)


def replay(inputs,out,configuration,household=None,stage='both',all_fixed_seeds=False,workers=1):
    inputs,out=Path(inputs).resolve(),Path(out).resolve();batch=read(inputs);cfg=config(read(configuration))
    if batch.get('schema')!='eb.public_life_replay.v1':raise ValueError('UNKNOWN_PUBLIC_REPLAY_SCHEMA')
    if cfg['A_target_context_mode']!='life_conditional_v1':raise ValueError('EXPECTED_EXPLICIT_CONDITIONAL_TARGET_INTERFACE')
    if stage not in ('compile','A','both'):raise ValueError('UNKNOWN_PUBLIC_REPLAY_STAGE')
    records=[r for r in batch['households'] if household is None or r['household_id']==household]
    if not records:raise ValueError('REQUESTED_HOUSEHOLD_NOT_IN_PUBLIC_INPUTS')
    out.mkdir(parents=True,exist_ok=False)
    seeds=[cfg['seed']]+[s for s in range(8) if s!=cfg['seed']] if all_fixed_seeds else [cfg['seed']]
    save(out/'FROZEN_REPLAY.json',dict(manifest_sha256=sha(inputs),configuration=cfg,seeds=seeds,
        household_dates=[dict(household_id=r['household_id'],dates=r['dates']) for r in records],
        stage=stage,portraits_frozen=True,dates_frozen_before_A=True,source_manifest=batch,
        expected_outputs_only_used_after_computation=True,physical_runs=0))
    results=[];AB=[];failed_dates=[]
    for record in records:
        hid=record['household_id'];dates=record['dates']
        spec_batch=checked_file(inputs.parent,record['life']);world_batch=checked_file(inputs.parent,record['world'])
        spec=next(r for r in spec_batch['households'] if r['household_id']==hid)
        world=next(r for r in world_batch['households'] if r['household_id']==hid)
        portrait=checked_file(inputs.parent,record['portrait'])
        if portrait['household_id']!=hid:raise ValueError('PORTRAIT_IDENTITY_MISMATCH')
        problem=original_problem(spec,world,dates)
        save(out/hid/'COMPILED_PROBLEM.json.gz',problem)
        expected=checked_file(inputs.parent,record['expected_problem'])
        compilation_equal=digest(problem)==digest(expected)
        save(out/hid/'COMPILATION_CHECK.json',dict(exact_expected_problem=compilation_equal,
            compiled_sha256=digest(problem),expected_sha256=digest(expected),
            from_original_life_and_world=True,expected_problem_not_used_as_solver_input=True))
        if not compilation_equal:
            failed_dates.extend(dict(household_id=hid,date=d,reason='compiler_replay_mismatch;not_no_opportunity') for d in dates)
            results.append(dict(household_id=hid,compilation_equal=False));continue
        if stage=='compile':
            results.append(dict(household_id=hid,compilation_equal=True));continue
        for seed in seeds:
            answer=solve(problem,portrait,seed=seed,deterministic_time=cfg['A_deterministic_time'],target_mode=cfg['A_target_context_mode'])
            save(out/hid/('A_'+str(seed)+'.json.gz'),answer)
            check=inspect(problem,answer['A'],answer['ev_charging_steps']) if answer['status']=='feasible' else None
            item=dict(household_id=hid,seed=seed,compilation_equal=True,status=answer['status'],independent_check=check,
                optimal=answer.get('optimal'),objective=answer.get('objective'),bound=answer.get('best_bound'))
            if seed==record['expected_seed']:
                expected_A=checked_file(inputs.parent,record['expected_A'])
                keys=('A','ev_charging_steps','conditional_target_context')
                item['expected_plan_and_targets_equal']=all(answer.get(k)==expected_A.get(k) for k in keys)
            results.append(item)
            if seed==cfg['seed']:
                if answer['status']!='feasible' or not check or not check['passed']:
                    failed_dates.extend(dict(household_id=hid,date=d,reason='baseline_not_independently_verified;not_resampled') for d in dates)
                else:
                    for date in dates:
                        context=fresh_context(problem,answer,date,portrait,cfg)
                        path=out/hid/(date+'.json.gz');save(path,context)
                        AB.append(dict(household_id=hid,date=date,context_path=str(path),
                            portrait_path=str(bound(inputs.parent,record['portrait']['path']))))
            save(out/'A_REPLAY_PROGRESS.json',results)
    save(out/'GIVEN_DATE_FAILURES.json',failed_dates)
    save(out/'A_REPLAY_RESULTS.json',results)
    save(out/'NEW_A_INPUTS.json',dict(schema='eb.unified.inputs.v1',mode='fresh_generation',records=AB))
    B=audited_build(out/'NEW_A_INPUTS.json',out/'AB',cfg,workers) if stage=='both' and AB else None
    expected_checks=[r['expected_plan_and_targets_equal'] for r in results if 'expected_plan_and_targets_equal' in r]
    summary=dict(configured_households=len(records),given_date_slots=10*len(records),
        compiled_problem_records=len(records),A_records=sum('seed' in r for r in results),
        compilation_equal=all(r['compilation_equal'] for r in results),failed_date_slots=len(failed_dates),
        expected_A_checks=len(expected_checks),expected_A_equal=all(expected_checks) if expected_checks else None,
        selected_A_date_slots=len(AB),collection=B,stage=stage,physical_runs=0,
        profile_sampling_rerun=False,online_changed=False,population1000_started=False,main_updated=False)
    save(out/'REPLAY_REPORT.json',summary);return summary


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--inputs',required=True);p.add_argument('--out',required=True);p.add_argument('--config',required=True)
    p.add_argument('--household');p.add_argument('--stage',choices=['compile','A','both'],default='both');p.add_argument('--all-fixed-seeds',action='store_true');p.add_argument('--workers',type=int,default=1)
    a=p.parse_args();print(replay(a.inputs,a.out,a.config,a.household,a.stage,a.all_fixed_seeds,a.workers))
