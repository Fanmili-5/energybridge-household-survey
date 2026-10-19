import copy
import unittest
from pathlib import Path
from .common import read
from .generate import DEFAULT_RULES, binding, generate, thermal_candidates
from .life import generate_household
from .opportunity import profile_evidence, thermal_evidence, joint_evidence
from .sampling import catalogue, response_coverage, validate_plan
from .effects import targeted_response

HERE = Path(__file__).parent


class OpportunityTests(unittest.TestCase):
    def setUp(self):
        self.c = read(HERE / 'examples/family.json')
        self.tank = next(d for d in self.c['devices'] if 'water_heater' in d['types'])
        self.tank['parameters'].update(deadband_C=2, number_of_nodes=6)
        for c in self.c['A']['controls']:
            if c['asset_id'] == self.tank['asset_id']:
                c['value_C'] = 55
        for r in self.c['reference']['thermal'][self.tank['asset_id']]:
            r.update(temperature_C=55, electric_kWh=0, headroom_kWh=.4, node_temperatures_C=[55] * 6)
        self.c['reference']['binding'] = binding(self.c)

    def tank_candidates(self):
        return thermal_candidates(self.c, self.tank, DEFAULT_RULES)[0]

    def test_rating_headroom_alone_stays_exploratory_and_is_retained(self):
        rows = [r for r in self.tank_candidates() if r['factors']['direction'] == 'opposing']
        self.assertTrue(rows)
        self.assertTrue(all(r['opportunity']['status'] == 'exploratory' for r in rows))
        self.assertTrue(all(not r['static_issues'] for r in rows))

    def test_cold_all_node_bound_supports_new_heat_call(self):
        for r in self.c['reference']['thermal'][self.tank['asset_id']]:
            r['node_temperatures_C'] = [52] * 6
        rows = [r for r in self.tank_candidates() if r['factors']['direction'] == 'opposing']
        self.assertTrue(all(r['opportunity']['status'] == 'supported' for r in rows))
        self.assertTrue(all(r['opportunity']['witness_minutes'] for r in rows))

    def test_average_tank_temperature_is_not_a_control_sensor(self):
        for r in self.c['reference']['thermal'][self.tank['asset_id']]:
            r.update(temperature_C=52, node_temperatures_C=[58, 52, 52, 52, 52, 52])
        self.assertTrue(all(r['opportunity']['status'] == 'exploratory' for r in self.tank_candidates()))

    def test_missing_control_nodes_does_not_invent_support(self):
        for r in self.c['reference']['thermal'][self.tank['asset_id']]:
            r.pop('node_temperatures_C')
        self.assertTrue(all(r['opportunity']['status'] == 'exploratory' for r in self.tank_candidates()))

    def test_later_supported_window_added_without_deleting_early_uncertain_window(self):
        available = {r['minute'] for r in self.c['reference']['thermal'][self.tank['asset_id']]}
        event = next(e for e in self.c['events'] if e['start_min'] in available)
        start = event['start_min']
        for r in self.c['reference']['thermal'][self.tank['asset_id']]:
            if r['minute'] >= start + 20:
                r['node_temperatures_C'] = [52] * 6
        rows = [r for r in self.tank_candidates() if r['factors']['direction'] == 'opposing'
                and r['factors']['event_id'] == event['event_id']
                and r['factors']['setpoint_delta_C'] == .5 and r['factors']['requested_duration_min'] == 20]
        self.assertEqual({'supported', 'exploratory'}, {r['opportunity']['status'] for r in rows})

    def test_incomplete_or_nonfinite_node_vector_is_rejected(self):
        row = self.c['reference']['thermal'][self.tank['asset_id']][0]
        row['node_temperatures_C'] = [55]
        with self.assertRaisesRegex(ValueError, 'INVALID_TANK_NODE_REFERENCE|Out of range float'):
            generate(self.c)
        row['node_temperatures_C'] = [55] * 5 + [float('nan')]
        with self.assertRaisesRegex(ValueError, 'INVALID_TANK_NODE_REFERENCE|Out of range float'):
            generate(self.c)

    def test_equal_daily_energy_does_not_hide_time_shift(self):
        context = {'decision_min': 0, 'horizon_min': [0, 60]}
        a = [{'asset_id': 'washer', 'start_min': 0, 'end_min': 10, 'power_kw': 1}]
        b = [{**a[0], 'start_min': 20, 'end_min': 30}]
        evidence = profile_evidence(context, a, b)
        self.assertEqual('supported', evidence['status'])
        self.assertAlmostEqual(1 / 3, evidence['asset_L1_kWh']['washer'])
        self.assertEqual('exploratory', profile_evidence(context, a, a)['status'])

    def test_single_policy_uses_support_but_catalogue_keeps_exploration(self):
        result = generate(self.c)
        by_id = {r['id']: r for r in result['candidates']}
        self.assertTrue([r for r in by_id.values() if r['opportunity']['status'] == 'exploratory'])
        for selection in result['selections'].values():
            self.assertTrue(all(by_id[i]['opportunity']['status'] == 'supported' for i in selection['candidate_ids']))
        rows = catalogue({self.c['case_id']: self.c}, {'one': {self.c['case_id']: result}})
        self.assertIn('exploratory', {r['features']['opportunity'] for r in rows})

    def test_joint_does_not_upgrade_one_unsupported_child(self):
        children = [{'id': 'one', 'asset_id': 'ev', 'opportunity': {'status': 'supported'}},
                    {'id': 'two', 'asset_id': 'tank', 'opportunity': {'status': 'exploratory'}}]
        joint = joint_evidence(children)
        self.assertEqual('mixed', joint['joint_support'])
        self.assertEqual('exploratory', joint['status'])
        self.assertEqual(2, len(joint['children']))

    def test_response_deficit_fails_batch_without_deleting_record(self):
        rows = [{'case_id': 'c', 'sample_id': 's', 'stratum': 'uncertain', 'features': {'opportunity': 'exploratory'},
                 'coverage_credit': True, 'observation': {'report': {'targeted_response': {
                     'pattern': 'no_target_response', 'B_native_trace_sha256': 'hash',
                     'records': [{'kind': 'water_heater', 'observable_response': False}]}}}}]
        report = response_coverage(rows, {'minimum_changed_kinds': ['water_heater']})
        self.assertFalse(report['passed'])
        self.assertEqual(1, len(report['records']))
        self.assertEqual({'no_target_response': 1}, report['patterns'])


