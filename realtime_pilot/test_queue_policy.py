from date_sampling import assigned_context
"""Queue waiting bounds preserve independent human submissions; no model calls."""
import concurrent.futures
import http.client
import json
import tempfile
import threading
import unittest
from unittest.mock import patch
from common import digest
from paired_contract import CONTEXT,QUESTIONNAIRE_VERSION,QUESTIONS
from server import Store,make_server
from test_pilot import NoExecute
from regional_test_support import answers
from export_household_records import records
from queue_policy import forecast


class QueuePolicyTests(unittest.TestCase):
    def intake(self,store,owner):
        return store.save_household(owner,{'questionnaire_context_hash':assigned_context(owner)["context_hash"],'answers':answers(),'request_id':'queue_intake_00000001',
            'questionnaire_version':QUESTIONNAIRE_VERSION,'questionnaire_hash':digest(QUESTIONS),
            'research_consent':True,'research_notice_version':'eb.research_notice.v1'})
    def payload(self,sid,nonce='queue_generate_00000001'):
        return {'submission_id':sid,'request_id':nonce,'scenario_id':CONTEXT['id'],'scenario_understood':True}
    def test_fifty_families_saved_but_queue_admission_is_bounded(self):
        with tempfile.TemporaryDirectory() as root:
            store=Store(root,human_pilot=True,workers=2,max_queue_wait=120,estimated_job_seconds=60);store.pool=NoExecute()
            try:
                with patch('server.time.time',return_value=100000):
                    with concurrent.futures.ThreadPoolExecutor(50) as pool:
                        intakes=list(pool.map(lambda i:self.intake(store,'owner-'+str(i)),range(50)))
                    def generate(i):
                        try:return store.create('owner-'+str(i),self.payload(intakes[i]['id']),paired_flow=True)
                        except OverflowError:return None
                    with concurrent.futures.ThreadPoolExecutor(50) as pool:results=list(pool.map(generate,range(50)))
                admitted=[r for r in results if r is not None]
                self.assertEqual(len(admitted),4)
                self.assertEqual(len(store.db.household_summaries('owner-49')),1)
                self.assertEqual(len(list(records(root))),50)
                self.assertEqual(len(store.jobs),len(admitted))
            finally:store.db.close()

    def test_school_capacity_admits_fifty_distinct_families_without_losing_answers(self):
        with tempfile.TemporaryDirectory() as root:
            store=Store(root,human_pilot=True,workers=16,max_pending=64,max_daily_jobs=50,
                        max_session_jobs=2,max_queue_wait=600,estimated_job_seconds=60)
            store.pool=NoExecute()
            try:
                with patch('server.subprocess.Popen') as process:
                    with concurrent.futures.ThreadPoolExecutor(50) as pool:
                        intakes=list(pool.map(lambda i:self.intake(store,'owner-'+str(i)),range(50)))
                    with concurrent.futures.ThreadPoolExecutor(50) as pool:
                        jobs=list(pool.map(lambda i:store.create('owner-'+str(i),self.payload(intakes[i]['id']),paired_flow=True),range(50)))
                    self.assertEqual(len({j['id'] for j in jobs}),50)
                    self.assertEqual(len(list(records(root))),50)
                    self.assertEqual(len(store.jobs),50)
                    for i,job in enumerate(jobs):
                        self.assertEqual(job['household_record_hash'],intakes[i]['household_record_hash'])
                        self.assertEqual(store.create('owner-'+str(i),self.payload(intakes[i]['id']),paired_flow=True)['id'],job['id'])
                    process.assert_not_called()
            finally:store.db.close()

    def test_expired_never_spawns_and_new_nonce_retries_frozen_intake(self):
        with tempfile.TemporaryDirectory() as root:
            store=Store(root,human_pilot=True,workers=2,max_queue_wait=120,max_session_jobs=1);store.pool=NoExecute()
            try:
                with patch('server.time.time',return_value=100000):
                    intake=self.intake(store,'owner');payload=self.payload(intake['id'])
                    job=store.create('owner',payload,paired_flow=True)
                saved_request=store.db.document(job['id'],'request.json')
                with patch('server.time.time',return_value=100121),patch('server.subprocess.Popen') as process:
                    store.execute(job['id']);process.assert_not_called()
                    self.assertEqual(store.jobs.summary(job['id'])['status'],'expired')
                    self.assertEqual(store.db.document(job['id'],'request.json'),saved_request)
                    self.assertEqual(store.create('owner',payload,paired_flow=True)['id'],job['id'])
                    retried=store.create('owner',self.payload(intake['id'],'queue_generate_00000002'),paired_flow=True)
                self.assertNotEqual(retried['id'],job['id'])
                self.assertEqual(retried['household_record_hash'],intake['household_record_hash'])
                self.assertEqual(len(list(records(root))),1)
            finally:store.db.close()

    def test_restart_preserves_deadline(self):
        with tempfile.TemporaryDirectory() as root:
            with patch('server.time.time',return_value=100000):
                store=Store(root,human_pilot=True,max_queue_wait=120);store.pool=NoExecute()
                intake=self.intake(store,'owner');job=store.create('owner',self.payload(intake['id']),paired_flow=True)
            deadline=job['queue_deadline_at'];store.db.close()
            with patch('server.time.time',return_value=100050):
                recovered=Store(root,human_pilot=True,max_queue_wait=999);recovered.pool=NoExecute()
            try:
                self.assertEqual(recovered.jobs.summary(job['id'])['queue_deadline_at'],deadline)
                with patch('server.time.time',return_value=100121):recovered.expire_queued()
                self.assertEqual(recovered.jobs.summary(job['id'])['status'],'expired')
                self.assertIsNotNone(recovered.db.document(job['id'],'request.json'))
            finally:recovered.db.close()

    def test_status_and_session_authorize_from_summaries_only(self):
        with tempfile.TemporaryDirectory() as root:
            server=make_server(0,root,human_pilot=True,disable_planning=True);server.store.pool=NoExecute()
            owner='a'*64;intake=self.intake(server.store,owner)
            job=server.store.create(owner,self.payload(intake['id']),paired_flow=True)
            job.update(status='complete',result={'large_trace':'x'*1024*1024})
            server.store.persist(job)
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            host,port=server.server_address
            def get(path,cookie=owner):
                c=http.client.HTTPConnection(host,port,timeout=5)
                c.request('GET',path,headers={'Cookie':'pilot_session='+cookie})
                r=c.getresponse();result=(r.status,json.loads(r.read()));c.close();return result
            try:
                with patch.object(server.store.db,'job',side_effect=AssertionError('status loaded full job')), \
                     patch.object(server.store.db,'households',side_effect=AssertionError('session loaded full households')):
                    self.assertEqual(get('/api/jobs/'+job['id']+'/status')[0],200)
                    self.assertEqual(get('/api/jobs/'+job['id']+'/status','b'*64)[0],404)
                    code,session=get('/api/session');self.assertEqual(code,200)
                    self.assertEqual(session['households'][0]['id'],intake['id'])
                    self.assertEqual(server.store.jobs.cached_count,0)
            finally:
                server.shutdown();server.server_close();server.store.db.close();thread.join()

    def test_forecast_fifo_and_engineering_timings_do_not_calibrate_humans(self):
        rows=[{'id':'engineering','flow':'paired_ep_v1','data_origin':'synthetic_engineering_test','status':'complete','started_at':1,'finished_at':2},
              {'id':'late','status':'queued','created_at':11},{'id':'early','status':'queued','created_at':10}]
        prediction=forecast(rows,1,20,60,'local_pilot_self_reported_human')
        self.assertEqual(prediction['estimate_basis'],'configured_cold_start')
        self.assertEqual(prediction['jobs']['early']['estimated_wait_seconds'],0)
        self.assertEqual(prediction['jobs']['late']['estimated_wait_seconds'],60)
        self.assertEqual(prediction['next_wait_seconds'],120)

    def test_fast_failures_do_not_lower_wait_estimate(self):
        rows=[{'id':str(i),'flow':'paired_ep_v1','data_origin':'local_pilot_self_reported_human',
               'status':'failed','started_at':i*2,'finished_at':i*2+1} for i in range(20)]
        rows.extend({'id':'queued'+str(i),'created_at':100+i,'status':'queued'} for i in range(4))
        prediction=forecast(rows,2,200,60,'local_pilot_self_reported_human')
        self.assertEqual(prediction['estimate_basis'],'configured_cold_start')
        self.assertEqual(prediction['next_wait_seconds'],120)

    def test_dispatcher_recovers_transient_expiry_write_and_preserves_cache(self):
        import sqlite3,time
        from durable_queue import DurableQueue
        with tempfile.TemporaryDirectory() as root:
            store=Store(root,human_pilot=True,max_queue_wait=120);store.pool=NoExecute()
            with patch('server.time.time',return_value=time.time()-121):
                intake=self.intake(store,'owner');job=store.create('owner',self.payload(intake['id']),paired_flow=True)
            queue=DurableQueue(store,1);original=store.persist
            failed=threading.Event();recovered=threading.Event();attempts=[];cache_states=[]
            def persist(row,documents=None):
                if row['status']=='expired':
                    attempts.append(row['id'])
                    if len(attempts)==1:
                        cache_states.append((store.jobs.summary(job['id'])['status'],store.jobs[job['id']]['status']))
                        failed.set();raise sqlite3.OperationalError('temporary test lock')
                original(row,documents)
                if row['status']=='expired':recovered.set()
            try:
                with patch.object(store,'persist',side_effect=persist),patch('server.subprocess.Popen') as process,patch('durable_queue.logging.exception'):
                    queue.resume();self.assertTrue(failed.wait(1))
                    self.assertEqual(cache_states,[('queued','queued')])
                    self.assertTrue(recovered.wait(3));self.assertTrue(queue.thread.is_alive())
                    self.assertEqual(store.jobs.summary(job['id'])['status'],'expired')
                    process.assert_not_called()
            finally:queue.shutdown();store.db.close()

    def test_resume_replaces_dead_dispatcher(self):
        from durable_queue import DurableQueue
        with tempfile.TemporaryDirectory() as root:
            store=Store(root);store.pool=NoExecute();queue=DurableQueue(store,1)
            dead=threading.Thread(target=lambda:None);dead.start();dead.join();queue.thread=dead
            try:
                queue.resume();self.assertIsNot(queue.thread,dead);self.assertTrue(queue.thread.is_alive())
                active=queue.thread;queue.resume();self.assertIs(queue.thread,active)
            finally:queue.shutdown();store.db.close()

    def test_http_fifty_intakes_then_bounded_admission_without_workers(self):
        with tempfile.TemporaryDirectory() as root:
            srv=make_server(0,root,human_pilot=True,disable_planning=True,workers=2,max_queue_wait=120,estimated_job_seconds=60)
            srv.store.pool=NoExecute();srv.planning_disabled=False
            thread=threading.Thread(target=srv.serve_forever,daemon=True);thread.start()
            host,port=srv.server_address;owners=[f'{i:064x}' for i in range(50)]
            payload={'answers':answers(),'request_id':'queue_http_intake_000001','questionnaire_version':QUESTIONNAIRE_VERSION,
                     'questionnaire_hash':digest(QUESTIONS),'research_consent':True,'research_notice_version':'eb.research_notice.v1'}
            def call(i,path,body):
                c=http.client.HTTPConnection(host,port,timeout=15)
                c.request('POST',path,json.dumps(body),{'Cookie':'pilot_session='+owners[i],
                    'Origin':f'http://{host}:{port}','Content-Type':'application/json'})
                r=c.getresponse();out=(r.status,json.loads(r.read()));c.close();return out
            try:
                with patch('server.subprocess.Popen') as process:
                    with concurrent.futures.ThreadPoolExecutor(50) as pool:
                        receipts=list(pool.map(lambda i:call(i,'/api/households',{**payload,'questionnaire_context_hash':assigned_context(owners[i])['context_hash']}),range(50)))
                    self.assertTrue(all(code==201 for code,row in receipts))
                    self.assertEqual(len(srv.store.db.households()),50)
                    with concurrent.futures.ThreadPoolExecutor(50) as pool:
                        decisions=list(pool.map(lambda i:call(i,'/api/paired',self.payload(receipts[i][1]['id'])),range(50)))
                    self.assertEqual(sum(code==202 for code,row in decisions),4)
                    self.assertEqual(sum(code==429 for code,row in decisions),46)
                    self.assertEqual(len(list(records(root))),50)
                    self.assertEqual(len(srv.store.jobs),4)
                    process.assert_not_called()
                    for i,(code,row) in enumerate(decisions):
                        if code==202:
                            repeated=call(i,'/api/paired',self.payload(receipts[i][1]['id']))
                            self.assertEqual(repeated[0],202);self.assertEqual(repeated[1]['id'],row['id'])
            finally:srv.shutdown();srv.server_close();srv.store.db.close();thread.join()

if __name__=='__main__':unittest.main()
