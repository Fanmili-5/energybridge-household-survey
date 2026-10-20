"""Run every frozen input exactly once, with bounded isolated engine processes.

History groups are explicit input settings, never selected by outcomes. Native
failures stay in the ledger. The complete source export and compiler receipts
are checked before any engine execution. No generation or sampling takes place.
"""
import argparse
import json
import shutil
from pathlib import Path
from benchmark.housing_simulation.pipeline import compile_pairs,run_pairs,read,save,seal,sha,verify
from benchmark.housing_simulation.validation import audit
from .reference_physics_results import bind
from .reference_physics_execute import execute as execute_native


def run(collection,exported,out,engine,engine_sha256,workers=4,resume=False):
    collection,exported,out=map(lambda p:Path(p).resolve(),(collection,exported,out))
    verify(exported);out.mkdir(parents=True,exist_ok=resume)
    compiled=out/'compiled';records=[];receipts=[];resource_hashes=None
    if resume:
        cm=verify(compiled)
        if cm['export_manifest_sha256']!=sha(exported/'MANIFEST.json'):raise ValueError('RESUME_COMPILATION_EXPORT_MISMATCH')
    else:compiled.mkdir()
    for number,name in enumerate([] if resume else read(exported/'JOBS.json')['jobs']):
        group=out/'groups'/str(number)
        m=compile_pairs(exported/name,group,workers)
        if resource_hashes is not None and resource_hashes!=m['resource_hashes']:raise ValueError('GROUP_RESOURCES_DIFFER')
        resource_hashes=m['resource_hashes'];receipts.append({'job':name,'manifest_sha256':sha(group/'MANIFEST.json'),'settings':m['settings']})
        for r in m['records']:
            shutil.copytree(group/r['id'],compiled/r['id']);records.append(r)
        print(json.dumps({'stage':'compile','cases':len(records),'total':500}),flush=True)
    if not resume:
        if len(records)!=500 or len({r['id'] for r in records})!=500:raise ValueError('COMPLETE500_REQUIRED')
        seal(compiled,{'schema':'eb.housing_physics.compilation.v1','export_manifest_sha256':sha(exported/'MANIFEST.json'),
            'resource_hashes':resource_hashes,'group_receipts':receipts,'records':records,'pair_count':500,'new_EnergyPlus_runs':0})
    rm=execute_native(compiled,out/'runs',Path(engine),engine_sha256,workers)
    print(json.dumps({'stage':'executed','arm_receipts':len(rm['records'])}),flush=True)
    audit(compiled,out/'runs',out/'audit')
    summary=bind(collection,exported,compiled,out/'runs',out/'audit',out/'results')
    save(out/'SUMMARY.json',summary);print(json.dumps(summary),flush=True)
    return summary


if __name__=='__main__':
    p=argparse.ArgumentParser()
    for name in ('collection','exported','out','engine','engine-sha256'):p.add_argument('--'+name,required=True)
    p.add_argument('--workers',type=int,default=4);p.add_argument('--resume',action='store_true');a=p.parse_args()
    run(a.collection,a.exported,a.out,a.engine,a.engine_sha256,a.workers,a.resume)
