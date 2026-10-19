"""Check static plan receipts. Never launch an engine or require B outcomes."""
import argparse
import hashlib
from pathlib import Path

from benchmark.ab_generation.common import digest, read, save, sha, verify
from benchmark.ab_generation.generate import DEFAULT_RULES, program_domain_coverage
from benchmark.ab_generation.sampling import validate_plan


def recompute(out):
    folder = Path(__file__).parent
    verify(folder / 'frozen_inputs')
    package = folder.parents[1]
    plan_path = package / 'examples/gap_supplement/tail_plan.json'
    plan = read(plan_path)
    validate_plan(plan)
    grid = all(program_domain_coverage({**DEFAULT_RULES, **v['overrides']})['complete_within_radius']
               for v in plan['variants'])
    static = read(folder / 'STATIC_GENERATION.json')
    equivalence = read(folder / 'GENERATION_EQUIVALENCE.json')
    equivalent = equivalence['passed'] and len(equivalence['records']) == len(static['records']) == 2 and all(
        e['complete_result_bytes_identical'] and any(
            r['reference_id'] == e['case_id'] and r['generated_result_sha256'] == e['result_sha256']
            and (r['singles'], r['joints']) == (e['singles'], e['joints']) for r in static['records'])
        for e in equivalence['records'])
    total = sum(r['singles'] + r['joints'] for r in static['records'])
    joint = all(r['joint_search_coverage']['coverage_passed']
                and r['joint_search_coverage']['pair_dose_complete']
                and r['joint_search_coverage']['pair_dose_covered'] == r['joint_search_coverage']['pair_dose_required']
                and r['program_shift_domain']['complete_within_radius'] for r in static['records'])
    invalid_retained = all(r['all_generated_invalid_requests_retained']
        and r['static_valid_singles'] + r['static_invalid_singles'] == r['singles']
        and r['static_valid_joints'] + r['static_invalid_joints'] == r['joints']
        and r['all_actual_outcomes_unobserved'] for r in static['records'])
    status = read(folder / 'A_STATUS.json')
    source, identity = read(folder / 'A_BUILD_SOURCE.json'), read(folder / 'A_BUILD_IDENTITY.json')
    file_hashes = {k: hashlib.sha256(v.encode()).hexdigest() for k, v in source['files'].items()}
    source_matches = digest(file_hashes) == source['code_sha256'] == identity['code_sha256']
    runtime_matches = digest(source['runtime_files']) == source['runtime_sha256'] == identity['runtime_sha256']
    runtime_matches &= all(source['runtime_files']['benchmark/ab_generation/' + k] == v for k, v in file_hashes.items())
    repository = folder.parents[3]
    runtime_matches &= all(sha(repository / k) == v for k, v in source['runtime_files'].items()
                           if k.startswith('benchmark/housing_simulation/') or k.endswith('/LAUNDRY_MODEL.json'))
    old = read(folder / 'DIAGNOSIS.json')
    old_folder = folder.parent / 'joint_tail'
    unchanged = (sha(old_folder / 'RESULT.json') == old['old_result_sha256']
                 and sha(old_folder / 'frozen_sample/SELECTION.json') == old['old_selection_sha256'])
    multi = next(r for r in old['records'] if r['reference_id'] == 'family_multibatch')
    witnesses = (multi['coarse']['valid_positive_cost_count'] == multi['coarse']['valid_two_job_count'] == 0
                 and multi['fine']['valid_positive_cost_count'] == 1 and multi['fine']['valid_two_job_count'] == 6
                 and multi['fine']['two_job_product_count'] == 2304
                 and multi['fine']['full_context_witness_recheck'])
    winter = status['unadmitted_diagnostics']
    winter_candidates = [r for case in read(folder / 'WINTER_PLAN_CANDIDATES.json')['records']
                         for r in case['candidates']]
    winter_static = (len(winter) == 1 and winter[0]['heating_static_valid'] == winter[0]['heating_candidates'] == 10
                     and len(winter_candidates) == 10 and all(not r['static_issues'] for r in winter_candidates)
                     and all(sum(r['factors']['direction'] == direction and r['opportunity']['status'] == 'supported'
                                 for r in winter_candidates) == 4 for direction in ('aligned', 'opposing')))
    checks = {'full_10min_shift_grid': grid, 'declared_joint_interaction_coverage': joint,
        'invalid_candidates_retained': invalid_retained, 'implementation_equivalence_receipts': bool(equivalent),
        'candidate_count_consistent': total == static['total_candidates'] == equivalence['total_candidates_compared'] == 11565,
        'fixed_plan_binding': sha(plan_path) == static['tail_plan_sha256'],
        'A_source_snapshot_verified': source_matches, 'A_runtime_snapshot_verified': runtime_matches,
        'original_batch_unchanged': unchanged, 'grid_gap_witnesses_present': witnesses,
        'projection_cross_check': read(folder / 'PROJECTION_CHECK.json')['passed'],
        'winter_static_candidates_present': winter_static, 'all_planned_scenarios_accounted': status['all_planned_accounted']}
    result = {'schema': 'eb.ab_gap_static_check.v1', 'passed': all(checks.values()), 'checks': checks,
        'physics_required_for_plan_acceptance': False, 'new_physics_runs': 0, 'new_B_executed': False,
        'formal_selection_completed': False, 'actual_response_coverage': 'deferred_unverified',
        'deduplicated_stratified_sample_coverage': 'not_completed',
        'winter_physical_failure_retained': not status['all_planned_A_admitted'],
        'scope': 'static plan regression plus bound receipt consistency;not proof of all scenarios, formal sample acceptance or physical performance'}
    save(Path(out) / 'CHECKS.json', result)
    if not result['passed']:
        raise ValueError('GAP_STATIC_CHECK_FAILED;inspect_checks;do_not_reselect')
    return result


if __name__ == '__main__':
    p = argparse.ArgumentParser(__doc__)
    p.add_argument('--out', type=Path, required=True)
    print(recompute(p.parse_args().out))
