import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
from urllib.request import Request, build_opener, ProxyHandler
from urllib.error import HTTPError
import zipfile
from common import digest, write_json
from compute_protocol import PROTOCOL, safe_unpack
from compute_service import ComputeStore, ComputeHTTPServer, Handler
from remote_compute import run_remote, check_remote_ready

class ComputeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.script=self.root/'fixture.py'
        self.script.write_text("import sys,json,time\nfrom pathlib import Path\np=Path(sys.argv[1])\n(p/'started').write_text('1')\ntime.sleep(.15)\n(p/'outcome.json').write_text(json.dumps({'fixture':True}))\n")
        with patch('compute_service.release_hash',return_value='release'):
            self.store=ComputeStore(self.root/'jobs',slots=1,lease=2,timeout=10,min_free=0,
                command=lambda p:[sys.executable,str(self.script),str(p)])
        self.server=ComputeHTTPServer(('127.0.0.1',0),Handler);self.server.token='x'*40;self.server.store=self.store
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.base='http://127.0.0.1:'+str(self.server.server_port)
    def tearDown(self):
        self.store.close();self.server.shutdown();self.server.server_close();self.thread.join();self.tmp.cleanup()
    def payload(self):return {'protocol':PROTOCOL,'release':'release','request':{'fixture':1},'request_hash':digest({'fixture':1})}
    def test_live_readiness_is_read_only_and_rejects_partial_deployment(self):
        token=self.root/'token';token.write_text('x'*40)
        with patch.dict(os.environ,{'EB_COMPUTE_URL':self.base,'EB_COMPUTE_TOKEN_FILE':str(token)}):
            self.assertEqual(check_remote_ready(expected='release')['release'],'release')
            with self.assertRaisesRegex(ValueError,'Compute release mismatch'):
                check_remote_ready(expected='partially-updated-cloud')
        self.assertEqual(self.store.jobs,{})

    def test_worker_preflight_rejects_mismatch_without_creating_task(self):
        folder=self.root/'cloud';folder.mkdir();write_json(folder/'request.json',{'fixture':1})
        token=self.root/'token';token.write_text('x'*40)
        with patch.dict(os.environ,{'EB_COMPUTE_URL':self.base,'EB_COMPUTE_TOKEN_FILE':str(token)}),patch('remote_compute.release_hash',return_value='wrong'):
            with self.assertRaisesRegex(ValueError,'Compute release mismatch'):run_remote(folder)
        self.assertEqual(self.store.jobs,{})
    def test_roundtrip_and_no_duplicate_on_lost_response(self):
        folder=self.root/'cloud';folder.mkdir();write_json(folder/'request.json',{'fixture':1})
        token=self.root/'token';token.write_text('x'*40)
        with patch.dict(os.environ,{'EB_COMPUTE_URL':self.base,'EB_COMPUTE_TOKEN_FILE':str(token)}),patch('remote_compute.release_hash',return_value='release'):
            run_remote(folder)
            first=json.loads((folder/'compute_transport.json').read_text())
            run_remote(folder)
        self.assertEqual(len(self.store.jobs),1)
        self.assertEqual(json.loads((folder/'outcome.json').read_text()),{'fixture':True})
        self.assertTrue((folder/'transport_manifest.json').exists())
        self.assertEqual(first['request_hash'],digest({'fixture':1}))
    def test_release_conflict_and_capacity(self):
        payload=self.payload()
        with self.assertRaises(ValueError):self.store.submit('a'*64,{**payload,'release':'wrong'})
        self.store.submit('a'*64,payload)
        with self.assertRaises(BlockingIOError):self.store.submit('b'*64,payload)
        with self.assertRaises(ValueError):self.store.submit('a'*64,{**payload,'request':{},'request_hash':digest({})})
    def test_sixteen_http_jobs_are_isolated_and_seventeenth_waits(self):
        self.store.slots=16;self.store.lease=20
        self.script.write_text("import sys,time,json\nfrom pathlib import Path\np=Path(sys.argv[1])\nwhile not (p.parent/'release_workers').exists():time.sleep(.05)\n(p/'outcome.json').write_text(json.dumps({'id':p.name}))\n")
        def submit(i):
            req=Request(self.base+'/jobs/'+format(i,'064x'),data=json.dumps(self.payload()).encode(),
                        headers={'Authorization':'Bearer '+self.server.token,'Content-Type':'application/json'})
            with build_opener(ProxyHandler({})).open(req,timeout=5) as r:return json.load(r)
        with ThreadPoolExecutor(16) as pool:rows=list(pool.map(submit,range(16)))
        self.assertTrue(all(row['status']=='running' for row in rows))
        self.assertEqual(len(self.store.processes),16)
        with self.assertRaises(HTTPError) as e:submit(16)
        self.assertEqual(e.exception.code,429);e.exception.close()
        self.assertEqual(len(self.store.jobs),16)
        (self.store.root/'release_workers').touch()
        limit=time.monotonic()+5
        while self.store.processes and time.monotonic()<limit:time.sleep(.05)
        self.assertFalse(self.store.processes)
        for i in range(16):
            jid=format(i,'064x')
            self.assertEqual(self.store.snapshot(jid)['status'],'complete')
            self.assertEqual(json.loads((self.store.root/jid/'outcome.json').read_text())['id'],jid)
        submit(16)
    def test_cloud_restart_reuses_remote_job_across_attempts(self):
        token=self.root/'token';token.write_text('x'*40)
        for attempt in ('0001','0002'):
            folder=self.root/'cloud_job'/'attempts'/attempt;folder.mkdir(parents=True)
            write_json(folder/'request.json',{'fixture':1})
            with patch.dict(os.environ,{'EB_COMPUTE_URL':self.base,'EB_COMPUTE_TOKEN_FILE':str(token)}),patch('remote_compute.release_hash',return_value='release'):
                run_remote(folder)
        self.assertEqual(len(self.store.jobs),1)
    def test_data_root_migration_reuses_remote_job(self):
        token=self.root/'token';token.write_text('x'*40)
        ids=[]
        for root in ('old_data_root','restored_data_root'):
            folder=self.root/root/'same_logical_job'/'attempts'/'0001';folder.mkdir(parents=True)
            write_json(folder/'request.json',{'fixture':1})
            with patch.dict(os.environ,{'EB_COMPUTE_URL':self.base,'EB_COMPUTE_TOKEN_FILE':str(token)}),patch('remote_compute.release_hash',return_value='release'):
                run_remote(folder)
            ids.append(json.loads((folder/'compute_transport.json').read_text())['job_id'])
        self.assertEqual(ids[0],ids[1])
        self.assertEqual(len(self.store.jobs),1)
    def test_expired_lease_kills_process(self):
        self.script.write_text('import time\ntime.sleep(30)\n');self.store.lease=.1
        self.store.submit('a'*64,self.payload());process=self.store.processes['a'*64]
        limit=time.monotonic()+3
        while time.monotonic()<limit and process.poll() is None:time.sleep(.05)
        self.assertIsNotNone(process.poll());self.assertEqual(self.store.snapshot('a'*64)['status'],'expired')
    def test_unauthorized_request_is_rejected(self):
        with self.assertRaises(HTTPError) as e:build_opener(ProxyHandler({})).open(self.base+'/health')
        self.assertEqual(e.exception.code,401)
        e.exception.close()
    def test_restart_does_not_retry_interrupted_job(self):
        self.script.write_text('import time\ntime.sleep(30)\n');self.store.submit('a'*64,self.payload());self.store.close()
        with patch('compute_service.release_hash',return_value='release'):
            other=ComputeStore(self.root/'jobs',min_free=0)
        self.assertEqual(other.snapshot('a'*64)['status'],'interrupted');self.assertEqual(other.processes,{})
    def test_archive_traversal_rejected(self):
        archive=self.root/'bad.zip'
        with zipfile.ZipFile(archive,'w') as z:z.writestr('../escape','x')
        with self.assertRaises(ValueError):safe_unpack(archive,self.root/'unpacked')
        self.assertFalse((self.root/'escape').exists())
    def test_cancellation_during_packaging_stays_terminal(self):
        from compute_protocol import archive_job
        entered=threading.Event();proceed=threading.Event()
        def slow(folder):
            entered.set();proceed.wait(3);return archive_job(folder)
        with patch('compute_service.archive_job',side_effect=slow):
            self.store.submit('a'*64,self.payload())
            try:
                self.assertTrue(entered.wait(2));self.store.cancel('a'*64)
            finally:proceed.set()
            limit=time.monotonic()+3
            while self.store.processes and time.monotonic()<limit:time.sleep(.05)
        self.assertEqual(self.store.snapshot('a'*64)['status'],'cancelled')

if __name__=='__main__':unittest.main()
