from pathlib import Path
import tempfile
import unittest

from .connect import connect
from .core import HERE, generate, read, save, sha, verify


class ConnectionTests(unittest.TestCase):
    def test_all_six_families_reach_housing_and_life_A_including_shared_context(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            generate(HERE / 'examples/batch.json', root / 'families')
            result = connect(root / 'families', root / 'connected')
            self.assertEqual(result['requested'], 6)
            self.assertEqual(result['constructed'], 6, result['records'])
            self.assertEqual(result['EP_runs'], 0)
            self.assertTrue(verify(root / 'connected')['passed'])
            source = read(root / 'families/SUMMARY.json')
            for r in result['records']:
                life = read(root / 'connected/life_A' / r['household_id'] / 'SUMMARY.json')
                self.assertTrue(life['all_A_constructed'])
                original = next(x for x in source['records'] if x['household_id'] == r['household_id'])
                self.assertEqual(original['sha256'], r['family_sha256'])
                folder = root / 'connected/life_inputs' / r['household_id']
                normalized = read(folder / 'resource_worlds.json')
                self.assertEqual(normalized['source_world_contract_sha256'], sha(folder / 'world_contracts.json'))
                self.assertEqual(read(folder / 'family_context.json')['archetype_definition']['role'], r['archetype'])
                portrait = read(root / 'connected' / r['energy_portrait'])
                self.assertEqual(portrait['role'], r['archetype'])
                self.assertFalse(portrait['source_calendar_or_A_modified'])
                self.assertFalse(portrait['B_outcomes_or_answers_used'])
                programmed = [d for d in portrait['devices'] if d['kind'] in ('washer', 'dishwasher')]
                for device in programmed:
                    self.assertTrue(device['declared_settings']['program_policies'])
                    for need in device['requirements']:
                        self.assertIn('preferred_start_at', need)

    def test_missing_source_support_stays_in_connection_denominator(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); pool = read(HERE / 'examples/REFERENCE_POOL.json')
            pool['templates'][-1]['life'].pop('mobility')
            save(root / 'pool.json', pool)
            cfg = read(HERE / 'examples/batch.json'); cfg['pool'] = {'path': 'pool.json', 'sha256': sha(root / 'pool.json')}
            save(root / 'input.json', cfg)
            generate(root / 'input.json', root / 'families')
            result = connect(root / 'families', root / 'connected')
            self.assertEqual(len(result['records']), 6)
            self.assertEqual(result['constructed'], 5)
            self.assertEqual(result['records'][-1]['status'], 'connection_rejected')


if __name__ == '__main__': unittest.main()
