"""Distinguish adverse household outcomes from corrupt/unbound physics."""
import unittest
from .reference_physics_results import integrity_failures,mixed_water_delivery


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

    def test_mixed_water_reports_actual_cold_delivery_without_success_label(self):
        meta={'tank_name':'TANK','hot_water_model':'native_mixed_water_plant','water_needs':[{'release_min':480,'deadline_min':500,'quantity':30,'target_C':40}]}
        trace={'Water Use Equipment Total Volume|SHOWER':{'unit':'m3','native_aggregation':'Sum','values':[[480,.01],[490,.02]]},
               'Water Use Equipment Mixed Water Temperature|SHOWER':{'unit':'C','values':[[480,20],[490,35]]}}
        row=mixed_water_delivery(meta,trace,480,500)
        self.assertEqual(row['delivered_mixed_liters'],30);self.assertEqual(row['requested_mixed_liters'],30)
        self.assertAlmostEqual(row['volume_weighted_reported_temperature_C'],30)
        self.assertEqual(row['minimum_active_10min_mean_C'],20);self.assertFalse(row['service_pass_inferred'])
        del trace['Water Use Equipment Total Volume|SHOWER']['native_aggregation']
        self.assertEqual(mixed_water_delivery(meta,trace,480,500)['status'],'unavailable')


if __name__=='__main__':unittest.main()
