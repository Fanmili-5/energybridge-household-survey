"""Supplement a sealed mapped bank with the pinned literal checker.

Reads the canonical admitted-row bank and original contexts, not the enormous
native domains. No candidates, selection, facts or outcome fields are changed.
This proves literal engineering checks only; coverage and causal checks remain
separate evidence.
"""
import argparse
from collections import Counter
from pathlib import Path

from benchmark.ab_generation.common import read,save,sha
from benchmark.ab_generation.model import apply
from benchmark.ab_generation.unified import independent
from benchmark.ab_generation.unified.contract import code_hash
from .acceptance import record_sources


def inspect_rows(rows,contexts):
    ids=Counter(r['id'] for r in rows);dates=Counter();errors=[]
    for row in rows:
        key=(row['household_id'],row['date']);dates[key]+=1
        context=contexts.get(key)
        if context is None:
            errors.append(dict(id=row['id'],household_id=key[0],date=key[1],errors=['UNDECLARED_SOURCE_DATE']))
            continue
        try:
            plan=apply(context['A'],row['patches'])
            bad=independent.audit(context,context['A'],plan)
        except (ValueError,KeyError,TypeError,IndexError) as error:
            bad=['LITERAL_ROW_ERROR:'+type(error).__name__+':'+str(error)]
        if bad:errors.append(dict(id=row['id'],household_id=key[0],date=key[1],errors=bad))
    missing=sorted(set(contexts)-set(dates));unexpected=sorted(set(dates)-set(contexts))
    duplicates=sorted(k for k,n in ids.items() if n>1)
    return dict(passed=not errors and not missing and not unexpected and not duplicates,
                admitted_rows=len(rows),given_date_slots=len(contexts),admitted_date_slots=len(dates),
                missing_given_dates=[list(k) for k in missing],unexpected_dates=[list(k) for k in unexpected],
                duplicate_case_ids=duplicates,engineering_errors=errors)


def run(collection,out,expected_core):
    collection,out=Path(collection).resolve(),Path(out).resolve()
    if out==collection or out.is_relative_to(collection):
        raise ValueError('LITERAL_REVIEW_OUTPUT_INSIDE_FROZEN_BANK')
    out.mkdir(parents=True,exist_ok=False)
    effective=code_hash()
    if effective!=expected_core:
        report=dict(passed=False,admission_error='WRONG_LITERAL_CHECKER_CORE',
                    expected_core_sha256=expected_core,effective_core_sha256=effective)
        save(out/'RESULT.json',report);return report
    manifest=read(collection/'MANIFEST.json');pre,paths=record_sources(collection)
    if manifest.get('schema')!='eb.frozen_catalogue_linked_selection.v1':
        report=dict(passed=False,admission_error='EXPECTED_SEALED_MAPPED_BANK')
        save(out/'RESULT.json',report);return report
    pins=dict(pre['source_sha256'])
    pins[str(collection/'MANIFEST.json')]=sha(collection/'MANIFEST.json')
    for name in ('PRE_GENERATION.json','CANDIDATE_ROWS.json.gz','GENERATION.json'):
        if name not in manifest['files']:
            raise ValueError('CANONICAL_BANK_FILE_NOT_IN_SEAL:'+name)
        pins[str(collection/name)]=manifest['files'][name]
    pins[str(Path(__file__).resolve())]=sha(__file__)
    pins[str(Path(independent.__file__).resolve())]=sha(independent.__file__)
    changed=[p for p,h in pins.items() if not Path(p).is_file() or sha(p)!=h]
    save(out/'PROTOCOL.json',dict(collection=str(collection),expected_core_sha256=expected_core,
         source_pins=pins,original_generation_code_sha256=pre['code_sha256'],
         post_generation_mapping=pre.get('post_generation_mapping'),
         scope='all canonical admitted rows;literal engineering only;not raw domains or coverage',
         no_candidate_generation=True,no_candidate_filtering=True,no_reselection=True,physical_runs=0))
    if changed:
        report=dict(passed=False,admission_error='SOURCE_CHANGED_BEFORE_LITERAL_REVIEW',changed_sources=changed)
        save(out/'RESULT.json',report);return report
    rows=read(collection/'CANDIDATE_ROWS.json.gz');contexts={key:read(path) for key,path in paths.items()}
    generation=read(collection/'GENERATION.json');counts=Counter((r['household_id'],r['date']) for r in generation)
    generation_ok=set(counts)==set(paths) and all(n==1 for n in counts.values())
    report=inspect_rows(rows,contexts)
    changed_after=[p for p,h in pins.items() if not Path(p).is_file() or sha(p)!=h]
    source_ok=not changed_after and code_hash()==expected_core
    report.update(passed=report['passed'] and generation_ok and source_ok,
        generation_dates_exact=generation_ok,source_files_verified_before_and_after=source_ok,
        changed_sources_after=changed_after,checker_core_sha256=expected_core,
        checker_source_sha256=sha(independent.__file__),
        candidate_bank_sha256=pins[str(collection/'CANDIDATE_ROWS.json.gz')],
        candidate_bank_and_original_contexts_unchanged=source_ok,
        causal_or_coverage_acceptance_claimed=False,physical_runs=0,original_records_modified=False)
    save(out/'RESULT.json',report);return report


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    for name in ('collection','out','expected-core'):parser.add_argument('--'+name,required=True)
    args=parser.parse_args();result=run(args.collection,args.out,args.expected_core)
    print({k:v for k,v in result.items() if k!='engineering_errors'})
    if not result['passed']:raise SystemExit(1)
