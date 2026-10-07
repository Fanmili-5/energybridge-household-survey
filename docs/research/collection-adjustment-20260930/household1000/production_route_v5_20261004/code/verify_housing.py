#!/usr/bin/env python3
"""Independent scope/margin/lineage checks plus discriminating negative controls."""
import collections
import copy
import hashlib
import json
from pathlib import Path

from housing_scope import shared_allocation, binding_gate

HERE = Path(__file__).resolve().parent
ROUTE = HERE.parent
H = ROUTE.parent


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')


def main():
    checks = 0
    def check(value, name):
        nonlocal checks
        if not value:
            raise AssertionError(name)
        checks += 1
    newpath = ROUTE / 'housing1000/HOUSEHOLDS1000.json'
    new = json.loads(newpath.read_text())
    old = json.loads((H / 'production_route_v4_20261003/facilities1000_v2/FAMILY_HOUSING_FACILITIES1000.json').read_text())
    ps, olds = new['profiles'], {p['slot_id']: p for p in old['profiles']}
    check(len(ps) == 1000 and len({p['slot_id'] for p in ps}) == 1000, 'unique_fixed_1000_slots')
    for p in ps:
        o = olds[p['slot_id']]
        check(p['family'] == o['family'], 'family_not_resampled_for_housing')
        check(all(p[k] == o[k] for k in ['province', 'size_category', 'generation_category']), 'fixed_population_margins')
        h = p['housing']
        check(h['H5_is_ordinary_model_assigned'] == o['housing']['H5_is_ordinary_model_assigned'], 'fixed_H5')
        check('sleep_groups' not in h, 'H7_not_promoted_to_bedroom_assignment')
        check('whole_to_exclusive_design_ratio' not in h['sharing_model'], 'arbitrary_shared_ratio_withdrawn')
        if h['current_tenure_model'] == 'rented':
            ref = h['area_reference']
            check(ref['source_tenure_codes'] == [2], 'all_rental_area_reference_excludes_owners')
            check(ref['source_H7_condition'] is None and not ref['area_room_dependency_identified'], 'rental_H7_joint_not_fabricated')
            check(h['occupied_usable_area_m2_proxy'] is not None, 'rental_native_occupied_area_reference_available')
        if h['occupancy_scope'] != 'whole_household_private':
            check(h['H6_building_area_m2'] is None and h['H6_predictive_support_bins'] is None, 'unknown_H6_allocation_not_whole_unit_imputation')
        else:
            check(h['whole_dwelling_building_area_m2'] == h['H6_building_area_m2'], 'private_model_household_boundary')
            check(any(b['lower_m2'] - .00501 <= h['H6_building_area_m2'] <= b['upper_m2'] + .00501
                      for b in h['H6_predictive_support_bins']), 'private_same_tenure_scope_support')
        if h['H7_census_bin'] == '5+':
            check(h['H7_natural_rooms_exact'] is None and h['H7_natural_rooms_minimum'] == 5, 'topcoded_room_tail_not_owner_draw')
        check(not p['complete_actor_card'] and p['human_answers'] is None, 'actor_not_ready_no_answers')
    def h7margins(items):
        return collections.Counter((p['province'], p['generation_category'], p['housing']['H7_census_bin'])
                                   for p in items if p['housing']['H5_is_ordinary_model_assigned'])
    def facilitymargins(items):
        return collections.Counter((p['province'], p['housing']['facilities']['housing_source'],
                                    p['housing']['facilities']['kitchen_toilet_state'])
                                   for p in items if p['housing']['H5_is_ordinary_model_assigned'])
    check(h7margins(ps) == h7margins(old['profiles']), 'census_province_G_H7_integer_margins')
    check(facilitymargins(ps) == facilitymargins(old['profiles']), 'province_source_facility_integer_joint_margins')
    lock = json.loads((ROUTE / 'housing1000/INPUT_LOCK.json').read_text())
    for item in lock['files']:
        check(sha(Path(item['path'])) == item['sha256'], 'input_hash_' + item['path'])
    check(sha(newpath) == lock['candidate_sha256'], 'candidate_bytes_locked')
    protected = {}
    for directory in ['production_route_v4_20261003', 'construction_chain_20261003']:
        folder = H / directory
        manifest = json.loads((folder / 'PACKAGE_MANIFEST.json').read_text())['files']
        for rel, digest in manifest.items():
            check(sha(folder / rel) == digest, 'sealed_artifact_unchanged_' + rel)
        protected[directory] = len(manifest)
    witnesses = []
    for name, exclusive, common, rooms, expected in [
        ('two_households', [45, 45], 10, [['a', 'b'], ['c']], [50, 50]),
        ('three_unequal_households', [20, 30, 35], 15, [['a'], ['b', 'c'], ['d']], [25, 35, 40]),
        ('census_rounding_is_per_household', [10.5, 10.5], 0, [['a'], ['b']], [10.5, 10.5])]:
        households = [{'household_id': str(i), 'exclusive_gross_m2': a, 'exclusive_natural_room_ids': r}
                      for i, (a, r) in enumerate(zip(exclusive, rooms))]
        total = sum(exclusive) + common
        result = shared_allocation(total, common, households, [r for rs in rooms for r in rs])
        check([h['household_H6_unrounded_m2'] for h in result['households']] == expected, 'independent_official_formula_witness')
        check(abs(result['unrounded_H6_conservation_residual_m2']) < 1e-6, 'unrounded_area_conservation')
        witnesses.append({'name': name, 'result': result})
    controls = []
    fixture = [{'household_id': 'a', 'exclusive_gross_m2': 45, 'exclusive_natural_room_ids': ['a']},
               {'household_id': 'b', 'exclusive_gross_m2': 45, 'exclusive_natural_room_ids': ['b']}]
    for name, unit, common, rows in [
        ('whole_area_assigned_to_each_household', 100, 10, [{**h, 'exclusive_gross_m2': 100} for h in fixture]),
        ('one_room_used_as_independent_by_two_households', 100, 10, [{**h, 'exclusive_natural_room_ids': ['a']} for h in fixture]),
        ('missing_common_area', 100, None, fixture),
        ('incorrect_sharing_count', 100, 10, fixture[:1])]:
        try:
            shared_allocation(unit, common, rows, ['a', 'b'])
            detected = False
        except ValueError:
            detected = True
        check(detected, name)
        controls.append({'name': name, 'detected': detected})
    coupling = json.loads((ROUTE / 'housing1000/RENTAL_AREA_ROOM_COUPLING_WITNESSES.json').read_text())
    byid = {p['slot_id']: p for p in ps}
    for scenario in ['same_rank', 'opposite_rank']:
        rows = [r for r in coupling['assignments'] if r['coupling'] == scenario]
        actual, target = collections.defaultdict(list), collections.defaultdict(list)
        for r in rows:
            p = byid[r['slot_id']]
            key = (p['province'], p['generation_category'])
            actual[key].append(r['H6_building_area_m2'])
            target[key].append(p['housing']['H6_building_area_m2'])
            check(r['H7_bin_unchanged'] == p['housing']['H7_census_bin'], 'coupling_H7_marginal')
        check({k: sorted(v) for k, v in actual.items()} == {k: sorted(v) for k, v in target.items()}, 'coupling_area_multiset_preserved')
    layout = json.loads((H / 'idf_unit_evidence_20261004/HighS_Beijing_2018_NATIVE.json').read_text())
    unit = layout['units'][0]
    profile = copy.deepcopy(next(p for p in ps if p['housing']['occupancy_scope'] == 'whole_household_private'))
    gate = binding_gate(profile, unit)
    check(not gate['household_physical_binding_approved'] and any('door_access' in x or 'functional_access' in x for x in gate['issues']), 'native_unit_inventory_does_not_certify_binding')
    save(ROUTE / 'SCOPE_WITNESSES.json', {'witnesses': witnesses, 'negative_controls': controls, 'engineering_not_population_observations': True})
    save(ROUTE / 'BINDING_GATE_WITNESS.json', gate)
    states = collections.Counter(p['housing']['facilities']['kitchen_toilet_state'] for p in ps if p['housing']['H5_is_ordinary_model_assigned'])
    result = {'pass': True, 'assertions': checks, 'profiles': len(ps), 'members': sum(p['family']['resident_count'] for p in ps),
        'ordinary': sum(p['housing']['H5_is_ordinary_model_assigned'] for p in ps), 'nonordinary': 52,
        'rental_roles': sum(p['housing']['current_tenure_model'] == 'rented' for p in ps),
        'rental_area_references_with_owned_source_weight': 0,
        'shared_ordinary': sum(p['housing']['occupancy_scope'] == 'shared_household' for p in ps),
        'ordinary_source_other_tenure_unknown': sum(p['housing']['H5_is_ordinary_model_assigned'] and p['housing']['current_tenure_model'] is None for p in ps),
        'ordinary_H6_known_model': sum(p['housing']['H6_building_area_m2'] is not None for p in ps),
        'ordinary_H6_unknown_allocation_or_tenure': sum(p['housing']['H5_is_ordinary_model_assigned'] and p['housing']['H6_building_area_m2'] is None for p in ps),
        'facility_states': dict(states), 'sealed_files_unchanged': protected, 'candidate_sha256': sha(newpath),
        'source_semantics_arithmetic_and_lineage_verified': True, 'full_joint_population_or_service_validity_verified': False,
        'actor_ready': 0, 'IDFs_bound_to_1000': 0, 'collection_release': False, 'training_release': False}
    save(ROUTE / 'VERIFICATION.json', result)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
