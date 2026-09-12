"""Loopback-only, authenticated native job executor behind SSH reverse forwarding.

The website owns admission and final records. No automatic retry of native jobs.
Heartbeat leases stop abandoned jobs, including when a cloud client is SIGKILLed.
"""
import argparse
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
from common import ROOT, digest, write_json
from compute_protocol import PROTOCOL, MAX_REQUEST, archive_job, release_hash

ID = re.compile(r'^[a-f0-9]{64}$')
TERMINAL={'complete','failed','cancelled','expired','interrupted'}

def kill(process):
    if process.poll() is None:
        try:os.killpg(process.pid,signal.SIGKILL)
        except ProcessLookupError:pass
    process.wait()

class ComputeStore:
    def __init__(self,root,slots=4,lease=60,timeout=600,command=None,min_free=10*1024**3):
        if not 1<=slots<=32 or lease<=0 or timeout<=0:raise ValueError('Invalid compute capacity or deadline')
        self.root=Path(root);self.root.mkdir(parents=True,exist_ok=True)
        self.slots=slots;self.lease=lease;self.timeout=timeout;self.min_free=min_free
        self.command=command or (lambda folder:[sys.executable,'-u',str(ROOT/'paired_worker.py'),str(folder)])
        self.lock=threading.RLock();self.processes={};self.jobs={};self.stopping=False
        self.release=release_hash()
        for path in self.root.glob('*/transport_state.json'):
            row=json.loads(path.read_text());jid=path.parent.name
            if row['status'] not in TERMINAL:
                row.update(status='interrupted',error_type='ComputeServiceRestarted')
                write_json(path,row)
            self.jobs[jid]=row

    def save(self,jid):write_json(self.root/jid/'transport_state.json',self.jobs[jid])

    def submit(self,jid,payload):
        if not ID.fullmatch(jid):raise ValueError('Invalid job id')
        if payload.get('protocol')!=PROTOCOL or payload.get('release')!=self.release:
            raise ValueError('Compute release mismatch')
        request=payload['request'];sha=digest(request)
        if sha!=payload.get('request_hash'):raise ValueError('Request hash mismatch')
        with self.lock:
            if self.stopping:raise RuntimeError('Compute stopping')
            if jid in self.jobs:
                if self.jobs[jid]['request_hash']!=sha:raise ValueError('Job id conflict')
                self.jobs[jid]['heartbeat']=time.time();self.save(jid)
                return self.snapshot(jid)
            if len(self.processes)>=self.slots:raise BlockingIOError('Compute full')
            if shutil.disk_usage(self.root).free<self.min_free:raise BlockingIOError('Compute disk reserve')
            folder=self.root/jid;folder.mkdir(exist_ok=False)
            write_json(folder/'request.json',request)
            row={'status':'running','request_hash':sha,'release':self.release,
                 'started':time.time(),'heartbeat':time.time(),'protocol':PROTOCOL}
            self.jobs[jid]=row;self.save(jid)
            env=dict(os.environ);env.pop('EB_COMPUTE_URL',None);env.pop('EB_COMPUTE_TOKEN_FILE',None)
            try:
                with (folder/'native_worker.log').open('w') as log:
                    process=subprocess.Popen(self.command(folder),cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
            except Exception:
                row.update(status='failed',error_type='ComputeStartFailed');self.save(jid);raise
            self.processes[jid]=process
            threading.Thread(target=self.monitor,args=(jid,process),daemon=True).start()
            return self.snapshot(jid)

    def monitor(self,jid,process):
        folder=self.root/jid
        try:
            while process.poll() is None:
                with self.lock:
                    row=self.jobs[jid];now=time.time()
                    if row['status'] in TERMINAL:return
                    reason='cancelled' if self.stopping or row['status']=='cancelled' else 'expired' if now-row['heartbeat']>self.lease or now-row['started']>self.timeout else None
                    if reason:
                        kill(process);row.update(status=reason,error_type='ComputeLeaseOrDeadline');self.save(jid)
                        return
                time.sleep(.2)
            with self.lock:
                row=self.jobs[jid]
                if row['status'] in TERMINAL:return
                row['status']='packaging';self.save(jid)
            status='complete' if process.returncode==0 and (folder/'outcome.json').is_file() else 'failed'
            archive_sha=archive_job(folder)
            with self.lock:
                if row['status'] in TERMINAL:return
                row.update(status=status,archive_sha256=archive_sha,finished=time.time());self.save(jid)
        except Exception as exc:
            with self.lock:
                if self.jobs[jid]['status'] not in TERMINAL:
                    self.jobs[jid].update(status='failed',error_type=type(exc).__name__);self.save(jid)
        finally:
            with self.lock:self.processes.pop(jid,None)

    def snapshot(self,jid,heartbeat=False):
        with self.lock:
            row=self.jobs[jid]
            if heartbeat:row['heartbeat']=time.time()
            result=dict(row)
            p=self.root/jid/'progress.json'
            if p.exists():result['progress']=json.loads(p.read_text())
            return result

    def cancel(self,jid):
        with self.lock:
            row=self.jobs[jid]
            if row['status'] not in TERMINAL:
                row['status']='cancelled';self.save(jid)
                if jid in self.processes:kill(self.processes[jid])

    def close(self):
        with self.lock:
            self.stopping=True
            for jid,process in list(self.processes.items()):
                kill(process)
                if self.jobs[jid]['status'] not in TERMINAL:
                    self.jobs[jid]['status']='interrupted';self.save(jid)

class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def setup(self):super().setup();self.connection.settimeout(15)
    def respond(self,status,value):
        body=json.dumps(value,allow_nan=False).encode()
        self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
    def dispatch(self):
        expected='Bearer '+self.server.token
        if not hmac.compare_digest(self.headers.get('Authorization',''),expected):return self.respond(401,{'error':'unauthorized'})
        store=self.server.store
        try:
            if self.path=='/health' and self.command=='GET':
                return self.respond(200,{'protocol':PROTOCOL,'release':store.release,'active':len(store.processes),'slots':store.slots,'ep_slots':int(os.environ.get('EB_EP_SLOTS','2')),'api_slots':int(os.environ.get('EB_API_SLOTS','2')),'timeout':store.timeout})
            match=re.fullmatch(r'/jobs/([a-f0-9]{64})(/archive)?',self.path)
            if not match:return self.respond(404,{'error':'not_found'})
            jid,archive=match.groups()
            if self.command=='POST' and not archive:
                size=int(self.headers.get('Content-Length','0'))
                if not 0<size<=MAX_REQUEST:raise ValueError('Request size')
                return self.respond(200,store.submit(jid,json.loads(self.rfile.read(size))))
            if self.command=='DELETE' and not archive:
                store.cancel(jid);return self.respond(200,store.snapshot(jid))
            if self.command=='GET':
                row=store.snapshot(jid,heartbeat=True)
                if not archive:return self.respond(200,row)
                if row['status'] not in ('complete','failed') or not row.get('archive_sha256'):
                    return self.respond(409,{'error':'not_ready'})
                path=store.root/jid/'result.zip'
                self.send_response(200);self.send_header('Content-Length',str(path.stat().st_size));self.end_headers()
                with path.open('rb') as f:shutil.copyfileobj(f,self.wfile)
                return
            self.respond(405,{'error':'method'})
        except KeyError:self.respond(404,{'error':'unknown_job'})
        except BlockingIOError:self.respond(429,{'error':'capacity'})
        except (ValueError,TypeError):self.respond(400,{'error':'invalid_request_or_release'})
        except (BrokenPipeError,ConnectionResetError):pass
        except Exception:self.respond(500,{'error':'compute_error'})
    do_GET=dispatch;do_POST=dispatch;do_DELETE=dispatch

class ComputeHTTPServer(ThreadingHTTPServer):
    daemon_threads=True
    request_queue_size=128

def main():
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--token-file',type=Path,required=True)
    p.add_argument('--port',type=int,default=18768);p.add_argument('--slots',type=int,choices=range(1,33),default=4);p.add_argument('--timeout',type=int,default=600)
    a=p.parse_args();os.umask(0o077)
    token=a.token_file.read_text().strip()
    if len(token)<32:raise ValueError('Weak compute token')
    server=ComputeHTTPServer(('127.0.0.1',a.port),Handler)
    server.token=token;server.store=ComputeStore(a.root,slots=a.slots,timeout=a.timeout)
    def stop(*args):threading.Thread(target=server.shutdown,daemon=True).start()
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    try:server.serve_forever()
    finally:server.store.close();server.server_close()

if __name__=='__main__':main()
