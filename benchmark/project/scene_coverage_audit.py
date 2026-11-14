"""Recompute changed question coverage from actual original-domain requests.

A sealed parent batch supplies unchanged questions. Every changed proposal is
reconstructed from the frozen household, full daily A, explicit event, and the
original finite action grammar. A stored coverage label is never the oracle.
"""
import argparse,hashlib,json,copy
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor
from collections import Counter
from benchmark.ab_generation.candidate_completion import CompletionContext
from benchmark.ab_generation.scene_coverage import scene_context
from benchmark.ab_generation.cohort_coverage import load,simple_tokens
from benchmark.ab_generation.generate_native import record_raw_cells
from benchmark.ab_generation.unified.candidates import request
from benchmark.ab_generation.common import digest
from benchmark.ab_generation.generate_cohort import save

_STATE=None

def init(parent,households,native,batch):
    global _STATE
    _STATE=(CompletionContext(parent,households,native),Path(batch))

def check(record):
    ctx,batch=_STATE;i=record['index'];date=record['date']
    pair=load(batch/record['relative_path']);old=load(ctx.root/f'{i:04}'/(date+'_PAIR.json.gz'))
    if pair['selected_proposal']==old['selected_proposal']:
        if pair['A']!=old['A'] or pair['B']!=old['B']:raise ValueError('UNCHANGED_PROPOSAL_PLAN_CHANGED')
        return dict(index=i,date=date,status='unchanged_parent_identity')
    row=pair['selected_proposal']
    if row.get('scene_event'):
        base,bound,c,cfg=scene_context(ctx,i,date,row['scene_event']['start_min'])
        from benchmark.ab_generation.unified.candidates import catalogue_domains
        g=catalogue_domains(c,cfg)
    else:c,g=ctx.context(i,date);cfg=ctx.cfg
    raw={r['id']:r for values in g['values'] for r in values if r}
    raw.update({r['id']:r for r in g['support_domain']})
    missing=[x['id'] for x in row['components'] if x['id'] not in raw]
    if missing:raise ValueError('COMPONENT_NOT_IN_REGENERATED_NATIVE_DOMAIN')
    children=[raw[x['id']] for x in row['components']]
    for stored,actual in zip(row['components'],children):
        if stored['patches']!=actual['patches'] or stored['family']!=actual['family'] or stored['mechanism']!=actual['mechanism']:
            raise ValueError('STORED_COMPONENT_MISMATCH')
    actual=request(c,children,cfg,None)
    if actual.get('engineering_diagnostic') or actual.get('relevance_diagnostic') or not actual['native_execution']['passed']:
        raise ValueError('REGENERATED_REQUEST_NOT_QUALIFIED')
    record_raw_cells(dict(factors=g['descriptors'],native_domains=g['values'],rows=[actual]))
    for key in ['patches','raw_root_cells','changed_assets','independent_units','known_event_reduction_kWh','unknown_thermal_response']:
        if actual[key]!=row[key]:raise ValueError('RECOMPUTED_COVERAGE_FIELD_MISMATCH:'+key)
    if simple_tokens(actual)!=simple_tokens(row):raise ValueError('RECOMPUTED_BASIC_TOKEN_MISMATCH')
    if [x['change_axes'] for x in actual['components']]!=[x['change_axes'] for x in row['components']]:
        raise ValueError('RECOMPUTED_CHANGE_AXES_MISMATCH')
    return dict(index=i,date=date,status='changed_proposal_recomputed',cells=len(actual['raw_root_cells']))

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ['parent','batch','households','native-source','out']:p.add_argument('--'+name,required=True,type=Path)
    p.add_argument('--workers',type=int,default=6);a=p.parse_args()
    if not 1<=a.workers<=8:p.error('workers must be1..8')
    records=[json.loads(l) for l in (a.batch/'PAIR_INDEX.jsonl').read_text().splitlines()]
    counts=Counter();results=[]
    with ProcessPoolExecutor(max_workers=a.workers,initializer=init,initargs=(a.parent,a.households,a.native_source,a.batch)) as pool:
        for r in pool.map(check,records):
            results.append(r);counts[r['status']]+=1
            if len(results)%500==0:print(json.dumps(dict(checked=len(results),counts=dict(counts))),flush=True)
    manifest=load(a.batch/'DATASET_MANIFEST.json')
    result=dict(schema='eb.independent_scene_coverage_recomputation.v1',passed=True,questions=len(results),counts=dict(counts),
        input_pair_index_sha256=manifest['pair_index_sha256'],
        audit_code_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        claims='changed labels/features rebuilt from source-domain commands;unchanged rows equal frozen parent;not human realism or physical outcomes')
    save(a.out,result);print(json.dumps(result),flush=True)
if __name__=='__main__':main()
