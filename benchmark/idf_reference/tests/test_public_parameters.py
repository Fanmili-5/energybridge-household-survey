import json
from pathlib import Path
import tempfile
import unittest

from scripts.public_parameters import ROOT, catalog, materialize, check, inside


class PublicParameterTests(unittest.TestCase):
    def test_catalog_has_three_reference_kinds_in_each_registered_country(self):
        value = catalog()
        countries = {'CN', 'US', 'GB', 'ES', 'DE', 'MX', 'IN', 'AU'}
        self.assertEqual({x['country'] for x in value['classes']}, countries)
        for country in countries:
            kinds = {k for x in value['classes'] if x['country'] == country for k in x['conditions']['kind']}
            self.assertEqual(kinds, {'apartment', 'attached', 'detached'})
        self.assertEqual(len(value['sites']), 9)
        self.assertFalse(value['class_wide_native_acceptance_claimed'])

    def test_fixed_inputs_stage_idempotently_but_never_overwrite_conflicts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = materialize(root)
            self.assertEqual(materialize(root), first)
            self.assertEqual(first['fixed_inputs_staged'], 18)
            self.assertFalse(first['native_simulation_executed'])
            logical = next(iter(json.loads((ROOT / 'parameters/LAYOUT.json').read_text())['files']))
            target = root / logical
            target.write_text('different existing configuration')
            with self.assertRaisesRegex(ValueError, 'conflicts'):
                materialize(root)
            self.assertEqual(target.read_text(), 'different existing configuration')

    def test_missing_external_inputs_cannot_be_mistaken_for_native_readiness(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            materialize(root)
            result = check(root)
            self.assertFalse(result['selected_input_references_present'])
            self.assertTrue(any(x['state'] == 'missing' for x in result['files']))
            self.assertFalse(result['native_runtime_ready_or_physics_accepted'])
            with self.assertRaisesRegex(ValueError, 'outside'):
                inside(root, '../escape.json')


if __name__ == '__main__':
    unittest.main()
