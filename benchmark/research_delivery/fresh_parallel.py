"""Same predeclared A runs, parallel execution; completed results are reused.

Inputs, seeds, 20 deterministic-time budget and original solver are unchanged.
An interrupted technical attempt is logged, never treated as a household failure.
"""
import argparse
import copy
import datetime as dt
import time
from pathlib import Path
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from benchmark.ab_generation.common import read,save,sha,digest
from benchmark.ab_generation.unified.a_solver import compile_life,solve
from benchmark.ab_generation.unified.pipeline import fresh_context,build
from benchmark.ab_generation.unified.contract import config
from benchmark.ab_generation.unified.delivery import a_score


def job(task):
    problem,portrait,seed,path=task;path=Path(path);expected=digest({k:v for k,v in problem.items() if k!='legacy_comparator'})
    if path.exists():
        a=read(path)
        if a['input_sha256']!=expected or a['portrait_sha256']!=digest(portrait):raise ValueError('EXISTING_A_RESULT_INPUT_MISMATCH')
        elapsed=None;reused=True
    else:
        start=time.perf_counter();a=solve(problem,portrait,seed=seed,deterministic_time=20);elapsed=time.perf_counter()-start
        save(path,a);reused=False
    return dict(household_id=problem['household_id'],seed=seed,path=str(path),status=a['status'],
        cp=a_score(problem,a.get('A'),portrait),legacy=a_score(problem,problem['legacy_comparator']['A'],portrait),
        wall_seconds=elapsed,reused_exact_completed_result=reused,optimal=a.get('optimal'),objective=a.get('objective'),best_bound=a.get('best_bound'))


def run(out,prior,workers=6):
    out,prior=Path(out),Path(prior);manifest=prior/'public-inputs-v6/INPUTS.json'
    rs=read(manifest)['records'];groups=defaultdict(list)
    for r in rs:
        for key in ('context_path','portrait_path'):
            if r.get(key) and not Path(r[key]).is_absolute():r[key]=str((manifest.parent/r[key]).resolve())
    for r in rs:groups[r['household_id']].append(r)
    tasks=[];problems={};portraits={};source_pins={};base=read(out/'PROTOCOL.json')['base_config']
    for hid,records in sorted(groups.items()):
        root=prior/'public-A-source/connected/life_inputs'/hid
        spec=read(root/'LIFE_INPUT.json')['households'][0];world=read(root/'resource_worlds.json')['households'][0]
        dates=sorted(r['date'] for r in records);spec=copy.deepcopy(spec)
        spec['end_exclusive']=(dt.date.fromisoformat(dates[-1])+dt.timedelta(days=3)).isoformat()
        p=compile_life(spec,world);p['jobs']=[j for j in p['jobs'] if j['date'] in dates]
        p['validation_horizon']='ten original dates;two original-calendar lookahead days;no extra program demands'
        problems[hid]=p;portraits[hid]=read(records[0]['portrait_path'])
        save(out/'fresh-public/source'/hid/'PARALLEL_PROBLEM.json.gz',p)
        source_pins[str(root/'LIFE_INPUT.json')]=sha(root/'LIFE_INPUT.json');source_pins[str(root/'resource_worlds.json')]=sha(root/'resource_worlds.json')
        for seed in [20261022]+list(range(8)):
            tasks.append((p,portraits[hid],seed,out/'fresh-public/A'/hid/(str(seed)+'.json.gz')))
    summaries=[]
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for result in pool.map(job,tasks,buffersize=workers*2):
            summaries.append(result);save(out/'fresh-public/A_PARALLEL_PROGRESS.json',summaries)
            print('A',len(summaries),'/',len(tasks),result['household_id'],result['seed'],result['status'],flush=True)
    save(out/'fresh-public/A_COMPARISON.json',summaries)
    inputs=[]
    for hid,records in sorted(groups.items()):
        a=read(out/'fresh-public/A'/hid/'20261022.json.gz')
        if a['status']!='feasible':continue
        for r in records:
            c=fresh_context(problems[hid],a,r['date'],portraits[hid],config(base));path=out/'fresh-public/contexts'/(hid+'__'+r['date']+'.json.gz');save(path,c)
            inputs.append({**r,'context_path':str(path.resolve())})
    save(out/'fresh-public/SOURCE_PINS.json',source_pins)
    save(out/'fresh-public/INPUTS.json',dict(schema='eb.unified.inputs.v1',mode='fresh_generation',records=inputs))
    result=build(out/'fresh-public/INPUTS.json',out/'fresh-public/collection',base,workers=workers) if inputs else {'status':'no_feasible_A;not_resampled'}
    report=dict(A_runs=len(summaries),feasible=sum(r['status']=='feasible' for r in summaries),collection=result,
        execution='parallel_same_problems_seeds_and_budgets;technical_restart_logged',physical_runs=0)
    save(out/'STAGE_fresh.json',report);return report


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--out',required=True);p.add_argument('--prior',required=True);p.add_argument('--workers',type=int,default=6)
    a=p.parse_args();print(run(a.out,a.prior,a.workers))
