import copy
import itertools
import unittest
from pathlib import Path

from .common import read
from .life import generate_household
from .sensitivity import choose_joint, life_measurements, perturb, variants

HERE = Path(__file__).parent


class SensitivityTests(unittest.TestCase):
    def setUp(self):
        self.plan = read(HERE / 'examples/sensitivity/plan.json')
        self.design = {v['id']: v for v in variants(self.plan)}
        self.spec = read(HERE / 'examples/strategy_review/life_batch.json')['households'][0]
        self.spec['end_exclusive'] = '2025-03-08'
        self.world = next(w for w in read(HERE / 'examples/strategy_review/resource_worlds.json')['households']
                          if w['household_id'] == self.spec['household_id'])

    def generated(self, name):
        s, w = perturb(self.spec, self.world, self.design[name]['values'])
        a = generate_household(s, w)
        return a, life_measurements(s, w, a)

    def test_factorial_is_complete_and_pairwise_balanced(self):
        corners = [v['signs'] for v in self.design.values() if v['design'] == 'full_factorial']
        self.assertEqual(55, len(self.design)); self.assertEqual(32, len(corners))
        for a, b in itertools.combinations(self.plan['factors'], 2):
            self.assertEqual({(-1, -1), (-1, 1), (1, -1), (1, 1)}, {(r[a], r[b]) for r in corners})
            for aa, bb in itertools.product((-1, 1), repeat=2):
                self.assertEqual(8, sum(r[a] == aa and r[b] == bb for r in corners))

    def test_EV_change_preserves_real_away_home_boundary_and_input(self):
        before = copy.deepcopy((self.spec, self.world))
        s, _ = perturb(self.spec, self.world, self.design['ev_arrival_delta_min_high']['values'])
        self.assertEqual(1110, s['mobility']['journey_templates']['weekday'][0]['arrival_min'])
        cal = s['member_calendars']['adult1']['weekday']
        self.assertEqual(1110, next(e['end_min'] for e in cal if e['location'] == 'away'))
        self.assertEqual(before, (self.spec, self.world))

    def test_zero_textiles_does_not_invent_wash_or_dry(self):
        a, m = self.generated('textile_zero')
        self.assertTrue(all(m['checks'].values())); self.assertEqual('A_constructed', a['status'])
        self.assertEqual(0, m['cycles'].get('washer', 0)); self.assertEqual(0, m['cycles'].get('dryer', 0))

    def test_daily_fixed_cycle_and_full_batch_are_distinct_assumptions(self):
        _, low = self.generated('textile_kg_low'); _, high = self.generated('textile_kg_high')
        self.assertEqual(low['washer_kWh'], high['washer_kWh'])
        self.assertLess(low['served_textile_kg'], high['served_textile_kg'])
        _, low_batch = self.generated('full_batch_low'); _, high_batch = self.generated('full_batch_high')
        self.assertLess(low_batch['cycles'].get('washer', 0), high_batch['cycles'].get('washer', 0))
        self.assertTrue(all(low_batch['checks'].values()) and all(high_batch['checks'].values()))

    def test_missing_handler_is_retained_without_replacement(self):
        a, m = self.generated('ev_missing_handler')
        self.assertEqual('needs_unserved', a['status'])
        self.assertIn('NO_REAL_EV_PLUG_HANDLER', m['unserved_reasons'])
        self.assertTrue(all(m['checks'].values()))

    def test_selector_has_no_fallback_or_actual_outcome_dependency(self):
        panel = self.plan['panels']['family']
        self.assertIsNone(choose_joint({'candidates': [], 'joint_candidates': []}, panel))
        def c(cid, family):
            return {'id': cid, 'family': family, 'asset_id': cid, 'opportunity': {'status': 'supported'},
                    'factors': {'handling_mode': 'shift_chain', 'program_shift_min': 30, 'ev_delay_min': 60}}
        x = {'candidates': [c('wash', 'washer'), c('car', 'ev')],
             'joint_candidates': [{'id': 'joint', 'candidate_ids': ['wash', 'car'], 'static_issues': []}]}
        selected = choose_joint(x, panel)
        x['joint_candidates'][0]['actual_outcomes'] = {'B_failed': True}
        self.assertEqual(selected, choose_joint(x, panel))
        x['joint_candidates'][0]['static_issues'] = ['OPERATOR_DOUBLE_BOOKED']
        self.assertIsNone(choose_joint(x, panel))


if __name__ == '__main__':
    unittest.main()
