import unittest
from .source_scope import requires_source_rebuild

class SourceScopeTest(unittest.TestCase):
    def test_presentation_and_record_hashes_do_not_change_source_worlds(self):
        self.assertFalse(requires_source_rebuild([
            'benchmark/project/reference_collection_release.py',
            'benchmark/project/reference_refined_release.py',
            'benchmark/project/reference_collection_physics.py',
            'benchmark/project/reference_physics_results.py',
            'benchmark/project/reference_physics_selfcheck.py',
            'benchmark/project/reference_physical_release.py',
            'benchmark/project/refined91/housing_drawing.js',
            'benchmark/project/reference_presentation_release.py',
            'benchmark/project/questionnaire.py','benchmark/project/preview-client.js',
            'benchmark/collector/ledger.py','benchmark/collector/collection-client.js',
            'benchmark/collector/test_protocol.py','benchmark/collector/test_rounds.py',
            'benchmark/project/examples/questionnaire/source-snapshots/source.txt',
            'benchmark/project/examples/questionnaire/SUMMARY.json',
            'benchmark/project/UI91_VALIDATION.json',
            'benchmark/project/FULL500_PHYSICS_VALIDATION.json',
            'benchmark/releases/reference50-v4-ui91-physics/MANIFEST.json',
            'benchmark/ab_generation/validation/collection_v4/REFERENCE50_RELEASE_REVIEW.json',
            'benchmark/project/PACKAGE_MANIFEST.json','benchmark/README.md']))

    def test_generator_inputs_and_unknown_changes_fail_safe_to_full_rebuild(self):
        for path in ['benchmark/ab_generation/collection_selection.py',
                     'benchmark/project/pipeline.py','benchmark/family_generation/core.py',
                     'benchmark/housing_simulation/worker.py',
                     'benchmark/housing_simulation/kernel/compiler.py',
                     'benchmark/housing_simulation/kernel/multi_ac.py',
                     'benchmark/ab_generation/examples/collection/design.json',
                     'benchmark/project/examples/questionnaire/public/index.json',
                     'benchmark/collector/server.py','new_unknown_source.py']:
            with self.subTest(path=path):self.assertTrue(requires_source_rebuild([path]))

if __name__=='__main__':unittest.main()
