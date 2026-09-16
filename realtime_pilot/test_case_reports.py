"""Reports/diagnostics use saved records only. No EP or paid API execution."""
import concurrent.futures
import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import case_reports
from common import digest
from date_sampling import assigned_context
from paired_contract import QUESTIONS, QUESTIONNAIRE_VERSION, CONTEXT
from server import Store, make_server, PARTICIPANT_UI_VERSION
from test_pilot import NoExecute
from regional_test_support import answers


class ReportTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.store=Store(self.tmp.name,max_queue_wait=0)
        self.store.pool.shutdown();self.store.pool=NoExecute()
        self.owner='a'*64

    def tearDown(self):
        self.store.db.close();self.tmp.cleanup()

    def intake(self, name='', nonce='household_report_0001'):
        return self.store.save_household(self.owner,{
            'request_id':nonce,'answers':answers(),'participant_name':name,
            'questionnaire_version':QUESTIONNAIRE_VERSION,'questionnaire_hash':digest(QUESTIONS),
            'questionnaire_context_hash':assigned_context(self.owner)['context_hash'],
            'ui_version':PARTICIPANT_UI_VERSION})

    def case(self, sid):
        return self.store.create(self.owner,{'request_id':'case_report_create_0001',
              'submission_id':sid,'scenario_id':CONTEXT['id'],'scenario_understood':True},paired_flow=True)

    def payload(self, target, kind='case', nonce='report_test_00000001'):
        return {'target_type':kind,'target_id':target,'category':'schedule',
                'description':'洗衣结束时间不合理','request_id':nonce,'ui_version':PARTICIPANT_UI_VERSION}

    def test_optional_name_separate_from_planner_and_old_intake_unchanged(self):
        sid=self.intake('小林')['id'];job=self.case(sid)
        stored=self.store.db.household(sid)
        self.assertEqual(stored['participant_name'],'小林')
        self.assertEqual(job['household_submission_id'],sid)
        for name in ['request.json','household_config.json','questionnaire_submission.json','household_record.json']:
            self.assertNotIn('小林',json.dumps(self.store.db.document(job['id'],name),ensure_ascii=False))
        new=self.intake('小张','household_report_0002')
        self.assertNotEqual(sid,new['id']);self.assertEqual(self.store.db.household(sid)['participant_name'],'小林')
        self.assertEqual(self.store.db.household(self.intake(nonce='household_report_0003')['id'])['participant_name'],'')
        with self.assertRaises(ValueError):self.intake('x'*81,'household_report_0004')

    def test_report_ownership_idempotency_no_execution_and_pre_case_failure(self):
        sid=self.intake()['id']
        with patch('server.paired.prepare',side_effect=ValueError('bad input')):
            with self.assertRaises(ValueError):self.case(sid)
        report=case_reports.submit(self.store,self.owner,self.payload(sid,'household'))
        self.assertTrue(report['saved']);self.assertEqual(len(self.store.jobs),0)
        job=self.case(sid);jid=job['id'];before=digest(self.store.db.job(jid))
        payload=self.payload(jid,nonce='report_case_0000001')
        with patch.object(self.store.pool,'submit',side_effect=AssertionError('must not execute')):
            first=case_reports.submit(self.store,self.owner,payload)
            again=case_reports.submit(self.store,self.owner,payload)
        self.assertEqual(first['report_id'],again['report_id'])
        self.assertEqual(before,digest(self.store.db.job(jid)))
        self.assertIsNone(self.store.db.document(jid,'decision.json'))
        with self.assertRaises(KeyError):case_reports.submit(self.store,'b'*64,payload)
        with self.assertRaises(ValueError):case_reports.submit(self.store,self.owner,{**payload,'description':'changed'})
        with self.assertRaises(ValueError):case_reports.submit(self.store,self.owner,{**payload,'target_id':'../../etc/passwd'})

    def test_concurrent_duplicate_restart_review_and_backup(self):
        sid=self.intake()['id'];payload=self.payload(sid,'household')
        with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
            receipts=list(pool.map(lambda _:case_reports.submit(self.store,self.owner,payload),range(50)))
        self.assertEqual(len({r['report_id'] for r in receipts}),1)
        rid=receipts[0]['report_id']
        case_reports.review(self.store,rid,{'status':'not_bug','note':'原安排合理'},'researcher')
        case_reports.review(self.store,rid,{'status':'open','note':'再核对'},'researcher')
        self.store.db.backup(Path(self.tmp.name)/'backup.sqlite3')
        self.store.db.close();self.store=Store(self.tmp.name,max_queue_wait=0);self.store.pool.shutdown();self.store.pool=NoExecute()
        report=case_reports.list_reports(self.store,'open')['reports'][0]
        self.assertEqual(len(report['review_history']),2)
        self.assertEqual(report['description'],payload['description'])
        self.assertEqual(case_reports.list_reports(self.store,'not_bug')['reports'],[])
        self.assertEqual(case_reports.list_reports(self.store,before=rid)['reports'],[])

    def test_quota_and_diagnostic_partial_artifacts_redaction(self):
        sid=self.intake('不导出名字')['id'];job=self.case(sid);job['status']='failed';self.store.persist(job)
        root=Path(self.tmp.name)/job['id'];attempt=root/'attempts/0001';attempt.mkdir(parents=True)
        (attempt/'worker.log').write_text('Authorization: Bearer sensitive\napi_key=secret-value\nsk-abcdefghi1234\n/home/test/private.json')
        (attempt/'plan.json').write_text(json.dumps({'action':'wait','api_key':'private','owner':self.owner}))
        (attempt/'partial.json').write_text('{')
        (attempt/'token.txt').write_text('private-value')
        (attempt/'outside.log').symlink_to('/etc/hosts')
        for i in range(20):case_reports.submit(self.store,self.owner,self.payload(job['id'],nonce=f'report_quota_{i:016}'))
        with self.assertRaises(OverflowError):case_reports.submit(self.store,self.owner,self.payload(job['id'],nonce='report_quota_extra1'))
        bundle=case_reports.diagnostic(self.store,'case',job['id'])
        self.assertEqual(bundle['job']['household_submission_id'],sid)
        self.assertIn('outcome.json',bundle['missing_documents']);self.assertIn('decision.json',bundle['missing_documents'])
        self.assertEqual(bundle['artifacts']['attempts/0001/plan.json'],{'action':'wait'})
        text=json.dumps(bundle,ensure_ascii=False)
        for value in ['不导出名字',self.owner,'secret-value','sk-abcdefghi1234','private-value','/home/test/private.json']:
            self.assertNotIn(value,text)
        statuses={v['path']:v['status'] for v in bundle['artifact_manifest']}
        self.assertEqual(statuses['attempts/0001/partial.json'],'unavailable_or_incomplete')
        self.assertEqual(statuses['attempts/0001/outside.log'],'excluded')
        self.assertEqual(bundle['job']['status'],'failed')

    def test_backup_includes_failed_trace_and_reports(self):
        import tarfile, sqlite3
        from backup_backend import backup
        sid=self.intake()['id'];job=self.case(sid);job['status']='timeout';self.store.persist(job)
        path=Path(self.tmp.name)/job['id']/'attempts/0001';path.mkdir(parents=True)
        (path/'worker.log').write_text('partial execution')
        case_reports.submit(self.store,self.owner,self.payload(job['id']))
        with tempfile.TemporaryDirectory() as folder:
            output=Path(folder)/'backup.tar.gz';result=backup(self.tmp.name,output)
            self.assertTrue(result['includes_terminal_traces'])
            with tarfile.open(output) as archive:
                self.assertIn(job['id']+'/attempts/0001/worker.log',archive.getnames())
                snapshot=Path(folder)/'state.sqlite3';snapshot.write_bytes(archive.extractfile('state.sqlite3').read())
            with sqlite3.connect(snapshot) as conn:
                self.assertEqual(conn.execute('SELECT COUNT(*) FROM case_reports').fetchone()[0],1)

    def test_optional_research_fields_remain_optional(self):
        for question in QUESTIONS:
            if question.get('research_only'):
                self.assertFalse(question['required_for_intake'])
                self.assertFalse(question['required_for_generation'])
        members=next(q for q in QUESTIONS if q['id']=='M_MEMBERS')
        self.assertEqual([f['id'] for f in members['fields'] if f.get('required')],['routine'])

    def test_running_report_reads_actual_progress_file(self):
        sid=self.intake()['id'];job=self.case(sid);job.update(status='running',run_directory='attempts/0001');self.store.persist(job)
        folder=Path(self.tmp.name)/job['id']/job['run_directory'];folder.mkdir(parents=True)
        (folder/'progress.json').write_text(json.dumps({'stage':'planning'}))
        case_reports.submit(self.store,self.owner,self.payload(job['id']))
        report=case_reports.list_reports(self.store)['reports'][0]
        self.assertEqual(report['reported_stage'],'planning')
        self.assertEqual(report['reported_status'],'running')

    def test_page_report_before_any_intake_needs_no_case(self):
        payload={**self.payload(None,'page'),'page_context':'家庭成员'}
        receipt=case_reports.submit(self.store,self.owner,payload)
        self.assertEqual(case_reports.submit(self.store,self.owner,payload)['report_id'],receipt['report_id'])
        report=case_reports.list_reports(self.store)['reports'][0]
        self.assertIsNone(report['case_id']);self.assertIsNone(report['household_submission_id'])
        self.assertEqual(report['reported_status'],'page_only');self.assertEqual(report['page_context'],'家庭成员')
        bundle=case_reports.diagnostic(self.store,'page',report['target_id'])
        self.assertEqual(bundle['reports'][0]['id'],receipt['report_id'])
        self.assertIsNone(bundle['job']);self.assertIsNone(bundle['household_submission'])
        self.assertEqual(self.store.db.household_count(),0);self.assertEqual(len(self.store.jobs),0)
        with self.assertRaises(ValueError):case_reports.submit(self.store,self.owner,{**payload,'target_id':report['target_id']})
        case_reports.submit(self.store,'b'*64,payload)
        other=case_reports.list_reports(self.store)['reports'][0]
        self.assertNotEqual(other['target_id'],report['target_id'])

    def test_http_permissions_and_routes_while_planning_disabled(self):
        server=make_server(0,self.tmp.name,disable_planning=True,admin_user='researcher',max_queue_wait=0)
        sid=self.intake()['id']
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        def call(path,body=None,admin=False,owner=None,origin=True):
            conn=http.client.HTTPConnection(*server.server_address,timeout=10)
            headers={'Cookie':'pilot_session='+(owner or self.owner),'Content-Type':'application/json'}
            if origin:headers['Origin']=f'http://127.0.0.1:{server.server_address[1]}'
            if admin:headers['X-EB-Authenticated-User']='researcher'
            conn.request('GET' if body is None else 'POST',path,None if body is None else json.dumps(body),headers)
            response=conn.getresponse();data=json.loads(response.read());conn.close();return response.status,data
        try:
            self.assertEqual(call('/api/admin/reports')[0],403)
            self.assertEqual(call('/admin/api/admin/diagnostics/household/'+sid)[0],403)
            self.assertEqual(call('/api/reports',self.payload(sid,'household'),owner='b'*64)[0],404)
            self.assertEqual(call('/api/reports',self.payload(sid,'household'),origin=False)[0],403)
            code,receipt=call('/api/reports',self.payload(sid,'household'));self.assertEqual(code,201)
            path='/api/admin/reports/'+receipt['report_id']
            self.assertEqual(call(path,{'status':'fixed'})[0],403)
            self.assertEqual(call('/admin'+path,{'status':'fixed'},admin=True)[0],200)
            self.assertEqual(call('/admin/api/admin/reports?status=fixed',admin=True)[1]['reports'][0]['id'],receipt['report_id'])
            self.assertEqual(call('/admin/api/admin/diagnostics/household/'+sid,admin=True)[0],200)
            self.assertEqual(call('/api/admin/diagnostics/case/'+'f'*32,admin=True)[0],404)
        finally:
            server.shutdown();server.server_close();server.store.pool.shutdown();server.store.db.close();thread.join()


if __name__=='__main__':unittest.main()
