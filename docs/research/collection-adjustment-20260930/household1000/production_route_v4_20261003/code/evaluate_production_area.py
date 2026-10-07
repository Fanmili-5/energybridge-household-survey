#!/usr/bin/env python3
"""Whole-source-household holdout of the actual V4 area distribution stage.

Test inputs are province/N/G/H7 proxies. This is conditional component
validation in CHFS's owned branch, not full target2020 population validation.
"""
import collections
import hashlib
import json
import math
import sys
from pathlib import Path
import numpy as np

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROUTE = HERE.parent
sys.path.insert(0, str(HERE))
import generate_population as gen


def expected_abs_uniform(low, high, y):
    if high == low:
        return abs(low - y)
    if y <= low:
        return (low + high) / 2 - y
    if y >= high:
        return y - (low + high) / 2
    return ((y - low) ** 2 + (high - y) ** 2) / (2 * (high - low))


def pair_abs(a, b, c, d):
    if a == b:
        return expected_abs_uniform(c, d, a)
    if c == d:
        return expected_abs_uniform(a, b, c)
    return (abs(b - c) ** 3 + abs(a - d) ** 3 - abs(a - c) ** 3 - abs(b - d) ** 3) / (6 * (b - a) * (d - c))


def scores(bins, y):
    mean = sum(b['probability'] * (b['lower_m2'] + b['upper_m2']) / 2 for b in bins)
    first = sum(b['probability'] * expected_abs_uniform(b['lower_m2'], b['upper_m2'], y) for b in bins)
    spread = sum(a['probability'] * b['probability'] * pair_abs(a['lower_m2'], a['upper_m2'], b['lower_m2'], b['upper_m2']) for a in bins for b in bins) / 2
    return abs(mean - y), first - spread


def empirical(records):
    # Analytical weighted point-mass CRPS without an O(n^2) pair expansion.
    x = np.array([r['area_candidate_m2'] for r in records], float)
    w = np.array([r['weight'] for r in records], float)
    order = np.argsort(x)
    x, w = x[order], w[order] / w.sum()
    c = np.cumsum(w)
    return x, w, float((x * w).sum()), float((w * x * (2 * (c - w) + w - 1)).sum())


