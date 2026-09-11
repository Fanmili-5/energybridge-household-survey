"""Bounded Python heap for large historical jobs, without losing research evidence."""
import json
import sqlite3
import tempfile
import tracemalloc
import unittest
from pathlib import Path
from unittest.mock import patch
from durable_storage import Database
from job_index import LazyJobIndex,summarize_job


class LazyStorageTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.db=Database(self.tmp.name)
    def tearDown(self):
        self.db.close();self.tmp.cleanup()
    def job(self,i,status='complete',blob=''):
        return {'id':f'job-{i}','owner':'owner','request_id':f'request-{i}','request_hash':f'hash-{i}',
                'status':status,'created_at':i,'flow':'paired_ep_v1','task':'plan_judgement',
                'decision_saved':True,'rating_saved':False,'household_submission_id':'intake',
                'profile':{'members':[{'comfort':'sensitive','cost':None}]},
                'household_record':{'raw_answers':{'city':'测试城市'},'unreported':None},
                'decision':{'choice':'reject','score':3.75,'comfort_score':2.5,'energy_score':4.2,'vpp_score':2.25,'comment':'不方便'},
                'result':{'trace':blob,'display':{'title':'两份方案'}},'attempts':2}
    def save(self,job):
        # Large mirror files are not needed for index tests; DB writes remain real.
        with patch.object(self.db,'export'):self.db.save(job)

    def test_thousand_large_jobs_have_small_startup_heap_and_no_payload_reads(self):
        # ~125 MiB of payload in SQLite, excluded from the measured setup heap.
        blob='x'*(128*1024)
        with self.db.lock,self.db.conn:
            for i in range(1000):
                j=self.job(i,blob=blob)
                self.db.conn.execute('INSERT INTO jobs VALUES(?,?,?,?,?,?)',
                    (j['id'],j['owner'],j['request_id'],j['status'],i,json.dumps(j,ensure_ascii=False)))
        tracemalloc.start()
        try:
            with patch.object(self.db,'job',side_effect=AssertionError('full job read at startup')), \
                 patch.object(self.db,'jobs',side_effect=AssertionError('all history loaded')):
                index=LazyJobIndex(self.db)
                self.assertEqual(len(index),1000)
                self.assertEqual(len(list(index.summaries())),1000)
                self.assertIn('job-999',index)
                self.assertEqual(index.cached_count,0)
            _,peak=tracemalloc.get_traced_memory()
        finally:tracemalloc.stop()
        self.assertLess(peak,12*1024*1024,peak)
        self.assertNotIn('result',next(index.summaries()))

    def test_terminal_get_is_exact_and_does_not_cache(self):
        original=self.job(1,blob='long trace'*1000);self.save(original)
        index=LazyJobIndex(self.db)
        first=index['job-1'];second=index.get('job-1')
        self.assertEqual(first,original);self.assertEqual(second,original)
        self.assertIsNot(first,second);self.assertEqual(index.cached_count,0)
        first['decision']['score']=1
        self.assertEqual(index['job-1']['decision']['score'],3.75)
        self.assertIsNone(index.get('missing'))
        with self.assertRaises(KeyError):index['missing']

    def test_active_identity_and_terminal_transition_release_cache(self):
        original=self.job(2,'queued');self.save(original);index=LazyJobIndex(self.db)
        live=index['job-2'];self.assertIs(index['job-2'],live)
        live['status']='running';self.save(live);index['job-2']=live
        self.assertIs(index.get('job-2'),live);self.assertEqual(index.cached_count,1)
        live['status']='complete';self.save(live);index['job-2']=live
        self.assertEqual(index.cached_count,0);self.assertIsNot(index['job-2'],live)
        self.assertEqual(index['job-2'],live)
        snap=next(index.summaries());snap['status']='corrupted'
        self.assertEqual(next(index.summaries())['status'],'complete')

    def test_mapping_values_stream_full_records_and_summary_never_drops_source(self):
        originals=[self.job(i,blob='trace'+str(i)) for i in range(5)]
        for job in originals:self.save(job)
        index=LazyJobIndex(self.db)
        with patch.object(self.db,'job',wraps=self.db.job) as read:
            values=iter(index.values());self.assertEqual(read.call_count,0)
            first=next(values);self.assertEqual(read.call_count,1)
            self.assertEqual(first,originals[0]);self.assertEqual(list(values),originals[1:])
        self.assertEqual(index.cached_count,0)
        self.assertEqual(list(index.summaries()),[summarize_job(j) for j in originals])
        del index['job-0'];self.assertNotIn('job-0',index)
        self.assertEqual(self.db.job('job-0'),originals[0]) # index deletion does not erase evidence

    def test_legacy_database_schema_and_payload_unchanged(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'state.sqlite3';original=self.job(8);serialized=json.dumps(original,ensure_ascii=False)
            with sqlite3.connect(path) as db:
                db.execute('CREATE TABLE jobs(id TEXT PRIMARY KEY,owner TEXT NOT NULL,request_id TEXT NOT NULL,status TEXT NOT NULL,created REAL NOT NULL,payload TEXT NOT NULL,UNIQUE(owner,request_id))')
                db.execute('INSERT INTO jobs VALUES(?,?,?,?,?,?)',('job-8','owner','request-8','complete',8,serialized))
                db.execute('PRAGMA user_version=1')
            recovered=Database(root)
            try:
                index=LazyJobIndex(recovered);self.assertEqual(index['job-8'],original)
                self.assertEqual(recovered.conn.execute('SELECT payload FROM jobs').fetchone()[0],serialized)
                self.assertEqual(recovered.household_summaries('owner'),[])
            finally:recovered.close()

    def test_household_summary_and_exact_idempotency_lookup(self):
        original={'id':'intake','owner':'owner','request_id':'req','created_at':1,
                  'questionnaire_version':'v3.9','questionnaire_hash':'qhash','household_record_hash':'rhash',
                  'raw_answers':{'large':'x'*1024*1024},'profile':{'score':None}}
        self.db.save_household(original)
        with patch('durable_storage.json.loads',side_effect=AssertionError('summary decoded full intake')):
            summary=self.db.household_summaries('owner')
        self.assertEqual(summary,[{k:original[k] for k in ('id','created_at','questionnaire_version','questionnaire_hash','household_record_hash')}])
        self.assertEqual(self.db.household_by_request('owner','req'),original)
        self.assertIsNone(self.db.household_by_request('other','req'))
        self.assertEqual(self.db.household_summaries('other'),[])

    def test_summary_read_is_detached_and_expired_is_terminal(self):
        original=self.job(9,'expired',blob='large'*1000)
        original.update(queue_deadline_at=300,queue_seconds=291)
        self.save(original);index=LazyJobIndex(self.db)
        with patch.object(self.db,'job',side_effect=AssertionError('summary loaded full record')):
            row=index.summary('job-9');self.assertEqual(row['owner'],'owner')
            self.assertEqual(row['queue_deadline_at'],300);self.assertEqual(row['queue_seconds'],291)
            row['status']='queued';self.assertEqual(index.summary('job-9')['status'],'expired')
            self.assertIsNone(index.summary('missing'))
        self.assertEqual(index['job-9'],original);self.assertEqual(index.cached_count,0)
        index['job-9']=original;self.assertEqual(index.cached_count,0)

if __name__=='__main__':unittest.main()
