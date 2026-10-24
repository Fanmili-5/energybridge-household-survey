"""Locate unresolved mechanisms without upgrading generator diagnostics to proof."""
import argparse
from collections import Counter,defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from benchmark.ab_generation.common import read,save,sha
from benchmark.ab_generation.unified.semantics import mechanism


def job(task):
    slot,path,gaps=task;cat=read(path);records=[]
    for e in gaps:
        factors=[];native=0;labels=[]
        for i,vs in enumerate(cat['native_domains']):
            matches=[v for v in vs if v and (v['asset_id'],v.get('service_need_id'),mechanism(v['mechanism']),v['magnitude'].get('axis'))==(e['asset_id'],e['need_id'],e['mechanism'],e['axis'])]
            if matches:factors.append(i);native+=len(matches);labels.extend(sorted({v['mechanism'] for v in matches}))
        probes=[p for p in cat.get('within_device_interactions',[]) if p['factor'] in factors and mechanism(p['target'][0])==e['mechanism']]
        reasons=Counter((p['status'],p.get('reason')) for p in probes)
        dependent=[]
        for r in cat['rows']:
            for c in r['components']:
                if (c['asset_id'],c.get('service_need_id'),mechanism(c['mechanism']),c['magnitude'].get('axis'))==(e['asset_id'],e['need_id'],e['mechanism'],e['axis']) and c['event_relevance']['role']!='direct_event_request':dependent.append(r['id'])
        records.append(dict(household_id=slot['household_id'],date=slot['date'],asset_id=e['asset_id'],need_id=e['need_id'],family=e['family'],mechanism=e['mechanism'],axis=e['axis'],
            independent_input_reason=e['reason'],native_alternatives=native,factors=factors,raw_mechanism_names=sorted(set(labels)),
            saved_single_unit_probe_results=[dict(status=k[0],reason=k[1],count=v) for k,v in reasons.items()],
            dependent_only_witness_ids=sorted(set(dependent)),catalogue_sha256=sha(path),
            attribution='bounded_single_unit_extension_search;global_joint_feasibility_unresolved',
            structural_impossibility_claimed=False,generator_self_checks_are_not_independent_feasibility_proof=True))
    return records


def run(out,label,collection,workers=4):
    out,collection=Path(out),Path(collection);ledger=read(out/(label+'_INPUT_OPPORTUNITY_COVERAGE.json.gz'))
    by={(x['household_id'],x['date']):[e for e in x['mechanisms'] if e['status']=='potential' and e['gap']] for x in ledger};tasks=[]
    for slot in read(collection/'GENERATION.json'):
        es=by[(slot['household_id'],slot['date'])]
        if es:tasks.append((slot,collection/slot['path'],es))
    with ProcessPoolExecutor(max_workers=workers) as pool:rows=[r for rs in pool.map(job,tasks,buffersize=workers*2) for r in rs]
    result=dict(records=rows,unresolved=len(rows),all_have_native_implementation=all(r['native_alternatives'] for r in rows),
        mechanisms=dict(Counter(r['family']+':'+r['mechanism'] for r in rows)),
        statement='absence of direct witness is not no-opportunity;single-unit infeasibility does not exclude a joint repair or dependency')
    save(out/(label+'_GAP_DIAGNOSTICS.json'),result);return {k:v for k,v in result.items() if k!='records'}


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--out',required=True);p.add_argument('--label',required=True);p.add_argument('--collection',required=True);p.add_argument('--workers',type=int,default=4)
    a=p.parse_args();print(run(a.out,a.label,a.collection,a.workers))
