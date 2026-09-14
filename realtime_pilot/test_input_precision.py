"""Precision contract and zone/substep accounting; no model/network calls."""
from types import SimpleNamespace
import unittest
from native_clock import synchronized_appliances
from common import normalize_answers
from paired_contract import LOOKUP, prepare, sanitize_profile
from questionnaire_persona import visible_profile
from verify_paired_physics import answers
from survey_time import clock_options, duration_options, start_hour

class PrecisionTests(unittest.TestCase):
    def test_ten_minute_grid_and_decimal_answers_reach_context(self):
        starts=[start_hour(value) for value,label in clock_options(aliases=True)]
        self.assertEqual(len(starts),144)
        self.assertTrue(all(abs((b-a)*60-10)<1e-7 for a,b in zip(starts,starts[1:])))
        self.assertEqual([round(float(v)*60) for v,_ in duration_options()],list(range(10,241,10)))
        raw=answers();raw.update(H_ac_temp='26.3',P_AC_CHANGE='0.3',P_AC_RANGE='24.3_26.7',H_washer='18.1666666667',T_washer=str(70/60),E_washer='8.16666666667',D_washer='23.1666666667')
        profile=sanitize_profile(normalize_answers(raw,list(LOOKUP),LOOKUP))
        ordinary,_=prepare(profile,'precision_contract')
        self.assertAlmostEqual(ordinary['devices']['washer']['start_h'],18+10/60)
        self.assertEqual(ordinary['devices']['ac']['setpoint'],26.3)
        context=visible_profile(profile,list(LOOKUP.values()))
        item=next(r for r in context['stated_attitudes'] if r['question_id']=='P_AC_RANGE')
        self.assertEqual(item['answer'],'24.3—26.7℃')

    def test_invalid_precision_rejected_without_silent_rounding(self):
        for value in ('26_24','24_24','17_26','24_31','24.35_26.7','NaN_26','24_Infinity'):
            with self.subTest(value=value),self.assertRaises(ValueError):
                normalize_answers({'P_AC_RANGE':value},['P_AC_RANGE'],LOOKUP)
        for key,value in [('H_washer','18.2'),('H_ac_temp','26.35'),('T_washer','1.2')]:
            with self.subTest(key=key),self.assertRaises(ValueError):normalize_answers({key:value},[key],LOOKUP)

    def test_boundary_execution_holds_substeps_and_leaves_prediction_untouched(self):
        class Suite:
            def __init__(self):self.calls=[]
            def step(self,h,dt):self.calls.append((h,dt));return {'washer':1.5}
        live,forecast=Suite(),Suite();loop=SimpleNamespace(appliance_suite=live)
        writes=[]
        def writer(ex,state,loop,powers,h):
            writes.append(h);ex.set_actuator_value(state,'heater',55 if h<24 else 50)
            ex.set_actuator_value(state,'washer',powers.get('washer',0))
        runner=SimpleNamespace(_write_appliance_actuators=writer)
        values={};ex=SimpleNamespace(zone_time_step=lambda state:1/6,set_actuator_value=lambda state,k,v:values.update({k:v}))
        original=Suite.step
        with synchronized_appliances(runner,Suite,[loop]) as audit:
            for h in [23+50/60-1e-14,23+52/60,23+55/60,24,24,24+2/60,24+10/60]:
                powers=live.step(h,1/6);runner._write_appliance_actuators(ex,None,loop,powers,h)
            forecast.step(24+7/60,1/6)
            self.assertEqual(len(live.calls),3)
            self.assertEqual(len(writes),3)
            self.assertEqual(len(forecast.calls),1)
            self.assertEqual(values,{'heater':50,'washer':1.5})
            self.assertEqual(audit['held_substeps'],4)
            self.assertEqual(audit['zone_step_hours'],[1/6])
        self.assertIs(Suite.step,original)
        self.assertIs(runner._write_appliance_actuators,writer)

    def test_decimal_deadline_and_cross_midnight_are_preserved(self):
        raw=answers();raw.update(H_washer='23.1666666667',T_washer=str(70/60),E_washer='23',D_washer='0.333333333333')
        profile=sanitize_profile(normalize_answers(raw,list(LOOKUP),LOOKUP))
        ordinary,_=prepare(profile,'precision_overnight')
        task=ordinary['devices']['washer']
        self.assertAlmostEqual(task['duration_h']*60,70)
        self.assertAlmostEqual(task['deadline_h']*60,20)
        raw['D_washer']='0.166666666667'
        with self.assertRaises(ValueError):prepare(sanitize_profile(normalize_answers(raw,list(LOOKUP),LOOKUP)),'too_short')
