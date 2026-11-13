"""Heater window compilation; actual physics is verified separately."""
import copy
import unittest
from national_idf.case_commands import CaseTimeline
from national_idf.eb_water_heater_window import MODE,available,effective_setpoint,validate
from tests.synthetic_inputs import case,domain
class HeaterWindowTests(unittest.TestCase):
 def example(self):
  c=case();c['controls'].update(water_heater_window_encoding=MODE,water_heater_windows_by_date={'2007-01-01':[dict(start_min=960,end_min=1200)],'2007-01-02':[]});return c
 def test_window_is_half_open_and_empty_tail_is_off(self):
  c=self.example();self.assertFalse(available(c,'2007-01-01',959));self.assertTrue(available(c,'2007-01-01',960));self.assertFalse(available(c,'2007-01-01',1200));self.assertFalse(available(c,'2007-01-02',1000))
 def test_compiler_preserves_draws_and_requested_temperature(self):
  c=self.example();before=copy.deepcopy(c);a=CaseTimeline(c,domain());frames=[a.frame(i) for i in range(a.steps)]
  self.assertEqual(80,sum(f['mixed_water']['requested_volume_L'] for f in frames));self.assertEqual(c,before)
  self.assertEqual(48,sum(f['control']['water_heater_window_open'] for f in frames))
  for f in frames:
   control=f['control'];self.assertEqual(55,control['tank_target_C'])
   self.assertEqual(55 if control['water_heater_window_open'] else 0,effective_setpoint(control))
 def test_legacy_without_window_keeps_original_target(self):
  a=CaseTimeline(case(),domain());self.assertTrue(a.frame(0)['control']['water_heater_window_open']);self.assertEqual(55,effective_setpoint(a.frame(0)['control']))
 def test_multiple_window_and_off_grid_are_rejected(self):
  c=self.example();c['controls']['water_heater_windows_by_date']['2007-01-01']*=2
  with self.assertRaises(Exception):validate(c,domain())
  c=self.example();c['controls']['water_heater_windows_by_date']['2007-01-01'][0]['start_min']=961
  with self.assertRaises(Exception):validate(c,domain())
 def test_mode_cannot_silently_disappear(self):
  c=self.example();del c['controls']['water_heater_window_encoding']
  with self.assertRaises(Exception):validate(c,domain())
if __name__=='__main__':unittest.main()
