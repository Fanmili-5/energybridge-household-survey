"""Recheck published receipts; green integrity does not imply coverage acceptance."""
import argparse
import hashlib
from pathlib import Path

from benchmark.ab_generation.common import digest, read, save, sha, verify
from benchmark.ab_generation.sampling import coverage_report


def recompute(out, require_coverage=False):
    folder = Path(__file__).parent
    verify(folder / 'frozen_inputs'); verify(folder / 'frozen_sample')
    expected, observations = read(folder / 'RESULT.json'), read(folder / 'OBSERVATIONS.json')
    actual = coverage_report(folder / 'frozen_sample', observations)
    fields = ('coverage', 'records', 'outcome_counts', 'response_coverage', 'selection_interaction_coverage')
    identical = {k: actual[k] == expected[k] for k in fields}
    gen = read(folder / 'frozen_sample/GENERATION_COVERAGE.json')
    grid = all(r['program_shift_domain']['complete_within_radius'] for r in gen)
    joint = all(r['coverage']['coverage_passed'] for r in gen)
    status = read(folder / 'A_STATUS.json')
    source, identity = read(folder / 'A_BUILD_SOURCE.json'), read(folder / 'A_BUILD_IDENTITY.json')
    file_hashes = {k: hashlib.sha256(v.encode()).hexdigest() for k, v in source['files'].items()}
    A_source_matches = digest(file_hashes) == source['code_sha256'] == identity['code_sha256']
    runtime_matches = digest(source['runtime_files']) == source['runtime_sha256'] == identity['runtime_sha256']
    runtime_matches &= all(source['runtime_files']['benchmark/ab_generation/' + k] == v for k, v in file_hashes.items())
    repository = folder.parents[3]
    runtime_matches &= all(sha(repository / k) == v for k, v in source['runtime_files'].items()
                           if k.startswith('benchmark/housing_simulation/') or k.endswith('/LAUNDRY_MODEL.json'))
    old = read(folder / 'DIAGNOSIS.json')
    old_folder = folder.parent / 'joint_tail'
    old_unchanged = (sha(old_folder / 'RESULT.json') == old['old_result_sha256']
                     and sha(old_folder / 'frozen_sample/SELECTION.json') == old['old_selection_sha256'])
    selection = read(folder / 'frozen_sample/SELECTION.json')
    freeze = read(folder / 'PRE_B_FREEZE.json')
    selection_unchanged = sha(folder / 'frozen_sample/SELECTION.json') == freeze['selection_sha256']
    accounted = len(actual['records']) == len(selection['records']) and all(r['coverage_credit'] for r in actual['records'])
    integrity = all(identical.values()) and grid and joint and A_source_matches and runtime_matches and old_unchanged and accounted and selection_unchanged and status['all_planned_accounted']
    required_B = actual['passed'] and grid and joint
    result = {'schema': 'eb.ab_gap_supplement.self_check.v1', 'passed': bool(integrity),
        'required_B_coverage_passed': required_B, 'all_planned_A_admitted': status['all_planned_A_admitted'],
        'supplement_accepted': required_B and status['all_planned_A_admitted'], 'complete_benchmark_ready': False,
        'recomputed_fields_identical': identical, 'program_grid_complete': grid, 'joint_generation_complete': joint,
        'A_source_snapshot_byte_verified': A_source_matches, 'A_runtime_snapshot_verified': runtime_matches,
        'original_receipts_unchanged': old_unchanged, 'frozen_selection_unchanged': selection_unchanged,
        'all_selected_accounted': accounted, 'selected': len(selection['records']),
        'observations': len(observations), 'deficits': [r['stratum'] for r in actual['coverage'] if not r['passed']],
        'strict_coverage_gate_requested': require_coverage,
        'new_B_selection': False, 'new_physics_runs': 0,
        'scope': 'bound public report and source recomputation;not independent native SQL execution or human validity'}
    save(Path(out) / 'CHECKS.json', result)
    if not integrity or require_coverage and not result['supplement_accepted']:
        raise ValueError('GAP_SUPPLEMENT_CHECK_FAILED;inspect_admission_and_deficits;do_not_reselect')
    return result


if __name__ == '__main__':
    p = argparse.ArgumentParser(__doc__); p.add_argument('--out', type=Path, required=True)
    p.add_argument('--require-coverage', action='store_true'); a = p.parse_args()
    print(recompute(a.out, a.require_coverage))
