#!/usr/bin/env python3
"""Rebuild housing conditionals around census household scope, with private CHFS.

The fixed 1000 slots/rosters/H5 and census integer margins are inherited from V4.
V4 areas, sharing labels and sleeping assignments are discarded. No source row
or source identifier is exported. Unknown allocations never become H6 values.
"""
import collections
import copy
import hashlib
import importlib.util
import json
import math
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROUTE = HERE.parent
H = ROUTE.parent
sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location('v4_reference', H / 'production_route_v4_20261003/code/generate_population.py')
gp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gp)
gp.MODEL.update(shrinkage_tau=20.0, minimum_source_area_per_room_m2=1.0)
VERSION = 'HOUSING_SCOPE_TENURE_20261004_V5'
BASE = H / 'production_route_v4_20261003/facilities1000_v2/FAMILY_HOUSING_FACILITIES1000.json'
SOURCE = H / 'evidence_contract_20261001/CITY_AUTHORITY_CONSTRAINTS_V2.json'
OWNER_SOURCES = {'new_commercial_purchase', 'secondhand_purchase', 'former_public_purchase',
                 'affordable_purchase', 'self_built', 'inherited_or_gift'}
RENT_SOURCES = {'public_rental', 'other_rental'}
BIN_CACHE = {}
POOL_CACHE = {}


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')


def tenure(label):
    return 2 if label in RENT_SOURCES else (1 if label in OWNER_SOURCES else None)


def private_records():
    frame = gp.rb.load_bridge_pool()
    frame = frame[frame.eligible_for_generation_matching & frame.weight.notna() & (frame.weight > 0)]
    # C1002ab supplies sharing-household categories; the bridge did not expose it.
    extra = gp.rb.read('hh', ['hhid', 'c1002ab'])
    modes = dict(zip(extra.hhid, extra.c1002ab))
    records = frame.to_dict('records')
    for r in records:
        for key, value in list(r.items()):
            if isinstance(value, float) and not math.isfinite(value):
                r[key] = None
        r['_rental_mode'] = gp.integer(modes[r['_local_hhid']])
        r['tenure_code'] = gp.integer(r['tenure_code'])
    return records


def pool(records, profile, tag, predicate, room=None):
    key = (tag, profile['province'], profile['size_category'], profile['generation_category'], room)
    if key not in POOL_CACHE:
        admitted = [r for r in records if predicate(r)]
        if room is not None:
            admitted = [r for r in admitted if r['room_proxy_category'] == room]
        selected, route = gp.select_pool(admitted, profile['province'], profile['size_category'],
                                         profile['generation_category'], need='member')
        if selected:
            reference = gp.reference_summary(selected, route)
            reference['mixture_is_conditional_on_declared_source_subset'] = tag
        else:
            reference = {'source_records': 0, 'route': 'no_admitted_same_tenure_scope_reference'}
        POOL_CACHE[key] = (selected, reference)
    return POOL_CACHE[key]


