"""Real-household storage/projection boundaries; no EP or paid model calls."""
import copy,json,tempfile,unittest,subprocess,sys
from pathlib import Path
from common import normalize_answers,digest
from paired_contract import QUESTIONS,LOOKUP,QUESTIONNAIRE_VERSION,CONTEXT,prepare,sanitize_profile
from household_config import build_household_config
from household_extensions import build_record
from server import Store
from test_pilot import NoExecute
from verify_paired_physics import answers
from proposal_contract import candidate

class ExtensionTests(unittest.TestCase):
    def raw(self):
        a=answers();a.update(X_REGION='广东',X_CITY='深圳',X_BUILDING='apartment',X_AREA='90_119',X_EXTRA_DEVICES=['refrigerator','pv'],X_INCOME='10000_19999',X_COUNT_ac='2')
        a['M_MEMBERS'][0].update(age_band='older',life_roles=['retired','caregiver'],cost_importance='2',control='manual')
        return a
    def normalized(self,a):return sanitize_profile(normalize_answers(a,list(LOOKUP),LOOKUP))
    def test_optional_extensions_never_change_physics_or_planner(self):
        a=answers();b=copy.deepcopy(a);b.update(X_REGION='广东',X_CITY='深圳',X_INCOME='ge30000',X_COUNT_ac='3_plus')
        p1,p2=self.normalized(a),self.normalized(b)
        o1,s1=prepare(p1,'same');o2,s2=prepare(p2,'same')
        self.assertEqual(o1,o2);self.assertEqual(s1,s2)
        h1=build_household_config(p1,QUESTIONS,o1,'same');h2=build_household_config(p2,QUESTIONS,o2,'same')
        self.assertEqual({k:v for k,v in h1.items() if k!="answers_hash"},{k:v for k,v in h2.items() if k!="answers_hash"})
        self.assertNotEqual(h1["answers_hash"],h2["answers_hash"]) # provenance still covers the full answer snapshot
        self.assertNotIn('X_REGION',json.dumps(h2['observable_profile']))
        self.assertEqual(p1['X_EXTRA_DEVICES']['response_status'],'skipped')
    def test_member_multiselect_and_research_absence_are_not_invented(self):
        a=self.raw();p=self.normalized(a);o,s=prepare(p,'same');h=build_household_config(p,QUESTIONS,o,'same')
        self.assertEqual(h['reported_members'][0]['reported_fields']['life_roles']['label'],'退休、照顾家人')
        self.assertIn('60岁及以上',json.dumps(h['observable_profile'],ensure_ascii=False))
        self.assertIsNone(p['M_MEMBERS']['value'][1]['age_band'])
        self.assertIsNone(p['M_MEMBERS']['value'][1]['cost_importance'])
        for invalid in ('retired',['retired','retired'],['not_a_role']):
            a=self.raw();a['M_MEMBERS'][0]['life_roles']=invalid
            with self.assertRaises(ValueError):self.normalized(a)
        a=self.raw();a['X_EXTRA_DEVICES']=['pv','none']
        with self.assertRaises(ValueError):self.normalized(a)
        a=self.raw();a['B05']=['washer'];p=self.normalized(a)
        self.assertEqual(p['X_COUNT_ac']['response_status'],'not_applicable')
        self.assertEqual(p['X_EXTRA_DEVICES']['value'],['refrigerator','pv'])
    def test_transaction_restart_and_export_preserve_full_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=Store(tmp);store.pool=NoExecute();a=self.raw()
            job=store.create('extension-owner',{'answers':a,'request_id':'extension_request_0001','scenario_id':CONTEXT['id'],'scenario_understood':True},paired_flow=True)
            record=store.db.document(job['id'],'household_record.json')
            self.assertEqual(record['raw_answers'],a)
            self.assertEqual(record['derived_facts']['reported_age_counts'],{'under18':0,'adult':0,'older':1,'unreported':2})
            self.assertEqual(record['research_context']['X_CITY']['value'],'深圳')
            self.assertEqual(job['household_record_hash'],digest(record))
            self.assertEqual(store.db.document(job['id'],'request.json')['household_record_hash'],digest(record))
            job.update(status='complete',result={'schema_version':'eb.paired_ep.v2.7','household_config':job['household_config'],'proposal_plan':{},'display':{'participant_view':{'question':'是否接受？'}},'display_hash':'display','original_plan_hash':'original','proposal_plan_hash':'proposal'})
            target={'target_source':'engineering_test','choice':'reject','score':3.5,'comfort_score':2.2,'energy_score':4,'vpp_score':3,'comment':'工程测试','feedback_version':'eb.binary_decision_four_scores.v2'}
            c=candidate(job,target);store.persist(job,{'sft_candidate.json':c});store.db.close()
            restored=Store(tmp);restored.pool=NoExecute()
            self.assertEqual(restored.db.document(job['id'],'household_record.json'),record)
            self.assertEqual(restored.db.document(job['id'],'sft_candidate.json')['household_record'],record)
            prompt=json.loads(c['messages'][1]['content'])
            self.assertNotIn('X_CITY',json.dumps(prompt));self.assertIn('age_band',json.dumps(c['household_record']))
            self.assertEqual(json.loads(c['messages'][2]['content'])['decision'],'reject')
            output=Path(tmp)/'export.jsonl'
            subprocess.run([sys.executable,'export_candidates.py','--include-engineering','--data-dir',tmp,'--output',str(output)],check=True,capture_output=True)
            exported=json.loads(output.read_text());self.assertEqual(exported['household_record'],record)
            restored.db.close()
    def test_old_member_snapshot_remains_readable_without_new_fields(self):
        schema=json.loads(Path('ui_audit_20260911/members/schema.json').read_text());qs=schema['paired_questions'];lookup={q['id']:q for q in qs}
        a=answers();p=normalize_answers(a,list(lookup),lookup);o,s=prepare(self.normalized(a),'legacy')
        h=build_household_config(p,qs,o,'legacy')
        self.assertNotIn('age_band',h['reported_members'][0]['reported_fields'])
        self.assertNotIn('research_context',h)

if __name__=='__main__':unittest.main()
