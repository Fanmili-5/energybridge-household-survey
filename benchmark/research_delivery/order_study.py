"""One-factor IPOG column-order sensitivity using the frozen full native grammar.

Reuses no previously discovered witness. Physical/life outcomes and acceptance
never enter the oracle. Both orders share all other probes and numeric budgets.
The measured scope ends before optional outside-event support closure.
"""
import argparse
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from benchmark.ab_generation.common import read,save,digest,sha,canonical
from benchmark.ab_generation.unified.candidates import prepare,Oracle
from benchmark.ab_generation.unified.factorized import ProgramRecipe
from benchmark.ab_generation.unified.contract import config
from benchmark.ab_generation.unified.ipog import generate
from benchmark.ab_generation.unified.independent import audit
from benchmark.ab_generation.model import apply
from .shared_domain_comparison import read_catalogue


def job(task):
    record,basefile,cfg,out=task;cat=read_catalogue(basefile);c=prepare(read(record['context_path']),cfg)
    portrait=read(record['portrait_path']);values=[]
    for group in cat['native_domains']:
        vs=[]
        for r in group:
            if r and 'recipe' in r:
                t=cat['native_templates'][r['recipe']['template']]
                v=ProgramRecipe(t['template'],t['load'],t['unload'],r['recipe']['load_min'],r['recipe']['unload_min']);v.update(r);vs.append(v)
            else:vs.append(r)
        values.append(vs)
    g=dict(values=values,descriptors=cat['factors'],domains=[list(range(len(ds))) for ds in cat['factors']])
    n=len(values);budget=cfg['rows_per_unit']*max(1,n);axes={tuple(i for i,v in r['target']) for r in cat['coverage']['coverage']}
    triples=[a for a in axes if len(a)==3];summaries=[]
    for label,perm in [('original',list(range(n))),('reversed',list(reversed(range(n))))]:
        oracle=Oracle(c,g,cfg,portrait)
        for i,d in enumerate(g['domains']):
            if len(d)>1:oracle({**{j:0 for j in range(n) if j!=i},i:d[1]})
        for order in range(1,n+1):oracle({},order=order)
        for i,vs in enumerate(values):
            mechanisms=defaultdict(list)
            for j,r in enumerate(vs[1:],1):mechanisms[(r['mechanism'],r['magnitude'].get('axis','program'))].append(j)
            for _,ids in sorted(mechanisms.items()):oracle({j:0 for j in range(n) if j!=i},native_required={i:ids})
        inv={p:i for i,p in enumerate(perm)}
        def mapped(partial):
            status,witness,reason=oracle({perm[i]:v for i,v in partial.items()})
            return status,([witness[p] for p in perm] if witness is not None else None),reason
        result=generate([g['domains'][p] for p in perm],mapped,triples=[tuple(inv[i] for i in t) for t in triples],
            seed=cfg['seed'],row_budget=budget,query_budget=cfg['queries_per_row']*budget)
        for i,vs in enumerate(values):
            named=defaultdict(list)
            for j,r in enumerate(vs[1:],1):
                m=r['magnitude'];named[(r['mechanism'],r['relative_level'],m.get('duration_min'),m.get('precondition_min'))].append(j)
            for _,ids in sorted(named.items(),key=lambda kv:canonical(kv[0])):
                oracle({j:0 for j in range(n) if j!=i},native_required={i:ids})
        rows=list(oracle.rows.values());errors=[]
        for r in rows:
            e=audit(c,c['A'],apply(c['A'],r['patches']))
            if e:errors.append(dict(id=r['id'],errors=e))
        hit=set()
        for _,cells,_ in oracle.witnesses:
            for a in axes:hit.add(tuple((i,cells[i]) for i in a))
        stats=dict(household_id=record['household_id'],date=record['date'],seed=cfg['seed'],order=label,
            rows=len(rows),semantic_cell_interaction_witnesses=len(hit),oracle_calls=oracle.calls,materializations=oracle.materializations,
            independent_errors=len(errors),input_native_grammar_sha256=sha(basefile),
            scope='IPOG_column_order_only;common_breadth_and_detail_probes;before_optional_support_closure')
        save(Path(out)/(label+'.json.gz'),dict(summary=stats,rows=rows,diagnostics=oracle.diagnostics,engineering_errors=errors,coverage=result))
        summaries.append(stats)
    return summaries


def run(out,workers=6):
    out=Path(out);rows=read(out/'comparisons/RESULTS.json')
    comparison_protocol=out/'comparisons/PROTOCOL.json'
    protocol=read(comparison_protocol)['plan'] if comparison_protocol.exists() else read(out/'PROTOCOL.json')
    by={(r['seed'],r['household_id'],r['date']):r for r in rows if r['arm']=='ipog_base'};jobs=[]
    for seed in protocol['seeds']:
        for record in protocol['comparison_records']:
            r=by[(seed,record['household_id'],record['date'])];cfg=config({**protocol['base_config'],'seed':seed})
            jobs.append((record,r['path'],cfg,out/'order-study'/digest([seed,record])[:24]))
    results=[]
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for pair in pool.map(job,jobs,buffersize=workers*2):
            results+=pair;save(out/'order-study/PROGRESS.json',results);print('factor orders',len(results),'/384',flush=True)
    save(out/'order-study/RESULTS.json',results);return dict(runs=len(results),independent_errors=sum(r['independent_errors'] for r in results))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--out',required=True);p.add_argument('--workers',type=int,default=6)
    a=p.parse_args();print(run(a.out,a.workers))
