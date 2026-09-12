"""Reported clocks must survive pinned EB construction and actual actuator writing.

No model API is called. The optional EP test exercises the same live baseline
path as production; enable with EB_TEST_NATIVE_EP=1 when EP is installed.
"""
import os
import tempfile
import unittest
from pathlib import Path

from common import normalize_answers
from paired_contract import LOOKUP, QUESTIONS, prepare, sanitize_profile
from household_config import build_household_config
from eb_execution import ordinary, physical_defaults, replay
from verify_paired_physics import answers


def profile_for(devices, **updates):
    raw=answers();raw.update(B05=devices);raw.update(updates)
    return sanitize_profile(normalize_answers(raw,list(LOOKUP),LOOKUP))


def overnight_profile():
    updates={}
    for device,hour,duration in [('washer','0.5','1.0'),('dishwasher','1.5','1.5'),('dryer','2.5','0.5')]:
        updates.update({f'H_{device}':hour,f'E_{device}':'22',f'D_{device}':'7',f'T_{device}':duration})
    return profile_for(['washer','dishwasher','dryer'],**updates)


class NativeScheduleFidelityTests(unittest.TestCase):
    def test_next_day_clock_is_projected_and_actually_written(self):
        profile=overnight_profile();original,scenario=prepare(profile,'overnight-fidelity')
        household=build_household_config(profile,QUESTIONS,original,'fidelity-household')
        result=replay(original,original['eb_ordinary_plan'],scenario,proposal=False,sim_days=5)
        for device,hour in [('washer',.5),('dishwasher',1.5),('dryer',2.5)]:
            with self.subTest(device=device):
                self.assertEqual(profile[f'H_{device}']['value'],f'{hour:g}')
                self.assertEqual(original['devices'][device]['start_h'],hour)
                self.assertEqual(original['eb_appliance_config'][device]['preferred_h'],24+hour)
                self.assertEqual(original['eb_ordinary_plan']['appliances'][f'{device}_start_h'],hour)
                self.assertEqual(result['services'][device][3]['scheduled_abs_h'],96+hour)
                actual=[r for r in result['rows'] if r['sim_h']>=96 and r['actuators'].get(device,0)>0]
                self.assertAlmostEqual(actual[0]['sim_h'],96+hour)
                source=household['field_sources'][f'appliances.{device}.preferred_h']
                self.assertEqual(source['rule'],'overnight_start_unwrap_v1')
                self.assertEqual(source['reported_clock_h'],hour)
                self.assertEqual(source['projected_window_hour'],24+hour)

    def test_same_day_clock_remains_unmodified(self):
        profile=profile_for(['washer'],H_washer='0.5',E_washer='0',D_washer='7',T_washer='1.0')
        original,_=prepare(profile,'same-day-fidelity')
        self.assertEqual(original['eb_appliance_config']['washer']['preferred_h'],.5)
        household=build_household_config(profile,QUESTIONS,original,'same-day')
        self.assertEqual(household['field_sources']['appliances.washer.preferred_h']['kind'],'questionnaire')

    def test_true_water_answers_normalize_but_unsupported_generation_is_rejected(self):
        for start,end in [('0','2'),('23','1'),('1','12'),('1','1')]:
            with self.subTest(start=start,end=end):
                profile=profile_for(['electric_water_heater'],H_electric_water_heater=start,D_electric_water_heater=end)
                self.assertEqual(profile['H_electric_water_heater']['value'],start)
                self.assertEqual(profile['D_electric_water_heater']['value'],end)
                with self.assertRaisesRegex(ValueError,'真实答案可以保存'):
                    prepare(profile,'water-not-supported')

    def test_midnight_water_native_writer_disagrees_with_native_power(self):
        # Regression evidence for the intake/generation boundary, not permission
        # to replace native execution with a locally invented heater policy.
        config=physical_defaults()
        for device in config.values():device['present']=False
        config['water_heater'].update(present=True,normal_start_h=0,normal_end_h=2)
        plan=ordinary(config)
        result=replay({'eb_appliance_config':config,'eb_ordinary_plan':plan},plan,
                      {'decision_h':16,'event':{'trigger_h':17,'end_h':18}},proposal=False)
        zero=next(row for row in result['rows'] if row['sim_h']==72)
        self.assertGreater(zero['model_power_kw']['water_heater'],0)
        self.assertEqual(zero['actuators']['water_heater'],40)

    @unittest.skipUnless(os.environ.get('EB_TEST_NATIVE_EP')=='1','Explicit native EP verification')
    def test_live_ep_preserves_next_day_task_start_and_energy(self):
        from closed_loop import simulate_live
        profile=overnight_profile();original,scenario=prepare(profile,'overnight-live-ep')
        # Historical custom-loop continuation, separate from native day-end collection.
        from evaluation_window import make_window
        scenario['evaluation_window']=make_window(original)
        request={'profile':profile,'original_plan':original,'scenario':scenario,
                 'questionnaire_snapshot':QUESTIONS,'household_id':'native-schedule-fidelity'}
        with tempfile.TemporaryDirectory(prefix='eb-schedule-fidelity-') as directory:
            result=simulate_live(Path(directory)/'baseline',request)
        for device,hour in [('washer',.5),('dishwasher',1.5),('dryer',2.5)]:
            with self.subTest(device=device):
                task=result['task_outcomes'][device]
                self.assertAlmostEqual(task['actual_start_sim_h'],96+hour)
                self.assertTrue(task['completed'])
                check=result['task_energy_checks'][device]
                self.assertAlmostEqual(check['actuator_expected_kwh'],check['metered_kwh'])
                self.assertGreater(check['metered_kwh'],0)


if __name__=='__main__':unittest.main()
