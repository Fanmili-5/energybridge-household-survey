import copy
import unittest
import tempfile
from pathlib import Path

from .common import read, save, seal, sha
from .generate import generate
from .model import apply, program_issues
from .sampling import catalogue, classify_result, describe, validate_plan
from .test_sampling import plan, unit
from .test_joint_load_supply import two_jobs


class JointTailTests(unittest.TestCase):
    def setUp(self):
        self.c = read(Path(__file__).parent / 'examples/family.json')

    def report(self, failures):
        return {'case_id': 'case', 'readback_status': 'complete', 'A_reference_comparison': {'passed': True},
                'engine_status': {'A': 'completed', 'B': 'completed'}, 'failed_checks': failures,
                'actual_results_used_for_reselection': False, 'human_acceptance': None}

    def test_capacity_stress_is_explicit_and_cannot_waive_resource_conflicts_or_authority(self):
        child = next(c for c in generate(self.c, {'joint_family_limit': 1})['candidates'] if c['family'] == 'ev')
        B = apply(self.c['A'], child['patches']); issues = ['SITE_CAPACITY_NOT_CERTIFIED']
        self.c['electrical'] = {'supply_W': 8000}
        self.assertEqual('static_diagnostic', describe(self.c, B, [child], issues)[0]['admission'])
        def admission(extra=()):
            return describe(self.c, B, [child], issues + list(extra), stress_admissions=['declared_site_capacity_stress'])[0]
        self.assertEqual('declared_site_capacity_stress', admission()['admission'])
        self.assertEqual('uncertified_upper_bound', admission()['power_risk'])
        self.assertEqual('static_diagnostic', admission(['OPERATOR_UNAVAILABLE'])['admission'])
        self.c['authority']['assets'][child['asset_id']]['target_control_authorized'] = False
        self.assertEqual('static_diagnostic', admission()['admission'])

    def test_capacity_failure_and_unexpected_success_are_both_retained(self):
        sample = unit('one', admission='declared_site_capacity_stress')
        failure = classify_result(sample, self.report(['B_electrical_supply']))
        success = classify_result(sample, self.report([]))
        self.assertEqual('capacity_service_failure_retained', failure['status'])
        self.assertEqual('capacity_stress_executed_without_overload', success['status'])
        self.assertTrue(failure['coverage_credit']); self.assertTrue(success['coverage_credit'])
        self.assertFalse(classify_result(sample, self.report(['B_meter_closure']))['coverage_credit'])

    def test_new_unit_axes_are_independent_of_device_chain_asset_count(self):
        singles = generate(self.c, {'joint_family_limit': 1})['candidates']
        child = next(c for c in singles if c['family'] == 'washer')
        features, _ = describe(self.c, apply(self.c['A'], child['patches']), [child], child['static_issues'])
        self.assertEqual('1', features['unit_count']); self.assertEqual('1', features['family_count'])
        self.assertEqual('no', features['same_family_jobs'])
        second = copy.deepcopy(child); second['factors']['need_id'] += ':another_batch'
        features, _ = describe(self.c, apply(self.c['A'], child['patches']), [child, second], child['static_issues'])
        self.assertEqual('2', features['unit_count']); self.assertEqual('1', features['family_count'])
        self.assertEqual('yes', features['same_family_jobs'])

    def test_new_stress_plan_does_not_accept_arbitrary_exceptions_or_outcome_strata(self):
        p = plan(); p['stress_admissions'] = ['declared_site_capacity_stress']; validate_plan(p)
        p['stress_admissions'] = ['ignore_all_physics']
        with self.assertRaisesRegex(ValueError, 'INVALID_STRESS_ADMISSIONS'): validate_plan(p)
        p = plan(); p['strata'][0]['match']['actual_failure'] = ['yes']
        with self.assertRaises(ValueError): validate_plan(p)

    def test_new_joint_catalogue_keeps_high_order_and_invalid_rows(self):
        result = generate(self.c)
        rows = catalogue({self.c['case_id']: self.c}, {'new': {self.c['case_id']: result}})
        self.assertTrue(any(int(r['features']['unit_count']) >= 3 for r in rows))
        self.assertTrue(any(r['features']['admission'] == 'static_diagnostic' for r in rows))
        self.assertTrue(all(r['features']['unit_count'] == str(len(r['aliases'][0]['candidate_factors'])) for r in rows))

    def test_dependent_dryer_does_not_inherit_washer_control_authority(self):
        c = two_jobs(); root = c['A']['tasks'][0]
        c['A']['tasks'].append({**root, 'task_id': 'dry', 'need_id': 'dry', 'asset_id': 'dryer',
                               'kind': 'dryer', 'start_min': 200, 'end_min': 220, 'depends_on_need_id': 'first'})
        c['needs'].append({**c['needs'][0], 'need_id': 'dry', 'asset_id': 'dryer', 'kind': 'dryer'})
        c['A']['operations'] += [{**o, 'need_id': 'dry', 'operation_id': 'dry:' + o['kind'],
                                  'asset_id': 'dryer', 'start_min': a, 'end_min': a + 10}
                                 for o, a in zip(c['A']['operations'][:2], (190, 220))]
        c['authority'] = {'immutable_operator_ids': [], 'assets': {
            'washer': {'target_control_authorized': True, 'authorized_operator_ids': ['adult']},
            'dryer': {'target_control_authorized': False, 'authorized_operator_ids': ['adult']}}}
        B = copy.deepcopy(c['A']); B['tasks'][-1]['start_min'] += 10; B['tasks'][-1]['end_min'] += 10
        self.assertIn('TARGET_CONTROL_NOT_AUTHORIZED', program_issues(c, B, 'first'))

    def test_frozen_frame_needs_only_A_contexts_and_does_not_read_old_B(self):
        from .joint_tail import frame
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); reference = root / 'refs/example'; contexts = reference / 'contexts'
            save(contexts / 'c.json', self.c)
            save(contexts / 'BATCH.json', {'schema': 'eb.ab_generation.batch.v1',
                                         'records': [{'case_id': self.c['case_id'], 'context': 'c.json'}]})
            seal(contexts, {})
            # Invalid old B JSON would fail immediately if used as an input.
            (reference / 'RESULT.json').write_text('old B must not be read')
            save(root / 'refs/A_STAGE_RECEIPTS.json', [{'reference_id': 'example', 'path': 'example',
                 'A_stage_manifests': {'contexts': sha(contexts / 'MANIFEST.json')}}])
            save(root / 'references.json', {'schema': 'eb.ab_joint_tail.references.v1',
                                          'records': [{'id': 'example', 'path': 'example'}]})
            save(root / 'plan.json', plan())
            result = frame(root / 'refs', root / 'references.json', root / 'plan.json', root / 'sample', True)
            self.assertGreater(result['unique_catalogue_size'], 0)
            self.assertFalse(read(root / 'sample/SELECTION.json')['B_outcomes_read'])
            self.assertTrue(read(root / 'sample/MANIFEST.json')['frozen_context_replay_only'])


if __name__ == '__main__': unittest.main()
