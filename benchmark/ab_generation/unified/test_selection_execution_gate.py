"""A failed persisted execution audit cannot re-enter through selection."""
import copy
import unittest
from .selection import select_block
from .test_joint_order_selection import row,current

class SelectionExecutionGateTests(unittest.TestCase):
    def test_failed_disabled_or_incomplete_audit_is_rejected(self):
        invalid=[None,{},dict(enabled=False,passed=True,hard_errors=[]),
            dict(enabled=True,passed=False,hard_errors=[]),
            dict(enabled=True,passed=True,hard_errors=['EV_UNDECLARED_INTERRUPTION']),
            dict(enabled=True,passed=True),dict(passed=True,hard_errors=[])]
        for native in invalid:
            r=row(1,'2026-11-09','only');r['native_execution']=native
            with self.subTest(native=native),self.assertRaisesRegex(ValueError,'NATIVE_EXECUTION_NOT_PASSED_IN_SELECTION'):
                select_block([r],current())
    def test_verified_candidate_remains_eligible_and_is_not_modified(self):
        r=row(1,'2026-11-09','only');r['native_execution']=dict(enabled=True,passed=True,hard_errors=[])
        before=copy.deepcopy(r);answer=select_block([r],current())
        self.assertEqual(['only'],answer['selected_ids']);self.assertEqual(before,r)
    def test_explicit_legacy_candidate_without_new_audit_keeps_legacy_route(self):
        r=row(1,'2026-11-09','legacy')
        self.assertEqual(['legacy'],select_block([r],current())['selected_ids'])

if __name__=='__main__':unittest.main()
