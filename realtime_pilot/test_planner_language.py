"""Language projection preserves research evidence and physical inputs."""
from copy import deepcopy
import json
import re
import os
import tempfile
from pathlib import Path
from unittest.mock import patch
from contextlib import redirect_stdout
from io import StringIO
import unittest
from common import digest
from household_config import ensure_household_config
from paired_contract import QUESTIONS
from planner_language import english_question, english_answer, planner_household, CATALOG
from test_native_runner import request

class PlannerLanguageTests(unittest.TestCase):
    def test_all_current_questions_and_member_options_have_reviewed_labels(self):
        for q in QUESTIONS:
            if q.get('research_only'):continue
            en=english_question(q)
            self.assertFalse(re.search('[\u4e00-\u9fff]',en['prompt']))
            for field in [en]+en.get('fields',[]):
                self.assertFalse(re.search('[\u4e00-\u9fff]',field['prompt']))
                for option in field['options']:
                    self.assertFalse(re.search('[\u4e00-\u9fff]',option['label']))
                    if field is en:
                        answer=english_answer({'response_status':'answered','value':option['value']},en)
                        self.assertIsInstance(answer,str)
    def test_source_wording_changes_require_mapping_review(self):
        q=deepcopy(QUESTIONS[0]);q['prompt']+=' changed'
        with self.assertRaisesRegex(ValueError,'mapping needs review'):english_question(q)
        q=deepcopy(QUESTIONS[0]);q['options'][0]['label']+=' changed'
        with self.assertRaisesRegex(ValueError,'mapping needs review'):english_question(q)
    def test_projection_preserves_codes_numbers_hashes_unknowns_and_raw_evidence(self):
        req=request();raw=ensure_household_config(req);before=deepcopy(raw)
        en=planner_household(raw,req)
        self.assertEqual(raw,before)
        for key in ('appliances','schedule','preferences','tags','ordinary_plan','household_facts','field_sources','questionnaire_hash','answers_hash'):
            self.assertEqual(en[key],raw[key],key)
        self.assertEqual(en['planner_language']['source_household_config_hash'],digest(raw))
        original={a['id']:a for a in raw['onboarding']['answers']}
        for a in en['onboarding']['answers']:
            self.assertEqual(a['selected_option_ids'],original[a['id']]['selected_option_ids'])
            if a['id'] not in ('X_CITY','SIMULATION_ENVIRONMENT'):
                self.assertFalse(re.search('[\u4e00-\u9fff]',a['question']+a['answer']),a['id'])
        for old,new in zip(raw['reported_members'],en['reported_members']):
            for key,f in old['reported_fields'].items():
                self.assertEqual(f['value'],new['reported_fields'][key]['value'])
                self.assertEqual(f['response_status'],new['reported_fields'][key]['response_status'])
        self.assertFalse(re.search('[\u4e00-\u9fff]',json.dumps(en['calendar'],ensure_ascii=False)))
    def test_fractional_values_and_open_ended_option_keep_their_meaning(self):
        qs={q['id']:english_question(q) for q in QUESTIONS if not q.get('research_only')}
        def answer(qid,value):return english_answer({'response_status':'answered','value':value},qs[qid])
        self.assertEqual(answer('P_NOTICE','72'),'3 days or more')
        self.assertEqual(answer('P_AC_RANGE','24.1_26.7'),'24.1 to 26.7 degrees C')
        self.assertEqual(answer('H_washer','7.16666666667'),'07:10')
        self.assertIn('explicit agreement',answer('A_EB_CONTROL','confirm_required'))
        self.assertIsNone(english_answer({'response_status':'skipped','value':None},qs['P_COST']))
    @unittest.skipUnless(os.environ.get('EB_TEST_NATIVE_EP')=='1', 'requires native EnergyPlus')
    def test_translation_does_not_change_native_baseline_physics(self):
        from native_runner import run_native
        req=request()
        with tempfile.TemporaryDirectory() as tmp, redirect_stdout(StringIO()):
            english=run_native(Path(tmp)/'english',req,method='no_dr')
            with patch('planner_language.planner_household',side_effect=lambda household,request: {**deepcopy(household),'planner_language':{'language':'zh','fixture':True}}):
                chinese=run_native(Path(tmp)/'chinese',req,method='no_dr')
            self.assertEqual(english['controls'],chinese['controls'])
            self.assertEqual(english['idf_sha256'],chinese['idf_sha256'])
            self.assertEqual(english['weather_sha256'],chinese['weather_sha256'])
            self.assertEqual(json.loads((Path(tmp)/'english/ep_metric_series.json').read_text()),json.loads((Path(tmp)/'chinese/ep_metric_series.json').read_text()))
            saved=json.loads((Path(tmp)/'english/planner_household_en.json').read_text())
            self.assertEqual(saved['planner_language']['language'],'en')
            self.assertEqual(english['native']['household_binding']['planner_household_hash'],digest(saved))
            self.assertEqual(english['native']['llm_call_count'],0)

    def test_unmapped_free_text_is_not_silently_claimed_as_translated(self):
        with self.assertRaisesRegex(ValueError,'Free-text translation'):
            english_answer({'response_status':'answered','value':'中文原因'},{'id':'new_free_text','type':'text'})

if __name__=='__main__':unittest.main()