class LifeCapabilityTests(unittest.TestCase):
    def setUp(self):
        self.s = read(HERE / 'examples/life/life_batch.json')['households'][0]
        self.w = read(HERE / 'examples/life/resource_worlds.json')['households'][0]

    def test_program_power_cannot_exceed_declared_rating(self):
        next(d for d in self.w['devices'] if d['kind'] == 'washer')['parameters']['power_kw'] = 20
        with self.assertRaisesRegex(ValueError, 'PROGRAM_POWER_EXCEEDS_NAMEPLATE'):
            generate_household(self.s, self.w)

    def test_known_wash_capacity_limits_batch_setting(self):
        next(d for d in self.w['devices'] if d['kind'] == 'washer')['parameters']['capacity_kg'] = 1
        with self.assertRaisesRegex(ValueError, 'BATCH_CAPACITY_EXCEEDS_HARDWARE'):
            generate_household(self.s, self.w)

    def test_EV_cannot_start_above_battery_capacity(self):
        next(d for d in self.w['devices'] if d['kind'] == 'ev')['parameters']['initial_energy_kwh'] = 1000
        with self.assertRaisesRegex(ValueError, 'EV_INITIAL_ENERGY_EXCEEDS_CAPACITY'):
            generate_household(self.s, self.w)

    def test_EV_target_must_not_be_below_reserve(self):
        next(d for d in self.w['devices'] if d['kind'] == 'ev')['parameters']['target_soc'] = .01
        with self.assertRaisesRegex(ValueError, 'INVALID_EV_EFFICIENCY_OR_SOC_BOUNDS'):
            generate_household(self.s, self.w)

    def test_negative_water_quantity_is_not_a_valid_A(self):
        self.w['members'][0]['hot_water_liters'] = -20
        with self.assertRaisesRegex(ValueError, 'INVALID_NUMBER:hot_water_liters'):
            generate_household(self.s, self.w)
