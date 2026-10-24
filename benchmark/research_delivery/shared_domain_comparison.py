"""Matched-domain comparisons; cache only deterministic native construction.

Each seed/date constructs one complete domain, then runs all declared search
arms. Generation/admission/selection rules are not replaced. Shared immutable
domain artifacts avoid six copies of the same grid; all arms keep full search
records, failures and unknowns. Timing separates shared construction from arms.
"""
import argparse
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
import time
from unittest.mock import patch

from benchmark.ab_generation.common import read,save,sha,digest,bound
from benchmark.ab_generation.unified.contract import config,code_hash
from benchmark.ab_generation.unified.candidates import prepare,catalogue_domains
from benchmark.ab_generation.unified.factorized import export
from benchmark.ab_generation.unified.pipeline import _job
from benchmark.ab_generation.unified.delivery import metrics

ARMS=(('ipog_base',{}),('round_robin',{'search_strategy':'legacy_round_robin_adapter'}),
      ('budget_half',{'rows_per_unit':8}),('budget_double',{'rows_per_unit':32}),
      ('encoding_half',{'oracle_native_encoding_budget':128}),('encoding_double',{'oracle_native_encoding_budget':512}))
SHARED_FIELDS=('native_domains','native_templates','support_native_domain','factors')


def grammar_fingerprint(g):
    encoded,templates=export(g['values']+[g['support_domain']])
    return digest(dict(encoded=encoded,templates=templates,descriptors=g['descriptors'],domains=g['domains'],
                       diagnostics=g['engineering_diagnostics'],gaps=g['gaps'],raw_count=g['raw_count'],unmodified=g['unmodified']))


def read_catalogue(path):
    path=Path(path);record=read(path);ref=record.get('shared_native_domain')
    if not ref:return record
    source=bound(path.parent,ref['path'])
    if sha(source)!=ref['sha256']:raise ValueError('SHARED_NATIVE_DOMAIN_HASH_MISMATCH')
    shared=read(source)
    if set(shared)!=set(SHARED_FIELDS):raise ValueError('INCOMPLETE_SHARED_NATIVE_DOMAIN')
    if digest(shared)!=ref['content_sha256']:raise ValueError('SHARED_NATIVE_DOMAIN_CONTENT_MISMATCH')
    return {**record,**shared}


def group_job(task):
    record,base,out,arms=task;out=Path(out);out.mkdir(parents=True,exist_ok=False)
    raw=read(record['context_path']);cfg=config(base);c=prepare(raw,cfg)
    sources={str(p):sha(p) for p in (record['context_path'],record['portrait_path'])}
    started=time.perf_counter();g=catalogue_domains(c,cfg);construction_seconds=time.perf_counter()-started
    fingerprint=grammar_fingerprint(g);results=[];shared_hash=None;shared_content=None
    save(out/'PREDECLARED.json',dict(input_record=record,configuration=cfg,arms=arms,sources=sources,
        grammar_fingerprint=fingerprint,construction_seconds=construction_seconds,
        code_sha256=code_hash(),helper_sha256=sha(__file__),native_scope=g['scope']))
    for arm,change in arms:
        if set(change)-{'search_strategy','rows_per_unit','oracle_native_encoding_budget'}:
            raise ValueError('ARM_CHANGES_NATIVE_DOMAIN;REUSE_FORBIDDEN')
        arm_cfg=config({**cfg,**change});started=time.perf_counter()
        # Process-isolated, sequential arms: no concurrent global monkeypatch.
        # Only deterministic grammar construction is memoized; every oracle,
        # budget, literal request and independent audit is executed normally.
        with patch('benchmark.ab_generation.unified.candidates.catalogue_domains',return_value=g):
            result=_job((record,arm_cfg))
        seconds=time.perf_counter()-started
        if grammar_fingerprint(g)!=fingerprint:raise ValueError('SEARCH_MUTATED_SHARED_NATIVE_DOMAIN')
        shared={k:result.pop(k) for k in SHARED_FIELDS} if all(k in result for k in SHARED_FIELDS) else None
        if shared is not None:
            content=digest(shared)
            if shared_content is None:
                save(out/'NATIVE_DOMAIN.json.gz',shared);shared_content=content;shared_hash=sha(out/'NATIVE_DOMAIN.json.gz')
            elif shared_content!=content:raise ValueError('MATCHED_ARM_NATIVE_DOMAIN_CHANGED')
            result['shared_native_domain']=dict(path='NATIVE_DOMAIN.json.gz',sha256=shared_hash,content_sha256=shared_content,
                encoding='shared_exact_native_fields_v1;use_read_catalogue_to_reconstruct')
        result['comparison']=dict(arm=arm,configuration=arm_cfg,input_record=record,wall_seconds=seconds,
            shared_native_construction_seconds=construction_seconds,shared_domain_fingerprint=fingerprint,
            outcome_or_acceptance_used=False,timing_scope='search_and_audit_with_preconstructed_domain;construction_reported_separately')
        path=out/(arm+'.json.gz');save(path,result)
        results.append(dict(arm=arm,seed=cfg['seed'],household_id=record['household_id'],date=record['date'],path=str(path),
            shared_native_construction_seconds=construction_seconds,
            timing_scope='search_and_audit_with_preconstructed_domain;construction_separate',**metrics(result)))
        save(out/'PROGRESS.json',results)
        del result,shared
    changed=[p for p,h in sources.items() if sha(p)!=h]
    if changed:raise ValueError('COMPARISON_SOURCE_CHANGED:'+str(changed))
    save(out/'RESULTS.json',results)
    return results


def run(protocol,out,workers=1):
    protocol,out=Path(protocol),Path(out);plan=read(protocol);out.mkdir(parents=True,exist_ok=False)
    if len(plan['comparison_records'])!=24 or plan['seeds']!=list(range(8)):
        raise ValueError('EXPECTED_FROZEN_24_DATES_AND_EIGHT_SEEDS')
    base=config(plan['base_config']);pins=code_hash();jobs=[]
    for seed in plan['seeds']:
        for record in plan['comparison_records']:
            cfg={**base,'seed':seed};key=digest([record,cfg])[:24]
            jobs.append((record,cfg,str(out/'groups'/key),ARMS))
    save(out/'PROTOCOL.json',dict(source_protocol_sha256=sha(protocol),plan=plan,arms=ARMS,code_sha256=pins,
        helper_sha256=sha(__file__),groups=len(jobs),runs=len(jobs)*len(ARMS),workers=workers,
        full_domains_retained=True,physical_runs=0,main_updated=False))
    rows=[]
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for completed,result in enumerate(pool.map(group_job,jobs,buffersize=workers*2),1):
            rows.extend(result);save(out/'PROGRESS.json',rows)
            print('matched group',completed,'/',len(jobs),'arms',len(rows),flush=True)
    if pins!=code_hash():raise ValueError('GENERATOR_CHANGED_DURING_COMPARISON')
    save(out/'RESULTS.json',rows)
    summary=dict(completed=len(rows),expected=len(jobs)*len(ARMS),groups=len(jobs),
        all_seeds_retained=True,independent_errors=sum(r['independent_errors'] for r in rows),
        shared_storage='all literal domain fields retained once per seed/date;hash-checked references',
        scientific_claim='matched-domain comparison;not same elapsed CPU or behavioral validity')
    save(out/'SUMMARY.json',summary);return summary


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--protocol',required=True);p.add_argument('--out',required=True);p.add_argument('--workers',type=int,default=1)
    a=p.parse_args();print(run(a.protocol,a.out,a.workers))
