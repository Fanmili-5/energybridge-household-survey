"""Change only IPOG column order inside the actual frozen production pipeline.

The original arm is reused from the matched comparison. Every reverse-order
oracle, breadth probe, support closure and independent check executes normally.
This replaces neither the grammar nor production's surrounding search policy.
"""
import argparse
import json
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
import time
from unittest.mock import patch

from benchmark.ab_generation.common import read,save,digest,sha,bound
from benchmark.ab_generation.unified import candidates
from benchmark.ab_generation.unified.contract import config,code_hash
from benchmark.ab_generation.unified.pipeline import _job
from benchmark.ab_generation.unified.delivery import metrics
from benchmark.ab_generation.unified.ipog import interactions
from .shared_domain_comparison import grammar_fingerprint,SHARED_FIELDS,ARMS


def reorder_search(search,permutation):
    """Permute IPOG inputs; restore every witness and target to original axes."""
    def run(domains,oracle,*,triples=(),**kwargs):
        n=len(domains);perm=list(permutation)
        if sorted(perm)!=list(range(n)):raise ValueError('INVALID_COLUMN_PERMUTATION')
        inverse={old:new for new,old in enumerate(perm)}
        def original_order(values):
            return [values[inverse[i]] for i in range(n)]
        def mapped(partial):
            status,witness,reason=oracle({perm[i]:v for i,v in partial.items()})
            return status,([witness[i] for i in perm] if witness is not None else None),reason
        result=search([domains[i] for i in perm],mapped,
                      triples=[tuple(inverse[i] for i in t) for t in triples],**kwargs)
        result['rows']=[original_order(row) for row in result['rows']]
        for row in result['coverage']:
            row['target']=sorted([[perm[i],v] for i,v in row['target']])
        by_target={tuple(map(tuple,row['target'])):row for row in result['coverage']}
        result['coverage']=[by_target[target] for target in interactions(domains,triples)]
        return result
    return run


def reverse_job(task):
    record,cfg,basepath,out,expected_core=task;out=Path(out);out.mkdir(parents=True,exist_ok=False)
    if code_hash()!=expected_core:raise ValueError('RUN_ORDER_STUDY_FROM_FROZEN_SOURCE_PACKAGE')
    basepath=Path(basepath);base=read(basepath);source=read(basepath.parent/'PREDECLARED.json')
    if source['code_sha256']!=expected_core or source['input_record']!=record or source['configuration']!=cfg:
        raise ValueError('ORDER_STUDY_BASELINE_MISMATCH')
    pins={p:sha(p) for p in (record['context_path'],record['portrait_path'])}
    if pins!=source['sources']:raise ValueError('FROZEN_ORDER_INPUT_CHANGED')
    ref=base['shared_native_domain'];native=bound(basepath.parent,ref['path'])
    if sha(native)!=ref['sha256']:raise ValueError('ORDER_NATIVE_ARCHIVE_CHANGED')
    original=dict(base['comparison']);base_metrics=metrics(base)
    # Full baseline rows are not provided to the new oracle or constructor.
    del base
    start=time.perf_counter();c=candidates.prepare(read(record['context_path']),cfg)
    grammar=candidates.catalogue_domains(c,cfg);construction=time.perf_counter()-start
    fingerprint=grammar_fingerprint(grammar)
    if fingerprint!=source['grammar_fingerprint']:raise ValueError('ORDER_STUDY_DOMAIN_CHANGED')
    permutation=list(reversed(range(len(grammar['domains']))))
    save(out/'PREDECLARED.json',dict(input_record=record,configuration=cfg,permutation=permutation,
        source_sha256=pins,baseline_path=str(basepath),baseline_sha256=sha(basepath),
        native_path=str(native),native_sha256=sha(native),grammar_fingerprint=fingerprint,
        frozen_core_sha256=expected_core,helper_sha256=sha(__file__),
        construction_seconds=construction,only_changed_factor='IPOG_parameter_column_order',
        original_arm_reused=True,previously_found_witnesses_used_by_new_search=False))
    start=time.perf_counter()
    with patch.object(candidates,'catalogue_domains',return_value=grammar), \
         patch.object(candidates,'generate',reorder_search(candidates.generate,permutation)):
        result=_job((record,cfg))
    elapsed=time.perf_counter()-start
    if grammar_fingerprint(grammar)!=fingerprint:raise ValueError('ORDER_SEARCH_MUTATED_GRAMMAR')
    shared={k:result.pop(k) for k in SHARED_FIELDS}
    if digest(shared)!=ref['content_sha256']:raise ValueError('ORDER_OUTPUT_NATIVE_FIELDS_CHANGED')
    result['comparison_native_reference']=dict(path=str(native),sha256=sha(native),
        content_sha256=ref['content_sha256'],schema='explicit_external_frozen_domain_reference',
        note='Not a standalone catalogue; resolve and verify this archive to restore native fields.')
    summary=dict(household_id=record['household_id'],date=record['date'],seed=cfg['seed'],
        original=base_metrics,reversed=metrics(result),reverse_wall_seconds=elapsed,
        construction_seconds=construction,original_comparison=original,
        scope='actual generate_day and independent _job audit;only IPOG column order changed',
        family_breadth_multibatch_probes_and_support_closure_unchanged=True,
        physical_runs=0,one_factor_comparison=True)
    save(out/'REVERSED.json.gz',result);save(out/'SUMMARY.json',summary)
    if code_hash()!=expected_core or any(sha(p)!=h for p,h in pins.items()):
        raise ValueError('ORDER_STUDY_SOURCE_CHANGED_DURING_RUN')
    return summary


