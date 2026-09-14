"""Proof lifecycle and expensive-route enforcement, with execution disabled."""
import base64
import http.client
import json
import tempfile
import threading
import unittest
from unittest.mock import patch
from local_captcha import LocalCaptcha,CaptchaError
from server import make_server
from test_pilot import NoExecute
from regional_test_support import answers
from paired_contract import CONTEXT

class CaptchaTests(unittest.TestCase):
    def test_lifecycle_binding_expiry_and_attempts(self):
        c=LocalCaptcha();c._new_code=lambda:'AC2346'
        with patch('local_captcha.time.monotonic',return_value=100):
            issued=c.issue('owner','request_captcha_0001')
            self.assertTrue(base64.b64decode(issued['image'].split(',')[1]).startswith(b'\x89PNG'))
            self.assertNotIn('AC2346',json.dumps(issued))
            with self.assertRaises(OverflowError):c.issue('owner','request_captcha_0002')
            for owner,nonce in [('other','request_captcha_0001'),('owner','request_captcha_0002')]:
                with self.assertRaises(CaptchaError):c.consume(owner,nonce,{'id':issued['id'],'answer':'AC2346'})
            for _ in range(3):
                with self.assertRaises(CaptchaError):c.consume('owner','request_captcha_0001',{'id':issued['id'],'answer':'WRONG'})
            with self.assertRaises(CaptchaError):c.consume('owner','request_captcha_0001',{'id':issued['id'],'answer':'AC2346'})
            issued=c.issue('owner','request_captcha_0001')
        with patch('local_captcha.time.monotonic',return_value=281):
            with self.assertRaises(CaptchaError):c.consume('owner','request_captcha_0001',{'id':issued['id'],'answer':'AC2346'})
            issued=c.issue('owner','request_captcha_0001')
            c.consume('owner','request_captcha_0001',{'id':issued['id'],'answer':' ac2346 '})
            with self.assertRaises(CaptchaError):c.consume('owner','request_captcha_0001',{'id':issued['id'],'answer':'AC2346'})

    def test_http_gate_idempotency_and_admin_namespace(self):
        with tempfile.TemporaryDirectory() as root:
            s=make_server(0,root,disable_planning=True,local_captcha=True,admin_user='admin')
            s.store.pool.shutdown();s.store.pool=NoExecute();s.planning_disabled=False;s.captcha._new_code=lambda:'AC2346'
            threading.Thread(target=s.serve_forever,daemon=True).start()
            def call(path,body=None,admin=False,owner='a'*64):
                c=http.client.HTTPConnection(*s.server_address);headers={'Origin':f'http://127.0.0.1:{s.server_address[1]}','Content-Type':'application/json','Cookie':'pilot_session='+owner}
                if admin:headers['X-EB-Authenticated-User']='admin'
                c.request('GET' if body is None else 'POST',path,None if body is None else json.dumps(body),headers)
                r=c.getresponse();raw=r.read();out=json.loads(raw) if 'application/json' in r.headers.get('Content-Type','') else None;c.close();return r.status,out
            body={'request_id':'captcha_submit_00001','answers':answers(),'scenario_id':CONTEXT['id'],'scenario_understood':True}
            try:
                self.assertEqual(call('/')[0],200)
                self.assertTrue(call('/api/session')[1]['captcha_enabled'])
                for route in ['/admin/survey','/admin/api/session','/admin/admin.js']:
                    self.assertEqual(call(route)[0],403)
                    self.assertEqual(call(route,admin=True)[0],200)
                self.assertFalse(call('/admin/api/session',admin=True)[1]['captcha_enabled'])
                self.assertEqual(call('/api/paired',body)[0],400)
                self.assertEqual(len(s.store.jobs),0)
                proof=call('/api/captcha',{'request_id':body['request_id']})[1]
                bad={**body,'captcha':{'id':proof['id'],'answer':'WRONG!'}}
                self.assertEqual(call('/api/paired',bad)[1]['code'],'captcha_invalid')
                valid={**body,'captcha':{'id':proof['id'],'answer':'AC2346'}}
                self.assertEqual(call('/api/paired',valid,owner='b'*64)[0],400)
                status,job=call('/api/paired',valid);self.assertEqual(status,202)
                self.assertEqual(call('/api/paired',body)[1]['id'],job['id'])
                self.assertEqual(call('/api/paired',{**body,'scenario_understood':False})[0],400)
                self.assertEqual(call('/api/paired',{**valid,'request_id':'captcha_submit_00002'})[0],400)
                request=s.store.db.document(job['id'],'request.json');self.assertNotIn('captcha',request)
                status,job=call('/admin/api/paired',body,admin=True);self.assertEqual(status,202)
                self.assertTrue(s.store.jobs[job['id']]['admin_test'])
            finally:s.shutdown();s.server_close();s.store.db.close()
