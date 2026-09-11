"""Real native application ledger checks; no planner/model API or upstream edits."""
from copy import deepcopy
import unittest

from eb_execution import ordinary,physical_defaults,replay
from native_execution_diagnostics import diagnose_native_execution


def run_native(start,end,*,enabled=True):
    config=physical_defaults()
    for device in config.values():device['present']=False
    config['water_heater'].update(present=True,normal_start_h=20,normal_end_h=22)
    original_plan=ordinary(config)
    original={'eb_appliance_config':config,'eb_ordinary_plan':original_plan}
    plan=deepcopy(original_plan)
    plan['appliances'].update(water_heater_preheat=enabled,
        water_heater_preheat_start_h=start,water_heater_preheat_end_h=end)
    native=replay(original,plan,{'decision_h':0,'event':{'trigger_h':1,'end_h':2}},proposal=True)
    # simulate_live persists this exact application object with sim_h and kind.
    trace={'execution':{'applications':native['applications']}}
    return trace,native


class NativeExecutionDiagnosticTests(unittest.TestCase):
    def test_accepted_midnight_detected_using_real_ledger_and_writer(self):
        trace,native=run_native(0,2);before=deepcopy(trace)
        result=diagnose_native_execution(trace)
        self.assertFalse(result['execution_compatible'])
        issue=next(i for i in result['issues'] if i['code']=='native_water_midnight_start_fallback')
        self.assertEqual(issue['application_kind'],'proposal')
        self.assertEqual(issue['sim_h'],72)
        self.assertTrue(issue['applied_actions']['water_heater_preheat'])
        actual=next(r for r in native['rows'] if r['sim_h']==72)
        self.assertGreater(actual['model_power_kw']['water_heater'],0)
        self.assertEqual(actual['actuators']['water_heater'],40)
        self.assertEqual(trace,before)

    def test_accepted_overnight_detected_from_real_application(self):
        trace,native=run_native(23,1)
        result=diagnose_native_execution(trace)
        self.assertFalse(result['execution_compatible'])
        self.assertIn('native_water_nonincreasing_window',[i['code'] for i in result['issues']])
        actual=next(r for r in native['rows'] if r['sim_h']==95)
        self.assertEqual(actual['actuators']['water_heater'],40)
        self.assertEqual(actual['model_power_kw']['water_heater'],0)

    def test_disabled_request_does_not_create_false_positive(self):
        trace,_=run_native(0,2,enabled=False)
        self.assertTrue(diagnose_native_execution(trace)['execution_compatible'])

    def test_rejected_requested_window_is_not_treated_as_applied(self):
        trace,_=run_native(0,12) # Native contract rejects more than eight hours.
        proposal=next(a for a in trace['execution']['applications'] if a['kind']=='proposal')
        self.assertTrue(proposal['rejections'])
        self.assertNotIn('water_heater_preheat',proposal['applied_actions'])
        self.assertTrue(diagnose_native_execution(trace)['execution_compatible'])

    def test_native_normalized_start_uses_applied_instead_of_requested(self):
        trace,_=run_native(0,8) # Native bounding shortens this window from its end.
        proposal=next(a for a in trace['execution']['applications'] if a['kind']=='proposal')
        self.assertEqual(proposal['requested_actions']['water_heater_preheat_start_h'],0)
        self.assertGreater(proposal['applied_actions']['water_heater_preheat_start_h'],0)
        self.assertTrue(diagnose_native_execution(trace)['execution_compatible'])

    def test_unverifiable_ledger_fails_closed(self):
        self.assertFalse(diagnose_native_execution({})['execution_compatible'])
        result=diagnose_native_execution({'execution':{'applications':[{'requested_actions':{}}]}})
        self.assertFalse(result['execution_compatible'])

    def test_empty_native_actions_are_valid(self):
        result=diagnose_native_execution({'execution':{'applications':[{'sim_h':72,'kind':'proposal','applied_actions':{}}]}})
        self.assertTrue(result['execution_compatible'])
        self.assertEqual(result['checked_enabled_water_commands'],0)


if __name__=='__main__':unittest.main()
