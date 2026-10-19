"""Regress the discovered grid omission using the unchanged public family A."""
import unittest
import copy
from pathlib import Path

from .common import read
from .gap_review import program_audit
from .generate import DEFAULT_RULES, program_domain_coverage
from .sampling import validate_plan
from .model import program_issues, apply
from .test_joint_load_supply import two_jobs

HERE = Path(__file__).parent


class GapReviewTests(unittest.TestCase):
    def test_literal_patching_preserves_inputs_and_isolates_nested_output(self):
        c = two_jobs(); c['A']['tasks'][0]['metadata'] = {'mass': [1.2]}
        original = copy.deepcopy(c['A'])
        replacement = {**c['A']['tasks'][0], 'start_min': 200, 'end_min': 220}
        patches = [{'type': 'rows', 'collection': 'tasks', 'identity': 'task_id', 'rows': [replacement]}]
        output = apply(c['A'], patches)
        moved = next(t for t in output['tasks'] if t['task_id'] == 'first')
        moved['metadata']['mass'][0] = 9
        self.assertEqual(original, c['A'])
        self.assertEqual([1.2], replacement['metadata']['mass'])
        self.assertEqual(['second', 'first'], [t['task_id'] for t in output['tasks']])

    def test_hold_index_keeps_missing_and_first_duplicate_retrieval_semantics(self):
        c = two_jobs(); plan = copy.deepcopy(c['A'])
        first = next(o for o in plan['operations'] if o['operation_id'] == 'first:unload')
        plan['operations'].append({**first, 'start_min': 200, 'end_min': 210})
        self.assertNotIn('ASSET_HOLD_CONFLICT', program_issues(c, plan, 'second'))
        plan['operations'] = [o for o in plan['operations'] if o['need_id'] != 'first' or o['kind'] != 'unload']
        self.assertIn('ASSET_HOLD_CONFLICT', program_issues(c, plan, 'second'))

    def test_sparse_grid_cannot_claim_complete_time_opportunities(self):
        coverage = program_domain_coverage(DEFAULT_RULES)
        self.assertFalse(coverage['complete_within_radius'])
        self.assertEqual(18, len(coverage['missing_grid_shifts_min']))
        self.assertIn(40, coverage['missing_grid_shifts_min'])
        self.assertIn(-20, coverage['missing_grid_shifts_min'])

    def test_supplement_is_a_full_symmetric_grid_and_keeps_adverse_strata(self):
        plan = read(HERE / 'examples/gap_supplement/tail_plan.json'); validate_plan(plan)
        rules = {**DEFAULT_RULES, **plan['variants'][0]['overrides']}
        self.assertEqual(set(range(-120, 121, 10)) - {0}, set(rules['program_shifts_min']))
        self.assertTrue(program_domain_coverage(rules)['complete_within_radius'])
        self.assertTrue(all(s['required'] for s in plan['strata']))
        self.assertTrue({'same_family_invalid', 'other_invalid', 'unchanged_control'} <= {s['id'] for s in plan['strata']})

    def test_original_multibatch_contains_missed_cost_and_joint_witnesses(self):
        folder = HERE / 'validation/joint_tail/frozen_inputs/family_multibatch/contexts'
        batch = read(folder / 'BATCH.json'); c = read(folder / batch['records'][0]['context'])
        coarse = program_audit(c, DEFAULT_RULES['program_shifts_min'])
        fine = program_audit(c, [v for v in range(-120, 121, 10) if v])
        self.assertEqual((0, 0), (coarse['valid_positive_cost_count'], coarse['valid_two_job_count']))
        self.assertEqual((1, 6), (fine['valid_positive_cost_count'], fine['valid_two_job_count']))
        self.assertEqual(2304, fine['two_job_product_count'])
        self.assertTrue(fine['full_context_witness_recheck'])
        self.assertFalse(fine['B_outcomes_read'])


if __name__ == '__main__':
    unittest.main()
