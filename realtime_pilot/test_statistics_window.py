"""Fixed-duration accounting never truncates or fabricates simulation evidence."""
from copy import deepcopy
import unittest
from native_scenario import statistics_window, window
from native_presentation import metrics


class StatisticsWindowTests(unittest.TestCase):
    def original(self,arrival=22,departure=8):
        return {'devices':{'home_ev':{}},'eb_appliance_config':{'ev':{'arrival_h':arrival,'departure_h':departure}}}

    def test_ev_cycle_covers_arrival_for_every_legal_clock_pair(self):
        for a in range(144):
            for d in range(144):
                if a==d:continue
                original=self.original(a/6,d/6);s=statistics_window(original)
                arrival=a/6+(24 if a<d else 0)
                self.assertLess(s['start_sim_h'],arrival)
                self.assertLess(arrival,s['end_sim_h'])
                self.assertAlmostEqual(s['end_sim_h']-s['start_sim_h'],24)
                self.assertGreaterEqual(window(original)['end_sim_h'],s['end_sim_h'])

    def test_no_ev_day_and_later_task_display_are_separate(self):
        original={'devices':{},'eb_appliance_config':{}}
        self.assertEqual(statistics_window(original)['start_sim_h'],0)
        self.assertEqual(window(original)['end_sim_h'],24)
        original['devices']['washer']={'earliest_h':23,'deadline_h':10}
        self.assertEqual(window(original)['end_sim_h'],34)
        self.assertEqual(statistics_window(original)['end_sim_h'],24)

    def fixture(self):
        original=self.original();scenario={'evaluation_window':window(original),'statistics_window':statistics_window(original),
            'event':{'trigger_h':19,'end_h':20}}
        rows=[{'start_h':i/6,'end_h':(i+1)/6,'kwh':1 if i<48 else 2,
               'unit_price':.5 if i<144 else 1.5} for i in range(192)]
        for r in rows:r['cost_normalized']=r['kwh']*r['unit_price']
        run={'electricity':rows,'temperature':[{'end_h':19.5,'c':25}],
             'native':{'day_ahead_price_metrics':{'available':True,'price_unit':'normalized TOU cost/kWh',
               'priced_energy_kwh':sum(r['kwh'] for r in rows),'total_cost_eur':sum(r['cost_normalized'] for r in rows)}},
             'horizon':32,'idf_sha256':'same','weather_sha256':'same'}
        return scenario,run

    def test_only_24_hours_count_and_tariff_uses_each_interval(self):
        scenario,run=self.fixture();v=metrics(run,run,scenario)
        self.assertEqual(v['original']['daily_kwh'],288)
        self.assertEqual(v['original']['daily_cost_normalized'],96+144)
        self.assertEqual(v['comparison_window']['start_sim_h'],8)
        self.assertEqual(v['simulation_window']['start_sim_h'],0)
        changed=deepcopy(run)
        for r in changed['electricity'][:48]:r['kwh']+=100;r['cost_normalized']=r['kwh']*r['unit_price']
        p=changed['native']['day_ahead_price_metrics'];p['priced_energy_kwh']+=4800;p['total_cost_eur']+=2400
        self.assertEqual(metrics(run,changed,scenario)['relative_cost_reduction'],0)

    def test_missing_or_mispriced_intervals_are_rejected(self):
        scenario,run=self.fixture()
        for bad in ('gap','cost'):
            changed=deepcopy(run)
            if bad=='gap':changed['electricity'][100]['start_h']+=1/6
            else:changed['electricity'][100]['cost_normalized']+=1
            with self.assertRaises(ValueError):metrics(run,changed,scenario)

    def test_old_records_keep_their_full_horizon(self):
        scenario,run=self.fixture();scenario.pop('statistics_window')
        self.assertEqual(metrics(run,run,scenario)['original']['daily_kwh'],336)


if __name__=='__main__':unittest.main()
