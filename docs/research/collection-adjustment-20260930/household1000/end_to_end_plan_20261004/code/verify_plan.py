#!/usr/bin/env python3
"""Verify plan closure and coverage; explicitly not production validation."""
import collections
import hashlib
import json
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    spec = json.loads((OUT / 'PIPELINE_SPEC.json').read_text())
    routes = json.loads((OUT / 'PLANNED_ROUTES1000.json').read_text())
    contract = json.loads((OUT / 'ROLE_PACKAGE_CONTRACT.json').read_text())
    sources = json.loads((OUT / 'SOURCE_REGISTER.json').read_text())
    checks = 0
    def check(value, name):
        nonlocal checks
        if not value:
            raise AssertionError(name)
        checks += 1
    sourceids = {s['id'] for s in sources['entries']}
    stages = {s['key']: s for s in spec['stages']}
    done = set()
    for s in spec['stages']:
        check(set(s['parents']) <= done, 'acyclic_stage_order_and_declared_parents')
        check(set(s['sources']) <= sourceids, 'stage_sources_registered')
        check(bool(s['method']) and bool(s['completion_gate']) and bool(s['output']), 'stage_production_rule_output_gate')
        done.add(s['key'])
    check(len(stages) == len(spec['stages']) == 14, 'stage_keys_unique')
    for gap, handler in spec['gap_completion_handlers'].items():
        check(handler['stage'] in stages and bool(handler['rule']), 'all_gap_handlers_have_method_and_stage')
    basepath = Path(routes['input_file'])
    check(sha(basepath) == routes['input_sha256'] == spec['input_diagnostic_cohort_sha256'], 'input_diagnostic_bytes_not_modified')
    base = {p['slot_id']: p for p in json.loads(basepath.read_text())['profiles']}
    check(len(routes['rows']) == len(base) == 1000, 'full1000_routes')
    check({r['slot_id'] for r in routes['rows']} == set(base), 'each_current_slot_exactly_once')
    ids = [s['id'] for s in spec['stages']]
    for r in routes['rows']:
        check(r['completion_recipe'] in spec['recipes'], 'recipe_defined')
        check(r['required_stage_ids'] == ids, 'no_skipped_terminal_actor_or_physics_stage')
        check(set(r['gaps_with_handlers']) <= spec['gap_completion_handlers'].keys(), 'no_gap_without_concrete_completion_rule')
        check(r['human_answers'] is None and r['status'] == 'planned_route_complete_not_materialized_role', 'routing_not_promoted_to_generated_or_human_data')
        p = base[r['slot_id']]
        signature = hashlib.sha256(json.dumps(p, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        check(signature == r['input_profile_sha256'], 'route_binds_original_diagnostic_profile')
    counts = dict(collections.Counter(r['completion_recipe'] for r in routes['rows']))
    check(counts == routes['route_counts'] == spec['current_diagnostic_route_counts'], 'route_counts')
    check(sum(counts.values()) == 1000 and len(counts) == 6, 'all_six_housing_paths_accounted')
    check('strict_residential_scope' in spec['recipes']['nonordinary_city_family'], 'nonordinary_not_silently_relabelled')
    check('strict_residential1000' in contract and 'all_city1000' in contract, 'both_population_contracts_explicit')
    for name, fields in contract['files_required'].items():
        check(bool(fields) and len(fields) == len(set(fields)), 'required_package_fields_nonempty_unique')
    check(not spec['release']['collection_release'] and not spec['release']['training_release'], 'plan_cannot_open_release')
    check(routes['materialized_actor_ready_roles'] == 0, 'materialized_role_count_honest')
    # Verify the newly found modern broad-group fields actually exist in the
    # supplied metadata; a questionnaire grouping is not a single-device rate.
    meta = json.loads((OUT.parent / 'chfs_admission_20261003/private_metadata/chfs2021_hh_pub_v0_20260131_metadata.json').read_text())['variable_labels']
    entry = next(s for s in sources['entries'] if s['id'] == 'chfs2021')
    for field in entry['new_fields']:
        check(field in meta, 'modern_durable_group_field_exists:' + field)
    result = {'schema': 'eb.full1000_plan_verification.v1', 'pass': True, 'assertions': checks,
              'planned_routes': 1000, 'stage_modules': 14, 'required_package_artifacts': len(contract['files_required']),
              'route_counts': counts, 'source_entries': len(sourceids), 'gaps_without_planned_handler': 0,
              'existing_candidate_modified': False, 'new_complete_roles_generated': 0,
              'meaning': 'production design graph/source references and diagnostic routing closure;not feasibility proof or materialized1000pack validation',
              'full_joint_representativeness_validated': False, 'collection_release': False, 'training_release': False}
    (OUT / 'VERIFICATION.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
