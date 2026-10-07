"""Recompute coverage and discriminating semantic tests from sealed inputs."""
import collections
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
from census_projection import compare, project

OUT = Path(__file__).resolve().parent.parent
BASE = OUT.parent


def read(path):
    return json.loads(path.read_text())


def save(name, value):
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')


def room(name, kind, users):
    return {'room_id': name, 'census_room_class': kind, 'using_household_ids': users,
            'classification_evidence': 'engineering_scenario'}


def semantic_tests():
    world = {'area_basis': 'census_building_area_components', 'area_evidence': 'engineering_scenario',
             'whole_unit_building_area_m2': 100, 'common_building_area_m2': 30,
             'households': [{'household_id': 'A', 'exclusive_building_area_m2': 40},
                            {'household_id': 'B', 'exclusive_building_area_m2': 30}],
             'rooms': [room('A1', 'bedroom', ['A']), room('A2', 'study', ['A']),
                       room('B1', 'bedroom', ['B']), room('shared_study', 'study', ['A', 'B']),
                       room('K', 'kitchen', ['A', 'B']), room('T', 'toilet', ['A', 'B']),
                       room('H', 'hall', ['A', 'B'])]}
    result = project(world)
    assert [h['H6_census_integer_m2'] for h in result['households']] == [55, 45]
    assert [h['H7_independent_natural_rooms'] for h in result['households']] == [2, 1]
    assert all(h['facilities']['kitchen'] == 'shared' for h in result['households'])
    assert compare({'H7_bin': '2', 'H7_exact': 2, 'H6_census_integer_m2': 55,
                    'facilities': {'kitchen': 'shared'}}, result, 'A')['same_scope_compatible']
    assert not compare({'H7_bin': '2', 'H7_exact': 2, 'H6_census_integer_m2': 100}, result, 'A')['same_scope_compatible']
    assert not compare({'H7_bin': '3', 'H7_exact': 3, 'H6_census_integer_m2': 55}, result, 'A')['same_scope_compatible']
    assert not compare({'H7_bin': '2', 'H7_exact': 2, 'facilities': {'kitchen': 'private'}}, result, 'A')['same_scope_compatible']
    unknown = compare({'H7_bin': '2', 'H7_exact': 2}, result, 'A')
    assert unknown['unknown_source_H6_preserved'] and not unknown['physical_binding_approved']
    shared_only = copy.deepcopy(world)
    for r in shared_only['rooms']:
        r['using_household_ids'] = ['A', 'B']
    zero = project(shared_only)
    assert all(h['H7_independent_natural_rooms'] == 0 for h in zero['households'])
    # Whether this design belongs in a particular census table/frame is separate
    # from its response operator. Never fabricate an exclusive room to force>=1.
    bad_cases = []
    for label, mutation in [
        ('thermal_area_relabelled_H6', lambda w: w.update(area_basis='thermal_floor_area_sum')),
        ('no_area_evidence_identity', lambda w: w.update(area_evidence='')),
        ('ambiguous_living_room_H7', lambda w: w['rooms'][0].update(census_room_class='living_unspecified')),
        ('duplicate_household', lambda w: w['households'][1].update(household_id='A')),
        ('duplicate_natural_room', lambda w: w['rooms'].append(copy.deepcopy(w['rooms'][0]))),
        ('nonconserving_shared_area', lambda w: w.update(common_building_area_m2=0)),
        ('unknown_room_user', lambda w: w['rooms'][0].update(using_household_ids=['C'])),
        ('boolean_area', lambda w: w.update(whole_unit_building_area_m2=True)),
        ('nonfinite_area', lambda w: w.update(whole_unit_building_area_m2='NaN'))]:
        candidate = copy.deepcopy(world); mutation(candidate)
        try:
            project(candidate)
        except ValueError as exc:
            bad_cases.append({'case': label, 'rejected': True, 'reason': str(exc)})
        else:
            raise AssertionError('invalid_world_accepted:' + label)
    rounding = copy.deepcopy(world)
    rounding.update(whole_unit_building_area_m2=101, common_building_area_m2=31)
    rr = project(rounding)
    assert [h['H6_census_integer_m2'] for h in rr['households']] == [56, 46]
    assert sum(h['H6_census_integer_m2'] for h in rr['households']) != 101
    tail = copy.deepcopy(world)
    tail['rooms'] += [room('A3', 'study', ['A']), room('A4', 'study', ['A']), room('A5', 'study', ['A'])]
    tp = project(tail)
    assert compare({'H7_bin': '5+', 'H7_exact': None}, tp, 'A')['same_scope_compatible']
    assert compare({'H7_bin': '5+', 'H7_exact': None}, tp, 'A')['topcoded_H7_exact_is_design']
    return {'shared_natural_room_not_forced_into_exclusive_H7': result,
            'shared_only_response_zero_preserved_without_population_frame_claim': zero,
            'rounding_can_change_unit_sum': rr, 'invalid_cases': bad_cases,
            'topcode_compatibility_preserves_design_identity': True,
            'checks_passed': True, 'scope': 'arithmetic_and_measurement_semantics_only'}


