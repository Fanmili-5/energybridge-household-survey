import json
from pathlib import Path
import unittest
from copy import deepcopy
from clean_collected_case import comparison, measure, service, clock_h

BASE=Path(__file__).resolve().parents[1]/'examples/real-test-20260914'
class FirstStageCleaningTests(unittest.TestCase):
    def setUp(self):self.raw=json.loads((BASE/'full-collected-record.json').read_text());self.clean=json.loads((BASE/'cleaned-supervision.json').read_text())
    def test_saved_comparison_reproduces_cleaned_comparison(self):
        original=deepcopy(self.raw['shown_to_participant'])
        self.assertEqual(comparison(original),self.clean['input']['comparison'])
        self.assertEqual(original,self.raw['shown_to_participant'])
        metrics=self.clean['input']['comparison']['metrics']
        self.assertEqual(metrics[0]['baseline'],{'value':41.30,'unit':'kWh'})
        self.assertEqual(metrics[1]['eb'],{'value':60.63,'unit':'normalized_cost'})
        self.assertEqual(metrics[2]['eb'],{'value':.92,'unit':'kWh'})
    def test_no_source_answer_or_feedback_is_lost_or_relabelled(self):
        i=self.clean['input'];aux=self.clean['auxiliary']
        covered=set(i['household_answers'])|set(i['unanswered_fields'])|set(aux['supplementary_answers'])|{'M_MEMBERS'}
        self.assertEqual(covered,set(self.raw['questionnaire']['answers']))
        for qid,row in i['household_answers'].items():self.assertEqual(row['selected_value'],self.raw['questionnaire']['answers'][qid])
        for old,new in zip(self.raw['questionnaire']['answers']['M_MEMBERS'],i['members']):
            for key,value in old.items():self.assertEqual(value,new['reported_fields'][key]['value'])
        for key in ('score','comfort_score','energy_score','vpp_score','comment'):
            self.assertEqual(self.clean['target'][key],self.raw['feedback'][key])
        self.assertEqual(self.clean['target']['decision'],self.raw['feedback']['choice'])
        self.assertEqual(self.clean['provenance']['stored_data_origin'],'synthetic_engineering_test')
        self.assertFalse(self.clean['provenance']['training_release'])
        self.assertNotIn('messages',self.clean)
        self.assertNotIn('comment',i)
    def test_next_day_and_cutoffs_survive_cleaning(self):
        self.assertEqual(clock_h('次日07:30'),31.5)
        self.assertEqual(clock_h('24:00'),24)
        self.assertEqual(service('截至次日07:30：当天任务未完成')['status'],'not_completed')
        self.assertEqual(service('次日07:30离家前电量 60.0%（目标 80%，未达到）')['target_met'],False)
        chart=self.clean['input']['comparison']
        self.assertEqual(chart['statistics_window']['duration_h'],24)
        self.assertEqual(chart['statistics_window']['start_sim_h'],7.5)
        self.assertEqual(chart['timeline_window']['start_h'],0)
        self.assertEqual(chart['device_timeline'][0]['eb'][-1]['end_status'],'observation_cutoff')
    def test_unrecognized_values_do_not_turn_into_zero_or_fake_units(self):
        for value in ('暂无数据','58.68 元','NaN kW'):
            with self.assertRaises(ValueError):measure(value)
        with self.assertRaises(ValueError):service('热水一定够用')

if __name__=='__main__':unittest.main()
