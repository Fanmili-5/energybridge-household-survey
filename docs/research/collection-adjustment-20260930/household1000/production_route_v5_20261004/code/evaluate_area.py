#!/usr/bin/env python3
"""Whole-household CHFS area-stage validation, separated by tenure and scope."""
import collections
import hashlib
import json
import math
import sys
from pathlib import Path

import numpy as np
import rebuild_housing as model

HERE = Path(__file__).resolve().parent
OUT = HERE.parent / 'area_component_holdout'
SALT = 'EB_CHFS_WHOLE_HOUSEHOLD_FOLDS_20261003_V1'


def eu(a, b, y):
    if a == b:
        return abs(a-y)
    if y <= a:
        return (a+b)/2-y
    if y >= b:
        return y-(a+b)/2
    return ((y-a)**2+(b-y)**2)/(2*(b-a))


def pair(a, b, c, d):
    if a == b:
        return eu(c, d, a)
    if c == d:
        return eu(a, b, c)
    return (abs(b-c)**3+abs(a-d)**3-abs(a-c)**3-abs(b-d)**3)/(6*(b-a)*(d-c))


def scores(bins, y):
    mean = sum(b['probability']*(b['lower_m2']+b['upper_m2'])/2 for b in bins)
    first = sum(b['probability']*eu(b['lower_m2'], b['upper_m2'], y) for b in bins)
    spread = sum(a['probability']*b['probability']*pair(a['lower_m2'], a['upper_m2'], b['lower_m2'], b['upper_m2']) for a in bins for b in bins)/2
    return abs(mean-y), first-spread


def label(r):
    a = r['area_candidate_m2']
    if a is None or a <= 0 or r['branch_overlap'] or r['usable_larger_than_building']:
        return None
    scopes = {'whole_current_owned_dwelling': 'owned_private', 'partial_occupancy_requires_allocation': 'owned_partial_whole_unit',
              'whole_rented_dwelling': 'rented_private', 'shared_area_allocation_unknown': 'rented_shared_occupied'}
    result = scopes.get(r['sharing_scope'])
    if result == 'owned_private':
        room = model.gp.integer(r['room_count_h7_proxy'])
        if room is None or room <= 0 or a/room < 1:
            return None
    return result


def fold(r):
    return int(hashlib.sha256((SALT+'|'+str(r['_local_hhid'])).encode()).hexdigest(), 16) % 5


def profile_for(r, stratum):
    return {k: r[k] for k in ['province', 'size_category', 'generation_category']} | {'housing': {
        'current_tenure_model': 'owned' if stratum.startswith('owned') else 'rented',
        'occupancy_scope': 'whole_household_private' if stratum.endswith('private') else 'shared_household',
        'H7_census_bin': r['room_proxy_category'] if stratum == 'owned_private' else None}}


def empirical(records):
    x = np.array([r['area_candidate_m2'] for r in records], float)
    w = np.array([r['weight'] for r in records], float)
    order = np.argsort(x)
    x, w = x[order], w[order]/w.sum()
    c = np.cumsum(w)
    return x, w, float((x*w).sum()), float((w*x*(2*(c-w)+w-1)).sum())