def assign_sources(profiles, records):
    """Preserve published source/facility integer cells; add modeled tenure-N/G association."""
    by_province = collections.defaultdict(list)
    for p in profiles:
        if p['housing']['H5_is_ordinary_model_assigned']:
            by_province[p['province']].append(p)
    audit = []
    for province, ps in by_province.items():
        cells = collections.Counter((p['housing']['facilities']['housing_source'],
                                     p['housing']['facilities']['kitchen_toilet_state']) for p in ps)
        columns = sorted(cells)
        groups = collections.defaultdict(list)
        for p in ps:
            groups[(p['size_category'], p['generation_category'])].append(p)
        rows = sorted(groups)
        # National weighted tenure baseline, not the existing source label ratio.
        all_known = [r for r in records if r['tenure_code'] in [1, 2]]
        total = sum(r['weight'] for r in all_known)
        marginal = {t: sum(r['weight'] for r in all_known if r['tenure_code'] == t) / total for t in [1, 2]}
        probabilities = []
        row_refs = []
        for key in rows:
            refpool, ref = pool(records, groups[key][0], 'known_tenure', lambda r: r['tenure_code'] in [1, 2])
            mass = sum(r['weight'] for r in refpool)
            cond = {t: sum(r['weight'] for r in refpool if r['tenure_code'] == t) / mass for t in [1, 2]}
            probabilities.append([cells[cell] / len(ps) * (cond[tenure(cell[0])] / marginal[tenure(cell[0])]
                                  if tenure(cell[0]) is not None else 1.0) for cell in columns])
            row_refs.append({'N': key[0], 'G': key[1], 'conditional_tenure_reference': cond, 'reference': ref})
        joint, _ = gp.fit_transport([len(groups[key]) for key in rows], [cells[c] for c in columns], probabilities)
        for key, allocation in zip(rows, joint):
            psrow = sorted(groups[key], key=lambda p: p['slot_id'])
            gp.stage_rng(20261004, 'tenure_assignment_' + province + str(key)).shuffle(psrow)
            cursor = 0
            for (label, state), count in zip(columns, allocation):
                for p in psrow[cursor:cursor + count]:
                    f = p['housing']['facilities']
                    f.update(housing_source=label, kitchen_toilet_state=state,
                             kitchen_present_any=state in ['both_kitchen_toilet', 'kitchen_only'],
                             toilet_present_any=state in ['both_kitchen_toilet', 'toilet_only'])
                cursor += count
        audit.append({'province': province, 'rows': row_refs,
                      'source_facility_integer_cells_preserved': [{'source': c[0], 'state': c[1], 'count': cells[c]} for c in columns]})
    return audit


def assign_sharing(profiles, records, seed):
    for p in profiles:
        h = p['housing']
        ordinary = h['H5_is_ordinary_model_assigned']
        t = tenure(h['facilities']['housing_source']) if ordinary else None
        h['current_tenure_model'] = {1: 'owned', 2: 'rented', None: None}[t]
        h['tenure_mapping_evidence'] = ('census_source_category_to_owned_or_rented; subtype_not_mapped_to_CHFS_landlord'
                                        if t else 'census_other_source_or_nonordinary_not_mapped_to_observed_tenure')
        if t is None:
            h['occupancy_scope'] = None
            h['sharing_model'] = {'status': 'unknown; no_forced_nonordinary_shared_subtype', 'sharing_household_count': None}
            continue
        refpool, ref = pool(records, p, 'sharing_tenure_' + str(t), lambda r: r['tenure_code'] == t)
        private = 'whole_current_owned_dwelling' if t == 1 else 'whole_rented_dwelling'
        shared = 'partial_occupancy_requires_allocation' if t == 1 else 'shared_area_allocation_unknown'
        masses = collections.Counter()
        for r in refpool:
            category = ('whole' if r['sharing_scope'] == private else
                        ('shared' if r['sharing_scope'] == shared else 'unknown'))
            masses[category] += r['weight']
        known = masses['whole'] + masses['shared']
        prob = masses['shared'] / known
        rr = gp.stage_rng(seed, 'sharing_' + p['slot_id'])
        is_shared = rr.random() < prob
        count, count_bin = (1, '1') if not is_shared else (None, None)
        if is_shared and t == 2:
            cm = collections.Counter()
            for r in refpool:
                if r['sharing_scope'] == shared and r['_rental_mode'] in [2, 3, 4]:
                    cm[r['_rental_mode']] += r['weight']
            draw = gp.weighted_choice(rr, list(cm), list(cm.values()))
            count = draw if draw < 4 else None
            count_bin = str(draw) if draw < 4 else '4+'
        h['occupancy_scope'] = 'shared_household' if is_shared else 'whole_household_private'
        h['sharing_model'] = {'status': 'new_modeled_draw_from_tenure_N_G_conditional_source_reference',
            'weighted_known_reference_shared_probability': prob,
            'unknown_scope_weight_fraction': masses['unknown'] / sum(masses.values()),
            'unknown_scope_probability_bounds': [masses['shared'] / sum(masses.values()),
                                               (masses['shared'] + masses['unknown']) / sum(masses.values())],
            'missing_scope_design': 'known_scope_conditional_distribution; bounds_are_identification_not_CI',
            'sharing_household_count': count, 'sharing_household_count_bin': count_bin,
            'sharing_count_evidence': 'CHFS_C1002ab_category_new_draw' if t == 2 and is_shared else
                                      ('unknown_owner_partial_occupancy' if is_shared else 'whole_household_boundary'),
            'source_reference': ref, 'population_frequency_validated': False}


