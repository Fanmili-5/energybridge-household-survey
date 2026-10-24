"""Optional explicit-date orchestration over the existing life/A/B pipeline.

No fixed cohort size, retries, simulations, answer generation or deployment.
Dates and portraits are frozen before solving A, including failed households.
"""
import argparse
import copy
import datetime as dt
from pathlib import Path
from benchmark.ab_generation.common import read,save,sha,bound,digest
from benchmark.ab_generation.unified.contract import config,dates
from benchmark.ab_generation.unified.a_solver import compile_life,solve
from benchmark.ab_generation.unified.pipeline import fresh_context,build
from benchmark.ab_generation.unified.opportunities import declare


def audited_build(inputs,out,configuration=None,workers=2):
    """Persist the independent denominator BEFORE entering candidate code.

    A later technical exception cannot erase the input-side opportunity record.
    Baseline failures with no A stay unknown, not zero-opportunity cases.
    """
    inputs,out=Path(inputs).resolve(),Path(out).resolve();cfg=config(configuration)
    batch=read(inputs);out.mkdir(parents=True,exist_ok=False);manifest=[]
    for r in batch['records']:
        p=Path(r['context_path']);p=p if p.is_absolute() else bound(inputs.parent,p)
        c=read(p);ledger=declare(c,cfg)
        target=out/'input-opportunities'/(digest([r['household_id'],r['date']])+'.json')
        save(target,ledger);manifest.append(dict(household_id=r['household_id'],date=r['date'],
            context_sha256=sha(p),ledger_path=str(target.relative_to(out)),ledger_sha256=sha(target)))
    save(out/'INDEPENDENT_INPUT_LEDGER.json',dict(records=manifest,persisted_before_candidate_generation=True,
        input_sha256=sha(inputs),configuration=cfg))
    return build(inputs,out/'collection',cfg,workers)


def produce(life_batch,portraits,out,configuration=None,date_manifest=None,workers=2):
    life_batch,portraits,out=map(lambda p:Path(p).resolve(),(life_batch,portraits,out));cfg=config(configuration)
    batch=read(life_batch);world_path=bound(life_batch.parent,batch['worlds']['path'])
    if sha(world_path)!=batch['worlds']['sha256']:raise ValueError('WORLD_SOURCE_CHANGED')
    worlds={w['household_id']:w for w in read(world_path)['households']}
    supplied=read(date_manifest) if date_manifest else {};frozen=[]
    out.mkdir(parents=True,exist_ok=False)
    for spec in batch['households']:
        hid=spec['household_id'];p=portraits/(hid+'.json');profile=read(p)
        if profile['household_id']!=hid:raise ValueError('PROFILE_ID_MISMATCH')
        first,last=map(dt.date.fromisoformat,(spec['anchor'],spec['end_exclusive']))
        available=[(first+dt.timedelta(days=i)).isoformat() for i in range((last-first).days)]
        chosen=dates(available,cfg['seed'],hid,supplied.get(hid))
        frozen.append(dict(household_id=hid,dates=chosen,portrait_path=str(p),portrait_sha256=sha(p),
            spec_sha256=digest(spec),date_origin='supplied_manifest' if hid in supplied else 'independent_seed_without_A_B_or_results'))
    save(out/'FROZEN_INPUTS.json',dict(households=frozen,life_batch_sha256=sha(life_batch),
        configuration=cfg,dates_frozen_before_A=True,physical_runs=0))
    records=[];failures=[]
    for spec,f in zip(batch['households'],frozen):
        hid=f['household_id'];p=Path(f['portrait_path'])
        if sha(p)!=f['portrait_sha256']:raise ValueError('PORTRAIT_CHANGED_AFTER_FREEZE')
        profile=read(p);problem=compile_life(spec,worlds[hid]);a=solve(problem,profile,seed=cfg['seed'],deterministic_time=cfg['A_deterministic_time'],target_mode=cfg['A_target_context_mode'])
        save(out/'source'/hid/'A.json.gz',a)
        if a['status']!='feasible':
            failures.extend(dict(household_id=hid,date=d,status=a['status'],reason='baseline_not_proved_feasible;no_replacement',A_path=str(out/'source'/hid/'A.json.gz')) for d in f['dates'])
            continue
        for d in f['dates']:
            c=fresh_context(problem,a,d,profile,cfg);path=out/'source'/hid/(d+'.json.gz');save(path,c)
            records.append(dict(household_id=hid,date=d,context_path=str(path),portrait_path=str(p)))
    save(out/'BASELINE_FAILURE_SLOTS.json',failures)
    save(out/'INPUTS.json',dict(schema='eb.unified.inputs.v1',mode='fresh_generation',records=records))
    result=audited_build(out/'INPUTS.json',out/'AB',cfg,workers) if records else {'status':'no_feasible_baselines;no_replacement'}
    save(out/'PRODUCTION_REPORT.json',dict(configured_households=len(frozen),configured_slots=10*len(frozen),
        failed_slots=len(failures),collection=result,physical_runs=0,online_changed=False,main_updated=False))
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--life-batch',required=True);p.add_argument('--portraits',required=True)
    p.add_argument('--out',required=True);p.add_argument('--config');p.add_argument('--dates');p.add_argument('--workers',type=int,default=2)
    a=p.parse_args();print(produce(a.life_batch,a.portraits,a.out,read(a.config) if a.config else None,a.dates,a.workers))
