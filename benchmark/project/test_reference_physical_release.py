"""Distinguish adverse household outcomes from corrupt/unbound physics."""
import unittest
from .reference_physics_results import integrity_failures


class PhysicalInformationTests(unittest.TestCase):
    def test_adverse_service_is_not_an_engineering_rejection_filter(self):
        check={'checks':{'B_service_execution':False,'B_EV_departure_target':False,
                         'B_electrical_supply':False,'recovery_observable_residuals':False,
                         'pre_notice_trajectory_equal':True,'A_meter_closure':True}}
        self.assertEqual(integrity_failures(check),[])

    def test_unreliable_pair_remains_diagnostic_and_unknown(self):
        check={'checks':{'B_service_execution':False,'pre_notice_trajectory_equal':False,
                         'B_program_energy':False,'readback_complete':False}}
        self.assertEqual(set(integrity_failures(check)),{'pre_notice_trajectory_equal','B_program_energy','readback_complete'})


if __name__=='__main__':unittest.main()
