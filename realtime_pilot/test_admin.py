"""Trusted proxy admin role relaxes quotas without relaxing execution safety."""
import http.client
import json
import tempfile
import threading
import unittest
from common import digest
from paired_contract import CONTEXT,QUESTIONS,QUESTIONNAIRE_VERSION
from server import make_server
from test_pilot import NoExecute
from regional_test_support import answers


class AdminTests(unittest.TestCase):
    def test_role_quotas_data_origin_and_public_isolation(self):
        with tempfile.TemporaryDirectory() as root:
            server=make_server(0,root,disable_planning=True,human_pilot=True,admin_user='testadmin',max_session_jobs=1,max_daily_jobs=1,max_pending=1,max_queue_wait=0)
            server.store.pool.shutdown();server.store.pool=NoExecute();server.planning_disabled=False
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            def call(path,body=None,admin=False,cookie='a'*64):
                conn=http.client.HTTPConnection(*server.server_address,timeout=10)
                headers={'Origin':f'http://127.0.0.1:{server.server_address[1]}','Cookie':'pilot_session='+cookie,'Content-Type':'application/json'}
                if admin:headers['X-EB-Authenticated-User']='testadmin'
                conn.request('GET' if body is None else 'POST',path,None if body is None else json.dumps(body),headers)
                r=conn.getresponse();out=(r.status,json.loads(r.read()) if path!='/admin' else None);conn.close();return out
            def intake(admin=False,cookie='a'*64):
                return call('/api/households',{'questionnaire_context_hash':call('/api/session',admin=admin,cookie=cookie)[1]['questionnaire_context']['context_hash'],'request_id':'admin_intake_test_00001','answers':answers(),'questionnaire_version':QUESTIONNAIRE_VERSION,'questionnaire_hash':digest(QUESTIONS),'research_consent':True,'scenario_understood':True,'research_notice_version':'eb.research_notice.v2'},admin,cookie)[1]['id']
            def payload(sid,i):return {'submission_id':sid,'request_id':f'admin_generate_test_{i:04d}','scenario_id':CONTEXT['id'],'scenario_understood':True,'is_admin':True}
            def finish(jid):
                j=server.store.jobs[jid];j.update(status='failed');server.store.persist(j)
            try:
                self.assertEqual(call('/admin')[0],403)
                self.assertEqual(call('/api/admin/status')[0],403)
                self.assertFalse(call('/api/session')[1]['is_admin'])
                state=call('/api/session',admin=True)[1]
                self.assertTrue(state['is_admin']);self.assertEqual(state['collection_mode'],'engineering')
                public_sid=intake();admin_sid=intake(True)
                self.assertEqual(server.store.db.household(admin_sid)['data_origin'],'synthetic_engineering_test')
                self.assertEqual(server.store.db.household(public_sid)['data_origin'],'local_pilot_self_reported_human')
                code,first=call('/api/paired',payload(public_sid,1));self.assertEqual(code,202)
                # A full queue blocks even an admin, and paused planning still blocks it.
                self.assertEqual(call('/api/paired',payload(admin_sid,1),True)[0],429)
                finish(first['id'])
                server.planning_disabled=True
                self.assertEqual(call('/api/paired',payload(admin_sid,1),True)[0],503)
                server.planning_disabled=False
                self.assertEqual(call('/api/paired',payload(public_sid,2))[0],429)
                for i in range(1,4):
                    code,job=call('/api/paired',payload(admin_sid,i),True,cookie=str(i)*64);self.assertEqual(code,202)
                    saved=server.store.jobs[job['id']]
                    self.assertTrue(saved['admin_test']);self.assertEqual(saved['data_origin'],'synthetic_engineering_test')
                    self.assertEqual(server.store.db.document(job['id'],'request.json')['data_origin'],'synthetic_engineering_test')
                    self.assertEqual(call('/api/paired',payload(admin_sid,i),True,cookie='e'*64)[1]['id'],job['id'])
                    self.assertEqual(call('/api/jobs/'+job['id'],cookie=saved['owner'])[0],404)
                    finish(job['id'])
                status=call('/api/admin/status',admin=True)[1]
                self.assertEqual(status['tasks']['admin_tests'],3)
                self.assertEqual(status['limits']['pending_limit'],1)
                other=intake(cookie='b'*64)
                self.assertEqual(call('/api/paired',payload(other,1),cookie='b'*64)[0],429)
            finally:
                server.shutdown();server.server_close();server.store.db.close();thread.join()

    def test_admin_metadata_survives_restart_without_using_public_daily_budget(self):
        from server import Store
        with tempfile.TemporaryDirectory() as root:
            s=Store(root,max_daily_jobs=1,max_queue_wait=0);s.pool.shutdown();s.pool=NoExecute()
            request={'request_id':'admin_direct_00000001','answers':answers(),'scenario_id':CONTEXT['id'],'scenario_understood':True}
            try:
                j=s.create('admin_owner',request,paired_flow=True,admin=True);j.update(status='failed');s.persist(j)
            finally:s.db.close()
            s=Store(root,max_daily_jobs=1,max_queue_wait=0);s.pool.shutdown();s.pool=NoExecute()
            try:
                self.assertTrue(s.jobs.summary(j['id'])['admin_test'])
                ordinary=s.create('ordinary_owner',request,paired_flow=True)
                self.assertFalse(ordinary['admin_test'])
            finally:s.db.close()


if __name__=='__main__':unittest.main()
