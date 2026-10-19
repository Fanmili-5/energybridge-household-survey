"""Recompute the sealed public coverage; no new selection or engine execution."""
import argparse
from pathlib import Path
from benchmark.ab_generation.common import read, save, sha, verify
from benchmark.ab_generation.sampling import coverage_report


def recompute(out, require_coverage=False):
    folder = Path(__file__).parent
    sample = folder / 'frozen_sample'
    verify(sample)
    expected = read(folder / 'RESULT.json')
    observations = read(folder / 'OBSERVATIONS.json')
    current = coverage_report(sample, observations)
    fields = ('coverage', 'records', 'outcome_counts', 'response_coverage', 'selection_interaction_coverage')
    identical = {key: current[key] == expected[key] for key in fields}
    generation = read(sample / 'GENERATION_COVERAGE.json')
    generation_passed = all(row['coverage'].get('coverage_passed') is True for row in generation)
    selection = read(sample / 'SELECTION.json')
    result = {'schema': 'eb.ab_joint_tail.public_self_check.v1',
              'passed': all(identical.values()) and generation_passed and all(r['coverage_credit'] for r in current['records']),
              'required_coverage_passed': current['passed'] and generation_passed,
              'strict_coverage_gate_requested': require_coverage,
              'recomputed_fields_identical': identical, 'generation_coverage_passed': generation_passed,
              'all_selected_accounted': len(current['records']) == len(selection['records']),
              'selected': len(selection['records']), 'executed_observations': len(observations),
              'outcome_counts': current['outcome_counts'],
              'response_patterns': current['response_coverage']['patterns'],
              'deficits': [{k: r[k] for k in ('stratum', 'required', 'requested', 'selected', 'verified', 'verification_deficit')}
                          for r in current['coverage'] if r['verification_deficit']],
              'expected_RESULT_sha256': sha(folder / 'RESULT.json'),
              'selection_sha256': sha(sample / 'SELECTION.json'),
              'new_B_selection': False, 'new_physics_runs': 0,
              'scope': 'recompute frozen coverage and admissions from bound public reports;not independent reexecution of SQL or human validation'}
    out = Path(out); out.mkdir(parents=True, exist_ok=False)
    save(out / 'CHECKS.json', result)
    if not result['passed']:
        raise ValueError('JOINT_TAIL_PUBLIC_RECHECK_FAILED;preserved_results_not_replaced')
    if require_coverage and not result['required_coverage_passed']:
        raise ValueError('JOINT_TAIL_REQUIRED_COVERAGE_FAILED;inspect_deficits;do_not_reselect')
    return result


if __name__ == '__main__':
    p = argparse.ArgumentParser(__doc__); p.add_argument('--out', type=Path, required=True)
    p.add_argument('--require-coverage', action='store_true')
    args = p.parse_args()
    print(recompute(args.out, args.require_coverage))