def old_gate_witness(profiles, units):
    spec = importlib.util.spec_from_file_location('old_scope', BASE / 'production_route_v5_20261004/code/housing_scope.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    profile = copy.deepcopy(next(p for p in profiles if p['housing']['H6_building_area_m2'] is not None
                                and p['housing']['H7_natural_rooms_exact'] is not None
                                and p['housing']['occupancy_scope'] == 'whole_household_private'
                                and p['housing']['facilities'].get('kitchen_present_any') is True
                                and p['housing']['facilities'].get('toilet_present_any') is True))
    # Deliberately adversarial synthetic input, NOT a source-unit approval.
    unit = copy.deepcopy(units[0]); unit['door_access_verified'] = True
    scenario = {field: 'placeholder' for field in ['city', 'building_form', 'code_era',
                'unit_position_and_exposure', 'area_scope_bridge', 'H7_living_hall_mapping',
                'neighbor_boundary', 'meter_boundary']}
    scenario['H7_living_hall_mapping'] = 'INVALID_NO_SUCH_MAPPING'
    scenario['area_scope_bridge'] = False
    scenario['meter_boundary'] = {}
    outcome = module.binding_gate(profile, unit, scenario)
    assert outcome['household_physical_binding_approved']
    return {'old_gate_accepted_adversarial_placeholder': True,
            'invalid_inputs': scenario, 'old_gate_result': outcome,
            'source_unit_approved': False, 'real_world_approved': False,
            'resolution': 'presence_gate_withdrawn_as_approval_authority; new_semantic_projection_is_not_a_full_physical_gate'}


def main():
    paths = [BASE / 'production_route_v5_20261004/housing1000/HOUSEHOLDS1000.json',
             BASE / 'production_route_v5_20261004/area_component_holdout/RESULT.json']
    native_paths = sorted((BASE / 'idf_unit_evidence_20261004').glob('*_NATIVE.json'))
    profiles = read(paths[0])['profiles']
    sources = [read(p) for p in native_paths]
    units = [u for s in sources for u in s['units']]
    supported = sorted({v for u in units for v in u['H7_mapping_scenarios'].values()})
    rows = []
    for p in profiles:
        h = p['housing']; ordinary = h['H5_is_ordinary_model_assigned']
        n = h['H7_natural_rooms_exact']
        direct_whole_match = ordinary and h['occupancy_scope'] == 'whole_household_private'
        rows.append({'slot_id': p['slot_id'], 'province': p['province'], 'ordinary': ordinary,
                     'occupancy_scope': h['occupancy_scope'], 'H7_bin': h['H7_census_bin'],
                     'known_same_scope_H6': h['H6_building_area_m2'] is not None,
                     'native_whole_unit_H7_candidate_possible': direct_whole_match and n in supported,
                     'native_whole_unit_H7_definite_outside_support': direct_whole_match and (
                         n is not None and n not in supported or h['H7_census_bin'] == '5+' and max(supported) < 5),
                     'complete_kinship_graph': p['family']['actor_fact_completeness']['detailed_kinship_graph'] != 'pending_ego_relation_generation_with_age_consistency',
                     'binding_approved': False})
    cv = read(paths[1])
    cv_comparison = []
    for s in cv['strata']:
        m = s['weighted_metrics']
        cv_comparison.append({'stratum': s['stratum'], 'n': s['scored_test_households'],
                              'baseline_CRPS': m['baseline_CRPS'], 'V5_CRPS': m['V5_CRPS'],
                              'delta_V5_minus_baseline': m['V5_CRPS'] - m['baseline_CRPS'],
                              'significance_test': 'not_available_design_metadata_missing',
                              'data_used_in_method_development_not_final_blind_test': True})
    summary = {'profiles': len(profiles), 'residents': sum(p['exact_member_count'] for p in profiles),
               'ordinary': sum(r['ordinary'] for r in rows),
               'nonordinary': sum(not r['ordinary'] for r in rows),
               'ordinary_unknown_H6': sum(r['ordinary'] and not r['known_same_scope_H6'] for r in rows),
               'kinship_graphs_complete': sum(r['complete_kinship_graph'] for r in rows),
               'H7_bins': dict(collections.Counter(str(r['H7_bin']) for r in rows)),
               'native_candidate_units': len(units), 'native_H7_union': supported,
               'native_units_with_verified_doors': sum(u['door_access_verified'] for u in units),
               'native_units_with_observed_census_gross_area': sum(u['whole_dwelling_gross_area_m2'] is not None for u in units),
               'whole_private_roles_definitely_outside_native_H7_support': sum(r['native_whole_unit_H7_definite_outside_support'] for r in rows),
               'whole_private_roles_with_H7_only_candidate': sum(r['native_whole_unit_H7_candidate_possible'] for r in rows),
               'ordinary_H7_1_or_5plus_including_shared_not_whole_unit_match_claim': sum(r['ordinary'] and r['H7_bin'] in {'1','5+'} for r in rows),
               'actual_1000_physical_bindings_approved': 0,
               'coverage_scope': 'current_four_native_sources_not_entire_DeST_catalog_or_all_possible_housing',
               'area_range_compared_directly_to_H6': False,
               'area_holdout_comparison': cv_comparison,
               'review_decision': 'major_revision; benchmark_not_yet_admitted',
               'future_work_scope': 'household_generation_and_IDF_only'}
    save('COHORT_AUDIT1000.json', {'summary': summary, 'slots': rows})
    save('SEMANTIC_WITNESSES.json', semantic_tests())
    save('MATCHER_ADVERSARIAL_WITNESS.json', old_gate_witness(profiles, units))
    lock = [{'path': str(p), 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()} for p in paths + native_paths]
    save('INPUT_LOCK.json', lock)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