def completed_group_base(results,record,cfg,group):
    """Readiness depends on complete fixed identities, never an arm's success."""
    expected={(name,cfg['seed'],record['household_id'],record['date']) for name,_ in ARMS}
    actual=[(r['arm'],r['seed'],r['household_id'],r['date']) for r in results]
    if len(actual)!=len(expected) or set(actual)!=expected:
        raise ValueError('ORDER_BASELINE_GROUP_INCOMPLETE_OR_DUPLICATE')
    row=next(r for r in results if r['arm']=='ipog_base')
    path=Path(row['path']).resolve()
    if path!=(Path(group)/'ipog_base.json.gz').resolve():
        raise ValueError('ORDER_BASELINE_GROUP_PATH_MISMATCH')
    return str(path)


def available_reverse_job(task):
    record,cfg,basepath,out,expected_core=task
    ready=Path(basepath).parent/'RESULTS.json';announced=False
    while True:
        if code_hash()!=expected_core:raise ValueError('ORDER_FROZEN_CORE_CHANGED_WHILE_WAITING')
        if ready.exists():
            try:results=read(ready)
            except json.JSONDecodeError:
                # The existing producer writes its small completion record in
                # one write. Allow that write to finish; do not rerun a search.
                time.sleep(1);results=read(ready)
            path=completed_group_base(results,record,cfg,ready.parent)
            return reverse_job((record,cfg,path,out,expected_core))
        if not announced:
            print('waiting for fixed complete baseline group',record['household_id'],record['date'],cfg['seed'],flush=True)
            announced=True
        time.sleep(5)


def run(comparison,out,workers=1,wait_for_baselines=False):
    comparison,out=Path(comparison).resolve(),Path(out).resolve()
    protocol=read(comparison/'PROTOCOL.json');plan=protocol['plan']
    if len(plan['comparison_records'])!=24 or plan['seeds']!=list(range(8)):
        raise ValueError('EXPECTED_FROZEN_24_DATES_EIGHT_SEEDS')
    base=None if wait_for_baselines else {(r['seed'],r['household_id'],r['date']):r for r in read(comparison/'RESULTS.json') if r['arm']=='ipog_base'}
    out.mkdir(parents=True,exist_ok=False);jobs=[]
    for seed in plan['seeds']:
        for record in plan['comparison_records']:
            cfg=config({**plan['base_config'],'seed':seed});key=digest([record,cfg])[:24]
            path=str(comparison/'groups'/key/'ipog_base.json.gz') if wait_for_baselines else base[(seed,record['household_id'],record['date'])]['path']
            jobs.append((record,cfg,path,str(out/key),protocol['code_sha256']))
    save(out/'PROTOCOL.json',dict(version='actual_pipeline_column_order_v1',jobs=jobs,
        code_sha256=protocol['code_sha256'],helper_sha256=sha(__file__),
        original_comparison_protocol_sha256=sha(comparison/'PROTOCOL.json'),
        baseline_availability_mode='complete_six_arm_group_barrier' if wait_for_baselines else 'complete_matrix',
        no_success_based_readiness_filter=True,all_192_inputs_declared_before_first_order_run=True,
        previous_manual_probe_helper_not_used=True,physical_runs=0))
    results=[]
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for row in pool.map(available_reverse_job if wait_for_baselines else reverse_job,jobs,buffersize=workers*2):
            results.append(row);save(out/'PROGRESS.json',results)
            print('actual pipeline column order',len(results),'/',len(jobs),flush=True)
    save(out/'RESULTS.json',results)
    summary=dict(records=len(results),expected=len(jobs),all_fixed_inputs_retained=True,
        errors=sum(r['reversed']['independent_errors'] for r in results),
        scope='fixed 192 seed-date inputs;actual pipeline IPOG order only;not all factor permutations or population validity')
    save(out/'SUMMARY.json',summary);return summary


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--comparisons',required=True);p.add_argument('--out',required=True);p.add_argument('--workers',type=int,default=1)
    p.add_argument('--wait-for-baselines',action='store_true')
    a=p.parse_args();print(run(a.comparisons,a.out,a.workers,a.wait_for_baselines))
