"""Contract tests: self-report is side metadata and malformed ages are rejected."""
import copy,json,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent/'runtime'))
from respondent import validate_respondent,QUESTIONNAIRE_UI_VERSION
from unified_live_server import App,validate_record,encoded

class RespondentTests(unittest.TestCase):
    def test_optional_and_declined_are_distinct(self):
        self.assertEqual(validate_respondent({'age_years':None,'gender':None}),{'age_years':None,'gender':None})
        self.assertEqual(validate_respondent({'age_years':21,'gender':'prefer_not_to_say'})['gender'],'prefer_not_to_say')

    def test_invalid_age_or_extra_identity_fields_rejected(self):
        for age in [True,False,0,121,20.1,'21',[],{}]:
            with self.subTest(age=age),self.assertRaises(ValueError):validate_respondent({'age_years':age,'gender':None})
        for value in [{'age_years':21,'gender':'invalid'},{'age_years':21,'gender':[]},{'age_years':21,'gender':'female','name':'invented'}]:
            with self.assertRaises(ValueError):validate_respondent(value)

    def test_save_roundtrip_source_and_input_unchanged(self):
        case={'identity':{'case_id':'engineering-fixture','date':'2025-01-01'}}
        record={'schema':'eb.joint_b.local_test_export.v6','questionnaire_ui_version':QUESTIONNAIRE_UI_VERSION,
            'status':'engineering_click_not_human_feedback','human_label_count':0,'training_release':False,'formal_export_eligible':False,
            'input':{'date':'2025-01-01','fields':{'role':'invented task'}},'respondent':{'age_years':21,'gender':'female'},
            'test_feedback':{'decision':'accept','decision_status':'answered','score':None,'comfort_score':None,'energy_score':None,'vpp_score':None,'comment':'engineering fixture'},
            'audit':{'source_case':case,'source_binding':{'source_package_sha256':'fixture-hash'}}}
        before=copy.deepcopy(record['input']);validate_record('answers',record,0,[case],['fixture-hash'])
        with tempfile.TemporaryDirectory()as t:
            root=Path(t);site=root/'site';site.mkdir();(site/'index.html').write_text('<script id="joint-cases-data">'+json.dumps([case])+'</script><script id="source-hashes-data">'+json.dumps(['fixture-hash'])+'</script>')
            app=App(site,root/'private','/fixture','https://survey.example.org');session=app.session(None,create=True)
            payload={'case_index':0,'record':record,'request_id':'00000000-0000-0000-0000-000000000001'}
            first=app.save('answers',payload,session['session_id']);again=app.save('answers',payload,session['session_id']);self.assertEqual(first['receipt_id'],again['receipt_id']);self.assertTrue(again['duplicate'])
            with app.connect()as db:saved=json.loads(db.execute('select record_json from writes').fetchone()[0])
            self.assertEqual(saved['respondent'],record['respondent']);self.assertEqual(saved['input'],before);self.assertEqual(saved['audit']['source_case'],case)
            bad=copy.deepcopy(payload);bad['record']['respondent']['age_years']=78
            with self.assertRaises(ValueError):app.save('answers',bad,session['session_id'])

if __name__=='__main__':unittest.main()
