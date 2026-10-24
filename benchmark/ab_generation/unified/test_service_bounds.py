import copy
import itertools
import unittest

from .exhaustive import fixtures
from .service_bounds import earliest, event_exclusion


class ServiceBoundTests(unittest.TestCase):
    def test_relaxed_bound_against_independent_chain_grid(self):
        _, base, _, _ = next(fixtures())
        cases = 0
        for release, parent_length, child_load in itertools.product((1060, 1080, 1110), (20, 60), (10, 20)):
            c = copy.deepcopy(base)
            c['needs'][0]['release_min'] = release
            c['needs'][1]['release_min'] = release
            c['A']['tasks'][0].update(start_min=1200, end_min=1200+parent_length)
            c['A']['tasks'][1].update(start_min=1340, end_min=1360)
            for o in c['A']['operations']:
                start = 1190 if o['need_id'] == 'first' else 1320
                length = child_load if o['need_id'] == 'second' and o['kind'] == 'load' else 10
                if o['kind'] == 'unload': start = 1200+parent_length if o['need_id'] == 'first' else 1360
                o.update(start_min=start, end_min=start+length)
            feasible = []
            # Explicit release, load, wash, collect and load inequalities.
            for wl in range(release, 1161, 10):
                for ws in range(wl+10, 1201, 10):
                    for wu in range(ws+parent_length, 1281, 10):
                        for dl in range(max(release, wu+10), 1341, 10):
                            feasible.append(dl+child_load)
            bound = earliest(c, 'second')
            self.assertTrue(feasible)
            self.assertEqual(min(feasible), bound['earliest_start_min'])
            excluded = event_exclusion(c, 'second', {'start_min':1080, 'end_min':1140})
            self.assertEqual(min(feasible) >= 1140, excluded is not None)
            cases += 1
        self.assertEqual(cases, 12)

    def test_missing_parent_is_unknown_not_structural_exclusion(self):
        _, c, _, _ = next(fixtures())
        c['needs'] = [n for n in c['needs'] if n['need_id'] != 'first']
        self.assertEqual('unknown', earliest(c, 'second')['status'])
        self.assertIsNone(event_exclusion(c, 'second', {'start_min':1080, 'end_min':1140}))

    def test_original_event_program_prevents_exclusion(self):
        _, c, _, _ = next(fixtures())
        self.assertIsNone(event_exclusion(c, 'first', {'start_min':1080, 'end_min':1140}))

    def test_preloaded_program_does_not_get_a_new_load_duration(self):
        _, c, _, _ = next(fixtures())
        load = next(o for o in c['A']['operations'] if o['need_id']=='first' and o['kind']=='load')
        load.update(start_min=470, end_min=480)
        self.assertEqual(480, earliest(c, 'first')['earliest_start_min'])

    def test_started_parent_future_retrieval_may_be_advanced(self):
        _, c, _, _ = next(fixtures())
        c['decision_min'] = 1100
        unload = next(o for o in c['A']['operations'] if o['need_id']=='first' and o['kind']=='unload')
        unload.update(start_min=1200, end_min=1210)
        # Parent finished at 1100; a future retrieval need not stay at 1200.
        self.assertEqual(1110, earliest(c, 'first')['earliest_unload_end_min'])
        self.assertEqual(1120, earliest(c, 'second')['earliest_start_min'])
        self.assertIsNone(event_exclusion(c, 'second', {'start_min':1080, 'end_min':1140}))

    def test_ledger_exclusion_is_opt_in_and_keeps_certificate(self):
        from .opportunities import declare
        from .contract import config
        _, c, _, _ = next(fixtures())
        c['needs'][0]['release_min']=1080
        c['A']['tasks'][0].update(start_min=1200,end_min=1260)
        c['A']['tasks'][1].update(start_min=1280,end_min=1300)
        old=declare(c,config())
        new=declare(c,config({'opportunity_bounds':'precedence_v1'}))
        self.assertEqual([r['key'] for r in old['entries']], [r['key'] for r in new['entries']])
        rows=[r for r in new['entries'] if r.get('independent_input_exclusion')]
        self.assertTrue(rows)
        for r in rows:
            self.assertEqual('potential',r['pre_bound_status'])
            self.assertEqual('inapplicable',r['status'])
            self.assertEqual(1170,r['independent_input_exclusion']['certificate']['earliest_start_min'])

    def test_independent_checker_enforces_immutable_operator_even_if_qualified(self):
        from .independent import audit
        _, c, b, _ = next(fixtures())
        c['authority']['immutable_operator_ids']=['adult']
        self.assertIn('IMMUTABLE_OPERATOR_CHANGED',audit(c,c['A'],b))
        self.assertNotIn('IMMUTABLE_OPERATOR_CHANGED',audit(c,c['A'],c['A']))


if __name__ == '__main__':
    unittest.main()
