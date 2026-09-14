import json
from pathlib import Path
import unittest
from copy import deepcopy
from clean_collected_case import plan_pair, _shown_clock

BASE=Path(__file__).resolve().parents[1]/'examples/real-test-20260914'
class FirstStageCleaningTests(unittest.TestCase):
    def setUp(self):self.raw=json.loads((BASE/'full-collected-record.json').read_text());self.clean=json.loads((BASE/'cleaned-supervision.json').read_text())
    def test_saved_schedule_reproduces_two_cleaned_plans(self):
        original=deepcopy(self.raw['shown_to_participant'])
        self.assertEqual(set(self.clean),{'input','output'})
        self.assertEqual(set(self.clean['input']),{
            'household_profile','event_condition','no_dr_plan','agent_plan','displayed_results'
        })
        self.assertEqual(plan_pair(original)['no_dr_plan'],self.clean['input']['no_dr_plan'])
        self.assertEqual(plan_pair(original)['agent_plan'],self.clean['input']['agent_plan'])
        self.assertEqual(original,self.raw['shown_to_participant'])
        self.assertNotIn('load_history',json.dumps(self.clean))
        self.assertNotIn('signal',json.dumps(self.clean))
        self.assertEqual(set(self.clean['output']),{
            'decision','score','comfort_score','energy_score','vpp_score','comment'
        })
    def test_no_training_answer_or_feedback_is_lost_or_relabelled(self):
        i=self.clean['input'];profile=i['household_profile']
        def keys(value):
            if isinstance(value,dict):
                for key,child in value.items():
                    yield key
                    yield from keys(child)
            elif isinstance(value,list):
                for child in value:yield from keys(child)
        all_keys=set(keys(self.clean))
        for forbidden in ('question','selected_value','response_status','reported_fields','signal','end_status','schedule_window','notification_time'):
            self.assertNotIn(forbidden,all_keys)
        self.assertEqual(profile['household_facts_and_preferences']['household_size'],'3 people')
        self.assertEqual(profile['household_facts_and_preferences']['washing_machine_usual_start_time'],'19:40')
        self.assertEqual(profile['members'][0]['age_band'],'18-59')
        self.assertEqual(profile['members'][0]['task'],'Only small advances or delays are acceptable')
        self.assertIsInstance(profile['household_facts_and_preferences']['included_appliances'],list)
        for key in ('score','comfort_score','energy_score','vpp_score','comment'):
            self.assertEqual(self.clean['output'][key],self.raw['feedback'][key])
        self.assertEqual(self.clean['output']['decision'],self.raw['feedback']['choice'])
        self.assertNotIn('messages',self.clean)
        self.assertNotIn('auxiliary',self.clean)
        self.assertNotIn('provenance',self.clean)
        self.assertNotIn('comment',i)
    def test_event_and_cross_day_plan_survive_cleaning(self):
        condition=self.clean['input']['event_condition']
        self.assertEqual(condition['event_window'],{'start_time':'day_1 17:00','end_time':'day_1 18:00'})
        self.assertNotIn('notification_time',condition)
        self.assertEqual(condition['simulation_date'],self.raw['simulation_context']['simulation_start_date'])
        self.assertEqual(condition['season'],self.raw['simulation_context']['questionnaire_context']['season'])
        self.assertEqual(self.clean['input']['agent_plan']['devices'][0]['schedule'][-1]['end_time'],'day_2 07:30')
        shown=self.clean['input']['displayed_results']
        self.assertEqual(shown['comparison_window'],{'start_time':'day_1 07:30','end_time':'day_2 07:30','duration_hours':24})
        self.assertEqual(shown['energy_use_kwh'],{'no_dr':41.3,'agent':43.15})
        self.assertEqual(shown['electricity_cost']['unit'],'relative_cost_units')
        ev=next(row for row in shown['service_results'] if row['device_id']=='home_ev')
        self.assertTrue(ev['agent']['departures'][0]['target_met'])
    def test_plan_parser_rejects_unknown_values(self):
        view=deepcopy(self.raw['shown_to_participant'])
        view['schedule_chart']['rows'][0]['original'][0]['label']='暂无数据'
        with self.assertRaises(ValueError):plan_pair(view)
        self.assertEqual(_shown_clock('24:00'),'day_2 00:00')

if __name__=='__main__':unittest.main()