def assign_rooms(profiles, records):
    """Keep census province/G H7 counts; rental/shared association is unidentified."""
    groups = collections.defaultdict(list)
    for p in profiles:
        if p['housing']['H5_is_ordinary_model_assigned']:
            groups[(p['province'], p['generation_category'])].append(p)
    audit = []
    for key, ps in groups.items():
        census_counts = collections.Counter(p['housing']['H7_census_bin'] for p in ps)
        cols = [str(x) for x in range(1, 5)] + ['5+']
        total = len(ps)
        prior = [census_counts[c] / total for c in cols]
        rows = collections.defaultdict(list)
        for p in ps:
            h = p['housing']
            rows[(p['size_category'], h['current_tenure_model'], h['occupancy_scope'])].append(p)
        keys = sorted(rows, key=str)
        probs, refs = [], []
        for rowkey in keys:
            p = rows[rowkey][0]
            if rowkey[1:] == ('owned', 'whole_household_private'):
                rp, ref = pool(records, p, 'whole_owner_H7_joint', lambda r: r['area_scope_supported']
                    and r['tenure_code'] == 1 and r['room_proxy_category'] is not None
                    and float(r['area_candidate_m2']) / int(r['room_count_h7_proxy']) >= 1)
                mass = sum(r['weight'] for r in rp)
                observed = [sum(r['weight'] for r in rp if r['room_proxy_category'] == c) / mass for c in cols]
                q = [.75 * x + .25 * y for x, y in zip(observed, prior)]
                note = 'CHFS_owned_shi_proxy_N_G_association_plus_0_25_census_prior; census_H7_equivalence_unresolved'
            else:
                q, ref = prior, {'source_room_joint_records': 0}
                note = 'census_province_G_prior; conditional_H7_independence_from_N_tenure_sharing_is_design_not_observed_joint'
            probs.append(q)
            refs.append({'size': rowkey[0], 'tenure': rowkey[1], 'occupancy_scope': rowkey[2], 'rule': note, 'reference': ref})
        matrix, _ = gp.fit_transport([len(rows[k]) for k in keys], [census_counts[c] for c in cols], probs)
        for rk, allocation, ref in zip(keys, matrix, refs):
            psrow = sorted(rows[rk], key=lambda p: p['slot_id'])
            rr = gp.stage_rng(20261004, 'rooms_' + str(key) + str(rk))
            rr.shuffle(psrow)
            labels = [label for label, n in zip(cols, allocation) for _ in range(n)]
            rr.shuffle(labels)
            for p, rbin in zip(psrow, labels):
                h = p['housing']
                h['H7_census_bin'] = rbin
                h['H7_natural_rooms_exact'] = int(rbin) if rbin != '5+' else None
                h['H7_natural_rooms_minimum'] = int(rbin) if rbin != '5+' else 5
                h['H7_definition'] = 'household_independently_used_natural_rooms; exclude_kitchen_toilet_corridor_hall'
                h['H7_evidence'] = ref['rule']
                h['H7_association_reference'] = ref
                h['whole_dwelling_natural_rooms_exact'] = h['H7_natural_rooms_exact'] if h['occupancy_scope'] == 'whole_household_private' else None
                h['H7_topcode_tail_status'] = 'unknown_ge5_no_owned_tail_transport_to_rental' if rbin == '5+' else 'not_topcoded'
        audit.append({'province': key[0], 'generation': key[1], 'census_integer_bins_preserved': dict(census_counts), 'rows': refs})
    return audit


