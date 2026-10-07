#!/usr/bin/env python3
"""Independent readback; does not import the generator or read source microdata."""
import argparse
import collections
import hashlib
import json
import math
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent


def load(path):
    def invalid(s):
        raise ValueError('nonfinite_JSON_literal')
    return json.loads(Path(path).read_text(), parse_constant=invalid)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def verify(batch):
    batch = Path(batch).resolve()
    body = load(batch / 'FAMILY_HOUSING_CANDIDATES.json')
    ps = body['profiles']
    targets = load(batch / 'CALIBRATION_TARGETS.json')
    lock = load(batch / 'GENERATOR_LOCK.json')
    allocation = load(ROOT / 'evidence_contract_20261001/POPULATION_ALLOCATION_CANDIDATE_V2.json')
    census = load(ROOT / 'evidence_contract_20261001/CITY_AUTHORITY_CONSTRAINTS_V2.json')
    byslot = {s['slot_id']: s for s in allocation['slots']}
    checks = []

    def check(name, ok, detail=None):
        checks.append({'check': name, 'pass': bool(ok), 'detail': detail})

    check('1000_unique_slots_and_family_ids', len(ps) == len({p['slot_id'] for p in ps}) == len({p['family']['family_id'] for p in ps}) == 1000)
    check('exact_target_slot_set', set(p['slot_id'] for p in ps) == set(byslot))
    faults = collections.Counter()
    member_ids = []
    h5actual = collections.Counter()
    h7actual = collections.defaultdict(collections.Counter)
    vintageactual = collections.defaultdict(collections.Counter)
    storeysactual = collections.defaultdict(collections.Counter)
    profile_payloads = collections.Counter()
    payload_without_ages = collections.Counter()
    for p in ps:
        t = byslot[p['slot_id']]
        f, h = p['family'], p['housing']
        if any(p[k] != t[k] for k in ['province', 'size_category', 'generation_category']):
            faults['changed_population_target'] += 1
        ms = f['members']; ids = [m['member_id'] for m in ms]
        member_ids += ids
        n = len(ms)
        if n != f['resident_count'] or n != p['exact_member_count'] or ids != f['resident_member_ids'] or len(set(ids)) != n:
            faults['roster_count_or_id_conflict'] += 1
        if t['size_category'] == '10+':
            if n < 10:
                faults['topcode_size_conflict'] += 1
        elif n != t['exact_member_count']:
            faults['exact_size_changed'] += 1
        levels = sorted(set(m['generation_level'] for m in ms))
        g = len(levels)
        if levels != f['generation_levels'] or g != f['generation_count_design'] or (g < 5 if p['generation_category'] == '5+' else g != int(p['generation_category'])):
            faults['occupied_generation_conflict'] += 1
        ages = {m['member_id']: m['age_years'] for m in ms}
        level = {m['member_id']: m['generation_level'] for m in ms}
        if any(type(a) is not int or a < 0 for a in ages.values()) or (n == 1 and min(ages.values()) < 20):
            faults['age_invalid_or_singleton_under20'] += 1
        for m in ms:
            if not m['age_reference_bin_years'][0] <= m['age_years'] <= m['age_reference_bin_years'][1]:
                faults['age_outside_declared_coarse_bin'] += 1
        for r in f['relation_design']:
            if r['kind'] not in ['shared_generation_design','cross_generation_co_residence_design']:
                faults['kinship_inferred_from_generation'] += 1
                continue
            aa, bb = r['member_ids']
            if aa not in level or bb not in level:
                faults['relationship_member_missing'] += 1
            elif r['kind']=='shared_generation_design' and level[aa]!=level[bb]:
                faults['shared_generation_membership_conflict'] += 1
            elif r['kind']=='cross_generation_co_residence_design' and abs(level[aa]-level[bb])!=r['generation_difference']:
                faults['cross_generation_membership_conflict'] += 1
        if f['age_kinship_policy']['same_generation_age_gap_limit'] is not None or f['age_kinship_policy']['mandatory_parent_age_gap'] is not None or f['age_kinship_policy']['mandatory_spouse_opposite_sex']:
            faults['unsupported_age_kinship_rule_reintroduced'] += 1
        if p['profile_version']!=body['generation_model']['version'] or f['profile_version']!=p['profile_version'] or p['generation_model_sha256']!=lock['code_sha256'] or not p['field_provenance']:
            faults['profile_version_or_provenance_missing'] += 1
        if h['dwelling_type'] is not None or h['household_storeys'] is not None or h['engineering_geometry_options_are_population_frequencies']:
            faults['dwelling_form_inferred_from_building_storeys'] += 1
        ref=f['member_generation_reference']
        blend=ref['reference_mixture'];components=blend['components'];tau=blend['design_tau']
        le,ne=components[0]['kish_ESS'],components[1]['kish_ESS']
        ll=le/(le+tau) if le else 0;nl=ne/(ne+tau) if ne else 0
        desired=[ll,(1-ll)*nl,(1-ll)*(1-nl)]
        if any(abs(x['mass']-y)>1e-12 for x,y in zip(components,desired)) or abs(sum(x['mass'] for x in components)-1)>1e-12:
            faults['ESS_continuous_mixture_policy_conflict'] += 1
        ordinary = h['H5_is_ordinary_model_assigned']
        key = (p['province'], p['generation_category'])
        h5actual[key] += ordinary
        rr = h['H7_natural_rooms_exact'] if ordinary else h['design_natural_rooms_exact']
        area = h['H6_building_area_m2'] if ordinary else h['design_floor_area_m2']
        if type(rr) is not int or rr < 1 or not isinstance(area, (int, float)) or not math.isfinite(area) or area <= 0:
            faults['housing_design_value_invalid'] += 1
        groups = h['sleep_groups']; flat = [x for z in groups for x in z]
        if len(groups) != rr or sorted(flat) != sorted(ids) or len(flat) != len(set(flat)):
            faults['sleep_assignment_conflict'] += 1
        if ordinary:
            rb = str(rr) if rr < 5 else '5+'
            if rb != h['H7_census_bin'] or h['H7_definition'] != 'natural_rooms_excluding_kitchen_toilet_corridor_hall' or not h['census_H6_H7_applicable']:
                faults['H7_bin_or_semantic_conflict'] += 1
            h7actual[key][rb] += 1
            vintageactual[p['province']][h['vintage_category_index']] += 1
            storeysactual[p['province']][h['building_storeys_category_index']] += 1
            if h['building_year_design'] > 2020 or h['building_total_storeys_design'] < 1:
                faults['building_time_storey_conflict'] += 1
        elif h['H6_building_area_m2'] is not None or h['H7_natural_rooms_exact'] is not None or h['census_H6_H7_applicable'] or h['H7_census_bin'] is not None:
            faults['nonordinary_census_fields_fabricated'] += 1
        if h['geometry_or_template_feasibility_used_to_choose_household'] or f['complete_original_source_family_copied']:
            faults['forbidden_claim_or_selection'] += 1
        if p['site']['city'] is not None or p['model_policy']['prototype_key'] is not None:
            faults['city_or_prototype_invented_by_generator'] += 1
        if p['human_answers'] is not None or p['complete_actor_card'] or p['devices']['status'] != 'pending' or p['activities']['status'] != 'pending':
            faults['unbound_role_completion_claim'] += 1
        # Identity/evidence fields are excluded from duplicate payload hashes.
        payload = {'members': [(m['age_years'], m['sex_design'], m['generation_level']) for m in ms],
                   'ordinary': ordinary, 'rooms': rr, 'area': area, 'scope': h['occupancy_scope'], 'dwelling_type': h['dwelling_type']}
        profile_payloads[hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()] += 1
        structural = {'n': n, 'levels': [m['generation_level'] for m in ms], 'ordinary': ordinary, 'rooms': rr,
                      'area_bin20m2': math.floor(area / 20), 'scope': h['occupancy_scope']}
        payload_without_ages[hashlib.sha256(json.dumps(structural, sort_keys=True).encode()).hexdigest()] += 1
    check('globally_unique_synthetic_member_ids', len(member_ids) == len(set(member_ids)))
    check('profile_semantic_checks', not faults, dict(faults))
    h5residual = []
    ordinary_rows = {r['province']: r for r in census['complete_province_generation_room_counts']}
    original_expected_total = 0
    for t in targets['H5_province_generation']:
        key = (t['province'], t['generation_category'])
        pi = census['modeled_population_completion']['province_order'].index(t['province'])
        gi = 4 if t['generation_category'] == '5+' else int(t['generation_category']) - 1
        all_count = census['tables']['A0109a']['rows'][t['province']]['counts_or_aggregates'][1 + gi * 2]
        ord_count = ordinary_rows[t['province']]['generation_totals'][gi]
        eligible = census['modeled_population_completion']['eligible_province_generation_counts'][pi][gi]
        low = max(0, ord_count - (all_count - eligible)) / eligible if gi == 0 else ord_count / all_count
        high = min(ord_count, eligible) / eligible if gi == 0 else ord_count / all_count
        mode = body['generation_model']['h5_mode']
        probability = low if mode == 'lower_ordinary' else high if mode == 'upper_ordinary' else ord_count / all_count
        original_expected_total += t['slots'] * probability
        check('H5_authority_probability_' + '_'.join(key), abs(t['p_ordinary'] - probability) < 1e-12)
        check('H5_integer_target_' + '_'.join(key), h5actual[key] == t['ordinary_assigned'])
        h5residual.append(abs(h5actual[key] - t['ordinary_expected']))
    check('H5_local_integer_residual_less_than1', max(h5residual) < 1 + 1e-10, max(h5residual))
    check('H5_global_nearest_integer_expected_total', sum(h5actual.values()) == math.floor(original_expected_total + .5))
    for t in targets['ordinary_H7_province_generation']:
        gi = 4 if t['generation_category'] == '5+' else int(t['generation_category']) - 1
        source_counts = ordinary_rows[t['province']]['generation_room_counts'][gi]
        probability = [z / sum(source_counts) for z in source_counts]
        check('H7_authority_probability_' + t['province'] + '_' + t['generation_category'], all(abs(a - b) < 1e-12 for a, b in zip(probability, t['census_probability'])))
        actual = [h7actual[(t['province'], t['generation_category'])][rr] for rr in ['1', '2', '3', '4', '5+']]
        expected = [t['ordinary_profiles'] * v for v in t['census_probability']]
        check('H7_bins_' + t['province'] + '_' + t['generation_category'], actual == t['integer_room_bin_target'] and all(abs(x - y) < 1 + 1e-10 for x, y in zip(actual, expected)))
    area_residual = []
    expected_area_residual = []
    for t in targets['ordinary_H6_province_vintage_means']:
        if not t['profiles']: continue
        reference_mean = census['long_form_housing_summary'][t['province']]['vintage_whole_area_means_m2'][t['vintage_category_index']]
        check('H6_authority_mean_'+t['province']+'_'+str(t['vintage_category_index']),abs(reference_mean-t['reference_mean_H6_m2'])<1e-12)
        selected=[p for p in ps if p['province']==t['province'] and p['housing']['H5_is_ordinary_model_assigned'] and p['housing']['vintage_category_index']==t['vintage_category_index']]
        average=sum(p['housing']['H6_building_area_m2'] for p in selected)/len(selected)
        expected=sum(p['housing']['area_policy']['expected_area_m2'] for p in selected)/len(selected)
        area_residual.append(abs(average-reference_mean));expected_area_residual.append(abs(expected-reference_mean))
        check('H6_realized_residual_reported_'+t['province']+'_'+str(t['vintage_category_index']),len(selected)==t['profiles'] and abs(t['actual_mean_H6_m2']-average)<1e-9 and abs(t['realized_mean_residual_m2']-(average-reference_mean))<1e-9 and not t['mean_constraint_realized'])
        check('H6_expected_residual_reported_'+t['province']+'_'+str(t['vintage_category_index']),abs(t['expected_model_mean_H6_m2']-expected)<1e-9 and abs(t['expected_mean_residual_m2']-(expected-reference_mean))<1e-9)
        lo=sum(min(b['lower_m2'] for b in p['housing']['H6_predictive_support_bins']) for p in selected)/len(selected)
        hi=sum(max(b['upper_m2'] for b in p['housing']['H6_predictive_support_bins']) for p in selected)/len(selected)
        feasible=lo<reference_mean<hi
        check('H6_original_support_hull_'+t['province']+'_'+str(t['vintage_category_index']),all(abs(x-y)<1e-9 for x,y in zip([lo,hi],t['reference_support_convex_hull_mean_m2'])) and feasible==t['official_mean_strictly_inside_support_hull'] and not t['area_multiplicative_scaling_used'] and not t['new_support_added_to_fit_mean'])
        if body['generation_model']['area_mode']=='tilt' and feasible:
            check('H6_tilt_expected_mean_'+t['province']+'_'+str(t['vintage_category_index']),abs(expected-reference_mean)<1e-6)
        else:
            check('H6_reference_track_unforced_'+t['province']+'_'+str(t['vintage_category_index']),all(p['housing']['area_policy']['theta_per_m2']==0 for p in selected))
        for p in selected:
            h=p['housing'];a=h['H6_building_area_m2'];bins=h['H6_predictive_support_bins']
            if not any(b['lower_m2']-.005001<=a<=b['upper_m2']+.005001 for b in bins):faults['H6_area_outside_original_support']+=1
            if h['area_policy']['posterior_source_ESS']<1-1e-9 or not 0<h['area_policy']['posterior_maximum_source_weight']<=1+1e-9:faults['area_posterior_influence_invalid']+=1
    check('H6_profile_support_and_influence',not faults,dict(faults))
    # Verify largest-remainder envelopes against independent census data.
    for province, counts in vintageactual.items():
        source = census['long_form_housing_summary'][province]
        total = sum(counts.values())
        check('vintage_margin_' + province, all(abs(counts[i] - total * source['vintage_counts'][i] / sum(source['vintage_counts'])) < 1 + 1e-10 for i in range(9)))
        check('building_storeys_margin_' + province, all(abs(storeysactual[province][i] - total * source['building_storeys_counts'][i] / sum(source['building_storeys_counts'])) < 1 + 1e-10 for i in range(4)))
    check('candidate_bytes_equal_locked_sha', sha(batch / 'FAMILY_HOUSING_CANDIDATES.json') == lock['output_sha256'])
    check('target_allocation_bytes_equal_locked_sha', body['target_allocation_sha256'] == sha(ROOT / 'evidence_contract_20261001/POPULATION_ALLOCATION_CANDIDATE_V2.json'))
    check('no_raw_identifying_source_field_names', not any('"' + key + '"' in (batch / 'FAMILY_HOUSING_CANDIDATES.json').read_text() for key in ['hhid', 'pline', '_local_hhid', 'total_income', 'total_consump']))
    check('actor_release_false', body['complete_actor_cards'] == body['human_answers'] == 0 and not body['collection_release'] and not body['training_release'])
    return {'schema': 'eb.family_housing_independent_QC.v1', 'candidate_sha256': sha(batch / 'FAMILY_HOUSING_CANDIDATES.json'),
            'check_count': len(checks), 'pass': all(x['pass'] for x in checks),
            'failed': [x for x in checks if not x['pass']], 'checks': checks,
            'profiles': len(ps), 'members': len(member_ids), 'ordinary': sum(p['housing']['H5_is_ordinary_model_assigned'] for p in ps),
            'nonordinary': sum(not p['housing']['H5_is_ordinary_model_assigned'] for p in ps),
            'ordinary_shared': sum(p['housing']['H5_is_ordinary_model_assigned'] and p['housing']['occupancy_scope'] != 'whole_household_private' for p in ps),
            'dwelling_type_counts': dict(collections.Counter(p['housing']['dwelling_type'] for p in ps)),
            'H7_bin_counts_ordinary': dict(collections.Counter(p['housing']['H7_census_bin'] for p in ps if p['housing']['H5_is_ordinary_model_assigned'])),
            'exact_size10plus': [p['family']['resident_count'] for p in ps if p['size_category'] == '10+'],
            'exact_room5plus_counts': dict(collections.Counter(p['housing']['H7_natural_rooms_exact'] for p in ps if p['housing']['H7_census_bin'] == '5+')),
            'occupied_noncontiguous_generation_profiles': sum(p['family']['generation_levels'] != list(range(len(p['family']['generation_levels']))) for p in ps),
            'maximum_H6_realized_official_mean_residual_m2': max(area_residual), 'maximum_H6_expected_official_mean_residual_m2':max(expected_area_residual),
            'exact_duplicate_nonidentity_family_housing_payload_extra_profiles': sum(n - 1 for n in profile_payloads.values() if n > 1),
            'coarse_structure_20m2_bin_repeat_extra_profiles': sum(n - 1 for n in payload_without_ages.values() if n > 1),
            'coarse_repeat_interpretation': 'coarsened structural repetition is expected in a constrained model, not proof of donor cloning; exact original-vector comparison not attempted',
            'one_generation_multimember_under20_count':sum(m['age_years']<20 for p in ps if p['generation_category']=='1' and p['family']['resident_count']>1 for m in p['family']['members']),
            'same_generation_age_gap_above6_profiles':sum(any(max(m['age_years'] for m in p['family']['members'] if m['generation_level']==lev)-min(m['age_years'] for m in p['family']['members'] if m['generation_level']==lev)>6 for lev in p['family']['generation_levels']) for p in ps),
            'maximum_member_reference_weight_share':max(p['family']['member_generation_reference']['maximum_weight_share'] for p in ps),
            'minimum_member_reference_ESS':min(p['family']['member_generation_reference']['kish_effective_sample_size'] for p in ps),
            'maximum_area_posterior_source_weight_share':max(p['housing']['area_policy']['posterior_maximum_source_weight'] for p in ps if p['housing']['H5_is_ordinary_model_assigned']),
            'unknown_dwelling_form_profiles':sum(p['housing']['dwelling_type'] is None and p['housing']['household_storeys'] is None for p in ps),
            'strict_census_observations_claimed': False, 'complete_actor_card_claimed': False,
            'independent_verifier_sha256': sha(__file__)}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('batch')
    parser.add_argument('--report')
    args = parser.parse_args()
    result = verify(args.batch)
    report = Path(args.report) if args.report else Path(args.batch) / 'PROFILES_QC.json'
    report.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
    print(json.dumps({k: result[k] for k in ['pass', 'check_count', 'profiles', 'members', 'ordinary', 'nonordinary', 'ordinary_shared', 'dwelling_type_counts', 'exact_size10plus', 'maximum_H6_realized_official_mean_residual_m2', 'exact_duplicate_nonidentity_family_housing_payload_extra_profiles']}, ensure_ascii=False))
    if not result['pass']:
        raise SystemExit(1)
