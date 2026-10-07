#!/usr/bin/env python3
"""Semantic corruption checks on disposable anonymous candidates, never sources."""
import copy
import hashlib
import importlib.util
import json
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = HERE / 'final_v2'
spec = importlib.util.spec_from_file_location('independent_verifier', HERE / 'verify_candidates.py')
verifier = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verifier)


def read(path):
    return json.loads(path.read_text())


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def first(body, predicate):
    return next(p for p in body['profiles'] if predicate(p))


def wrong_generation(body, targets):
    p = first(body, lambda p: p['family']['generation_count_design'] > 1)
    p['family']['generation_count_design'] += 1


def wrong_parent_age(body, targets):
    p = first(body, lambda p: any(r['kind'] == 'parent_child_design' for r in p['family']['relation_design']))
    r = next(r for r in p['family']['relation_design'] if r['kind'] == 'parent_child_design')
    older = next(m for m in p['family']['members'] if m['member_id'] == r['older_member_id'])
    younger = next(m for m in p['family']['members'] if m['member_id'] == r['younger_member_id'])
    younger['age_years'] = older['age_years']


def duplicate_member(body, targets):
    pair = [p for p in body['profiles'] if len(p['family']['members']) == 1][:2]
    p, other = pair
    previous = p['family']['members'][0]['member_id']
    duplicate = other['family']['members'][0]['member_id']
    p['family']['members'][0]['member_id'] = duplicate
    p['family']['resident_member_ids'] = [duplicate]
    p['housing']['sleep_groups'] = [[duplicate if x == previous else x for x in group] for group in p['housing']['sleep_groups']]


def wrong_room_bin(body, targets):
    p = first(body, lambda p: p['housing']['H7_census_bin'] == '5+')
    p['housing']['H7_natural_rooms_exact'] = 4


def duplicate_sleep(body, targets):
    p = body['profiles'][0]
    p['housing']['sleep_groups'][0].append(p['family']['resident_member_ids'][0])


def fabricated_nonordinary_area(body, targets):
    p = first(body, lambda p: not p['housing']['H5_is_ordinary_model_assigned'])
    p['housing']['H6_building_area_m2'] = 100


def wrong_population(body, targets):
    p = body['profiles'][0]
    p['province'] = '天津' if p['province'] != '天津' else '北京'


def wrong_area_mean(body, targets):
    p = first(body, lambda p: p['housing']['H5_is_ordinary_model_assigned'])
    p['housing']['H6_building_area_m2'] += 10000


def wrong_authority_probability(body, targets):
    targets['H5_province_generation'][0]['p_ordinary'] += .05


def underage_singleton(body, targets):
    p = first(body, lambda p: p['family']['resident_count'] == 1)
    p['family']['members'][0]['age_years'] = 19


def run():
    cases = [
        ('occupied_generation_metadata_conflict', wrong_generation, 'occupied_generation_conflict'),
        ('parent_ancestor_age_conflict', wrong_parent_age, 'parent_ancestor_age_level_conflict'),
        ('duplicate_synthetic_member_id', duplicate_member, 'globally_unique_synthetic_member_ids'),
        ('topcode_room_bin_conflict', wrong_room_bin, 'H7_bin_or_semantic_conflict'),
        ('sleep_member_duplicate', duplicate_sleep, 'sleep_assignment_conflict'),
        ('nonordinary_census_area_fabrication', fabricated_nonordinary_area, 'nonordinary_census_fields_fabricated'),
        ('population_province_change', wrong_population, 'changed_population_target'),
        ('H6_group_mean_corruption', wrong_area_mean, 'H6_group_mean_'),
        ('target_probability_not_matching_authority', wrong_authority_probability, 'H5_authority_probability_'),
        ('under20_singleton', underage_singleton, 'age_invalid_or_singleton_under20'),
    ]
    baseline = read(BASE / 'FAMILY_HOUSING_CANDIDATES.json')
    baseline_targets = read(BASE / 'CALIBRATION_TARGETS.json')
    baseline_lock = read(BASE / 'GENERATOR_LOCK.json')
    rows = []
    for name, mutate, expected in cases:
        body, targets = copy.deepcopy(baseline), copy.deepcopy(baseline_targets)
        mutate(body, targets)
        with tempfile.TemporaryDirectory(prefix='anonymous_negative_', dir=HERE) as directory:
            batch = Path(directory)
            save(batch / 'FAMILY_HOUSING_CANDIDATES.json', body)
            save(batch / 'CALIBRATION_TARGETS.json', targets)
            lock = copy.deepcopy(baseline_lock)
            # The byte hash is made self-consistent to test semantics, not just corruption detection.
            lock['output_sha256'] = sha(batch / 'FAMILY_HOUSING_CANDIDATES.json')
            save(batch / 'GENERATOR_LOCK.json', lock)
            result = verifier.verify(batch)
        failed_names = [x['check'] for x in result['failed']]
        semantic_faults = next((x['detail'] for x in result['failed'] if x['check'] == 'profile_semantic_checks'), {})
        detected = expected in semantic_faults or any(x.startswith(expected) for x in failed_names)
        byte_check_pass = next(x['pass'] for x in result['checks'] if x['check'] == 'candidate_bytes_equal_locked_sha')
        rows.append({'case': name, 'expected_semantic_failure': expected, 'candidate_rejected': not result['pass'],
                     'expected_failure_detected': detected, 'self_consistent_byte_hash_passed': byte_check_pass,
                     'semantic_faults': semantic_faults, 'failed_check_names': failed_names})
    baseline_result = verifier.verify(BASE)
    report = {'schema': 'eb.anonymous_generation_negative_controls.v1',
              'baseline_sha256': sha(BASE / 'FAMILY_HOUSING_CANDIDATES.json'), 'baseline_pass': baseline_result['pass'],
              'case_count': len(rows), 'pass': baseline_result['pass'] and all(r['candidate_rejected'] and r['expected_failure_detected'] and r['self_consistent_byte_hash_passed'] for r in rows),
              'cases': rows, 'microdata_read': False, 'source_ids_or_source_rows_exported': False,
              'disposable_mutant_candidates_retained': False, 'test_code_sha256': sha(Path(__file__))}
    save(HERE / 'NEGATIVE_CONTROL_RESULTS.json', report)
    print(json.dumps({'pass': report['pass'], 'cases': report['case_count'], 'baseline_sha256': report['baseline_sha256']}))
    if not report['pass']:
        raise SystemExit(1)


if __name__ == '__main__':
    run()