def area_reference(records, p):
    h = p['housing']
    t = h['current_tenure_model']
    scope = h['occupancy_scope']
    rbin = h['H7_census_bin']
    if t is None:
        return None
    room = rbin if t == 'owned' and scope == 'whole_household_private' else None
    tag = 'area_' + t + '_' + scope
    def admitted(r):
        a = r['area_candidate_m2']
        if not isinstance(a, (int, float)) or not math.isfinite(a) or a <= 0 or r['branch_overlap'] or r['usable_larger_than_building']:
            return False
        if t == 'rented':
            expected = 'whole_rented_dwelling' if scope == 'whole_household_private' else 'shared_area_allocation_unknown'
            return r['tenure_code'] == 2 and r['sharing_scope'] == expected
        expected = 'whole_current_owned_dwelling' if scope == 'whole_household_private' else 'partial_occupancy_requires_allocation'
        if r['tenure_code'] != 1 or r['sharing_scope'] != expected:
            return False
        nr = gp.integer(r['room_count_h7_proxy'])
        return room is None or (nr is not None and nr > 0 and a / nr >= 1)
    key = (tag, p['province'], p['size_category'], p['generation_category'], room)
    if key in BIN_CACHE:
        return BIN_CACHE[key]
    rp, ref = pool(records, p, tag, admitted, room)
    if not rp:
        return {'status': 'no_same_tenure_scope_area_reference', **ref, 'predictive_bins': []}
    values = collections.defaultdict(list)
    mass = collections.Counter()
    omitted = 0
    for r in rp:
        a = float(r['area_candidate_m2'])
        i = next((i for i in range(len(gp.AREA_EDGES) - 1) if gp.AREA_EDGES[i] <= a <= gp.AREA_EDGES[i + 1]), None)
        if i is None:
            omitted += r['weight']
        else:
            values[i].append(a)
            mass[i] += r['weight']
    norm = sum(mass.values())
    bins = [{'lower_m2': min(values[i]), 'upper_m2': max(values[i]), 'probability': w / norm,
             'coarsening_bin_m2': gp.AREA_EDGES[i:i + 2],
             'distribution': 'uniform_between_empirical_endpoints_or_point_mass'} for i, w in sorted(mass.items())]
    result = {**ref, 'status': 'same_tenure_and_scope_aggregate_reference', 'predictive_bins': bins,
              'source_tenure_codes': sorted({r['tenure_code'] for r in rp}),
              'source_occupancy_scopes': sorted({r['sharing_scope'] for r in rp}),
              'source_H7_condition': room, 'weighted_mass_outside_1_to2000_building_proxy_domain': omitted,
              'area_room_dependency_identified': t == 'owned' and scope == 'whole_household_private',
              'source_scope': 'whole_dwelling_building_area_proxy' if t == 'owned' or scope == 'whole_household_private'
                              else 'household_occupied_usable_area_times1_33_proxy; not_shared_H6_allocation',
              'native_area_conversion': 'CHFS_c1004_usable_times1_33' if t == 'rented' else 'CHFS_selected_owned_branch_building_or_usable_proxy',
              'domain_is_design_not_official_population_limit': True,
              'calibrated_observation': False}
    BIN_CACHE[key] = result
    return result