def main():
    if OUT.exists():
        raise ValueError('new_evaluation_output_required')
    OUT.mkdir()
    model.save(OUT / 'EVALUATION_LOCK.json', {'fold_unit': 'whole_source_household_across_all_reference_branches',
        'salt': SALT, 'folds': 5, 'locked_before_this_evaluation': True, 'not_prospectively_preregistered_research': True,
        'models': ['national_same_tenure_scope_empirical_baseline_H7_only_for_owned_private', 'actual_V5_area_reference'],
        'metrics': ['weighted_descriptive_MAE_of_mean', 'weighted_CRPS', 'missing_predictions', 'out_of_domain_test_outcomes'],
        'train_domain': '1..2000m2_building_or_occupied_times1_33_proxy', 'outside_domain_test_outcomes_retained': True,
        'vintage_selection_removed_because_model_does_not_use_vintage': True,
        'source_code_sha256': model.gp.sha(HERE / 'rebuild_housing.py'), 'evaluation_code_sha256': model.gp.sha(__file__),
        'stage_only_not_full_generator_2020_joint_validation': True})
    records = model.private_records()
    test_records = [(r, label(r)) for r in records if label(r) is not None]
    global_sums = collections.defaultdict(collections.Counter)
    reports = []
    missing = collections.Counter()
    for k in range(5):
        train = [r for r in records if fold(r) != k]
        test = [(r, s) for r, s in test_records if fold(r) == k]
        model.POOL_CACHE.clear()
        model.BIN_CACHE.clear()
        baselines = {}
        for r, stratum in test:
            p = profile_for(r, stratum)
            baseline_key = (stratum, p['housing']['H7_census_bin'])
            if baseline_key not in baselines:
                admitted = [t for t in train if label(t) == stratum and 1 <= t['area_candidate_m2'] <= 2000
                            and (stratum != 'owned_private' or t['room_proxy_category'] == r['room_proxy_category'])]
                baselines[baseline_key] = empirical(admitted) if admitted else None
            baseline = baselines[baseline_key]
            ref = model.area_reference(train, p)
            if baseline is None or not ref or not ref['predictive_bins']:
                missing[stratum] += 1
                continue
            y, w = r['area_candidate_m2'], r['weight']
            mae, crps = scores(ref['predictive_bins'], y)
            x, ws, mean, spread = baseline
            s = global_sums[stratum]
            s['weight'] += w
            s['records'] += 1
            s['baseline_MAE'] += w*abs(mean-y)
            s['baseline_CRPS'] += w*(float((ws*abs(x-y)).sum())-spread)
            s['V5_MAE'] += w*mae
            s['V5_CRPS'] += w*crps
            s['outcomes_outside_domain'] += int(not 1 <= y <= 2000)
        reports.append({'fold': k, 'all_reference_households_train': len(train), 'test_households': len(test),
                        'test_counts': dict(collections.Counter(s for r, s in test))})
        print(json.dumps(reports[-1]), flush=True)
    strata = []
    for stratum, s in global_sums.items():
        strata.append({'stratum': stratum, 'scored_test_households': int(s['records']), 'missing_predictions': missing[stratum],
                       'test_outcomes_outside_design_domain_retained': int(s['outcomes_outside_domain']),
                       'weighted_metrics': {k: s[k]/s['weight'] for k in ['baseline_MAE', 'baseline_CRPS', 'V5_MAE', 'V5_CRPS']},
                       'target_is_census_shared_H6': False,
                       'outcome_scope': 'owned_whole_building_area_proxy' if stratum.startswith('owned') else
                                        ('rented_whole_building_proxy_from_usable' if stratum == 'rented_private' else 'rented_household_occupied_usable_times1_33_proxy')})
    controls = [abs(pair(0, 1, 0, 1)-1/3) < 1e-12, abs(pair(0, 1, 2, 3)-2) < 1e-12,
                abs(scores([{'lower_m2': 0, 'upper_m2': 1, 'probability': 1}], .5)[1]-1/12) < 1e-12]
    assert all(controls)
    result = {'folds': reports, 'strata': strata, 'analytic_score_controls_pass': all(controls),
              'whole_source_holdout_households': len(test_records), 'missing_predictions': dict(missing),
              'test_fields_are_CHFS_proxies_not_census2020_truth': True,
              'rental_area_H7_association_validated': False, 'shared_H6_allocations_validated': False,
              'full_generator_or_national_joint_validated': False, 'survey_design_standard_errors_available': False,
              'no_model_winner_or_significance_claim': True, 'collection_release': False, 'training_release': False}
    model.save(OUT / 'RESULT.json', result)
    print(json.dumps({'strata': strata}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
