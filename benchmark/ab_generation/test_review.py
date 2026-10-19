import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from .common import read, save, seal, sha
from .evaluate import compare_traces, summarize
from .export import attach_legacy_requirements
from .generate import binding, generate
from .model import apply, request_issues
from .outcomes import bill, consequences


class StrategyReviewTests(unittest.TestCase):
    def setUp(self):
        self.c = read(Path(__file__).parent / 'examples/family.json')

    def result(self):
        self.c['reference']['binding'] = binding(self.c)
        return generate(self.c)

    def test_information_privilege_must_be_explicit_and_not_called_real_time(self):
        del self.c['reference']['information_set']
        with self.assertRaisesRegex(ValueError, 'INFORMATION_SET_REQUIRED'):
            self.result()
        self.setUp()
        self.c['reference']['information_set']['mode'] = 'real_time_forecast'
        with self.assertRaisesRegex(ValueError, 'UNSUPPORTED_INFORMATION_MODE'):
            self.result()

    def test_no_B_outcome_answers_or_integer_boolean_in_information_claims(self):
        for key, value in [('final_B_outcomes_available', True), ('human_answers_available', True),
                           ('real_time_deployment_claim', True), ('future_A_available', 1)]:
            self.setUp()
            self.c['reference']['information_set'][key] = value
            with self.assertRaisesRegex(ValueError, 'INFORMATION_SET_CONTRADICTION'):
                self.result()

    def test_reference_tail_cannot_be_hidden_by_primary_24h_disclosure(self):
        self.c['reference']['ev_charging_steps'].append(
            {'need_id': 'future-connection', 'start_min': 2000, 'end_min': 2010, 'grid_kWh': 1})
        with self.assertRaisesRegex(ValueError, 'A_INFORMATION_COVERAGE_UNDERSTATED'):
            self.result()
        self.c['reference']['information_set']['A_reference_span_min'][1] = 2010
        self.assertTrue(self.result()['information_set']['future_A_available'])

    def test_information_condition_changes_no_command_and_infers_no_consent(self):
        first = self.result()
        self.c['reference']['information_set']['mode'] = 'offline_full_A_counterfactual'
        second = self.result()
        self.assertEqual(first['candidates'], second['candidates'])
        self.assertEqual(first['selections'], second['selections'])
        self.assertIsNone(second['proposal_purpose']['human_satisfaction'])
        self.assertFalse(second['proposal_purpose']['original_EnergyBridge_controller_output'])

    def test_public_parameter_and_source_basis_is_closed(self):
        from .audit_design import audit
        self.assertTrue(audit()['passed'])

    def test_new_life_A_admission_requires_bound_passing_service_audit(self):
        from .life_physics import baseline_admission
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); compiled, runs, audits = (root / name for name in ('compiled', 'runs', 'audit'))
            for path in (compiled, runs, audits):
                path.mkdir()
            seal(compiled, {'records': [{'id': 'case'}]})
            seal(runs, {'compiled_manifest_sha256': sha(compiled / 'MANIFEST.json')})
            checks = {k: True for k in ('A_complete_finite_timeline', 'A_service_execution', 'A_service_completeness',
                                        'A_hot_water_service', 'A_EV_balance', 'A_EV_departure_target')}
            checks['A_service_execution'] = False
            metadata = {'schema': 'eb.housing_physics.audit.v1', 'records': [{'id': 'case', 'checks': checks}], 'passed': False,
                        'compiled_manifest_sha256': sha(compiled / 'MANIFEST.json'),
                        'runs_manifest_sha256': sha(runs / 'MANIFEST.json')}
            seal(audits, metadata)
            with self.assertRaisesRegex(ValueError, 'BASELINE_AUDIT_NOT_PASSED'):
                baseline_admission(compiled, runs, audits)
            metadata['passed'] = True; metadata['records'][0]['checks']['A_service_execution'] = True
            seal(audits, metadata)
            self.assertEqual('normal_A_service_and_physics_audit_passed', baseline_admission(compiled, runs, audits)['status'])
            metadata['runs_manifest_sha256'] = '0' * 64; seal(audits, metadata)
            with self.assertRaisesRegex(ValueError, 'BASELINE_AUDIT_BINDING_MISMATCH'):
                baseline_admission(compiled, runs, audits)

    def test_timer_and_preload_limits_survive_into_B(self):
        need = next(n for n in self.c['needs'] if n['kind'] == 'washer')
        start = min(t['start_min'] for t in self.c['A']['tasks'] if t['need_id'] == need['need_id'])
        load = next(o for o in self.c['A']['operations'] if o['need_id'] == need['need_id'] and o['kind'] == 'load')
        load['start_min'], load['end_min'] = start - 10, start
        need.update(timer_allowed=False, maximum_preload_wait_min=0)
        rows = [r for r in self.result()['candidates'] if r['family'] == 'washer' and r['factors']['handling_mode'] == 'timer_only' and r['factors']['program_shift_min'] > 0]
        self.assertTrue(rows)
        self.assertTrue(all({'TIMER_NOT_AVAILABLE', 'PRELOAD_WAIT_EXCEEDED'} <= set(r['static_issues']) for r in rows))

    def test_machine_windows_are_constraints_for_shifted_programs(self):
        n = next(n for n in self.c['needs'] if n['kind'] == 'washer')
        tasks = [t for t in self.c['A']['tasks'] if t['need_id'].startswith(n['need_id'])]
        n['machine_windows_min'] = [[min(t['start_min'] for t in tasks), max(t['end_min'] for t in tasks)]]
        rows = [r for r in self.result()['candidates'] if r['family'] == 'washer']
        self.assertTrue(all('MACHINE_WINDOW_VIOLATED' in r['static_issues'] for r in rows))

    def test_context_household_operations_are_immutable(self):
        self.c['authority']['immutable_operator_ids'] = list(self.c['operator_windows'])
        rows = [r for r in self.result()['candidates'] if r['family'] in ('washer', 'dishwasher') and r['factors']['handling_mode'] == 'shift_chain']
        self.assertTrue(rows)
        self.assertTrue(all('CONTEXT_OPERATOR_IMMUTABLE' in r['static_issues'] for r in rows))

    def test_asset_control_authority_is_required(self):
        self.c['authority']['assets']['ac']['target_control_authorized'] = False
        r = self.result()
        self.assertFalse([c for c in r['candidates'] if c['asset_id'] == 'ac'])
        self.assertIn({'asset_id': 'ac', 'reason': 'TARGET_CONTROL_NOT_AUTHORIZED'}, r['unavailable'])

    def test_thermal_axis_comes_from_native_energy_not_nearest_setpoint(self):
        for r in self.c['reference']['thermal']['ac']:
            r['temperature_C'] = 20.1
            r['axis_electric_kWh'] = {'heating': 0, 'cooling': .1}
        rows = [r for r in self.result()['candidates'] if r['family'] == 'ac' and r['factors']['direction'] == 'aligned']
        self.assertTrue(rows)
        self.assertEqual({'cooling'}, {r['factors']['thermal_axis'] for r in rows})

    def test_unknown_axis_cannot_be_called_an_actual_downward_opportunity(self):
        for r in self.c['reference']['thermal']['ac']:
            r.pop('axis_electric_kWh')
        result = self.result()
        self.assertFalse([r for r in result['candidates'] if r['family'] == 'ac' and r['factors']['direction'] == 'aligned'])
        self.assertTrue(any(r['reason'] == 'CURRENT_A_MODE_UNAVAILABLE' for r in result['unavailable']))

    def test_ongoing_EV_charge_can_pause_without_rewriting_the_past(self):
        control = next(c for c in self.c['A']['controls'] if c['kind'] == 'ev_charge_window')
        control.update(start_min=450, end_min=1440)
        self.c['reference']['ev_charging_steps'] = [{'need_id': control['need_id'], 'start_min': t, 'end_min': t + 10, 'grid_kWh': 1} for t in range(450, 540, 10)]
        self.c['reference']['information_set']['A_reference_span_min'][0] = 450
        rows = [r for r in self.result()['candidates'] if r['family'] == 'ev']
        self.assertTrue(rows)
        for r in rows:
            b = apply(self.c['A'], r['patches'])
            self.assertFalse(request_issues(self.c, b))
            self.assertTrue(any(c['start_min'] == 450 and c['end_min'] == 480 for c in b['controls'] if c['kind'] == 'ev_charge_window'))

    def test_EV_prediction_respects_existing_gaps_and_energy(self):
        control = next(c for c in self.c['A']['controls'] if c['kind'] == 'ev_charge_window')
        self.c['A']['controls'].remove(control)
        self.c['A']['controls'] += [{**control, 'start_min': 1000, 'end_min': 1040}, {**control, 'start_min': 1100, 'end_min': 1440}]
        self.c['reference']['ev_charging_steps'] = [{'need_id': control['need_id'], 'start_min': t, 'end_min': t + 10, 'grid_kWh': 1} for t in range(1000, 1030, 10)]
        rows = [r for r in self.result()['candidates'] if r['family'] == 'ev']
        self.assertEqual(3, len(rows))
        self.assertTrue(all(r['factors']['remaining_A_grid_kWh'] == 3 for r in rows))
        self.assertTrue(all(r['factors']['prediction_energy_shortfall_kWh'] < 1e-8 for r in rows))
        for r in rows:
            for step in r['prediction']['profiles']['B']:
                self.assertTrue((1000 <= step['start_min'] < 1040) or 1100 <= step['start_min'] < 1440)

    def test_duplicate_reference_times_are_ambiguous(self):
        self.c['reference']['thermal']['ac'].append(copy.deepcopy(self.c['reference']['thermal']['ac'][0]))
        with self.assertRaisesRegex(ValueError, 'DUPLICATE_REFERENCE_TIME'):
            self.result()

    def test_tariff_provenance_is_not_a_physical_dependency(self):
        old = binding(self.c)
        self.c['tariff_provenance'] = {'currency': 'declared_test_currency'}
        self.assertEqual(old, binding(self.c))

    def test_no_events_means_no_comparable_VPP_opportunity(self):
        self.c['events'] = []
        self.assertEqual('no_comparable_opportunity', self.result()['selections']['known_profile_vpp']['status'])

    def test_float_noise_does_not_override_disruption_tiebreak(self):
        rows = [copy.deepcopy(r) for r in self.result()['candidates'] if r['family'] == 'ev']
        short = next(r for r in rows if r['factors']['ev_delay_min'] == 30)
        long = next(r for r in rows if r['factors']['ev_delay_min'] == 120)
        short['prediction'].update(delta_cost=0, aligned_event_kWh=1)
        long['prediction'].update(delta_cost=-1e-15, aligned_event_kWh=1 + 1e-15)
        with patch('benchmark.ab_generation.generate.program_candidates', return_value=([], [])), \
             patch('benchmark.ab_generation.generate.thermal_candidates', return_value=([], [])), \
             patch('benchmark.ab_generation.generate.ev_candidates', return_value=([short, long], [])):
            r = self.result()
        for policy in ('known_profile_cost', 'known_profile_vpp'):
            self.assertEqual([short['id']], r['selections'][policy]['candidate_ids'])

    def test_duplicate_events_are_rejected(self):
        self.c['events'] *= 2
        with self.assertRaisesRegex(ValueError, 'DUPLICATE_EVENT_ID'):
            self.result()

    def test_old_context_without_resource_contract_requires_reimport(self):
        self.c.pop('authority')
        with self.assertRaisesRegex(ValueError, 'RESOURCE_CONTRACT_REQUIRED'):
            self.result()

    def test_program_capabilities_cannot_be_silently_assumed(self):
        next(n for n in self.c['needs'] if n['kind'] == 'washer').pop('timer_allowed')
        with self.assertRaisesRegex(ValueError, 'PROGRAM_CAPABILITY_CONTRACT_REQUIRED'):
            self.result()

    def test_legacy_requirements_include_the_full_original_followup(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'annual.json'
            annual = {'household_id': 'h', 'anchor': '2025-01-01', 'end_exclusive': '2025-02-01',
                      'tasks': [], 'operations': [], 'days': {
                          '2025-01-01': {'needs': [{'need_id': 'first', 'kind': 'washer', 'release_min': 100, 'deadline_min': 1000}]},
                          '2025-01-09': {'needs': [{'need_id': 'followup', 'kind': 'dishwasher', 'release_min': 12000, 'deadline_min': 13000}]}}}
            save(path, annual)
            pack = {k: annual[k] for k in ('household_id', 'anchor', 'end_exclusive', 'tasks', 'operations')}
            pack['source_annual_A_sha256'] = sha(path)
            result = attach_legacy_requirements(pack, path)
            self.assertEqual(['first', 'followup'], [n['need_id'] for n in result['service_needs']])
            self.assertNotIn('service_needs', pack)
            with self.assertRaisesRegex(ValueError, 'FULL_SERVICE_REQUIREMENTS_REQUIRED'):
                attach_legacy_requirements(pack, None)
            save(path, {**annual, 'household_id': 'changed'})
            with self.assertRaisesRegex(ValueError, 'ANNUAL_A_SOURCE_CHANGED'):
                attach_legacy_requirements(pack, path)

    def test_original_tasks_and_actors_cannot_be_replaced(self):
        b = copy.deepcopy(self.c['A']); b['tasks'].pop()
        self.assertIn('REQUEST_CHANGES_ORIGINAL_ROW_SET', request_issues(self.c, b))
        b = copy.deepcopy(self.c['A']); b['operations'][0]['operator_id'] = 'new_helper'
        self.assertIn('REQUEST_CHANGES_ORIGINAL_RESOURCE_OR_DURATION', request_issues(self.c, b))

    def test_home_departure_target_does_not_apply_to_away_return_leg(self):
        from benchmark.housing_simulation.kernel.execution import departure_target_times
        self.assertEqual({480, 1920}, departure_target_times({'night': (-360, 420), 'next': (1080, 1860)}, [480, 1070, 1920, 2510]))

    def test_missing_tariff_coverage_is_unknown_not_free(self):
        self.assertIsNone(bill({0: 1, 10: 1}, [{'start_min': 0, 'end_min': 10, 'price_per_kWh': .5}], 0, 20))
        self.assertEqual(1, bill({0: 1, 10: 1}, [{'start_min': 0, 'end_min': 20, 'price_per_kWh': .5}], 0, 20))

    def test_grid_response_cost_and_independent_comfort_are_not_interchangeable(self):
        traces = {}
        for side, facility, program, temperature in [('A', 1.5, 1, 25), ('B', 2, .5, 28)]:
            traces[side] = {name: {'unit': unit, 'values': [[0, value], [10, value]]} for name, unit, value in (
                ('Electricity:Facility|', 'J', facility * 3600000),
                ('Electric Equipment Electricity Energy|WASH', 'J', program * 3600000),
                ('Zone Mean Air Temperature|ROOM', 'C', temperature))}
        meta = {'run_interval_min': [0, 20], 'HVAC_equipment_mapping': {}, 'equipment_meter_mapping': {'WASH': {}},
                'tank_name': None, 'EV': {'installed': False}, 'world_assembly': {'room_ids': ['ROOM']},
                'execution': {'tasks': [], 'batches': []}}
        needs = [{'need_id': 'known', 'kind': 'comfort', 'room_id': 'ROOM', 'release_min': 0, 'deadline_min': 20,
                  'temperature_band_C': [24, 26], 'origin': 'declared_unit_scenario'},
                 {'need_id': 'unknown', 'kind': 'comfort', 'room_id': 'ROOM', 'release_min': 0, 'deadline_min': 20,
                  'temperature_band_C': None, 'origin': 'unknown'}]
        pair = {'decision_min': 0, 'needs_A': needs, 'A': {'operations': []}, 'B': {'operations': []},
                'VPP_events': [{'event_id': 'test', 'start_min': 0, 'end_min': 20, 'direction': 'down', 'target_kw': 1}]}
        context = {'horizon_min': [0, 20], 'tariff': [{'start_min': 0, 'end_min': 20, 'price_per_kWh': 1}]}
        result = consequences(pair, {'A': meta, 'B': meta}, traces, {'details': {}, 'checks': {}}, context)
        event = result['events'][0]
        self.assertFalse(event['target_met'])
        self.assertGreater(event['measured_scopes']['modeled_controlled_equipment']['aligned_response_kw'], 0)
        self.assertEqual(1, result['simulated_facility_cost']['intervals']['primary_24h']['B_minus_A'])
        known, unknown = result['independent_comfort']['records']
        self.assertEqual(20, known['B']['outside_declared_band_min'])
        self.assertIsNone(unknown['B']['outside_declared_band_min'])

    def test_reference_comparison_requires_full_timelines(self):
        a = {'T|room': {'unit': 'C', 'values': [[0, 25], [10, 26]]}}
        b = {'T|room': {'unit': 'C', 'values': [[0, 25]]}}
        self.assertFalse(compare_traces(a, b)['passed'])
        self.assertTrue(compare_traces(a, a)['passed'])

    def report_fixture(self, root, corrupt_audit=False):
        job = root / 'job.json'; compiled, runs, audit = (root / n for n in ('compiled', 'runs', 'audit'))
        pair = {'case_id': 'failed-case', 'AB_generation': {'policy': 'known_profile_vpp', 'status': 'candidate_selected'}}
        save(root / 'pair.json', pair)
        save(job, {'resource_root': '.', 'pairs': [{'id': 'case', 'pair': {'path': 'pair.json', 'sha256': sha(root / 'pair.json')}}]})
        seal(compiled, {'input_sha256': sha(job), 'records': [{'id': 'case', 'status': 'compiled'}]})
        for side in ('A', 'B'):
            save(runs / 'case' / side / 'RESULT.json', {'status': 'engine_failed'})
        seal(runs, {'compiled_manifest_sha256': sha(compiled / 'MANIFEST.json')})
        seal(audit, {'compiled_manifest_sha256': '0' * 64 if corrupt_audit else sha(compiled / 'MANIFEST.json'),
                     'runs_manifest_sha256': sha(runs / 'MANIFEST.json'), 'records': []})
        return job, compiled, runs, audit

    def test_report_cannot_mix_self_consistent_but_unrelated_audits(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with self.assertRaisesRegex(ValueError, 'REPORT_AUDIT_BINDING_MISMATCH'):
                summarize(*self.report_fixture(root, True), root / 'report')

    def test_engine_failure_is_retained_without_zero_outcomes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); summarize(*self.report_fixture(root), root / 'report')
            row = read(root / 'report/REPORT.json')['records'][0]
            self.assertEqual('incomplete', row['readback_status'])
            self.assertNotIn('events', row)
            self.assertIsNone(row['human_acceptance'])


if __name__ == '__main__':
    unittest.main()