def assign_area(profiles, records, seed):
    for p in profiles:
        h = p['housing']
        ordinary = h['H5_is_ordinary_model_assigned']
        ref = area_reference(records, p) if ordinary else None
        a = None
        if ref and ref['predictive_bins']:
            rr = gp.stage_rng(seed, 'area_' + p['slot_id'])
            b = gp.weighted_choice(rr, ref['predictive_bins'], [b['probability'] for b in ref['predictive_bins']])
            a = round(rr.uniform(b['lower_m2'], b['upper_m2']), 2)
        private = h['occupancy_scope'] == 'whole_household_private'
        h.update(H6_building_area_m2=a if private else None,
                 H6_census_integer_m2=math.floor(a + .5) if private and a is not None else None,
                 H6_definition='本户现住房建筑面积; shared=本户独用建筑面积+共用建筑面积/合住户数' if ordinary else None,
                 H6_evidence='new_same_tenure_scope_source_proxy_draw; shared_allocation_unknown_preserved' if ordinary else 'not_applicable_to_nonordinary',
                 whole_dwelling_building_area_m2=a if (private or h['current_tenure_model'] == 'owned') else None,
                 occupied_usable_area_m2_proxy=round(a / 1.33, 4) if a is not None and h['current_tenure_model'] == 'rented' else None,
                 household_exclusive_building_area_m2=a if private else None,
                 shared_common_building_area_m2=0.0 if private else None,
                 area_allocation_status='whole_household_boundary_model' if private else
                                        ('components_unknown_no_H6_imputation' if ordinary else 'not_applicable'),
                 area_reference=ref,
                 H6_predictive_support_bins=ref['predictive_bins'] if private and ref else None,
                 whole_unit_geometry_area_m2=None,
                 geometry_area_evidence='requires_source_layout_net_area_and_explicit_wall_common_area_bridge')
        # Withdraw V4 fields that encoded an invalid scope or invented allocation.
        for k in ['area_policy', 'area_before_policy_draw_m2', 'design_floor_area_m2',
                  'design_natural_rooms_exact', 'nonordinary_model_scenario', 'exact_room_tail_model',
                  'sleep_groups', 'sleep_evidence', 'physical_binding_status']:
            h.pop(k, None)
        h['sleeping_assignment'] = {'status': 'pending_functional_rooms_and_kinship; H7_does_not_equal_bedrooms'}
        h['physical_binding_status'] = 'pending_functional_layout_area_scope_exposure_services_and_meter_binding'
        p['housing_model_version'] = VERSION
        p['field_provenance']['housing.H6'] = 'V5_same_tenure_scope_proxy; shared_unknown_without_census_allocation_components'
        p['field_provenance']['housing.H7'] = 'V5_census_independent_room_margins; tenure_specific_identifiability_policy'
        p['field_provenance']['housing.sleep_groups'] = 'withdrawn_pending_functional_layout_and_kinship'
        p['complete_actor_card'] = False


def coupling_audit(profiles):
    """Frechet/rearrangement witness: no observed rental area-H7 joint exists.

    Permute the same generated rental areas within province/G. All their area
    and room margins survive. These are extremal rank couplings for that finite
    stratum, not posterior draws, population confidence limits or probabilities.
    """
    groups = collections.defaultdict(list)
    for p in profiles:
        h = p['housing']
        if h['current_tenure_model'] == 'rented' and h['occupancy_scope'] == 'whole_household_private' and h['H6_building_area_m2'] is not None:
            groups[(p['province'], p['generation_category'])].append(p)
    assignments, audits = [], []
    for key, ps in groups.items():
        ordered = sorted(ps, key=lambda p: (p['housing']['H7_natural_rooms_minimum'], p['slot_id']))
        areas = sorted(p['housing']['H6_building_area_m2'] for p in ordered)
        for direction in ['same_rank', 'opposite_rank']:
            permutation = areas if direction == 'same_rank' else list(reversed(areas))
            for p, a in zip(ordered, permutation):
                assignments.append({'slot_id': p['slot_id'], 'coupling': direction, 'H6_building_area_m2': a,
                                    'H7_bin_unchanged': p['housing']['H7_census_bin']})
            audits.append({'province': key[0], 'G': key[1], 'coupling': direction, 'households': len(ps),
                           'sum_area_times_min_rooms': sum(a * p['housing']['H7_natural_rooms_minimum'] for a, p in zip(permutation, ordered))})
    return {'scope': 'finite_stratum_rental_area_room_nonidentification_witness_not_complete_generator_validation',
            'margins_preserved': ['rental_private_area_multiset_within_province_G', 'H7_province_G_bins', 'family_slots', 'housing_source_facilities'],
            'areas_are_modeled_not_observed': True, 'probability_or_CI_assigned': False,
            'baseline_independence_is_design': True, 'assignments': assignments, 'strata': audits}


