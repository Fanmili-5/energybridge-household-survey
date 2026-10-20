"""Stable anonymous participants, multiple assigned households; fixture writes only."""
import json
import tempfile
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from admin import backup,status
from identity import now
from ledger import CollectionStore,Conflict,NOTICE_VERSION,response
from make_fixture import make
from release import Release,UI_VERSION


class RoundsTest(unittest.TestCase):
    def test_zero_to_five_integer_scores_distinguish_zero_from_missing(self):
        values={'decision':'reject','score':0,'comfort_score':0,'energy_score':0,'vpp_score':0,'reason':'测试'}
        for score in range(6):
            answer={**values,'score':score}
            self.assertEqual(response(answer,True,0,0),answer)
        self.assertEqual(response({**values,'score':None},False,0,0)['score'],None)
        with self.assertRaises(ValueError):response({**values,'score':None},True,0,0)
        for invalid in (False,-1,6,2.5,float('nan'),float('inf')):
            with self.assertRaises(ValueError):response({**values,'score':invalid},True,0,0)
        with self.assertRaises(ValueError):response(values,True,1,1)

    def test_integer_scores_are_release_specific_and_reject_all_fractional_fields(self):
        values={'decision':'reject','score':1,'comfort_score':2,'energy_score':3,'vpp_score':4,'reason':'测试'}
        self.assertEqual(response(values,True,0),values)
        for key in ('score','comfort_score','energy_score','vpp_score'):
            bad={**values,key:2.5}
            with self.assertRaisesRegex(ValueError,'整数'):response(bad,True,0)
            with self.assertRaisesRegex(ValueError,'整数'):response(bad,False,0)
            self.assertEqual(response(bad,True,1)[key],2.5)
        for invalid in (False,0,6,float('nan'),float('inf'),2.00000000001):
            with self.assertRaises(ValueError):response({**values,'score':invalid},True,0)
    @classmethod
    def setUpClass(cls):
        cls.bank=tempfile.TemporaryDirectory(prefix='eb-rounds-bank-')
        cls.release=Release(make(Path(cls.bank.name),households=3))

    @classmethod
    def tearDownClass(cls):cls.bank.cleanup()

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='eb-rounds-ledger-');self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)/'private';self.store=CollectionStore(self.root,self.release,fixtures=True)
        self.session,self.token=self.store.session(None,True);self.first=self.store.start_open(self.session)
        self.store.consent(self.session,{'accept':True,'understood_assigned_role':True,'notice_version':NOTICE_VERSION})

    def transition(self):
        s=self.store.state(self.session)
        return {k:s[k]for k in ('participant_id','assignment_id','release_sha256','ui_revision')}

    def finish(self):
        s=self.store.state(self.session);payload=None
        for row in self.release.records.values():
            if row['household_id']!=s['household_id']:continue
            m=self.release.models[row['case_id']]
            payload={'participant_id':s['participant_id'],'assignment_id':s['assignment_id'],
                'release_sha256':self.release.signature,'ui_revision':UI_VERSION,'case_id':row['case_id'],'case_sha256':row['sha256'],
                'expected_answer_revision':0,'expected_draft_version':0,'request_id':str(uuid.uuid4()),
                'response':{'decision':'reject','score':1,'comfort_score':2,'energy_score':3,'vpp_score':4,'reason':'隔离工程测试，不是真人答案。'},
                'presentation':{'fields':{k:m[k]for k in ('family','request','changes','impacts')},'schedule_seen':False,'schedule_text':None,'presented_at':now()}}
            self.store.save(self.session,payload)
        return payload

    def test_resume_next_round_recovery_and_all_round_withdrawal(self):
        with self.assertRaises(Conflict):self.store.next_round(self.session,self.transition())
        self.assertEqual(self.store.start_open(self.session)['assignment_id'],self.first['assignment_id'])
        stale=self.finish();old=self.transition();second=self.store.next_round(self.session,old)
        self.assertEqual(second['participant_id'],self.first['participant_id'])
        self.assertNotEqual(second['assignment_id'],self.first['assignment_id'])
        self.assertNotEqual(second['household_id'],self.first['household_id'])
        self.assertEqual(second['round_number'],2)
        self.assertEqual(self.store.state(self.session)['answers'],[])
        self.assertTrue(self.store.next_round(self.session,old)['duplicate'])
        with self.assertRaises(Conflict):self.store.save(self.session,stale)
        other,_=self.store.session(None,True)
        self.store.claim(other,self.store.cohort,self.first['recovery_code'],'fixture')
        self.assertEqual(self.store.state(other)['assignment_id'],second['assignment_id'])
        self.finish();s=status(self.store)
        self.assertEqual((s['active_identities'],s['active_assignments'],s['completed_rounds']),(1,2,2))
        with self.store.connect()as db:
            records=[json.loads(r[0])for r in db.execute('select record_json from responses_v69')]
        self.assertEqual({r['participant_id']for r in records},{self.first['participant_id']})
        self.assertEqual({r['round_number']for r in records},{1,2})
        self.assertEqual(len(records),20);self.assertTrue(all(r['human_label_count']==0 for r in records))
        # Restart retains root identity, both rounds, and the original recovery credential.
        self.store=CollectionStore(self.root,self.release,fixtures=True)
        self.assertEqual(len(self.store.state(other)['rounds']),2)
        self.assertEqual(backup(self.root,Path(self.temp.name)/'backup')['row_counts']['participant_rounds'],2)
        self.assertEqual(self.store.withdraw(other)['scope'],'all_participant_rounds')
        self.assertIsNone(self.store.state(self.session)['participant_id'])
        self.assertEqual(status(self.store)['submitted_latest_actor_cases'],0)
        with self.assertRaises(PermissionError):self.store.claim(other,self.store.cohort,self.first['recovery_code'],'fixture')

    def test_concurrent_next_round_idempotency_and_stale_other_device(self):
        other,_=self.store.session(None,True)
        self.store.claim(other,self.store.cohort,self.first['recovery_code'],'fixture')
        stale=self.finish();payload=self.transition()
        with ThreadPoolExecutor(max_workers=4)as pool:
            results=list(pool.map(lambda _:self.store.next_round(self.session,payload),range(4)))
        self.assertEqual(len({r['assignment_id']for r in results}),1)
        self.assertEqual(len(self.store.state(other)['rounds']),2)
        with self.assertRaises(Conflict):self.store.save(other,stale)
        self.finish();third=self.store.next_round(self.session,self.transition())
        self.assertEqual(third['round_number'],3)
        with self.assertRaises(Conflict):self.store.next_round(self.session,payload)
        rounds=self.store.state(self.session)['rounds']
        self.assertEqual(len({r['household_id']for r in rounds}),3)
        self.finish()
        self.assertFalse(self.store.state(self.session)['can_start_next_round'])
        with self.assertRaises(Conflict):self.store.next_round(self.session,self.transition())

    def test_no_household_selector_or_pending_edits_bypass(self):
        self.finish();transition=self.transition()
        with self.assertRaises(ValueError):self.store.next_round(self.session,{**transition,'household_id':'chosen'})
        s=self.store.state(self.session);row=next(r for r in self.release.records.values()if r['household_id']==s['household_id'])
        m=self.release.models[row['case_id']]
        draft={**transition,'case_id':row['case_id'],'case_sha256':row['sha256'],'expected_version':1,'expected_answer_revision':1,
            'response':{'decision':'reject','score':1,'comfort_score':2,'energy_score':3,'vpp_score':4,'reason':'未提交修改'},
            'presentation':{'fields':{k:m[k]for k in ('family','request','changes','impacts')},'schedule_seen':False,'schedule_text':None,'presented_at':now()}}
        self.store.draft(self.session,draft)
        with self.assertRaises(Conflict):self.store.next_round(self.session,transition)
        clear={k:v for k,v in draft.items()if k not in ('response','presentation')};clear['expected_version']=2
        self.store.draft(self.session,clear,clear=True)
        self.assertEqual(self.store.next_round(self.session,transition)['round_number'],2)


if __name__=='__main__':unittest.main()
