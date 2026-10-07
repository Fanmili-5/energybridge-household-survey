#!/usr/bin/env python3
"""Independent artifact/source/SQL verification, no generation imports."""
import collections
import hashlib
import json
import sqlite3
from pathlib import Path
import xlrd

P = Path(__file__).resolve().parent.parent
H = P.parent


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    checks = 0
    def check(ok, label):
        nonlocal checks
        if not ok:
            raise AssertionError(label)
        checks += 1
    sealed = H / 'construction_chain_20261003'
    manifest = json.loads((sealed / 'PACKAGE_MANIFEST.json').read_text())['files']
    for rel, digest in manifest.items():
        check(sha(sealed / rel) == digest, 'sealed_chain_changed:' + rel)
    authority = json.loads((H / 'evidence_contract_20261001/CITY_AUTHORITY_CONSTRAINTS_V2.json').read_text())
    ref = json.loads((P / 'facilities1000_v2/OFFICIAL_FACILITIES_REFERENCE.json').read_text())['references']
    for name in ['B0903a', 'B0904a', 'B0906a']:
        t = authority['tables'][name]
        raw = H / 'evidence_contract_20261001' / t['file']
        check(sha(raw) == t['sha256'], 'census_XLS_sha:' + name)
        sheet = xlrd.open_workbook(raw).sheet_by_index(0)
        for prov, meta in t['rows'].items():
            rr = sheet.row_values(meta['excel_row_1based'] - 1)
            check(''.join(rr[0].split()) == prov, 'census_row_name')
            check(rr[1:] == meta['counts_or_aggregates'], 'census_row_values')
    for prov, row in ref.items():
        f = authority['tables']['B0903a']['rows'][prov]['counts_or_aggregates']
        b = authority['tables']['B0906a']['rows'][prov]['counts_or_aggregates']
        totals = row['kitchen_toilet_state_counts']
        check(sum(totals.values()) == f[0], 'state_total')
        check(totals['both_kitchen_toilet'] == b[0], 'observed_both_reference')
        check(totals['both_kitchen_toilet'] + totals['kitchen_only'] == f[10] + f[11], 'kitchen_marginal')
        check(totals['both_kitchen_toilet'] + totals['toilet_only'] == sum(f[13:17]), 'toilet_marginal')
        for cell in row['source_by_facility_state']:
            check(abs(sum(cell['maximum_entropy_cell_counts']) - cell['source_count']) < 1e-6, 'completion_source_sum')
            for k in ['kitchen_presence_probability_identification_bounds', 'toilet_presence_probability_identification_bounds']:
                z = cell[k]
                check(z is None or 0 <= z[0] <= z[1] <= 1, 'identification_bounds')
    candidate = P / 'facilities1000_v2/FAMILY_HOUSING_FACILITIES1000.json'
    data = json.loads(candidate.read_text())
    profiles = data['profiles']
    allocation = json.loads((H / 'evidence_contract_20261001/POPULATION_ALLOCATION_CANDIDATE_V2.json').read_text())['slots']
    check(len(profiles) == 1000 and len({x['slot_id'] for x in profiles}) == 1000, '1000_distinct_slots')
    check(collections.Counter((x['province'], x['size_category'], x['generation_category']) for x in profiles)
          == collections.Counter((x['province'], x['size_category'], x['generation_category']) for x in allocation), 'population_allocation')
    ordinary = []
    for r in profiles:
        family, housing = r['family'], r['housing']
        check(family['resident_count'] == len(family['members']) == len(set(family['resident_member_ids'])), 'resident_roster')
        check(len(set(x['generation_level'] for x in family['members'])) == family['generation_count_design'], 'occupied_generation_count')
        check(not r['complete_actor_card'] and r['human_answers'] is None, 'no_false_actor_readiness')
        if housing['H5_is_ordinary_model_assigned']:
            ordinary.append(r)
            check(housing['area_policy']['theta_per_m2'] == 0, 'no_mean_tilt')
            check(any(b['lower_m2'] - .00501 <= housing['H6_building_area_m2'] <= b['upper_m2'] + .00501 for b in housing['H6_predictive_support_bins']), 'whole_H6_in_reference_support')
            check(housing['H6_predictive_support_bins'] == housing['area_reference']['predictive_area_bins'], 'shared_ratio_not_applied_to_H6')
            fac = housing['facilities']
            check(fac['operator_permission'] is None and fac['calibrated_electric_power'] is None, 'facilities_do_not_imply_device_control')
        else:
            check(housing['H6_building_area_m2'] is None and housing['facilities']['status'].startswith('unknown'), 'nonordinary_scope_preserved')
    audit = json.loads((P / 'facilities1000_v2/ASSIGNMENT_AUDIT.json').read_text())
    states = dict(collections.Counter(r['housing']['facilities']['kitchen_toilet_state'] for r in ordinary))
    check(states == audit['national_state_integer_target'], 'joint_integer_facility_margins')
    sql_checks = []
    for name, duration in [('aligned_15min', 15), ('unaligned_20min', 20), ('unaligned_1min', 1), ('day_start_1min', 1), ('day_end_1min', 1)]:
        folder = P / 'time_grid_verification' / name / 'physical'
        db = sqlite3.connect(folder / 'run/eplusout.sql')
        rows = db.execute("""SELECT r.Value, d.Units, t.Interval FROM ReportData r
            JOIN ReportDataDictionary d USING(ReportDataDictionaryIndex)
            JOIN Time t USING(TimeIndex) JOIN EnvironmentPeriods e USING(EnvironmentPeriodIndex)
            WHERE t.WarmupFlag=0 AND e.EnvironmentType=3 AND d.Name='Electricity:Facility'
            AND d.ReportingFrequency='Zone Timestep'""").fetchall()
        db.close()
        check(len(rows) == 96 and all(unit == 'J' and dt == 15 for _, unit, dt in rows), 'SQL_meter_domain')
        actual = sum(x[0] for x in rows) / 3.6e6
        check(abs(actual - duration / 60) < 1e-7, 'SQL_analytic_energy')
        sql_checks.append({'case': name, 'actual_kWh': actual, 'analytic_expected_kWh': duration / 60})
    regression = json.loads((P / 'component_regression/CHAIN_VERIFICATION.json').read_text())
    check(regression['pass'], 'existing_component_regression')
    holdout = json.loads((P / 'production_area_holdout/RESULT.json').read_text())
    check(sum(x['test_households'] for x in holdout['folds']) == holdout['test_source_households'] == 2628, 'whole_household_holdout_count')
    check(holdout['outcomes_outside_domain_retained'] == 1, 'unfavorable_test_outcome_retained')
    check(not data['collection_release'] and not data['training_release'], 'release_boundary')
    result = {'schema': 'eb.production_foundation_independent_verification.v1', 'pass': True, 'assertions': checks,
              'sealed_chain_files_unchanged': len(manifest), 'candidate_sha256': sha(candidate),
              'profiles': len(profiles), 'members': sum(r['family']['resident_count'] for r in profiles),
              'ordinary': len(ordinary), 'nonordinary': len(profiles) - len(ordinary),
              'facility_state_counts': states, 'independent_SQL_checks': sql_checks,
              'area_reference_maximum_single_source_share': max(r['housing']['area_policy']['posterior_maximum_source_weight'] for r in ordinary),
              'area_reference_minimum_Kish_ESS': min(r['housing']['area_policy']['posterior_source_ESS'] for r in ordinary),
              'area_holdout_metrics': holdout['weighted_metrics'],
              'not_full_joint_or_service_or_human_validity': True, 'actor_ready': 0,
              'formal_statistical_generator_approved': False, 'collection_release': False, 'training_release': False}
    (P / 'VERIFICATION.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
