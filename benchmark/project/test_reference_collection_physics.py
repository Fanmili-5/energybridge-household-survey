"""A-side initial state and presentation/protocol boundaries."""
import unittest
from .reference_collection_physics import initial_ev


class InitialStateTest(unittest.TestCase):
    def test_charge_is_integrated_but_departure_at_decision_is_not_applied_twice(self):
        pack={'anchor':'2025-01-01','world':{'parameter_pack':{'devices':[{'asset_id':'ev1','types':['ev'],
            'parameters':{'capacity_kwh':60,'charger_kw':7.4,'efficiency':.92,'target_soc':.85,'min_soc':.2}}]}}}
        annual={'initial_states':{'EV_SOC':.5},'EV_battery_energy_events':[
            {'kind':'charge','start_min':420,'end_min':540,'battery_kWh':6},
            {'kind':'traction','start_min':480,'end_min':480,'battery_kWh':-5},
            {'kind':'traction','start_min':400,'end_min':400,'battery_kWh':-2}]}
        state=initial_ev(pack,annual,'2025-01-01')
        self.assertEqual(state['initial_energy_kWh'],31)
        self.assertEqual(state['minimum_SOC'],.2)
        self.assertNotIn('A',state);self.assertNotIn('B',state)

    def test_missing_vehicle_is_not_a_zero_soc_vehicle(self):
        self.assertEqual(initial_ev({'world':{'parameter_pack':{'devices':[]}}},{},'2025-01-01'),{'status':'not_installed'})


if __name__=='__main__':unittest.main()
