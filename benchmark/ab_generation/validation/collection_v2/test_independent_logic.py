"""Mutation checks for the independent literal auditor, using a static fixture."""
import copy
import unittest
from pathlib import Path
from benchmark.ab_generation.common import read
from .independent_logic import literal_errors


class IndependentLogicTests(unittest.TestCase):
    def setUp(self):
        self.c=read(Path(__file__).resolve().parents[2]/'examples/family.json')
        self.b=copy.deepcopy(self.c['A'])

    def test_static_reference_has_no_engineering_error(self):
        self.assertEqual(literal_errors(self.c,self.b,['wash','dishes']),[])

    def test_detects_early_retrieval_and_capability_violation(self):
        self.b['operations'][1].update(start_min=800,end_min=810)
        self.assertIn('TAKEN_OUT_BEFORE_FINISHED',literal_errors(self.c,self.b,['wash']))
        self.c['needs'][1]['timer_allowed']=False
        self.assertIn('UNSUPPORTED_TIMER',literal_errors(self.c,self.b,['dishes']))

    def test_detects_two_programs_on_one_machine_and_duration_changes(self):
        self.b['tasks'][1].update(start_min=770,end_min=860)
        self.assertIn('MACHINE_RUNS_TWO_PROGRAMS',literal_errors(self.c,self.b,['wash']))
        self.b['tasks'][1]['end_min']=861
        self.assertIn('DURATION_CHANGED',literal_errors(self.c,self.b,['wash']))

    def test_EV_shortfall_is_not_structural_failure_but_unplugged_control_is(self):
        ev=next(r for r in self.b['controls'] if r['kind']=='ev_charge_window')
        ev['start_min']=1790
        self.assertEqual(literal_errors(self.c,self.b,[]),[])
        ev['end_min']=1810
        self.assertIn('EV_WITHOUT_CONNECTION',literal_errors(self.c,self.b,[]))

    def test_detects_thermal_deadband_and_hardware_errors(self):
        self.b['controls'][0]['heating_setpoint_C']=27
        self.b['controls'][2]['value_C']=70
        errors=literal_errors(self.c,self.b,[])
        self.assertIn('INVALID_AC_CONTROL',errors);self.assertIn('INVALID_TANK_CONTROL',errors)

    def test_censored_unchanged_calendar_boundary_is_outside_B_scope(self):
        r=copy.deepcopy(next(r for r in self.b['controls'] if r['kind']=='ev_charge_window'))
        r.update(need_id='source_boundary',start_min=0,end_min=100)
        self.c['A']['controls'].append(r);self.b['controls'].append(copy.deepcopy(r))
        self.assertEqual(literal_errors(self.c,self.b,[]),[])


if __name__=='__main__':unittest.main()
