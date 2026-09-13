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
        a=answers();a.update(X_REGION='广东',X_CITY='广州',X_BUILDING='apartment',X_AREA='90_119',X_AREA_BASIS='usable',X_FLOOR='middle',X_EXTRA_DEVICES=['refrigerator','pv'],X_INCOME='10000_19999',X_COUNT_ac='2')
        a['M_MEMBERS'][0].update(age_band='older',life_roles=['retired','caregiver'],cost_importance='2',control='manual')
        return a
    def normalized(self,a):return sanitize_profile(normalize_answers(a,list(LOOKUP),LOOKUP))
    def test_optional_extensions_never_change_physics_or_planner(self):
        a=answers();b=copy.deepcopy(a);b.update(X_INCOME='ge30000',X_COUNT_ac='3_plus')
        p1,p2=self.normalized(a),self.normalized(b)
        o1,s1=prepare(p1,'same');o2,s2=prepare(p2,'same')
        self.assertEqual(o1,o2);self.assertEqual(s1,s2)
        h1=build_household_config(p1,QUESTIONS,o1,'same');h2=build_household_config(p2,QUESTIONS,o2,'same')
        self.assertEqual({k:v for k,v in h1.items() if k!="answers_hash"},{k:v for k,v in h2.items() if k!="answers_hash"})
        self.assertNotEqual(h1["answers_hash"],h2["answers_hash"]) # provenance still covers the full answer snapshot
        self.assertNotIn('X_INCOME',json.dumps(h2['observable_profile']))
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
            self.assertEqual(record['normalized_answers']['X_CITY']['value'],'广州')
            self.assertEqual(job['household_record_hash'],digest(record))
            self.assertEqual(store.db.document(job['id'],'request.json')['household_record_hash'],digest(record))
            from paired_contract import VERSION
            from proposal_contract import decision_record
            result={'schema_version':VERSION,'household_config':job['household_config'],
                    'original_plan':job['original_plan'],'proposal_plan':{},
                    'display':{'participant_view':{'question':'是否接受？'}}}
            for key in ('household_config','original_plan','proposal_plan','display'):
                result[key+'_hash']=digest(result[key])
            job.update(status='complete',result=result)
            target=decision_record(job,{'choice':'reject','score':3.5,'comfort_score':2.2,'energy_score':4,'vpp_score':3,
                'comment':'工程测试',**{k:result[k] for k in ('display_hash','original_plan_hash','proposal_plan_hash')}})
            target.update(decision_hash=digest(target),submitted_at=1)
            c=candidate(job,target);store.persist(job,{'sft_candidate.json':c,'decision.json':target,'outcome.json':result});store.db.close()
            restored=Store(tmp);restored.pool=NoExecute()
            self.assertEqual(restored.db.document(job['id'],'household_record.json'),record)
            self.assertEqual(restored.db.document(job['id'],'sft_candidate.json')['household_record'],record)
            prompt=json.loads(c['messages'][1]['content'])
            self.assertIn('X_CITY',json.dumps(prompt));self.assertIn('age_band',json.dumps(c['household_record']))
            self.assertEqual(json.loads(c['messages'][2]['content'])['decision'],'reject')
            output=Path(tmp)/'export.jsonl'
            completed=subprocess.run([sys.executable,'export_candidates.py','--include-engineering','--data-dir',tmp,'--output',str(output)],capture_output=True,text=True)
            self.assertEqual(completed.returncode,0,completed.stderr)
            exported=json.loads(output.read_text());self.assertEqual(exported['household_record'],record)
            from export_candidates import verify_candidate
            docs={n:restored.db.document(job['id'],n) for n in ('outcome.json','decision.json','household_record.json','questionnaire_submission.json','request.json')}
            self.assertEqual(verify_candidate(c,job,docs),c)
            bad=copy.deepcopy(c);bad['messages'][2]['content']='{"decision":"accept","score":5}'
            with self.assertRaises(ValueError):verify_candidate(bad,job,docs)
            docs['outcome.json']['display']['participant_view']['question']='changed after rating'
            with self.assertRaises(ValueError):verify_candidate(c,job,docs)
            restored.db.close()

    def test_human_candidate_requires_hash_verified_native_artifacts(self):
        from export_candidates import verify_candidate
        a=self.raw();p=self.normalized(a);o,s=prepare(p,'evidence');h=build_household_config(p,QUESTIONS,o,'evidence')
        result={'schema_version':__import__('paired_contract').VERSION,'household_config':h,'original_plan':o,
                'proposal_plan':{},'baseline_plan':{},'display':{'participant_view':{'question':'是否接受？'}},
                'provenance':{'artifact_hashes':{'baseline/native_result.json':'0'*64}}}
        for key in ('household_config','original_plan','proposal_plan','baseline_plan','display'):result[key+'_hash']=digest(result[key])
        job={'id':'human-evidence','status':'complete','result':result,'flow':'paired_ep_v1','profile':p,
             'questionnaire_snapshot':QUESTIONS,'questionnaire_hash':digest(QUESTIONS),'data_origin':'local_pilot_self_reported_human',
             'household_id':'h','respondent_id':'r','run_directory':'attempts/0001','original_plan':o}
        payload={'choice':'accept','score':3,'comfort_score':3,'energy_score':3,'vpp_score':3,'comment':'可以接受',
                 **{key:result[key] for key in ('display_hash','original_plan_hash','proposal_plan_hash')}}
        from proposal_contract import decision_record
        decision=decision_record(job,payload);decision.update(decision_hash=digest(decision),submitted_at=1)
        row=candidate(job,decision);docs={'outcome.json':result,'decision.json':decision}
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError,'required native artifacts'):
                verify_candidate(row,job,docs,case_dir=tmp)
    def test_old_member_snapshot_remains_readable_without_new_fields(self):
        schema=json.loads(Path('ui_audit_20260911/members/schema.json').read_text());qs=schema['paired_questions'];lookup={q['id']:q for q in qs}
        a=answers();p=normalize_answers(a,list(lookup),lookup);o,s=prepare(self.normalized(a),'legacy')
        h=build_household_config(p,qs,o,'legacy')
        self.assertNotIn('age_band',h['reported_members'][0]['reported_fields'])
        self.assertNotIn('research_context',h)

if __name__=='__main__':unittest.main()