def main():
    out = ROUTE / 'housing1000'
    if out.exists() and any(out.iterdir()):
        raise ValueError('new_immutable_output_required')
    out.mkdir(exist_ok=True)
    body = json.loads(BASE.read_text())
    records = private_records()
    sourceaudit = assign_sources(body['profiles'], records)
    assign_sharing(body['profiles'], records, 20261004)
    roomaudit = assign_rooms(body['profiles'], records)
    assign_area(body['profiles'], records, 20261004)
    body['schema'] = 'eb.population_housing_household_scope_candidate.v5'
    body['housing_model'] = {'version': VERSION, 'seed': 20261004,
        'production_order': ['fixed_population_rosters_H5', 'source_facility_margin_and_tenure_N_G_transport',
            'tenure_specific_occupancy_scope', 'census_H7_household_independent_rooms', 'tenure_scope_specific_area',
            'unknown_allocation_and_layout_gate', 'conditional_engineering_scenarios_after_population_generation'],
        'detailed_kinship_pending': True, 'source_vintage_storeys_joint_unidentified': True,
        'area_room_joint_observed_for_rental_or_shared': False,
        'full_national_joint_validated': False, 'actor_ready': 0}
    body['input_v4_sha256'] = gp.sha(BASE)
    body['generator_sha256'] = gp.sha(__file__)
    body['collection_release'] = body['training_release'] = False
    save(out / 'HOUSEHOLDS1000.json', body)
    save(out / 'SOURCE_TENURE_ASSIGNMENT.json', {'observed_full_joint': False, 'audits': sourceaudit,
        'construction': 'fixed_census_source_facility_integer_cells_reassigned_using_shrunk_CHFS_tenure_N_G_prior_and_IPF_MILP',
        'public_vs_other_rental_CHFS_subtype_not_identified': True, 'other_source_tenure_unknown': True})
    save(out / 'H7_ASSOCIATION_AUDIT.json', {'audits': roomaudit, 'observed_CHFS_rental_H7_records': 0,
        'shared_H7_is_exclusive_not_whole_unit': True, 'topcode_exact_tail_unknown': True})
    save(out / 'RENTAL_AREA_ROOM_COUPLING_WITNESSES.json', coupling_audit(body['profiles']))
    source_counts = collections.Counter((str(r['tenure_code']), r['sharing_scope']) for r in records)
    save(out / 'SOURCE_COVERAGE.json', {'eligible_city_source_records': len(records),
        'source_tenure_scope_counts': [{'tenure': t, 'scope': s, 'n': n} for (t, s), n in source_counts.items()],
        'raw_source_IDs_exported': 0, 'raw_source_rows_exported': 0,
        'census2020_to_CHFS2021_2022_transport_observed': False})
    files = [BASE, SOURCE, Path(__file__), H / 'chfs_census_bridge_20261003/run_bridge.py',
             H / 'chfs_census_bridge_20261003/bridge_rules.py', *sorted(gp.rb.PACKAGE.glob('chfs2021_*_pub_*.dta')),
             Path('/Users/fanmili/Downloads/2021/CHFS问卷-2021/2021年中国家庭金融调查(CHFS)问卷.pdf'),
             H / 'evidence_contract_20261001/raw/census2020_plan_retry.pdf',
             H / 'production_route_v4_20261003/code/generate_population.py']
    save(out / 'INPUT_LOCK.json', {'files': [{'path': str(p.resolve()), 'sha256': gp.sha(p)} for p in files],
        'runtime': {'python': sys.version, 'numpy': np.__version__}, 'candidate_sha256': gp.sha(out / 'HOUSEHOLDS1000.json')})
    print(json.dumps({'output': str(out), 'profiles': len(body['profiles']), 'actor_ready': 0}))


if __name__ == '__main__':
    main()
