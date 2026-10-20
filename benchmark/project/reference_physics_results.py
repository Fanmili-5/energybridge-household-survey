"""Read paired physics into a version-bound, complete 500-case result ledger.

Keep unrun/unsupported/failed rows as null. This sidecar never edits an already
sealed questionnaire or retrospectively changes a respondent's information.
"""
import argparse
import json
from collections import Counter
from pathlib import Path
from benchmark.ab_generation.common import read, save, sha, verify, seal
from benchmark.ab_generation.outcomes import consequences


def bind(collection, exported, compiled, runs, audit, out):
    collection,exported,compiled,runs,audit,out=map(lambda p:Path(p).resolve(),(collection,exported,compiled,runs,audit,out))
    verify(collection);em=verify(exported);cm=verify(compiled);rm=verify(runs);am=verify(audit)
    if em['selection_sha256']!=sha(collection/'ASSIGNMENT.json'):raise ValueError('RESULT_SELECTION_MISMATCH')
    if rm['compiled_manifest_sha256']!=sha(compiled/'MANIFEST.json') or am['runs_manifest_sha256']!=sha(runs/'MANIFEST.json') or am['compiled_manifest_sha256']!=sha(compiled/'MANIFEST.json'):raise ValueError('RESULT_RUN_AUDIT_MISMATCH')
    cases=read(exported/'INPUT_REVIEW500.json')['records'];compiled_rows={r['id']:r for r in cm['records']};audits={r['id']:r for r in am['records']}
    if not set(compiled_rows)<={r['id'] for r in cases}:raise ValueError('UNKNOWN_COMPILED_COLLECTION_CASE')
    rows=[]
    for item in cases:
        ident=item['id'];row={**item,'outcomes':None,'questionnaire_payload_changed':False}
        if item['status']=='unsupported_world':rows.append(row);continue
        if ident not in compiled_rows:
            row['status']='not_computed';rows.append(row);continue
        if compiled_rows[ident]['status']!='compiled':
            row.update(status='compile_failed',reason='See preserved compiler log');rows.append(row);continue
        if compiled_rows[ident]['pair_sha256']!=item['pair']['sha256'] or compiled_rows[ident]['household_sha256']!=item['household']['sha256']:raise ValueError('RESULT_COMPILED_INPUT_MISMATCH')
        paths={s:runs/ident/s/'RESULT.json' for s in ('A','B')}
        if not all(p.exists() for p in paths.values()):
            row.update(status='incomplete_pair',reason='Both A and B receipts are required');rows.append(row);continue
        results={s:read(p) for s,p in paths.items()}
        if any(r['status']!='completed' for r in results.values()):
            row.update(status='execution_failed',reason='Preserved engine failure;no replacement B');rows.append(row);continue
        frozen_path=collection/'pairs'/(ident+'.json');frozen=read(frozen_path)
        if sha(frozen_path)!=item['source_frozen_pair_sha256']:raise ValueError('RESULT_FROZEN_PLAN_CHANGED')
        pair_path=exported/'resources'/item['pair']['path']
        if sha(pair_path)!=item['pair']['sha256']:raise ValueError('RESULT_EXPORTED_PAIR_CHANGED')
        pair=read(pair_path);metas={s:read(compiled/ident/s/'INPUT.json.gz') for s in ('A','B')}
        traces={}
        for side in ('A','B'):
            result=results[side];meta=metas[side];trace_path=runs/ident/side/'TRACE.json.gz';sql=runs/ident/side/'out/eplusout.sql'
            if meta['source_pair_sha256']!=pair['source_pair_sha256'] or meta['source_schedule_hash']!=pair['schedule_hashes'][side] or result['idf_sha256']!=meta['idf_sha256'] or result['trace_sha256']!=sha(trace_path) or result['SQL_sha256']!=sha(sql):raise ValueError('RESULT_ARM_BINDING_MISMATCH')
            traces[side]=read(trace_path)
        check=audits.get(ident)
        if check is None:
            row.update(status='audit_missing',reason='No complete paired audit;outcomes remain null');rows.append(row);continue
        context=read(collection/'contexts'/(frozen['row']['case_id']+'.json.gz'))
        row.update(status='computed',outcomes=consequences(pair,metas,traces,check,context),
            audit_status=check['status'],failed_checks=[k for k,v in check['checks'].items() if not v],
            engine_runs=2,IDFs_compiled=True,
            receipts={s:{k:results[s][k] for k in ('engine_sha256','idf_sha256','SQL_sha256','trace_sha256')} for s in ('A','B')})
        rows.append(row)
    out.mkdir(parents=True,exist_ok=False)
    summary={'cases':len(rows),'statuses':dict(Counter(r['status'] for r in rows)),
        'engine_arms_in_this_bound_run':len(rm['records']),'collection_answers_or_payloads_changed':False,
        'old_B_results_used':False,'reselection_after_results':False,'full1000_deferred':True}
    save(out/'RESULT_INDEX500.json',{'schema':'eb.reference50.bound_physics_results.v1',**summary,'records':rows})
    seal(out,{'schema':'eb.reference50.bound_physics_results.v1','source_selection_sha256':sha(collection/'ASSIGNMENT.json'),
        'export_manifest_sha256':sha(exported/'MANIFEST.json'),'compiled_manifest_sha256':sha(compiled/'MANIFEST.json'),
        'runs_manifest_sha256':sha(runs/'MANIFEST.json'),'audit_manifest_sha256':sha(audit/'MANIFEST.json'),
        'readback_code_sha256':sha(Path(__file__))})
    return summary


if __name__=='__main__':
    p=argparse.ArgumentParser()
    for name in ('collection','exported','compiled','runs','audit','out'):p.add_argument('--'+name,required=True)
    a=p.parse_args();print(json.dumps(bind(a.collection,a.exported,a.compiled,a.runs,a.audit,a.out),ensure_ascii=False))
