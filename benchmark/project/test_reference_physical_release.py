"""Distinguish adverse household outcomes from corrupt/unbound physics."""
import unittest
import hashlib
import tempfile
from pathlib import Path
from .reference_physics_results import integrity_failures,mixed_water_delivery,native_numerical_failures
from .reference_weather_audit import native_weather_review


class PhysicalInformationTests(unittest.TestCase):
    def test_weather_check_covers_cross_year_history_and_recovery_not_unrelated_months(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'weather.epw'
            p.write_text('\n'*8+'2005,12,31,24,0,?,0,0,113\n2005,1,9,1,0,?,0,0,255\n2005,7,1,1,0,?,0,0,130\n')
            h=hashlib.sha256(p.read_bytes()).hexdigest()
            review=native_weather_review(p,h,'RunPeriod,case,12,15,2025,1,9,2026;')
            self.assertFalse(review['passed'])
            self.assertEqual([r['RH_percent']for r in review['invalid_RH_records']],[113,255])
            self.assertEqual(review['weather_sha256'],h)
            self.assertFalse(review['source_modified'])

    def test_weather_native_tolerance_missing_sentinel_and_outside_period_are_explicit(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'weather.epw'
            p.write_text('\n'*8+'2005,1,1,1,0,?,0,0,110\n2005,1,2,1,0,?,0,0,999\n2005,7,1,1,0,?,0,0,113\n')
            h=hashlib.sha256(p.read_bytes()).hexdigest()
            self.assertTrue(native_weather_review(p,h,'RunPeriod,case,1,1,2025,1,9,2025;')['passed'])
            with self.assertRaisesRegex(ValueError,'WEATHER_INPUT_HASH_MISMATCH'):
                native_weather_review(p,'0'*64,'RunPeriod,case,1,1,2025,1,9,2025;')

    def test_successful_process_with_internal_nonconvergence_is_not_reliable_consequences(self):
        text='** Warning ** WetBulb not converged after 101 iterations(PsyTwbFnTdbWPb)'
        self.assertEqual(native_numerical_failures(text),['wetbulb_iteration_not_converged'])
        self.assertEqual(native_numerical_failures('** Severe  ** invalid native state'),['native_severe_error'])

    def test_intermediate_iteration_range_warning_does_not_invent_failure(self):
        text='** Warning ** Temperature out of range [-100. to 200.] (PsyPsatFnTemp)\nRoutine=PsyTwbFnTdbWPb'
        self.assertEqual(native_numerical_failures(text),[])

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
