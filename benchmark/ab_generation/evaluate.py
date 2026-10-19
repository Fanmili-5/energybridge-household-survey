"""Bound readback after selection, including incomplete and failed executions."""
import json
import lzma
from pathlib import Path
from .common import bound, read, save, seal, sha, verify
from .model import plan_hash
from .outcomes import consequences


def compare_traces(current, previous, same_channels=True):
    previous = {k.lower(): v for k, v in previous.items()}
    names = {k.lower() for k in current}
    rows = []
    for name, values in current.items():
        old = previous.get(name.lower())
        if old is None:
            continue
        now, before = dict(values['values']), dict(old['values'])
        common = now.keys() & before.keys()
        error = max((abs(now[t] - before[t]) for t in common), default=None)
        rows.append({'channel': name, 'unit': values['unit'], 'samples': len(common),
                     'reference_unit_verified': 'unit' in old, 'same_unit': old.get('unit', values['unit']) == values['unit'],
                     'complete_common_timeline': bool(common) and now.keys() == before.keys(),
                     'max_absolute_error': error, 'within_1e_minus6': error is not None and error < 1e-6})
    channels_equal = names == previous.keys()
    passed = bool(rows) and all(r['complete_common_timeline'] and r['within_1e_minus6'] and r['same_unit'] for r in rows) and (channels_equal or not same_channels)
    return {'status': 'passed' if passed else 'failed', 'passed': passed, 'common_channels': len(rows),
            'same_channel_set': channels_equal, 'scope': 'all_channels' if same_channels else 'common_channels_only',
            'within_1e_minus6_each_native_channel': passed, 'channels': rows}


def summarize(job_path, compiled, runs, audit, out, reference_stage=None, imported=None, reference_runs=None):
    job_path, compiled, runs, audit, out = map(Path, (job_path, compiled, runs, audit, out))
    job = read(job_path); cm, rm, am = verify(compiled), verify(runs), verify(audit)
    if cm['input_sha256'] != sha(job_path):
        raise ValueError('REPORT_JOB_COMPILATION_MISMATCH')
    if rm['compiled_manifest_sha256'] != sha(compiled / 'MANIFEST.json'):
        raise ValueError('REPORT_RUN_COMPILATION_MISMATCH')
    if am['compiled_manifest_sha256'] != sha(compiled / 'MANIFEST.json') or am['runs_manifest_sha256'] != sha(runs / 'MANIFEST.json'):
        raise ValueError('REPORT_AUDIT_BINDING_MISMATCH')
    if reference_runs and reference_stage:
        raise ValueError('AMBIGUOUS_A_REFERENCE')
    if reference_runs:
        reference_runs = Path(reference_runs); verify(reference_runs)
    contexts = {}
    if imported:
        incoming = Path(imported); verify(incoming)
        contexts = {r['case_id']: read(bound(incoming, r['context'])) for r in read(incoming / 'BATCH.json')['records']}
    audits = {r['id']: r for r in am['records']}; compiled_records = {r['id']: r for r in cm['records']}
    resources = (job_path.parent / job['resource_root']).resolve(); rows = []
    for entry in job['pairs']:
        pair_path = bound(resources, entry['pair']['path'])
        if sha(pair_path) != entry['pair']['sha256']:
            raise ValueError('REPORT_REQUEST_CHANGED')
        pair = read(pair_path); rid = entry['id']; context = contexts.get(pair['case_id'])
        if context and (plan_hash(pair['A']) != context['reference']['binding']['A_commands_sha256'] or pair['VPP_events'] != context['events']):
            raise ValueError('PRICING_CONTEXT_MISMATCH')
        if context and pair['AB_generation'].get('information_set') != context['reference'].get('information_set'):
            raise ValueError('REPORT_INFORMATION_CONDITION_MISMATCH')
        check = audits.get(rid, {'status': 'missing', 'checks': {}, 'details': {}})
        row = {'case_id': pair['case_id'], 'policy': pair['AB_generation']['policy'],
               'information_set': pair['AB_generation'].get('information_set'),
               'proposal_purpose': pair['AB_generation'].get('proposal_purpose'),
               'baseline_admission': pair['AB_generation'].get('baseline_admission'),
               'request_status': pair['AB_generation']['status'], 'engine_arms': 2,
               'A_reference_comparison': {'status': 'not_requested', 'passed': None},
               'audit_status': check['status'], 'failed_checks': [k for k, v in check['checks'].items() if not v],
               'actual_results_used_for_reselection': False, 'human_acceptance': None}
        try:
            if compiled_records.get(rid, {}).get('status') != 'compiled':
                raise ValueError('MODEL_NOT_COMPILED')
            results = {s: read(runs / rid / s / 'RESULT.json') for s in ('A', 'B')}
            row['engine_status'] = {s: results[s]['status'] for s in ('A', 'B')}
            if any(r['status'] != 'completed' for r in results.values()):
                raise ValueError('ENGINE_EXECUTION_INCOMPLETE')
            metas = {s: read(compiled / rid / s / 'INPUT.json.gz') for s in ('A', 'B')}
            traces = {s: read(runs / rid / s / 'TRACE.json.gz') for s in ('A', 'B')}
            for side in ('A', 'B'):
                if results[side]['idf_sha256'] != metas[side]['idf_sha256'] or results[side]['trace_sha256'] != sha(runs / rid / side / 'TRACE.json.gz') or results[side]['SQL_sha256'] != sha(runs / rid / side / 'out/eplusout.sql'):
                    raise ValueError('REPORT_ARM_RECEIPT_MISMATCH')
            row['history_days'] = metas['A']['history_days']
            row.update(consequences(pair, metas, traces, check, context))
            row['readback_status'] = 'complete'
            if reference_runs:
                oldpath = reference_runs / rid / 'A/TRACE.json.gz'
                if context is None or sha(oldpath) != context['source']['A_trace_sha256']:
                    raise ValueError('CURRENT_A_REFERENCE_TRACE_MISMATCH')
                row['A_reference_comparison'] = {**compare_traces(traces['A'], read(oldpath)), 'reference_trace_sha256': sha(oldpath)}
            elif reference_stage:
                oldpath = Path(reference_stage) / 'results/pilot50' / pair['household_id'] / pair['date'] / 'A/TRACE.json.xz'
                old = json.loads(lzma.decompress(oldpath.read_bytes()))['channels']
                normalized = {k: {'values': v} for k, v in old.items()}
                row['A_reference_comparison'] = {**compare_traces(traces['A'], normalized, False), 'reference_archive_sha256': sha(oldpath)}
        except (ValueError, KeyError, OSError) as error:
            row['readback_status'] = 'incomplete'; row['readback_reason'] = str(error)
            row['unverified_outcomes_are_not_zero'] = True
        rows.append(row)
    out.mkdir(parents=True, exist_ok=False)
    save(out / 'REPORT.json', {'schema': 'eb.ab_generation.physical_report.v3', 'records': rows,
                              'whole500_physical_acceptance': False, 'human_acceptance_inferred': False})
    seal(out, {'job_sha256': sha(job_path), 'compiled_manifest_sha256': sha(compiled / 'MANIFEST.json'),
               'runs_manifest_sha256': sha(runs / 'MANIFEST.json'), 'audit_manifest_sha256': sha(audit / 'MANIFEST.json')})
    return {'reported_cases': len(rows), 'engine_arms': sum(r['engine_arms'] for r in rows),
            'complete_readbacks': sum(r['readback_status'] == 'complete' for r in rows)}
