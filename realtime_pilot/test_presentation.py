"""Charts must preserve executed times, units and the participant's evidence."""
from copy import deepcopy
import unittest
from presentation import segments,thermal_chart,plan_chart
from paired_contract import participant_view
from household_config import occupancy_schedule

class PresentationTests(unittest.TestCase):
    def scenario(self):
        return {'decision_h':17,'event':{'trigger_h':18,'end_h':19},'evaluation_window':{'start_sim_h':72,'end_sim_h':98}}

    def test_overnight_segments_and_power_are_literal(self):
        s=segments([[23,26,.5]],'washer',{'washer':2000})[0]
        self.assertEqual((s['start_h'],s['end_h']),(23,26))
        self.assertEqual(s['label'],'1.000 kW')
        self.assertIn('次日02:00',s['description'])
        wh=segments([[18,19,40]],'electric_water_heater',{})[0]
        self.assertIn('待机',wh['label']);self.assertNotIn('kW',wh['description'])

    def test_recovery_temperature_and_chart_enter_same_sft_view(self):
        original={'devices':{'ac':{'active':True}}}
        base={'temperature':[{'end_h':89,'c':24.34},{'end_h':90.5,'c':25.12},{'end_h':92,'c':24.28}]}
        changed=deepcopy(base);changed['temperature'][-1]['c']=28.26
        thermal=thermal_chart(original,base,changed,self.scenario())
        self.assertEqual(thermal['periods'][2]['proposal'],'28.3—28.3℃')
        self.assertEqual(thermal['series']['proposal'][-1]['hour'],20)
        metrics={key:0 for key in ['daily_kwh','daily_cost_cny','event_kwh','event_mean_kw','event_temp_min_c','event_temp_max_c']}
        d={key:'' for key in ['title','notice','assumptions','question','selection_reason','execution_notice']}
        d.update(rows=[],context={'facts':[]},prediction={'original':metrics,'proposal':metrics},
                 schedule_chart=plan_chart([],self.scenario()),temperature_chart=thermal)
        view=participant_view(d)
        self.assertEqual(view['render_contract_version'],'eb.participant_view.v2')
        self.assertNotIn('temperature_chart',view)
        self.assertNotIn('selection_reason',view)
        self.assertNotIn('timeline',view)
        recovery=next(m for m in view['metrics'] if m['label'].startswith('响应结束后'))
        self.assertEqual(recovery['proposal'],'28.3—28.3℃')
        self.assertEqual(view['schedule_chart']['end_h'],26)
        thermal['series']['proposal'][-1]['c']=99
        self.assertEqual(recovery['proposal'],'28.3—28.3℃')

    def test_shift_summary_keeps_overnight_direction(self):
        from presentation import change_summary
        row={'active':True,'changed':True,'original':[{'start_h':23,'end_h':25,'label':'1.000 kW'}],
             'proposal':[{'start_h':24,'end_h':26,'label':'1.000 kW'}]}
        self.assertIn('推迟 60 分钟',change_summary(row))
        self.assertIn('23:00 → 24:00',change_summary(row))

    def test_water_timings_keep_gaps_and_fixtures_separate(self):
        from service_outcomes import water_periods
        def r(start,stop,temp,device='Showers_unit1'):
            return {'equipment':device,'start_h':start,'end_h':stop,'mixed_c':temp,'target_c':40}
        periods=water_periods({'draws':[r(95.5,95.75,35),r(95.75,96,42),r(96,96.25,36),r(96.5,96.75,34),r(95.5,95.75,38,'Sinks_unit1')]})
        shower=next(p for p in periods if p['label'].startswith('淋浴') and '23:30' in p['label'])
        self.assertEqual(len(shower['below_target_periods']),2)
        self.assertEqual(shower['below_target_periods'][1]['end_h'],24.25)
        self.assertEqual(len(periods),3)
        self.assertIn('15分钟',shower['detail'])

    def test_occupancy_answer_ends_at_22_not_23(self):
        p={k:{'value':v} for k,v in {'B02':'3','B04':'mostly_absent','F_EVENING':'mostly_away'}.items()}
        s=occupancy_schedule(p)
        self.assertEqual(s['hourly_fraction'][21],0)
        self.assertEqual(s['hourly_fraction'][22],1)
        self.assertIn('unasked 22:00-08:00',s['interpretation'])

if __name__=='__main__':unittest.main()
