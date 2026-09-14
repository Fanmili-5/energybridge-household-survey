"""Service evidence semantics, independent of acceptance and upstream heuristics."""
from copy import deepcopy
from types import SimpleNamespace
import unittest
from native_clock import synchronized_appliances
from native_service_evidence import evidence, service_text
from native_support import upstream

class ServiceEvidenceTests(unittest.TestCase):
    def run_ev(self, config):
        upstream()
        from energybridge.simulation.appliance_sim import ApplianceSuite
        cfg={'ev':{'present':True,'arrival_h':18,'departure_h':7.5,'initial_soc':.3,'target_soc':.8,**config}}
        live=ApplianceSuite(cfg,sim_days=1);reference=ApplianceSuite(cfg,sim_days=1)
        loop=SimpleNamespace(appliance_suite=live)
        runner=SimpleNamespace(_write_appliance_actuators=lambda *a:None)
        with synchronized_appliances(runner,ApplianceSuite,[loop]) as audit:
            for i in range(144):
                h=i/6
                actual=live.step(h,1/6)
                expected=reference.step(h+1e-9,1/6)
                self.assertEqual(actual,expected)
                self.assertEqual(live._ev._soc,reference._ev._soc)
                if i==45:self.assertNotEqual(audit['ev_state_trace'][-1]['soc_before'],audit['ev_state_trace'][-1]['soc_after'])
        result=evidence(audit,{}, {'appliances':cfg})
        return audit,result

    def test_departure_is_before_driving_not_day_end(self):
        audit,result=self.run_ev({})
        ev=result['ev'];self.assertEqual(ev['status'],'observed')
        departure=ev['departures'][0]
        self.assertEqual(departure['time_h'],7.5)
        self.assertEqual(departure['soc_before_drive'],audit['ev_state_trace'][45]['soc_before'])
        self.assertFalse(ev['departure_after_arrival_observed'])
        self.assertEqual(ev['departure_after_arrival_h'],31.5)
        self.assertNotIn('未验证',service_text('home_ev',{'service_evidence':result}))
        self.assertNotIn('次日',service_text('home_ev',{'service_evidence':result}))

    def test_same_day_departure_and_missing_trace(self):
        audit,result=self.run_ev({'arrival_h':0,'departure_h':18,'charger_kw':.01})
        self.assertTrue(result['ev']['departure_after_arrival_observed'])
        self.assertFalse(result['ev']['departures'][0]['target_met'])
        broken=deepcopy(audit);broken['ev_state_trace'].pop(20)
        missing=evidence(broken,{}, {'appliances':{'ev':{'present':True}}})
        self.assertEqual(missing['ev']['status'],'unavailable')
        self.assertIsNone(service_text('home_ev',{'service_evidence':missing}))

    def test_native_first_boundary_and_terminal_callback(self):
        audit,result=self.run_ev({})
        audit['ev_state_trace']=audit['ev_state_trace'][1:]
        terminal=deepcopy(audit['ev_state_trace'][-1]);terminal.update(start_h=24,end_h=24+1/6,soc_after=.99)
        audit['ev_state_trace'].append(terminal)
        observed=evidence(audit,{}, {'appliances':{'ev':{'present':True}}})['ev']
        self.assertEqual(observed['status'],'observed')
        self.assertEqual(observed['day_end_soc'],result['ev']['day_end_soc'])
        self.assertEqual(observed['observed_start_h'],1/6)

    def test_tank_observation_never_becomes_delivered_water_success(self):
        physical={'Water Heater Tank Temperature|WATER HEATER_TANK_UNIT1':[
            {'start_h':20+5/6,'end_h':21,'value':42.75,'unit':'C'},
            {'start_h':21,'end_h':21+1/6,'value':61,'unit':'C'}]}
        result=evidence({},physical,{'appliances':{'water_heater':{'present':True,'bath_required_h':21}}})
        self.assertEqual(result['water_heater']['tank_interval']['mean_c'],42.75)
        self.assertEqual(result['water_heater']['delivered_water_status'],'unverified')
        text=service_text('electric_water_heater',{'service_evidence':result})
        self.assertIn('42.8℃',text);self.assertNotIn('未验证',text)
        self.assertIn('水箱温度',text);self.assertNotIn('出水温度',text)
        self.assertNotIn('达标',text)
        missing=evidence({},physical,{'appliances':{'water_heater':{'present':True,'bath_required_h':23}}})
        self.assertEqual(missing['water_heater']['status'],'unavailable')

    def test_missing_pair_service_is_omitted_without_inventing_success(self):
        from native_presentation import service_rows
        original={'devices':{'home_ev':{},'electric_water_heater':{},'washer':{}}}
        empty={'task_outcomes':{'washer':{'completed':False}}}
        rows=service_rows(original,empty,empty)
        self.assertEqual([r['device_id'] for r in rows],['washer'])
        self.assertEqual(rows[0]['proposal'],'截至24:00未完成')
