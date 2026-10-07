"""Admit modern grouped-device evidence, without inventing individual appliances.

Local authorized CHFS2021 files; output contains aggregates only, no source
household IDs, member records, or individual monetary values.
"""
import hashlib
import json
import math
import sys
from pathlib import Path
import numpy as np

OUT = Path(__file__).resolve().parent.parent
BASE = OUT.parent
sys.path.insert(0, str(BASE / 'chfs_census_bridge_20261003'))
import run_bridge as rb


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024*1024), b''):
            h.update(block)
    return h.hexdigest()


def groups(frame):
    weights = frame.weight.to_numpy(dtype=float)
    total = float(weights.sum())
    output = []
    for key, g in frame.groupby(['c8001ab_2_mc', 'c8001ab_5_mc', 'c8001ab_19_mc'], dropna=False):
        w = g.weight.to_numpy(dtype=float)
        output.append({'groups_2_5_19': [int(x) if x is not None and not math.isnan(x) else None for x in key],
                       'source_households': len(g), 'source_weighted_share': float(w.sum()) / total,
                       'kish_ESS': float(w.sum()**2 / (w @ w))})
    return output


def main():
    binary = ['c8001ab_2_mc', 'c8001ab_5_mc', 'c8001ab_19_mc']
    values = ['c8001ab_exinteger2', 'c8001ab_exinteger5', 'c8001ab_exinteger19']
    all_choices = [f'c8001ab_{k}_mc' for k in [1,2,5,6,9,12,19,7777,7788]]
    hh = rb.read('hh', ['hhid'] + all_choices + values)
    pool = rb.load_bridge_pool()
    df = pool.merge(hh.rename(columns={'hhid': '_local_hhid'}), on='_local_hhid', validate='one_to_one')
    eligible = df[df.member_finance_pool].copy()
    assert len(eligible) == 9145
    for c in binary:
        assert set(eligible[c].dropna()) <= {0, 1}
    any_other = eligible[[c for c in all_choices if c != 'c8001ab_7788_mc']].eq(1).any(axis=1)
    none = eligible.c8001ab_7788_mc.eq(1)
    answer_valid = any_other | none
    contradiction = any_other & none
    aligned = eligible.visit_year == 2021
    all_weight = float(eligible.weight.sum())
    missing_weight = float(eligible.loc[~answer_valid, 'weight'].sum())
    source_labels = json.loads((BASE / 'chfs_admission_20261003/private_metadata/chfs2021_hh_pub_v0_20260131_metadata.json').read_text())['variable_labels']
    out = {'source_scope': 'CHFS_city_sampling_address_categories111_112; city_current_home_alignment_unverified',
           'co_residence_proxy': 'A2000c1_2 includes temporary absence returning within_three_months; not_proven_census_resident_equivalence',
           'questionnaire_2021_pdf_page': 107, 'questionnaire_2022_pdf_page': 106,
           'question': 'C8001ab grouped durable ownership and total_value; current_in_2021_form_vs_July2021_recall_in_2022_form',
           'source_city_households': len(df), 'positive_weight_eligible_source_households': len(eligible),
           'group_columns': binary, 'current_value_columns': values,
           'field_labels_verified': {c: source_labels[c] for c in binary + values},
           'all_choice_flags_source_QC': {'all_flags_unselected_not_an_explicit_none': int((~answer_valid).sum()),
                                        'none_selected_together_with_other_choices': int(contradiction.sum()),
                                        'source_weighted_unanswered_mass': missing_weight / all_weight,
                                        'zero_means_not_selected_in_export_not_automatic_absence': True},
           'group_binary_encoding_verified': True,
           'groups': {'2': ['TV','washer_dryer','refrigerator','satellite_receiver'],
                      '5': ['air_conditioner','air_purifier','fresh_air_ventilation'],
                      '19': ['water_heater','water_purifier','hood','stove','dishwasher','sterilizer']},
           'binary_missing_counts': {c: int(eligible[c].isna().sum()) for c in binary},
           'pooled_diagnostic_joint_group_ownership_patterns': groups(eligible),
           'primary_same_visit2021_group_prior': groups(eligible[(eligible.visit_year == 2021) & answer_valid & ~contradiction]),
           'primary_same_visit2021_answered_households': int((aligned & answer_valid & ~contradiction).sum()),
           'visit_year_sensitivity': [],
           'group_value_quality': [], 'raw_identifiers_or_individual_money_exported': False,
           '2020_national_frequency_validated': False, 'individual_device_count_or_installation_identified': False,
           'per_household_control_right_identified': False, 'admission': 'provisional_modern_group_attribute_prior'}
    out['value_missing_or_mc_conflict_policy'] = 'never_impute_zero_or_infer_specific_appliance; preserve_missingness_and_mc_vs_value_conflict_as_source_uncertainty'
    out['source_group_missingness_identification_bounds_not_CI'] = {
        c: [float(eligible.loc[eligible[c] == 1, 'weight'].sum()) / all_weight,
            (float(eligible.loc[eligible[c] == 1, 'weight'].sum()) + missing_weight) / all_weight]
        for c in binary}
    for year, frame in eligible.groupby('visit_year'):
        out['visit_year_sensitivity'].append({'actual_visit_year': int(year), 'source_households': len(frame),
                                              'asset_reference_time': 'actual_visit_current' if year == 2021 else '2021-07-end_recall',
                                              'asset_member_reference_aligned': year == 2021,
                                              'joint_group_patterns': groups(frame)})
    for binary_column, value_column in zip(binary, values):
        selected = eligible[binary_column] == 1
        finite = eligible[value_column].map(lambda x: x is not None and np.isfinite(float(x)))
        out['group_value_quality'].append({'group': binary_column, 'selected_source_households': int(selected.sum()),
                                           'selected_with_finite_current_value': int((selected & finite).sum()),
                                           'selected_missing_current_value': int((selected & ~finite).sum()),
                                           'selected_with_negative_current_value': int((selected & finite & (eligible[value_column] < 0)).sum()),
                                           'not_selected_with_positive_current_value': int((~selected & finite & (eligible[value_column] > 0)).sum()),
                                           'current_value_is_purchase_price': False})
    out['input_lock'] = [{'file_basename': p.name, 'sha256': sha(p)} for p in
                         [next(rb.PACKAGE.glob(f'chfs2021_{kind}_pub_*.dta')) for kind in ['hh','ind','master_hh']]]
    questionnaire_dir = Path('/Users/fanmili/Downloads/2021/CHFS问卷-2021')
    out['questionnaire_locks'] = [{'file_basename': p.name, 'sha256': sha(p)} for p in
                                 sorted(questionnaire_dir.glob('*.pdf'))]
    path = OUT / 'MODERN_ASSET_GROUP_ADMISSION.json'
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
    print(json.dumps({'eligible_households': len(eligible), 'joint_patterns': len(out['pooled_diagnostic_joint_group_ownership_patterns']),
                      'source_visit_year_counts': {str(int(y)): len(g) for y, g in eligible.groupby('visit_year')},
                      'missing_groups': out['binary_missing_counts'], 'admission': out['admission']}, indent=2))


if __name__ == '__main__':
    main()
