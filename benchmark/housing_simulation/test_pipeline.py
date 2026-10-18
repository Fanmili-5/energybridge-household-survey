"""Public tests use invented households/materials and require no study cohort."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from .pipeline import HERE, build_shell, match, read, save, sha, verify


class HousingPipelineTests(unittest.TestCase):
    def job(self, root):
        reference = HERE / 'examples/synthetic_assembly.json'
        (root / 'assembly.json').write_bytes(reference.read_bytes())
        job = read(HERE / 'examples/shell_batch.json')
        job['assembly'] = {'path': 'assembly.json', 'sha256': sha(root / 'assembly.json')}
        path = root / 'input.json'; save(path, job)
        return path, job

    def test_arbitrary_batch_and_area_conservation(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t); path, job = self.job(root)
            for count in (1, 3):
                item = copy.deepcopy(job); item['households'] = item['households'][:count]; save(path, item)
                out = root / str(count); result = build_shell(path, out)
                self.assertEqual(len(result['records']), count)
                for h in item['households']:
                    layout = read(out / h['household_id'] / 'layout.json')
                    self.assertAlmostEqual(layout['target_H6_unrounded_m2'], h['gross_area_m2'], places=6)
                    target_rooms = [r for r in layout['rooms'] if r['census_room_class'] == 'bedroom'
                                    and r['using_household_ids'] == [h['household_id']]]
                    self.assertEqual(len(target_rooms), h['natural_rooms'])
                    self.assertAlmostEqual(sum(layout['allocated_gross_area_by_context_household_m2'].values()),
                                           layout['whole_unit_building_area_m2'], places=6)
                verify(out)

    def test_impossible_household_retained_in_denominator(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t); path, job = self.job(root)
            job['households'][0]['gross_area_m2'] = .1; save(path, job)
            r = build_shell(path, root / 'out')
            self.assertEqual(len(r['records']), 3)
            self.assertEqual(r['records'][0]['status'], 'rejected')
            self.assertEqual(r['records'][1]['status'], 'shell_compiled')

    def test_input_hash_change_rejected_before_build(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t); path, job = self.job(root)
            (root / 'assembly.json').write_text('{}')
            with self.assertRaises(ValueError): build_shell(path, root / 'out')
            self.assertFalse((root / 'out').exists())

    def test_output_corruption_detected_and_output_not_overwritten(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t); path, job = self.job(root); out = root / 'out'
            build_shell(path, out)
            with self.assertRaises(FileExistsError): build_shell(path, out)
            (out / 'example-family/shell.idf').write_text('changed')
            with self.assertRaises(ValueError): verify(out)

    def test_duplicate_or_escaping_identifiers_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t); path, job = self.job(root)
            job['households'][0]['household_id'] = '../outside'; save(path, job)
            with self.assertRaises(ValueError): build_shell(path, root / 'out')
            self.assertFalse((root / 'out').exists())

    def test_matching_keeps_given_epoch_and_marks_renovation(self):
        req = read(HERE / 'examples/match_request.json')
        catalog = read(HERE / 'examples/synthetic_catalog.json')['references']
        result = match(req, catalog)
        self.assertEqual(result['given_epoch_interval'], [1980, 1989])
        self.assertEqual(result['envelope_mode'], 'explicit_refurbished_envelope_scenario')
        req['city'] = 'UnrepresentedCity'
        with self.assertRaises(ValueError): match(req, catalog)

    def test_packaged_kernel_hashes(self):
        for name, expected in read(HERE / 'SOURCE_MAP.json')['kernel_files'].items():
            self.assertEqual(sha(HERE / 'kernel' / name), expected, name)

    def test_overflowing_json_number_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            p = Path(t) / 'input.json'; p.write_text('{"area":1e9999}')
            with self.assertRaises(ValueError): read(p)


if __name__ == '__main__':
    unittest.main()
