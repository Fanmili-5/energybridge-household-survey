"""Regression tests for interpretation, exposure denominator and interval timing."""
import copy
import unittest
from regenerate import duration, energy_summary, room_metrics


class SummaryTests(unittest.TestCase):
    def test_midnight_and_gap_durations(self):
        result = duration([1430, 1440, 1460], '2025-06-04')
        self.assertEqual(result['total_minutes'], 30)
        self.assertEqual(result['longest_continuous_minutes'], 20)
        self.assertEqual(result['periods'][0]['end'], '2025-06-05T00:10')
        self.assertEqual(len(result['periods']), 2)

    def test_occupancy_and_signed_temperature_not_comfort(self):
        def arm(temperatures, occupants):
            return {'air_C': temperatures, 'radiant_C': temperatures, 'occupants': occupants, 'RH_percent': [50] * 4}
        data = {'A': arm([24, 24, 24, 24], [1, 1, 0, 1]),
                'B': arm([26, 22, 28, 27], [1, 1, 1, 0])}
        out = room_metrics(data, (0, 40), '2025-06-04')
        self.assertEqual(out['common_occupied_air_B_minus_A_range_C'], [-2, 2])
        self.assertEqual(out['common_room_occupied_minutes'], 20)
        self.assertEqual(out['air_delta_durations']['1.0']['B_warmer']['total_minutes'], 10)
        self.assertEqual(out['air_delta_durations']['1.0']['B_cooler']['total_minutes'], 10)
        self.assertEqual(out['air_delta_durations']['2.0']['B_warmer']['total_minutes'], 0)
        self.assertIsNone(out['subjective_comfort_or_acceptance'])

    def test_actual_exposure_keeps_other_arm_empty_periods(self):
        def arm(temp,occupants):
            return {'air_C':temp,'radiant_C':temp,'occupants':occupants,'RH_percent':[50]*3}
        data={'A':arm([20,20,20],[0,1,0]),'B':arm([24,20,25],[1,1,1])}
        out=room_metrics(data,(0,30),'2025-06-04')
        self.assertEqual(out['common_room_occupied_minutes'],10)
        self.assertEqual(out['common_occupied_air_B_minus_A_range_C'],[0,0])
        self.assertEqual(out['B']['actual_occupied_exposure']['occupied_minutes'],30)
        self.assertEqual(out['B']['other_arm_empty_exposure']['occupied_minutes'],20)
        self.assertEqual(len(out['B']['other_arm_empty_exposure']['occupied_periods']),2)
        self.assertEqual(out['B']['own_occupied_same_clock_air_delta_durations']['1.0']['B_warmer']['total_minutes'],20)
        bins=out['B']['actual_occupied_exposure']['air_temperature_bins']
        self.assertEqual(sum(b['total_minutes']for b in bins),30)
        self.assertEqual(next(b for b in bins if b['lower_inclusive_C']==24)['total_minutes'],20)

    def test_completed_tasks_do_not_imply_equivalent_comfort_or_saving(self):
        side = {'service_outcomes': {'all_known_program_services_completed': True,
                 'unexecuted_batches': [], 'future_unexecuted_batches': [], 'failed_retrieval_batches': [],
                 'retrieval_pending_after_horizon': [], 'no_recovery_boundary': 'no rescue assumed'},
                'EV_trips': [], 'water_delivery': [], 'given_electrical_supply_feasible_at_10min_resolution': True,
                'primary_energy_kWh': {'facility': 10}, 'rollout_energy_kWh': {'facility': 50}}
        source = {'A': side, 'B': copy.deepcopy(side),
                  'recovery': {'status': 'within_declared_tolerances_to_horizon', 'end_min': 12960},
                  'source_B_constraint_flags': [], 'delta_primary_kWh': {'facility': -1, 'controlled_portfolio': -1},
                  'delta_rollout_kWh': {'facility': -0.1, 'controlled_portfolio': -0.1}}
        result = energy_summary(source, '2025-06-04')
        self.assertFalse(result['subjective_comfort_equivalence_verified'])
        self.assertFalse(result['energy_saving_or_human_acceptance_inferred'])
        self.assertFalse(result['known_task_delivery_deficit_present'])
        source['B']['service_outcomes']['all_known_program_services_completed'] = False
        source['B']['service_outcomes']['future_unexecuted_batches'] = [{}] * 8
        result = energy_summary(source, '2025-06-04')
        self.assertTrue(result['known_task_delivery_deficit_present'])
        self.assertEqual(result['observation']['facility_B_minus_A_kWh'], -0.1)
        self.assertIn('unmet_task_or_delivery_present;lower_consumption_includes_service_difference', result['qualifiers'])


if __name__ == '__main__':
    unittest.main()
