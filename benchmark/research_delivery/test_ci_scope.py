import unittest
from .ci_scope import method_only


class MethodCIScopeTests(unittest.TestCase):
    def test_method_payload_routes_to_bounded_checks(self):
        self.assertTrue(method_only(['benchmark/ab_generation/unified/selection.py',
            'benchmark/family_generation/portrait_v3.py','benchmark/research_delivery/public_fixtures/PUBLIC_REPLAY.json',
            '.github/workflows/unified-method.yml','benchmark/PUBLICATION_MANIFEST.json']))

    def test_unrelated_runtime_or_physical_changes_are_not_hidden(self):
        for p in ('realtime_pilot/server.py','benchmark/housing_simulation/assembly.py','deploy/activate_reference50_ui91.py','benchmark/ab_generation/life.py'):
            self.assertFalse(method_only(['benchmark/ab_generation/unified/selection.py',p]))

    def test_empty_change_is_not_a_bounded_method_claim(self):
        self.assertFalse(method_only([]))


if __name__=='__main__':unittest.main()
