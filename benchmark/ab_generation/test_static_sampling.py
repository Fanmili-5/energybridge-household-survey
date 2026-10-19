"""Exact-index equivalence and frozen static acceptance regressions."""
import copy
import gc
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from .common import read, save, seal
from .generate import generate
from .model import request_issues
from .sampling import catalogue, command_hash, sample_catalogue
from .sampling_index import CommandIndex
from .static_sampling import ROOT, recheck
from .test_sampling import plan


class StaticSamplingTests(unittest.TestCase):
    def setUp(self):
        self.c = read(Path(__file__).parent / 'examples/family.json')

    def test_index_and_reference_catalogues_and_fixed_draw_are_identical(self):
        result = generate(self.c)
        before = copy.deepcopy(self.c)
        variants = {'a': {self.c['case_id']: result}, 'b': {self.c['case_id']: result}}
        fast = catalogue({self.c['case_id']: self.c}, variants)
        slow = catalogue({self.c['case_id']: self.c}, variants, indexed=False)
        self.assertEqual(slow, fast)
        self.assertEqual(sample_catalogue(slow, plan()), sample_catalogue(fast, plan()))
        self.assertEqual(before, self.c)
        self.assertTrue(any(r['features']['admission'] == 'static_diagnostic' for r in fast))

    def test_index_keeps_identity_duration_past_and_control_multiplicity_checks(self):
        index = CommandIndex(self.c)
        changes = []
        for field, value in [('task_id', 'new'), ('end_min', 999), ('start_min', -10), ('asset_id', 'not_original')]:
            B = copy.deepcopy(self.c['A']); B['tasks'][0][field] = value; changes.append(B)
        B = copy.deepcopy(self.c['A']); B['operations'].append(copy.deepcopy(B['operations'][0])); changes.append(B)
        B = copy.deepcopy(self.c['A']); B['controls'].append({**B['controls'][0], 'start_min': -10}); changes.append(B)
        for B in changes:
            self.assertEqual(request_issues(self.c, B), index.request_issues(B))
            self.assertEqual(command_hash(B), index.command_hash(B))

    def test_exact_coalescing_nested_unicode_gaps_and_recycled_temporary_rows(self):
        base = {'asset_id': '热水', 'kind': 'tank_setpoint', 'value_C': 55,
                'metadata': {'notes': ['甲', 1]}, 'start_min': 0, 'end_min': 60}
        c = {'decision_min': 30, 'A': {'tasks': [], 'operations': [], 'controls': [base]}}
        index = CommandIndex(c)
        for offset in (30, 40, 30, 20):
            for value in (55, 54):
                B = {'tasks': [], 'operations': [], 'controls': [
                    {**base, 'end_min': 30, '_ab_control_id': 'ignored'},
                    {**base, 'start_min': offset, 'value_C': value}]}
                self.assertEqual(command_hash(B), index.command_hash(B))
                self.assertEqual(request_issues(c, B), index.request_issues(B))
                del B
                gc.collect()

    def test_published_frozen_draw_and_all_selected_plans_recheck_without_processes(self):
        with tempfile.TemporaryDirectory() as folder, patch('subprocess.run', side_effect=AssertionError('no engine or subprocess')):
            result = recheck(ROOT / 'final_sample', folder)
            self.assertTrue(result['passed'])
            expected = read(ROOT / 'final_sample/RESULT.json')
            self.assertEqual(expected['required_deficits'], result['required_deficits'])
            self.assertEqual(0, result['new_engine_runs'])
            if not expected['passed']:
                with self.assertRaisesRegex(ValueError, 'retain_deficits'):
                    recheck(ROOT / 'final_sample', folder, True)

    def test_resealed_changed_patch_cannot_hide_wrong_selected_plan(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary) / 'sample'; shutil.copytree(ROOT / 'final_sample', folder)
            manifest = read(folder / 'MANIFEST.json')
            requests = read(folder / 'SELECTED_REQUESTS.json')
            request = next(r for r in requests if r['patches'])
            request['patches'] = []
            save(folder / 'SELECTED_REQUESTS.json', requests)
            seal(folder, {k: v for k, v in manifest.items() if k != 'files'})
            with self.assertRaisesRegex(ValueError, 'AUDIT_CHANGED'):
                recheck(folder, Path(temporary) / 'check')


if __name__ == '__main__':
    unittest.main()
