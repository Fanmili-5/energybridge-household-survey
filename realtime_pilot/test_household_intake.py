"""Independent household receipts, admission limits and authorization; zero API calls."""
import copy,json,tempfile,unittest
from unittest.mock import patch
from server import Store,make_server,PARTICIPANT_UI_VERSION
from test_pilot import NoExecute
from regional_test_support import answers
from paired_contract import CONTEXT,QUESTIONS,QUESTIONNAIRE_VERSION
from common import digest
from date_sampling import assigned_context
from export_household_records import records

class HouseholdIntakeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.store=Store(self.tmp.name,human_pilot=True);self.store.pool=NoExecute()
    def tearDown(self):
        self.store.db.close();self.tmp.cleanup()
    def payload(self,nonce='intake_request_00001',owner='owner'):
        return {'questionnaire_context_hash':assigned_context(owner)['context_hash'],'answers':answers(),'request_id':nonce,'questionnaire_version':QUESTIONNAIRE_VERSION,
                'questionnaire_hash':digest(QUESTIONS),'research_consent':True,'scenario_understood':True,
                'research_notice_version':'eb.research_notice.v2','ui_version':PARTICIPANT_UI_VERSION}
    def generate(self,sid,nonce='generate_request_00001'):
        return {'submission_id':sid,'request_id':nonce,'scenario_id':CONTEXT['id'],'scenario_understood':True,
                'questionnaire_version':QUESTIONNAIRE_VERSION,'questionnaire_hash':digest(QUESTIONS)}
    def test_relative_data_directory_survives_worker_cwd(self):
        import os,sys
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            store=Store(os.path.relpath(tmp));store.pool.shutdown();store.pool=NoExecute()
            try:
                from paired_contract import CONTEXT
                job=store.create('relative-owner',{'answers':answers(),'request_id':'relative_path_request_01','scenario_id':CONTEXT['id'],'scenario_understood':True},paired_flow=True)
                # Worker starts in the source directory, which differs from the caller cwd.
                store.worker_command=lambda folder:[sys.executable,'-c',"from pathlib import Path; import sys; assert Path(sys.argv[1]).is_file(); print('request-readable')",str(folder/'request.json')]
                store.execute(job['id'])
                log=store.root/job['id']/'attempts/0001/worker.log'
                self.assertEqual(log.read_text().strip(),'request-readable')
            finally:store.db.close()

    def test_intake_does_not_prepare_and_survives_failed_plan(self):
        with patch('server.paired.prepare',side_effect=RuntimeError('environment unavailable')) as prepare:
            receipt=self.store.save_household('owner',self.payload());prepare.assert_not_called()
            with self.assertRaises(RuntimeError):self.store.create('owner',self.generate(receipt['id']),paired_flow=True)
        self.assertEqual(len(self.store.db.jobs()),0)
        self.assertEqual(self.store.household_owned(receipt['id'],'owner')['raw_answers'],answers())
        exported=list(records(self.tmp.name));self.assertEqual(len(exported),1);self.assertEqual(exported[0]['case_ids'],[])
        self.store.db.close();self.store=Store(self.tmp.name,human_pilot=True);self.store.pool=NoExecute()
        self.assertEqual(self.store.household_owned(receipt['id'],'owner')['household_record_hash'],receipt['household_record_hash'])
    def test_consent_version_ownership_and_immutable_retry(self):
        p=self.payload();p['research_consent']=False
        with self.assertRaises(ValueError):self.store.save_household('owner',p)
        p=self.payload();p['scenario_understood']=False
        with self.assertRaises(ValueError):self.store.save_household('owner',p)
        p=self.payload();r=self.store.save_household('owner',p)
        self.assertTrue(self.store.save_household('owner',p)['duplicate'])
        p['ui_version']='changed'
        with self.assertRaises(ValueError):self.store.save_household('owner',p)
        with self.assertRaises(KeyError):self.store.household_owned(r['id'],'other')
        with self.assertRaises(KeyError):self.store.create('other',self.generate(r['id']),paired_flow=True)
        p=self.payload('intake_request_00002');p['questionnaire_hash']='old'
        with self.assertRaises(ValueError):self.store.save_household('owner',p)

    def test_intake_limits_preserve_idempotency_and_exempt_admin(self):
        self.store.max_session_intakes=1
        first=self.payload();receipt=self.store.save_household('owner',first)
        self.assertEqual(self.store.save_household('owner',first)['id'],receipt['id'])
        with self.assertRaises(OverflowError):
            self.store.save_household('owner',self.payload('intake_request_00002'))
        self.store.max_daily_intakes=1
        with self.assertRaises(OverflowError):
            self.store.save_household('other',self.payload('intake_request_00003','other'))
        admin=self.store.save_household('admin',self.payload('intake_request_00004','admin'),admin=True)
        self.assertTrue(admin['saved'])
    def test_native_unsupported_time_is_preserved_in_intake(self):
        p=self.payload();p['answers']['B05']=['electric_water_heater']
        p['answers'].update(H_electric_water_heater='0',D_electric_water_heater='8',P_HOT_WATER='8',P_PREHEAT='yes')
        r=self.store.save_household('owner',p)
        self.assertEqual(self.store.household_owned(r['id'],'owner')['profile']['H_electric_water_heater']['value'],'0')
        with self.assertRaises(ValueError):self.store.create('owner',self.generate(r['id']),paired_flow=True)
        self.assertEqual(len(list(records(self.tmp.name))),1)

    def test_contradictory_task_start_is_rejected_before_intake_persistence(self):
        p=self.payload();p['answers'].update(E_washer='8',D_washer='22',T_washer='2.0',H_washer='21')
        with self.assertRaisesRegex(ValueError,'平时开始时间必须落在可用时间内'):
            self.store.save_household('owner',p)
        self.assertEqual(self.store.db.households(),[])

    def test_cross_midnight_task_start_is_valid_at_intake(self):
        p=self.payload();p['answers'].update(E_washer='23',D_washer='0.333333333333',T_washer=str(70/60),H_washer='23.1666666667')
        receipt=self.store.save_household('owner',p)
        self.assertTrue(receipt['saved'])
    def test_linked_records_export_once_and_preserve_frozen_hash(self):
        r=self.store.save_household('owner',self.payload());job=self.store.create('owner',self.generate(r['id']),paired_flow=True)
        self.assertEqual(job['household_submission_id'],r['id']);self.assertEqual(job['household_record_hash'],r['household_record_hash'])
        from household_config import ensure_household_config
        request=self.store.db.document(job['id'],'request.json')
        self.assertIn('environment',request['scenario'])
        self.assertEqual(ensure_household_config(request),job['household_config'])
        self.assertEqual(request['household_config_hash'],job['household_config_hash'])
        self.assertEqual(self.store.db.document(job['id'],'questionnaire_submission.json')['raw_answers'],answers())
        job['status']='failed';self.store.persist(job)
        job2=self.store.create('owner',self.generate(r['id'],'generate_request_00002'),paired_flow=True)
        exported=list(records(self.tmp.name));self.assertEqual(len(exported),1)
        self.assertEqual(set(exported[0]['case_ids']),{job['id'],job2['id']})
    def test_queue_and_session_limits_keep_saved_intakes_and_retry_receipts(self):
        self.store.max_pending=1;self.store.max_session_jobs=1
        r=self.store.save_household('owner',self.payload());payload=self.generate(r['id'])
        job=self.store.create('owner',payload,paired_flow=True)
        self.assertEqual(self.store.create('owner',payload,paired_flow=True)['id'],job['id'])
        other=self.store.save_household('other',self.payload(owner='other'))
        with self.assertRaises(OverflowError):self.store.create('other',self.generate(other['id']),paired_flow=True)
        self.assertEqual(len(list(records(self.tmp.name))),2)
        job['status']='failed';self.store.persist(job)
        with self.assertRaises(OverflowError):self.store.create('owner',self.generate(r['id'],'generate_request_00002'),paired_flow=True)
    def test_human_legacy_generation_is_disabled(self):
        with self.assertRaises(ValueError):self.store.create('owner',{})
        with self.assertRaises(ValueError):self.store.example('owner')
        with self.assertRaises(ValueError):self.store.create('owner',{'request_id':'legacy_request_000001'},paired_flow=True)
    def test_intake_transaction_failure_never_returns_false_receipt(self):
        with self.store.db.lock,self.store.db.conn:
            self.store.db.conn.execute("CREATE TRIGGER abort_intake BEFORE INSERT ON household_submissions BEGIN SELECT RAISE(ABORT,'test failure'); END")
        with self.assertRaises(Exception):self.store.save_household('owner',self.payload())
        self.assertEqual(self.store.db.households('owner'),[])

    def test_fifty_concurrent_receipts_and_duplicate_retries(self):
        import concurrent.futures
        def save(i):return self.store.save_household('household-'+str(i),self.payload(owner='household-'+str(i)))
        with concurrent.futures.ThreadPoolExecutor(50) as pool:receipts=list(pool.map(save,range(50)))
        with concurrent.futures.ThreadPoolExecutor(50) as pool:duplicates=list(pool.map(save,range(50)))
        self.assertEqual(len(self.store.db.households()),50)
        self.assertEqual([r['id'] for r in receipts],[r['id'] for r in duplicates])
        self.assertTrue(all(r['duplicate'] for r in duplicates))
        self.assertEqual(len(list(records(self.tmp.name))),50)

    def test_http_intake_while_planning_paused_and_https_cookie(self):
        import http.client,threading
        with tempfile.TemporaryDirectory() as root:
            srv=make_server(0,root,human_pilot=True,disable_planning=True,public_origin='https://survey.example')
            thread=threading.Thread(target=srv.serve_forever,daemon=True);thread.start()
            host,port=srv.server_address
            def call(path,payload=None,cookie=None):
                c=http.client.HTTPConnection(host,port,timeout=10)
                headers={'Origin':f'http://{host}:{port}','Content-Type':'application/json'}
                if cookie:headers['Cookie']=cookie
                c.request('GET' if payload is None else 'POST',path,None if payload is None else json.dumps(payload),headers)
                r=c.getresponse();out=(r.status,json.loads(r.read()),r.getheader('Set-Cookie'));c.close();return out
            try:
                code,session,cookie=call('/api/session');self.assertEqual(code,200);self.assertIn('Secure',cookie)
                cookie=cookie.split(';')[0]
                code,receipt,_=call('/api/households',self.payload(owner=cookie.split('=',1)[1]),cookie);self.assertEqual(code,201)
                self.assertEqual(call('/api/households/'+receipt['id'],cookie=cookie)[0],200)
                self.assertEqual(call('/api/households/'+receipt['id'],cookie='pilot_session='+'f'*64)[0],404)
                code,current,_=call('/api/session',cookie=cookie);self.assertEqual(len(current['households']),1)
                self.assertEqual(call('/api/paired',self.generate(receipt['id']),cookie)[0],503)
                self.assertEqual(call('/api/example',{},cookie)[0],403)
                self.assertEqual(len(list(records(root))),1)
                code,cleared,new_cookie=call('/api/session/reset',{},cookie);self.assertEqual(code,200);self.assertTrue(cleared['cleared'])
                self.assertNotEqual(new_cookie.split(';')[0],cookie)
                rotated=new_cookie.split(';')[0]
                self.assertEqual(call('/api/session',cookie=rotated)[1]['households'],[])
                self.assertEqual(call('/api/households/'+receipt['id'],cookie=rotated)[0],404)
                # Clearing a shared browser severs browser access; immutable
                # research records remain available to the authorized export.
                self.assertEqual(len(list(records(root))),1)
            finally:
                srv.shutdown();srv.server_close();srv.store.pool.shutdown();srv.store.db.close();thread.join()

    def test_global_utc_daily_quota_counts_failed_jobs_and_preserves_retries(self):
        self.store.max_daily_jobs=1
        with patch('server.time.time',return_value=20000*86400+30):
            r=self.store.save_household('owner',self.payload());p=self.generate(r['id']);job=self.store.create('owner',p,paired_flow=True)
            job['status']='failed';self.store.persist(job)
            r2=self.store.save_household('other',self.payload(owner='other'))
            with self.assertRaises(OverflowError):self.store.create('other',self.generate(r2['id']),paired_flow=True)
            self.assertEqual(self.store.create('owner',p,paired_flow=True)['id'],job['id'])
            self.assertEqual(len(list(records(self.tmp.name))),2)
        with patch('server.time.time',return_value=20001*86400):
            self.assertEqual(self.store.create('other',self.generate(r2['id']),paired_flow=True)['status'],'queued')

    def test_public_human_http_rejected_before_binding(self):
        with self.assertRaises(ValueError):make_server(0,self.tmp.name,human_pilot=True,public_origin='http://survey.example',disable_planning=True)

    def test_backup_contains_intake_even_with_no_jobs(self):
        from pathlib import Path
        import tarfile
        from backup_backend import backup
        r=self.store.save_household('owner',self.payload())
        with tempfile.TemporaryDirectory() as directory:
            archive=Path(directory)/'saved.tar.gz';backup(self.tmp.name,archive)
            destination=Path(directory)/'restore'
            with tarfile.open(archive) as tar:tar.extractall(destination,filter='data')
            restored=Store(destination,human_pilot=True);restored.pool=NoExecute()
            try:self.assertEqual(restored.household_owned(r['id'],'owner')['household_record_hash'],r['household_record_hash'])
            finally:restored.db.close()

    def test_collection_funnel_keeps_saved_only_and_failed_households(self):
        from export_collection_funnel import build_report
        first=self.store.save_household('owner',self.payload())
        second=self.store.save_household('other',self.payload('intake_request_00002','other'))
        job=self.store.create('other',self.generate(second['id']),paired_flow=True)
        job.update(status='failed');self.store.persist(job)
        report=build_report(self.tmp.name)
        self.assertEqual(report['stages']['intake_saved'],2)
        self.assertEqual(report['stages']['environment_ready_at_intake'],2)
        self.assertEqual(report['stages']['environment_ready_current_catalog'],2)
        self.assertEqual(report['stages']['generation_attempted'],1)
        self.assertEqual(report['dropoff'],{'saved_without_generation':1,'generation_not_completed':1})
        self.assertEqual(report['case_statuses'],{'failed':1})
        month=assigned_context('owner')['date'][5:7]
        self.assertEqual(report['coverage']['assigned_month'],{month:1,assigned_context('other')['date'][5:7]:1} if month!=assigned_context('other')['date'][5:7] else {month:2})
        self.assertEqual(first['id'] in {r['id'] for r in self.store.db.households()},True)
        from household_classification import intake_records
        rows,conflicts=intake_records(self.tmp.name)
        self.assertEqual(len(rows),2)
        self.assertEqual(conflicts,[])

if __name__=='__main__':unittest.main()
