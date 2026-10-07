"""Checks for the public read-only entrypoint; fixtures are invented, not people."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
CLI = REPO / 'scripts/household1000.py'
REL = Path('docs/research/collection-adjustment-20260930/household1000')


def canonical_sha(value):
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
    return hashlib.sha256(raw.encode()).hexdigest()


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value) + '\n')
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fixture(root, corruption=None):
    """A minimal schema fixture cannot be used as the scientific family cohort."""
    base = root / REL / 'roleplay_mixed_production_20261007_v17'
    households = []
    for index in range(50):
        hid = 'engineering-fixture-' + str(index)
        world = {'household_id': hid, 'N': 1, 'members': [{'member_id': 'invented'}],
                 'world_content_sha256': 'fixture-world', 'parameter_pack_sha256': 'fixture-parameters'}
        world_path = Path('worlds') / (hid + '.json')
        household = {'household_id': hid, 'world_path': str(world_path),
                     'world_sha256': write(base / world_path, world), 'rounds': []}
        for step in range(10):
            plan = {'tasks': [], 'controls': []}
            pair = {'case_id': hid + ':' + str(step), 'household_id': hid,
                    'date': '2025-01-01', 'world_sha256': 'fixture-world',
                    'parameter_pack_sha256': 'fixture-parameters',
                    'needs_A': [{'quantity': 1}], 'needs_B': [{'quantity': 1}],
                    'A': plan, 'A_frozen_before_B_sha256': canonical_sha(plan)}
            if index == 0 and step == 0:
                if corruption == 'needs':
                    pair['needs_B'] = []
                if corruption == 'A':
                    pair['A'] = {'tasks': ['rewritten'], 'controls': []}
            pair_path = Path('pairs') / hid / (str(step) + '.json')
            household['rounds'].append({'pair_path': str(pair_path), 'pair_sha256': write(base / pair_path, pair),
                                         'date': pair['date']})
        households.append(household)
    write(base / 'SELECTION50.json', {'records': households})


class EntrypointTests(unittest.TestCase):
    def invoke(self, *args):
        result = subprocess.run([sys.executable, str(CLI), *args], capture_output=True, text=True)
        return result.returncode, json.loads(result.stdout)

    def test_missing_protected_inputs_remain_missing(self):
        with tempfile.TemporaryDirectory() as folder:
            code, result = self.invoke('check-bindings', '--workspace', folder)
            self.assertEqual(code, 2)
            self.assertEqual(result['status'], 'missing_prepared_inputs')

    def test_well_bound_fixture_and_no_execution(self):
        with tempfile.TemporaryDirectory() as folder:
            fixture(Path(folder))
            code, result = self.invoke('check-bindings', '--workspace', folder)
            self.assertEqual(code, 0)
            self.assertEqual(result['pairs'], 500)
            self.assertFalse(result['EP_started'])
            self.assertEqual(result['human_answers_created'], 0)

    def test_same_need_and_A_freeze_corruption_detected_even_with_valid_file_hashes(self):
        for corruption, expected in [('needs', ':same_needs'), ('A', ':A_frozen')]:
            with self.subTest(corruption=corruption), tempfile.TemporaryDirectory() as folder:
                fixture(Path(folder), corruption)
                code, result = self.invoke('check-bindings', '--workspace', folder)
                self.assertEqual(code, 1)
                self.assertTrue(any(error.endswith(expected) for error in result['failures']))


if __name__ == '__main__':
    unittest.main()
