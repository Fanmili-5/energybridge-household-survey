"""Read-only audit of the fixed sensitivity run; no generation or reselection."""
import argparse
from collections import Counter
from pathlib import Path

from benchmark.ab_generation.common import code_hash, read, save, sha, verify
from benchmark.ab_generation.evaluate import compare_traces
from benchmark.ab_generation.sampling import response_coverage

# Service deficits are retained observations. Numerical/model/binding failures
# cannot be turned into ordinary negative roleplay examples by this audit.
SERVICE_CHECKS = {side + suffix for side in ('A', 'B') for suffix in
    ('_EV_departure_target', '_hot_water_service', '_service_execution', '_service_completeness', '_declared_comfort')}


def energy(trace, prefix):
    channels = [v for k, v in trace.items() if k.lower().startswith(prefix.lower())]
    if not channels:
        return None
    if any(c['unit'] != 'J' for c in channels):
        raise ValueError('SENSITIVITY_ENERGY_UNIT_MISMATCH')
    return sum(v for c in channels for t, v in c['values'] if 480 <= t < 1920) / 3600000


def analyze(screen_root, physical_root, out):
    screen_root, physical_root, out = map(Path, (screen_root, physical_root, out))
    verify(screen_root); verify(physical_root)
    screen = read(screen_root / 'SCREEN.json'); physical = read(physical_root / 'PHYSICAL.json')
    plan = read(physical_root / 'FROZEN_PLAN.json')
    if physical['plan_sha256'] != sha(screen_root / 'FROZEN_PLAN.json') or physical['plan_sha256'] != screen['plan_sha256']:
        raise ValueError('SENSITIVITY_PLAN_MISMATCH')
    out.mkdir(parents=True, exist_ok=False)
    compact, response_rows = [], []
    baseline_identity = []
    for row in physical['records']:
        folder = physical_root / row['id']
        record = {k: v for k, v in row.items() if k not in ('physical_records', 'baseline_audit', 'B_audit', 'unserved')}
        if 'unserved' in row:
            record['unserved_reasons'] = dict(Counter(r['reason'] for r in row['unserved']))
        if 'baseline_audit' in row:
            record['baseline_audit_passed'] = row['baseline_audit']['passed']
            record['baseline_failed_checks'] = [k for r in row['baseline_audit']['records'] for k, v in r['checks'].items() if not v]
            trace = read(next((folder / 'baseline_runs').glob('*/A/TRACE.json.gz')))
            other = read(next((folder / 'baseline_runs').glob('*/B/TRACE.json.gz')))
            comparison = compare_traces(trace, other)
            baseline_identity.append(comparison['passed'])
            record['baseline_A_equals_B'] = {'passed': comparison['passed'], 'channels': comparison['common_channels'],
                'max_absolute_native_error': max(r['max_absolute_error'] for r in comparison['channels'])}
            record['baseline_A_primary_kWh'] = {k: energy(trace, p) for k, p in {
                'facility': 'Electricity:Facility|', 'cooling_coil': 'Cooling Coil Electricity Energy|',
                'water_heater': 'Water Heater Electricity Energy|', 'ev': 'Exterior Equipment Electricity Energy|EXTERNAL_EV',
                'programs': 'Electric Equipment Electricity Energy|PROGRAM_'}.items()}
        if (folder / 'candidates/MANIFEST.json').exists():
            generated = read(folder / 'candidates' / verify(folder / 'candidates')['records'][0]['path'])
            record['single_conflict_counts'] = dict(Counter(i for c in generated['candidates'] for i in c['static_issues']))
            record['joint_conflict_counts'] = dict(Counter(i for c in generated['joint_candidates'] for i in c['static_issues']))
            record['unavailable_reasons'] = generated['unavailable']
        if row.get('physical_records'):
            report = row['physical_records'][0]
            response_rows.append({'sample_id': row['id'], 'case_id': report['case_id'], 'stratum': row['panel'],
                'coverage_credit': True, 'features': {'admission': 'physical'}, 'observation': {'report': report}})
            record['observation'] = {k: report[k] for k in ('readback_status', 'failed_checks', 'targeted_response',
                'metered_energy', 'events', 'simulated_facility_cost', 'request_opportunity', 'independent_comfort') if k in report}
            record['A_reference_passed'] = report['A_reference_comparison']['passed']
            record['A_reference_max_absolute_native_error'] = max(r['max_absolute_error'] for r in report['A_reference_comparison']['channels'])
            record['physical_report_sha256'] = sha(folder / 'report/REPORT.json')
            record['selection_receipt_sha256'] = sha(folder / 'FROZEN_B_SELECTION.json')
        compact.append(record)
    coverage = response_coverage(response_rows, {'minimum_changed_kinds': [],
        'maximum_supported_no_response_fraction': plan['maximum_supported_no_response_fraction']})
    checks = {
        'all_planned_physical_cases_accounted': ({r['id'] for r in compact} == {r['id'] for r in plan['physical_cases']}
            and len(compact) == len(plan['physical_cases'])),
        'generation_invariants_passed': screen['invariants_passed'],
        'all_baseline_identity_controls_passed': bool(baseline_identity) and all(baseline_identity),
        'all_executed_B_readbacks_and_A_references_bound': bool(response_rows) and all(
            r['observation']['report']['readback_status'] == 'complete'
            and r['observation']['report']['A_reference_comparison']['passed'] for r in response_rows),
        'no_unclassified_numerical_or_model_audit_failures': all(
            not (set(r.get('baseline_failed_checks', [])) | set(r.get('observation', {}).get('failed_checks', []))) - SERVICE_CHECKS
            for r in compact),
        'response_accounting_gate_passed': coverage['passed'],
        'all_raw_generation_cases_hash_verified': all(sha(screen_root / r['raw']) == r['raw_sha256'] for r in screen['records']),
        'frozen_plan_and_code_match': screen['code_sha256'] == physical['code_sha256'] == code_hash(),
        'no_outcome_reselection': not screen['outcome_reselection'] and not physical['outcome_reselection'],
    }
    result = {'schema': 'eb.ab_parameter_sensitivity.validation.v1', 'checks': checks, 'integrity_passed': all(checks.values()),
        'generation_cases': screen['generation_cases'], 'generation_statuses': dict(Counter(r['status'] for r in screen['records'])),
        'physical_cases': len(compact), 'physical_statuses': dict(Counter(r['status'] for r in compact)),
        'engine_arms': physical['engine_arms'], 'baseline_identity_controls': len(baseline_identity),
        'executed_B_cases': len(response_rows), 'response_coverage': coverage,
        'all_A_feasible': screen['all_A_feasible'],
        'all_physical_panels_available': all(r['status'] == 'paired_B_completed' for r in compact),
        'code_sha256': physical['code_sha256'], 'plan_sha256': physical['plan_sha256'],
        'screen_manifest_sha256': sha(screen_root / 'MANIFEST.json'), 'physical_manifest_sha256': sha(physical_root / 'MANIFEST.json'),
        'engine_sha256': physical['engine_sha256'], 'weather_sha256': physical['weather_sha256'],
        'all_failures_and_missing_opportunities_retained': True,
        'empirical_calibration_or_global_physical_sensitivity_claimed': False}
    save(out / 'SCREEN.json', screen)
    save(out / 'PHYSICAL.json', {'records': compact, 'source_result_sha256': sha(physical_root / 'PHYSICAL.json')})
    save(out / 'CHECKS.json', result)
    if not result['integrity_passed']:
        raise ValueError('SENSITIVITY_INTEGRITY_OR_RESPONSE_GATE_FAILED;retain_all_cases')
    return {k: v for k, v in result.items() if k != 'response_coverage'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--screen-root', required=True)
    parser.add_argument('--physical-root', required=True)
    parser.add_argument('--out', required=True)
    a = parser.parse_args()
    print(analyze(a.screen_root, a.physical_root, a.out))
