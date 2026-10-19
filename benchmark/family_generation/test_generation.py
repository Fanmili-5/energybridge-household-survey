import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from .core import HERE, construct, digest, fixed_roster, generate, read, save, sha, validate_template, verify


class FamilyGenerationTests(unittest.TestCase):
    def setUp(self):
        self.pool = read(HERE / 'examples/REFERENCE_POOL.json')

    def run_batch(self, folder, pool=None, total=6, subset=6):
        save(folder / 'pool.json', pool or self.pool)
        cfg = read(HERE / 'examples/batch.json')
        cfg.update(total=total, subset_size=subset, pool={'path': 'pool.json', 'sha256': sha(folder / 'pool.json')})
        save(folder / 'input.json', cfg)
        return generate(folder / 'input.json', folder / 'out')

    def test_public_sources_are_joint_valid_scenarios(self):
        for t in self.pool['templates']:
            self.assertTrue(validate_template(t))

    def test_zip_truncation_regression_and_reordering(self):
        a = [{'member_id': 'a', 'age_years': 40}]
        extra = a + [{'member_id': 'b', 'age_years': 10}]
        self.assertTrue(all(x == y for x, y in zip(a, extra)))
        with self.assertRaisesRegex(ValueError, 'ADDED_OR_REMOVED'):
            fixed_roster(a, extra)
        self.assertTrue(fixed_roster(extra, list(reversed(extra))))

    def test_identity_remap_does_not_rename_device_kind(self):
        t = next(t for t in self.pool['templates'] if t['eligible_archetypes'] == ['F'])
        result = construct(t, 'new-family', 'F')
        self.assertEqual({d['kind'] for d in result['world']['devices']}, {'ac', 'washer', 'dryer', 'dishwasher', 'water_heater', 'ev'})
        mids = {m['member_id'] for m in result['world']['members']}
        self.assertEqual(mids, set(result['life']['member_calendars']))
        self.assertTrue(all(m.startswith('new-family-m') for m in mids))
        self.assertIsNone(result['human_acceptance'])

    def test_members_and_unknown_employment_conserved(self):
        t = self.pool['templates'][0]
        result = construct(t, 'new-family', 'A')
        self.assertEqual([m['age_years'] for m in t['facts']['members']], [m['age_years'] for m in result['facts']['members']])
        self.assertTrue(all(m['employment_status'] == 'unknown' for m in result['facts']['members']))

    def test_household_member_and_asset_ids_cannot_collide(self):
        t = copy.deepcopy(self.pool['templates'][0])
        t['facts']['context_household_ids'].append(t['world']['household_id'])
        t['shell']['shared_households'] += 1
        with self.assertRaisesRegex(ValueError, 'CROSS_NAMESPACE_ID'):
            validate_template(t)

    def test_input_mutation_cannot_seal_a_mixed_version(self):
        from . import core
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            save(root / 'pool.json', self.pool)
            cfg = read(HERE / 'examples/batch.json')
            cfg['pool'] = {'path': 'pool.json', 'sha256': sha(root / 'pool.json')}
            save(root / 'input.json', cfg)
            original = core.construct
            def mutate(*args):
                cfg['seed'] += 1
                save(root / 'input.json', cfg)
                return original(*args)
            with patch.object(core, 'construct', side_effect=mutate):
                with self.assertRaisesRegex(ValueError, 'INPUT_CHANGED_DURING'):
                    generate(root / 'input.json', root / 'out')
            self.assertFalse((root / 'out/MANIFEST.json').exists())

    def test_n_missing_member_and_missing_calendar_rejected(self):
        for mutate in [lambda t: t['facts'].update(N=99), lambda t: t['facts']['members'].pop(),
                       lambda t: t['life']['member_calendars'].clear()]:
            t = copy.deepcopy(self.pool['templates'][0]); mutate(t)
            with self.assertRaises(ValueError): validate_template(t)

    def test_parent_age_gap_does_not_invent_an_adoption_story(self):
        t = copy.deepcopy(self.pool['templates'][-1])
        for rows in [t['world']['members'], t['facts']['members']]:
            next(m for m in rows if m['member_id'] == 'adult1')['age_years'] = 19
        with self.assertRaisesRegex(ValueError, 'PARENT_AGE'):
            validate_template(t)

    def test_care_and_mobility_are_explicit_conditions(self):
        e = copy.deepcopy(next(t for t in self.pool['templates'] if t['eligible_archetypes'] == ['E']))
        e['facts']['care'] = []
        with self.assertRaisesRegex(ValueError, 'E_WITHOUT'):
            validate_template(e)
        f = copy.deepcopy(self.pool['templates'][-1]); f['life'].pop('mobility')
        with self.assertRaisesRegex(ValueError, 'F_WITHOUT'):
            validate_template(f)

    def test_unknown_permissions_not_granted_from_presence(self):
        t = copy.deepcopy(self.pool['templates'][0])
        t['world']['members'][0]['can_operate_asset_ids'].append('invented-helper-asset')
        with self.assertRaisesRegex(ValueError, 'ASSET_RIGHT'):
            validate_template(t)

    def test_neighbor_devices_cannot_supply_target_coverage(self):
        t = copy.deepcopy(next(t for t in self.pool['templates'] if t['eligible_archetypes'] == ['C']))
        neighbor = t['facts']['context_household_ids'][0]
        for device in t['world']['devices']:
            device['using_household_ids'] = [neighbor]
        with self.assertRaisesRegex(ValueError, 'DEVICE_COVERAGE'):
            validate_template(t)

    def test_F_requires_travel_not_just_an_EV_and_driver(self):
        t = copy.deepcopy(self.pool['templates'][-1])
        t['life']['mobility']['journey_templates']['weekday'] = []
        with self.assertRaisesRegex(ValueError, 'WEEKDAY_TRAVEL'):
            validate_template(t)

    def test_bed_group_cannot_cross_shared_households(self):
        t = copy.deepcopy(next(t for t in self.pool['templates'] if t['eligible_archetypes'] == ['C']))
        groups = {g['group_id']: g for g in t['world']['sleep_groups']}
        groups['parents']['member_ids'] = ['adult1', 'neighbor']
        groups['neighbor']['member_ids'] = ['adult2']
        with self.assertRaisesRegex(ValueError, 'CROSSES_HOUSEHOLDS'):
            validate_template(t)

    def test_complete_batch_and_subset_are_same_source(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); summary = self.run_batch(root, total=18, subset=6)
            self.assertEqual(summary['requested'], summary['constructed'])
            self.assertTrue(verify(root / 'out')['passed'])
            parent = {r['household_id']: r for r in summary['records']}
            subset = read(root / 'out/SUBSET.json')
            self.assertEqual(len(subset['records']), 6)
            self.assertTrue(all(row == parent[row['household_id']] for row in subset['records']))

    def test_invalid_source_keeps_requested_failed_slot(self):
        pool = copy.deepcopy(self.pool)
        pool['templates'][-1]['life'].pop('mobility')
        with tempfile.TemporaryDirectory() as temp:
            result = self.run_batch(Path(temp), pool)
            self.assertEqual(len(result['records']), 6)
            self.assertEqual(result['constructed'], 5)
            self.assertEqual(result['records'][-1]['status'], 'source_support_unavailable')
            self.assertIn('declared-F', result['invalid_source_templates'])

    def test_deleted_or_extra_products_do_not_pass_a_cached_record(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); result = self.run_batch(root)
            (root / 'out' / result['records'][0]['path']).unlink()
            with self.assertRaisesRegex(ValueError, 'MISSING_OR_UNREGISTERED'):
                verify(root / 'out')

    def test_changed_pool_and_nonfinite_json_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); self.run_batch(root)
            save(root / 'pool.json', {'changed': True})
            with self.assertRaisesRegex(ValueError, 'POOL_PATH_OR_HASH'):
                generate(root / 'input.json', root / 'another')
            (root / 'bad.json').write_text('{"power":1e999}')
            with self.assertRaises(ValueError): read(root / 'bad.json')

    def test_same_input_byte_reproduction(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); self.run_batch(root)
            generate(root / 'input.json', root / 'repeat')
            files = read(root / 'out/MANIFEST.json')['files']
            self.assertTrue(all(sha(root / 'repeat' / p) == h for p, h in files.items()))
            with self.assertRaises(FileExistsError):
                generate(root / 'input.json', root / 'out')


if __name__ == '__main__':
    unittest.main()
