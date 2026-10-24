"""Frozen calendar counterexamples and one full, outcome-blind pilot date."""
import argparse
from pathlib import Path
import time

from benchmark.ab_generation.common import read, save, sha, digest
from benchmark.ab_generation.model import apply
from benchmark.ab_generation.unified.contract import config, code_hash
from benchmark.ab_generation.unified.candidates import prepare, program_grammar, legacy_config, issues
from benchmark.ab_generation.unified.factorized import ProgramRecipe
from benchmark.ab_generation.unified.independent import audit
from benchmark.ab_generation.unified.pipeline import _job
from .acceptance import record_sources


def run(prior, examples, configuration, out):
    prior,examples,out=map(Path,(prior,examples,out))
    out.mkdir(parents=True,exist_ok=False)
    pre,contexts=record_sources(prior);cfg=config(read(configuration))
    samples=read(examples)['records'];records=[]
    slots={(s['household_id'],s['date']):s for s in read(prior/'GENERATION.json')}
    sources={str(p):sha(p) for p in {contexts[(r['household_id'],r['date'])] for r in samples}}
    save(out/'PROTOCOL.json',dict(configuration=cfg,code_sha256=code_hash(),helper_sha256=sha(__file__),
        counterexamples_sha256=sha(examples),sources=sources,
        dates=[(r['household_id'],r['date']) for r in samples],
        full_pilot_date=(samples[0]['household_id'],samples[0]['date']),
        official_bank_changed=False,physical_runs=0))
    for sample in samples:
        key=sample['household_id'],sample['date'];c=prepare(read(contexts[key]),cfg)
        asset=sample['patches'][0]['rows'][0]['asset_id']
        device=next(d for d in c['devices'] if d['asset_id']==asset)
        target=digest(sample['patches']);found=None
        for r in program_grammar(c,device,legacy_config(cfg),cfg['handling_calendar_domain']):
            if not isinstance(r,ProgramRecipe):continue
            if digest(r['patches'])==target:
                found=r;break
        old=read(prior/slots[key]['path'])
        old_ids={v['id'] for vs in old['native_domains'] for v in vs if v}
        checks=issues(c,found['patches'],found['needs']) if found else ([],[],{})
        errors=audit(c,c['A'],apply(c['A'],found['patches'])) if found else None
        record=dict(household_id=key[0],date=key[1],literal_sha256=target,
            previously_in_native_domain=target in old_ids,now_constructed=found is not None,
            life_issues=checks[0],hard_gate=checks[1],independent_engineering_errors=errors,
            input_sha256=sha(contexts[key]),not_appended_to_official_bank=True)
        records.append(record);save(out/'COUNTEREXAMPLES.json',records)
        print(key,'constructed',record['now_constructed'],'engineering',errors,flush=True)
    key=samples[0]['household_id'],samples[0]['date']
    portraits=[p for p in pre['source_sha256'] if Path(p).name==key[0]+'.json']
    if len(portraits)!=1:raise ValueError('AMBIGUOUS_PORTRAIT_SOURCE')
    item=dict(household_id=key[0],date=key[1],context_path=str(contexts[key]),portrait_path=portraits[0])
    started=time.perf_counter();pilot=_job((item,cfg))
    save(out/'PILOT.json.gz',pilot)
    old=read(prior/slots[key]['path'])
    old_ids={v['id'] for vs in old['native_domains'] for v in vs if v}
    new_ids={v['id'] for vs in pilot.get('native_domains',[]) for v in vs if v}
    grid=dict(old_native_ids=len(old_ids),new_native_ids=len(new_ids),
        removed_old_ids=sorted(old_ids-new_ids),added_ids=len(new_ids-old_ids),
        source_A_hash_unchanged=old['A_commands_sha256']==pilot.get('A_commands_sha256'),
        input_context_hash_unchanged=old['context_sha256']==pilot.get('context_sha256'),
        explicit_domain_revision=True,original_step_min=10,new_step_min=10)
    save(out/'DOMAIN_CROSSWALK.json',grid)
    changed=[p for p,h in sources.items() if sha(p)!=h]
    report=dict(counterexamples=len(records),all_constructed=all(r['now_constructed'] for r in records),
        counterexample_errors=sum(bool(r['independent_engineering_errors']) or r['independent_engineering_errors'] is None for r in records),
        pilot_status=pilot['status'],pilot_rows=len(pilot.get('rows',[])),
        pilot_independent_errors=pilot.get('independent_engineering_errors'),
        pilot_mechanisms=pilot.get('independent_opportunity_coverage'),
        pilot_telemetry=pilot.get('telemetry'),elapsed_with_export_seconds=time.perf_counter()-started,
        domain_crosswalk=grid,sources_changed=changed,
        code_unchanged=read(out/'PROTOCOL.json')['code_sha256']==code_hash(),
        full_fifty_acceptance=False,physical_runs=0)
    save(out/'RESULT.json',report)
    return {k:v for k,v in report.items() if k!='pilot_mechanisms'}


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--prior',required=True);p.add_argument('--examples',required=True)
    p.add_argument('--config',required=True);p.add_argument('--out',required=True)
    a=p.parse_args();print(run(a.prior,a.examples,a.config,a.out))
