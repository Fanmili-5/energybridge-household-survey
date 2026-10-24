"""Fixed complete gap list: compare query algorithms on unchanged native domains."""
import argparse
from collections import Counter,defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
import time

from benchmark.ab_generation.common import read,save,sha,digest
from benchmark.ab_generation.model import apply
from benchmark.ab_generation.unified.candidates import prepare,Oracle
from benchmark.ab_generation.unified.factorized import ProgramRecipe
from benchmark.ab_generation.unified.contract import config,code_hash
from benchmark.ab_generation.unified.independent import audit
from benchmark.ab_generation.unified.semantics import mechanism
from .acceptance import record_sources


def restore(cat):
    values=[]
    for group in cat['native_domains']:
        result=[]
        for r in group:
            if r and 'recipe' in r:
                t=cat['native_templates'][r['recipe']['template']]
                v=ProgramRecipe(t['template'],t['load'],t['unload'],r['recipe']['load_min'],r['recipe']['unload_min']);v.update(r)
                result.append(v)
            else:result.append(r)
        values.append(result)
    return dict(values=values,descriptors=cat['factors'],domains=[list(range(len(ds))) for ds in cat['factors']])


def job(task):
    slot,context,portrait,gaps,cfg,out=task;cat=read(slot['path']);g=restore(cat);raw=read(context);profile=read(portrait)
    c=prepare(raw,config(cfg));records=[]
    for gap in gaps:
        required={}
        for i,vs in enumerate(g['values']):
            ids=[j for j,r in enumerate(vs) if r and (r['asset_id'],r.get('service_need_id'),mechanism(r['mechanism']),r['magnitude'].get('axis'))==
                 (gap['asset_id'],gap['need_id'],gap['mechanism'],gap['axis'])]
            if ids:required[i]=ids
        if len(required)!=1:raise ValueError('GAP_MUST_BIND_ONE_EXISTING_NATIVE_FACTOR')
        i=next(iter(required));arms=[]
        for mode in ('none','interval_v1'):
            configuration=config({**cfg,'method_revision':'delivery_v2_5','oracle_propagation':mode})
            started=time.perf_counter();oracle=Oracle(c,g,configuration,profile)
            singleton=oracle({j:0 for j in range(len(g['values'])) if j!=i},native_required=required)
            # A failed singleton does not certify impossibility with support.
            joint=None if singleton[0]=='feasible' else oracle({},native_required=required)
            selected=singleton if singleton[0]=='feasible' else joint
            errors=[dict(id=r['id'],errors=audit(c,c['A'],apply(c['A'],r['patches']))) for r in oracle.rows.values()]
            arms.append(dict(mode=mode,singleton=singleton,joint_extension=joint,conclusion=selected,
                rows=list(oracle.rows.values()),diagnostics=oracle.diagnostics,propagation=oracle.propagation_log,
                independent_checks=errors,calls=oracle.calls,materializations=oracle.materializations,
                elapsed_seconds=time.perf_counter()-started))
        records.append(dict(**gap,arms=arms))
    key=digest([slot['household_id'],slot['date']]);path=Path(out)/'records'/(key+'.json.gz')
    save(path,dict(records=records,source_catalogue_sha256=sha(slot['path']),context_sha256=sha(context),portrait_sha256=sha(portrait),
        original_catalogue_or_selection_changed=False,physical_runs=0))
    return dict(household_id=slot['household_id'],date=slot['date'],path=str(path),gaps=len(records),
        arms={mode:dict(Counter(a['conclusion'][0] for r in records for a in r['arms'] if a['mode']==mode)) for mode in ('none','interval_v1')},
        independent_errors=sum(bool(e['errors']) for r in records for a in r['arms'] for e in a['independent_checks']))


def run(prior,out,workers=2):
    prior,out=Path(prior),Path(out);out.mkdir(parents=True,exist_ok=False)
    collection=prior/'fifty';pre,contexts=record_sources(collection)
    gaps=read(prior/'FIFTY_GAP_DIAGNOSTICS.json')['records'];by=defaultdict(list)
    for r in gaps:by[(r['household_id'],r['date'])].append(r)
    tasks=[]
    for s in sorted(read(collection/'GENERATION.json'),key=lambda r:(r['household_id'] not in ('ordinary-v6-0696','ordinary-v6-0756'),r['household_id'],r['date'])):
        key=s['household_id'],s['date']
        if key not in by:continue
        portraits=[p for p in pre['source_sha256'] if Path(p).name==s['household_id']+'.json']
        if len(portraits)!=1:raise ValueError('AMBIGUOUS_PORTRAIT_SOURCE')
        tasks.append(({**s,'path':str(collection/s['path'])},str(contexts[key]),portraits[0],by[key],pre['configuration'],str(out)))
    protocol=dict(gap_count=len(gaps),date_count=len(tasks),configuration=pre['configuration'],
        arms=['none','interval_v1'],fixed_seed=pre['configuration']['seed'],
        source_gap_sha256=sha(prior/'FIFTY_GAP_DIAGNOSTICS.json'),code_sha256=code_hash(),
        helper_sha256=sha(__file__),tasks=tasks,diagnostic_only=True,official_selection_changed=False,physical_runs=0)
    save(out/'PROTOCOL.json',protocol);results=[]
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for r in pool.map(job,tasks,buffersize=workers*2):
            results.append(r);save(out/'PROGRESS.json',results)
            print(len(results),'/',len(tasks),r['household_id'],r['arms'],flush=True)
    if code_hash()!=protocol['code_sha256']:raise ValueError('GENERATOR_CHANGED_DURING_REVIEW')
    totals={mode:dict(sum((Counter(r['arms'][mode]) for r in results),Counter())) for mode in protocol['arms']}
    report=dict(gaps=len(gaps),completed=sum(r['gaps'] for r in results),arms=totals,
        independent_errors=sum(r['independent_errors'] for r in results),coverage_accepted=False,
        scope='targeted_fixed_gap_queries;not_regenerated_or_reselected_500_questions')
    save(out/'SUMMARY.json',report);return report


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--prior',required=True);p.add_argument('--out',required=True);p.add_argument('--workers',type=int,default=2)
    a=p.parse_args();print(run(a.prior,a.out,a.workers))
