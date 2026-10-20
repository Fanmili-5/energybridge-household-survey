"""Independent room-unit switching, including disabled/unchanged second units."""
import unittest
from .kernel.multi_ac import thermostat_state


class MultiACTests(unittest.TestCase):
    def test_different_cooling_targets_do_not_share_first_unit_state(self):
        self.assertEqual(thermostat_state(28, -20, 26, True),(0,1))
        self.assertEqual(thermostat_state(28, -20, 30, True),(0,0))

    def test_heating_and_permission_remain_independent(self):
        self.assertEqual(thermostat_state(19,22,40,True),(1,0))
        self.assertEqual(thermostat_state(19,18,40,True),(0,0))
        self.assertEqual(thermostat_state(19,22,40,False,(1,1)),(0,0))

    def test_hysteresis_latches_until_opposite_boundary(self):
        self.assertEqual(thermostat_state(26, -20,26,True,(0,1)),(0,1))
        self.assertEqual(thermostat_state(25.8,-20,26,True,(0,1)),(0,0))
        self.assertEqual(thermostat_state(26.2,-20,26,True),(0,1))


if __name__=='__main__':unittest.main()