def main():
    out = ROUTE / 'production_area_holdout'
    if out.exists():
        raise ValueError('new_holdout_output_required')
    out.mkdir()
    policy = {'schema': 'eb.area_component_evaluation_lock.v1',
              'lock_before_new_evaluation': True, 'not_preregistered_before_prior_review': True,
              'fold_count': 5, 'fold_unit': 'whole CHFS source household across ALL reference branches',
              'salt': 'EB_CHFS_WHOLE_HOUSEHOLD_FOLDS_20261003_V1',
              'models': ['weighted empirical area|H7 baseline', 'actual V4 province/N/G/H7 hierarchical empirical-interval area stage'],
              'candidate_model_parameters': {'shrinkage_tau': 20, 'minimum_source_area_per_room_m2': 1, 'age_bin_width': 5, 'birthyear_upper_probability': .5},
              'quality_policy': 'source train bins1..2000 declared model domain; test outcomes outside domain retained and counted',
              'metrics': ['weighted MAE of conditional mean (descriptive)', 'weighted CRPS of predictive distribution', 'missing predictions', 'out-of-training-domain outcomes'],
              'source_code_sha256': gen.sha(HERE / 'generate_population.py'),
              'evaluation_code_sha256': gen.sha(Path(__file__)),
              'selection_rule': 'no automatic winner or formal population approval; target-year external joint validation still required'}
    gen.save(out / 'EVALUATION_LOCK.json', policy)
    gen.MODEL.update(**policy['candidate_model_parameters'])
    all_records = gen.load_references()
    years = gen.rb.read('hh', ['hhid', *[f'c2012a_{j}' for j in range(1, 7)]])
    year_map = {r['hhid']: r for r in years.to_dict('records')}
    test_records = []
    for r in all_records:
        if not r['area_scope_supported'] or not r['room_proxy_category']:
            continue
        room = gen.integer(r['room_count_h7_proxy'])
        j = gen.integer(r['current_dwelling_slot'])
        if room is None or j is None or r['area_candidate_m2'] / room < 1:
            continue
        v = gen.integer(year_map[r['_local_hhid']].get(f'c2012a_{j}'))
        if v is not None and 1000 <= v <= 2020:
            test_records.append(r)
    assert len(test_records) == 2628, 'cohort_changed_reaudit_required'
    def fold(r):
        return int(hashlib.sha256((policy['salt'] + '|' + str(r['_local_hhid'])).encode()).hexdigest(), 16) % 5
    totals = collections.Counter()
    reports = []
    for k in range(5):
        train = [r for r in all_records if fold(r) != k]
        test = [r for r in test_records if fold(r) == k]
        # Baseline shares the same training-domain/QC information as V4.
        pair = [r for r in train if r['area_scope_supported'] and r['room_proxy_category']
                and gen.integer(r['room_count_h7_proxy']) is not None
                and r['area_candidate_m2'] / r['room_count_h7_proxy'] >= 1
                and 1 <= r['area_candidate_m2'] <= 2000]
        baseline = {room: empirical([r for r in pair if r['room_proxy_category'] == room]) for room in ['1', '2', '3', '4', '5+']}
        gen.AREA_REFERENCE_CACHE.clear()
        sums = collections.Counter()
        missing = 0
        for r in test:
            slot = {a: r[a] for a in ['province', 'size_category', 'generation_category']}
            try:
                _, reference = gen.sample_area(train, slot, r['room_proxy_category'], gen.stage_rng(20261003, 'evaluation_unused_draw'))
            except ValueError:
                missing += 1
                continue
            mae, crps = scores(reference['predictive_area_bins'], r['area_candidate_m2'])
            x, ws, m, half = baseline[r['room_proxy_category']]
            w, y = r['weight'], r['area_candidate_m2']
            sums['weight'] += w
            sums['A_MAE'] += w * abs(m - y)
            sums['A_CRPS'] += w * (float((ws * abs(x - y)).sum()) - half)
            sums['V4_MAE'] += w * mae
            sums['V4_CRPS'] += w * crps
            sums['records'] += 1
            sums['outcomes_outside_domain'] += int(not 1 <= y <= 2000)
        totals.update(sums)
        reports.append({'fold': k, 'whole_reference_households_train': len(train), 'test_households': len(test),
                        'missing_predictions': missing, 'common_records': sums['records'],
                        'outcomes_outside_domain': sums['outcomes_outside_domain'],
                        **{m: sums[m] / sums['weight'] for m in ['A_MAE', 'V4_MAE', 'A_CRPS', 'V4_CRPS']}})
        print(json.dumps(reports[-1]), flush=True)
    result = {'schema': 'eb.actual_production_area_component_holdout.v1', 'test_source_households': len(test_records),
              'folds': reports, 'common_records': totals['records'],
              'weighted_metrics': {m: totals[m] / totals['weight'] for m in ['A_MAE', 'V4_MAE', 'A_CRPS', 'V4_CRPS']},
              'outcomes_outside_domain_retained': totals['outcomes_outside_domain'],
              'actual_generation_function_used': 'generate_population.sample_area + select_pool',
              'entire_1000_generator_validated': False, 'target2020_joint_representativeness_validated': False,
              'cohort_scope': 'owned whole current dwelling, H7 proxy and valid vintage candidate; owned-source only',
              'survey_design_standard_errors_available': False, 'collection_release': False, 'training_release': False}
    gen.save(out / 'RESULT.json', result)
    # Analytic negative/edge controls unrelated to production row outcomes.
    checks = [abs(pair_abs(0, 1, 0, 1) - 1 / 3) < 1e-12,
              abs(pair_abs(0, 1, 2, 3) - 2) < 1e-12,
              abs(scores([{'lower_m2': 0, 'upper_m2': 1, 'probability': 1}], .5)[1] - 1 / 12) < 1e-12,
              abs(scores([{'lower_m2': 2, 'upper_m2': 2, 'probability': 1}], 5)[1] - 3) < 1e-12]
    gen.save(out / 'SCORE_CONTROLS.json', {'analytic_controls': checks, 'pass': all(checks)})
    assert all(checks)
    print(json.dumps(result['weighted_metrics']), flush=True)


if __name__ == '__main__':
    main()
