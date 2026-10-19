import copy
from collections import Counter
from pathlib import Path
import tempfile
import unittest
from .common import digest, read, save, seal
from .generate import generate
from .model import request_issues
from .sampling import (catalogue, classify_result, command_hash, coverage_report,
                       describe, interactions, sample_catalogue, validate_plan)


def plan(strata=None):
    return {'schema': 'eb.ab_tail_plan.v1', 'seed': 20261019,
            'variants': [{'id': 'default', 'overrides': {}}],
            'coverage_axes': ['family', 'admission'],
            'strata': strata or [{'id': 'all', 'match': {}, 'households': 2, 'per_household': 1, 'required': True}]}


def unit(ident, household='h', **features):
    return {'sample_id': ident, 'household_id': household, 'case_id': 'case',
            'B_commands_sha256': 'B', 'features': {'family': 'ev', 'admission': 'normal', **features}}


class TailSamplingTests(unittest.TestCase):
    def setUp(self):
        self.c = read(Path(__file__).parent / 'examples/family.json')

    def catalogue(self, variants=None):
        result = generate(self.c)
        return catalogue({self.c['case_id']: self.c}, variants or {'default': {self.c['case_id']: result}})

    def test_semantic_dedup_coalesces_controls_but_preserves_gaps_and_values(self):
        A = {'tasks': [], 'operations': [], 'controls': [
            {'asset_id': 'x', 'kind': 'tank_setpoint', 'value_C': 55, 'start_min': 0, 'end_min': 60}]}
        B = copy.deepcopy(A)
        B['controls'] = [{**A['controls'][0], 'start_min': 30}, {**A['controls'][0], 'end_min': 30, '_ab_control_id': 'irrelevant'}]
        self.assertEqual(command_hash(A), command_hash(B))
        B['controls'][0]['start_min'] = 40
        self.assertNotEqual(command_hash(A), command_hash(B))
        B['controls'][0]['start_min'] = 30; B['controls'][0]['value_C'] = 54
        self.assertNotEqual(command_hash(A), command_hash(B))

    def test_past_sweep_preserves_multisets_and_grid_boundary_semantics(self):
        base = {'asset_id': 'x', 'kind': 'tank_setpoint', 'value_C': 55, 'start_min': 0, 'end_min': 90}
        c = {'decision_min': 60, 'A': {'tasks': [], 'operations': [], 'controls': [base]}}
        B = {**c['A'], 'controls': [{**base, 'end_min': 30}, {**base, 'start_min': 30, 'end_min': 60}, {**base, 'start_min': 60, 'value_C': 54}]}
        self.assertFalse(request_issues(c, B))
        B['controls'].append({**base, 'start_min': 10, 'end_min': 20})
        self.assertIn('REQUEST_REWRITES_PREDECISION_CONTROL', request_issues(c, B))

    def test_variants_dedup_before_quota_and_keep_all_aliases(self):
        result = generate(self.c)
        once = self.catalogue({'one': {self.c['case_id']: result}})
        twice = self.catalogue({'two': {self.c['case_id']: result}, 'one': {self.c['case_id']: result}})
        self.assertEqual([r['sample_id'] for r in once], [r['sample_id'] for r in twice])
        self.assertEqual(2 * sum(len(r['aliases']) for r in once), sum(len(r['aliases']) for r in twice))

    def test_full_joint_product_contains_more_than_optimal_representatives(self):
        result = generate(self.c)
        eligible = [r for r in result['candidates'] if not r['static_issues']]
        expected = {frozenset((a['id'], b['id'])) for a in eligible for b in eligible
                    if a['family'] != b['family'] and a['asset_id'] != b['asset_id']}
        self.assertEqual(expected, {frozenset(r['candidate_ids']) for r in result['joint_candidates']})
        self.assertGreater(len(expected), len({r['family'] for r in eligible}))

    def test_downstream_outcomes_forbidden_even_on_unselected_candidates(self):
        result = generate(self.c)
        result['candidates'][0]['actual_outcomes'] = {'successful': True}
        with self.assertRaisesRegex(ValueError, 'DOWNSTREAM_OUTCOMES_FORBIDDEN'):
            self.catalogue({'default': {self.c['case_id']: result}})

    def test_frozen_control_never_gets_fresh_candidate(self):
        self.c['assignment'] = {'mode': 'identical_control'}
        rows = self.catalogue()
        self.assertEqual(1, len(rows))
        self.assertEqual('control', rows[0]['features']['scope'])

    def test_preserved_failure_never_regenerated_or_called_normal(self):
        self.c['assignment'] = {'mode': 'preserved_failure_replay'}
        self.c['retained_B_request'] = copy.deepcopy(self.c['A'])
        rows = self.catalogue()
        self.assertEqual(1, len(rows))
        self.assertEqual('static_diagnostic', rows[0]['features']['admission'])

    def test_static_conflicts_not_admitted_as_ordinary_samples(self):
        rows = self.catalogue()
        rejected = [r for r in rows if r['static_issues']]
        self.assertTrue(rejected)
        self.assertTrue(all(r['features']['admission'] != 'normal' for r in rejected))

    def test_stress_label_cannot_waive_authority_or_invent_energy_shortfall(self):
        child = next(r for r in generate(self.c)['candidates'] if r['family'] == 'ev')
        B = copy.deepcopy(self.c['A'])
        control = next(c for c in B['controls'] if c['kind'] == 'ev_charge_window')
        control['start_min'] += 10
        child['factors']['prediction_energy_shortfall_kWh'] = 0
        f, _ = describe(self.c, B, [child], ['CHARGE_EXCEEDS_ORIGINAL_CONNECTION'])
        self.assertEqual('static_diagnostic', f['admission'])
        child['factors']['prediction_energy_shortfall_kWh'] = 1
        self.c['authority']['assets'][child['asset_id']]['target_control_authorized'] = False
        f, issues = describe(self.c, B, [child], ['CHARGE_EXCEEDS_ORIGINAL_CONNECTION'])
        self.assertEqual('static_diagnostic', f['admission'])
        self.assertIn('TARGET_CONTROL_NOT_AUTHORIZED', issues)

    def test_duplicate_catalogue_ids_cannot_inflate_quota(self):
        with self.assertRaisesRegex(ValueError, 'DUPLICATE_CATALOGUE_EXECUTION'):
            sample_catalogue([unit('one'), unit('one')], plan())

    def test_two_stage_probability_and_permutation_invariance(self):
        rows = [unit(h + str(i), h) for h in 'abc' for i in range(2)]
        one = sample_catalogue(rows, plan())
        two = sample_catalogue(list(reversed(rows)), plan())
        self.assertEqual(one, two)
        self.assertEqual(2, len({r['household_id'] for r in one['records']}))
        for r in one['records']:
            self.assertAlmostEqual(1 / 3, r['nominal_frame_inclusion_probability'])
            self.assertIsNone(r['population_weight'])

    def test_priority_does_not_always_select_same_request_or_only_best(self):
        rows = [unit(str(i)) for i in range(6)]
        selected = set()
        for seed in range(128):
            p = plan(); p['seed'] = seed; p['strata'][0]['households'] = 1
            selected.update(r['sample_id'] for r in sample_catalogue(rows, p)['records'])
        self.assertEqual({r['sample_id'] for r in rows}, selected)

    def test_overlapping_strata_exclusive_and_deficit_is_failure(self):
        p = plan(); p['strata'] *= 2; p['strata'][1] = {**p['strata'][0], 'id': 'later'}
        result = sample_catalogue([unit('one')], p)
        self.assertEqual(1, len(result['records']))
        self.assertFalse(result['selection_coverage_passed'])
        self.assertEqual(0, result['coverage'][1]['assigned_unique'])
        self.assertEqual(1, result['coverage'][1]['matched_unique'])

    def test_missing_opportunity_not_automatically_not_applicable_pass(self):
        result = sample_catalogue([], plan())
        self.assertFalse(result['selection_coverage_passed'])
        self.assertEqual(2, result['coverage'][0]['deficit'])

    def test_plan_rejects_outcome_strata_unknown_keys_and_boolean_quotas(self):
        for mutation in ('outcome', 'quota', 'field'):
            p = plan()
            if mutation == 'outcome': p['strata'][0]['match']['actual_success'] = ['true']
            if mutation == 'quota': p['strata'][0]['per_household'] = True
            if mutation == 'field': p['select_best'] = True
            with self.assertRaises(ValueError): validate_plan(p)

    def test_finite_frame_pairwise_coverage_reports_uncovered_cells(self):
        rows = [unit('one'), unit('two', family='ac')]
        data = interactions(rows, rows[:1], ['family', 'admission'])
        self.assertTrue(any(r['selected_unique'] == 0 for r in data))
        self.assertTrue(all(r['selected_unique'] <= r['available_unique'] for r in data))

    def report(self, failures=None):
        return {'case_id': 'case', 'readback_status': 'complete', 'A_reference_comparison': {'passed': True},
                'engine_status': {'A': 'completed', 'B': 'completed'}, 'failed_checks': failures or [],
                'actual_results_used_for_reselection': False, 'human_acceptance': None}

    def test_observed_service_failure_is_retained_without_success_filter(self):
        r = classify_result(unit('one'), self.report(['B_hot_water_service']))
        self.assertTrue(r['coverage_credit'])
        self.assertEqual('observed_service_failure_retained', r['status'])

    def test_only_predeclared_service_failure_can_credit_EV_stress(self):
        sample = unit('one', admission='declared_EV_shortfall_stress')
        self.assertTrue(classify_result(sample, self.report(['B_EV_departure_target']))['coverage_credit'])
        for failures in ([], ['B_EV_balance'], ['B_EV_departure_target', 'B_EV_balance']):
            self.assertFalse(classify_result(sample, self.report(failures))['coverage_credit'])

    def test_engine_failure_missing_readback_wrong_A_and_model_error_quarantine(self):
        for key, value in [('engine_status', {'A': 'completed', 'B': 'failed'}), ('readback_status', 'incomplete'),
                           ('A_reference_comparison', {'passed': False}), ('failed_checks', ['B_meter_closure'])]:
            r = self.report(); r[key] = value
            self.assertFalse(classify_result(unit('one'), r)['coverage_credit'])

    def test_missing_audit_cannot_be_assumed_successful(self):
        r = self.report(); del r['failed_checks']
        self.assertFalse(classify_result(unit('one'), r)['coverage_credit'])

    def test_postcheck_missing_duplicate_wrong_commands_and_static_diagnostic(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            p = plan(); p['strata'][0]['households'] = 1
            selection = sample_catalogue([unit('one')], p); selection['interaction_coverage'] = []
            save(root / 'SELECTION.json', selection); seal(root, {})
            self.assertFalse(coverage_report(root, [])['passed'])
            observation = {'sample_id': 'one', 'exported_B_commands_sha256': 'B', 'report': self.report(['B_hot_water_service'])}
            self.assertTrue(coverage_report(root, [observation])['passed'])
            with self.assertRaisesRegex(ValueError, 'DUPLICATE_EXECUTION'):
                coverage_report(root, [observation, observation])
            observation['exported_B_commands_sha256'] = 'wrong'
            with self.assertRaisesRegex(ValueError, 'SELECTED_B_EXECUTION_MISMATCH'):
                coverage_report(root, [observation])
            selection['records'][0]['features']['admission'] = 'static_diagnostic'
            save(root / 'SELECTION.json', selection); seal(root, {})
            self.assertTrue(coverage_report(root, [])['passed'])
            with self.assertRaisesRegex(ValueError, 'MUST_NOT_EXECUTE'):
                coverage_report(root, [observation])


if __name__ == '__main__':
    unittest.main()
