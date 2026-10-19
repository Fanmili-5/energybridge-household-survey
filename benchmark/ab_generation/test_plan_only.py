import copy
import unittest
from pathlib import Path
from .common import read
from .generate import binding, generate
from .information import information_set
from .model import apply


class PlanOnlyTests(unittest.TestCase):
    def context(self):
        c = read(Path(__file__).parent / 'examples/family.json')
        c['reference']['thermal'] = {}
        span = c['reference']['information_set']['A_reference_span_min']
        c['reference']['information_set'] = information_set('offline_unexecuted_A_plan', c['decision_min'], span)
        return c

    def test_unknown_thermal_state_stays_exploratory_without_predicted_savings(self):
        c = self.context(); original = copy.deepcopy(c)
        result = generate(c)
        rows = [r for r in result['candidates'] if r['family'] in ('ac', 'water_heater')]
        self.assertTrue(rows)
        for r in rows:
            self.assertEqual(r['opportunity']['status'], 'exploratory')
            self.assertIsNone(r['prediction']['delta_cost'])
            self.assertIsNone(r['prediction']['aligned_event_kWh'])
            self.assertIsNone(r['actual_outcomes'])
            self.assertIsNone(r['factors']['A_active_support_min'])
            b = apply(c['A'], r['patches'])
            for t in range(480, 1920, 10):
                if not any(p['start_min'] <= t < p['end_min'] for p in r['patches']):
                    for aid in {p['asset_id'] for p in r['patches']}:
                        states = lambda plan: [{k:v for k,v in row.items() if k not in ('start_min','end_min','_ab_control_id')}
                            for row in plan['controls'] if row['asset_id'] == aid and row['start_min'] <= t < row['end_min']]
                        self.assertEqual(states(c['A']), states(b))
        self.assertEqual(c, original)

    def test_declaring_future_thermal_state_in_unexecuted_mode_is_rejected(self):
        c = self.context(); c['reference']['thermal'] = {'ac': [{'minute': 600}]}
        with self.assertRaisesRegex(ValueError, 'UNEXECUTED_PLAN_CANNOT_DECLARE_THERMAL_STATE'):
            generate(c)

    def test_empty_room_and_missing_authority_do_not_create_ac_opportunities(self):
        for field in ('occupancy', 'authority'):
            c = self.context()
            if field == 'occupancy':
                c['occupancy'] = {}
            else:
                c['authority']['assets']['ac']['target_control_authorized'] = False
            c['reference']['binding'] = binding(c)
            self.assertFalse([r for r in generate(c)['candidates'] if r['family'] == 'ac'])

    def test_legacy_information_mode_does_not_gain_guessed_thermal_states(self):
        c = self.context()
        c['reference']['information_set']['mode'] = 'offline_full_A_counterfactual'
        c['reference']['information_set'] = information_set('offline_full_A_counterfactual', c['decision_min'],
            c['reference']['information_set']['A_reference_span_min'])
        result = generate(c)
        self.assertFalse([r for r in result['candidates'] if r['family'] in ('ac', 'water_heater')])


if __name__ == '__main__': unittest.main()
