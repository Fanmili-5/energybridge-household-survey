#!/usr/bin/env python3
"""Readback-only comparisons; no source microdata and no profile mutations."""
import collections
import hashlib
import json
from pathlib import Path
from verify_candidates import verify

HERE = Path(__file__).resolve().parent
BASELINE = 'final_v2'
BATCHES = ['reproduce_seed20261003', 'sensitivity_H5_lower', 'sensitivity_H5_upper',
           'sensitivity_H7_independent', 'sensitivity_minimum_tails',
           'replicate_seed20261004', 'replicate_seed20261005']


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def body(name):
    return json.loads((HERE / name / 'FAMILY_HOUSING_CANDIDATES.json').read_text())


def summary(q):
    return {k: q[k] for k in ['pass', 'check_count', 'profiles', 'members', 'ordinary', 'nonordinary',
                              'ordinary_shared', 'dwelling_type_counts', 'H7_bin_counts_ordinary',
                              'exact_size10plus', 'exact_room5plus_counts',
                              'maximum_H6_mean_rounding_residual_m2',
                              'exact_duplicate_nonidentity_family_housing_payload_extra_profiles']}


def compare(base, alt):
    x = {p['slot_id']: p for p in base['profiles']}
    y = {p['slot_id']: p for p in alt['profiles']}
    keys = sorted(x)
    unchanged_family = sum(digest(x[k]['family']) == digest(y[k]['family']) for k in keys)
    unchanged_roster = sum(digest(x[k]['family']['members']) == digest(y[k]['family']['members']) for k in keys)
    h5changes = sum(x[k]['housing']['H5_is_ordinary_model_assigned'] != y[k]['housing']['H5_is_ordinary_model_assigned'] for k in keys)
    roomchanges = sum(x[k]['housing']['H7_natural_rooms_exact'] != y[k]['housing']['H7_natural_rooms_exact'] for k in keys)
    room_bin_changes = sum(x[k]['housing']['H7_census_bin'] != y[k]['housing']['H7_census_bin'] for k in keys)
    area_pairs = [(x[k]['housing']['H6_building_area_m2'], y[k]['housing']['H6_building_area_m2']) for k in keys
                  if x[k]['housing']['H5_is_ordinary_model_assigned'] and y[k]['housing']['H5_is_ordinary_model_assigned']]
    return {'target_slot_keys_equal': set(x) == set(y),
            'population_keys_unchanged': all(all(x[k][z] == y[k][z] for z in ['province', 'size_category', 'generation_category']) for k in keys),
            'full_family_hash_unchanged_count': unchanged_family, 'actual_member_roster_unchanged_count': unchanged_roster,
            'H5_assignments_changed': h5changes, 'H7_exact_values_changed': roomchanges,
            'H7_census_bins_changed': room_bin_changes,
            'common_ordinary_H6_mean_absolute_difference_m2': sum(abs(a - b) for a, b in area_pairs) / len(area_pairs),
            'scope': 'population-model sensitivity, not physical calibration or observed family truth'}


def main():
    baseline = body(BASELINE)
    baseqc = verify(HERE / BASELINE)
    summaries = {BASELINE: summary(baseqc)}
    comparisons = {}
    for name in BATCHES:
        qc = verify(HERE / name)
        (HERE / name / 'PROFILES_QC.json').write_text(json.dumps(qc, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
        summaries[name] = summary(qc)
        comparisons[name] = compare(baseline, body(name))
    assert all(s['pass'] for s in summaries.values())
    assert all(c['population_keys_unchanged'] for c in comparisons.values())
    for name in ['sensitivity_H5_lower', 'sensitivity_H5_upper', 'sensitivity_H7_independent']:
        assert comparisons[name]['full_family_hash_unchanged_count'] == 1000
    basehash = hashlib.sha256((HERE / BASELINE / 'FAMILY_HOUSING_CANDIDATES.json').read_bytes()).hexdigest()
    repohash = hashlib.sha256((HERE / 'reproduce_seed20261003' / 'FAMILY_HOUSING_CANDIDATES.json').read_bytes()).hexdigest()
    assert basehash == repohash
    profiles = baseline['profiles']
    ordinary = [p for p in profiles if p['housing']['H5_is_ordinary_model_assigned']]
    refs = [p['family']['member_generation_reference'] for p in profiles]
    arefs = [p['housing']['area_reference'] for p in profiles]
    stats = {'model_composition_design_fallback_profiles': sum(p['family']['composition_evidence'].startswith('explicit_design') for p in profiles),
             'member_reference_route_counts': dict(collections.Counter(r['route'] for r in refs)),
             'area_reference_route_counts': dict(collections.Counter(r['route'] for r in arefs)),
             'member_reference_single_source_profiles': sum(r['source_records'] == 1 for r in refs),
             'member_reference_1to4_source_profiles': sum(0 < r['source_records'] < 5 for r in refs),
             'area_reference_1to4_source_profiles': sum(0 < r['source_records'] < 5 for r in arefs),
             'maximum_member_reference_weight_share': max(r['maximum_weight_share'] for r in refs),
             'maximum_area_reference_weight_share': max(r['maximum_weight_share'] for r in arefs),
             'H6_mean_calibration_scale_min': min(p['housing']['area_calibration_scale'] for p in ordinary),
             'H6_mean_calibration_scale_max': max(p['housing']['area_calibration_scale'] for p in ordinary),
             'ordinary_H6_min_m2': min(p['housing']['H6_building_area_m2'] for p in ordinary),
             'ordinary_H6_max_m2': max(p['housing']['H6_building_area_m2'] for p in ordinary),
             'H6_per_natural_room_below6m2_design_diagnostic_count': sum(p['housing']['H6_building_area_m2'] / p['housing']['H7_natural_rooms_exact'] < 6 for p in ordinary),
             'diagnostic_not_building_code': True}
    result = {'schema': 'eb.family_housing_generation_sensitivity.v1', 'baseline': BASELINE,
              'baseline_candidate_sha256': basehash, 'exact_reproduction_sha256': repohash,
              'exact_reproduction_pass': basehash == repohash, 'all_independent_batches_pass': True,
              'batch_summaries': summaries, 'paired_model_comparisons': comparisons,
              'reference_influence_and_calibration_diagnostics': stats,
              'national_detailed_joint_representativeness_claimed': False,
              'thermal_calibration_claimed': False, 'complete_actor_cards': 0}
    (HERE / 'SENSITIVITY_RESULTS.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
    print(json.dumps({'all_independent_batches_pass': True, 'exact_reproduction_pass': True,
                      'summaries': {k: {z: s[z] for z in ['ordinary', 'nonordinary', 'members', 'exact_size10plus']} for k, s in summaries.items()},
                      'reference_diagnostics': stats}, ensure_ascii=False))


if __name__ == '__main__':
    main()
