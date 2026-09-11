"""50-session HTTP/SQLite/restart/EP/feedback test. No real model calls."""
import argparse,concurrent.futures,http.client,json,secrets,sqlite3,sys,threading,time,os,fcntl
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from server import make_server
from durable_queue import DurableQueue
from common import digest,write_json
from verify_paired_physics import answers
from paired_contract import CONTEXT,QUESTIONS,QUESTIONNAIRE_VERSION

def main(root,count,workers):
    root.mkdir(parents=True,exist_ok=False)
    server=make_server(0,root,workers=workers,disable_planning=True)
    server.planning_disabled=False # Only this private test server accepts submissions.
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    host,port=server.server_address
    owners=[secrets.token_hex(32) for _ in range(count)]
    payloads=[{'request_id':secrets.token_hex(16),'answers':answers(),'scenario_id':CONTEXT['id'],'scenario_understood':True,'questionnaire_version':QUESTIONNAIRE_VERSION,'questionnaire_hash':digest(QUESTIONS),'ui_version':'engineering_backend_load_test'} for _ in owners]
    # Submissions commit to SQLite while dispatch is paused.
    server.store.pool.shutdown()
    class Hold:
        def submit(self,*args):pass
        def shutdown(self,**kwargs):pass
    server.store.pool=Hold()
    def call(owner,path,body=None):
        conn=http.client.HTTPConnection(host,port,timeout=40)
        headers={'Cookie':'pilot_session='+owner,'Origin':f'http://{host}:{port}','Content-Type':'application/json'}
        started=time.perf_counter()
        conn.request('POST' if body is not None else 'GET',path,None if body is None else json.dumps(body),headers)
        resp=conn.getresponse();code=resp.status;data=json.loads(resp.read());conn.close()
        return code,data,time.perf_counter()-started
    report={'ep_slots':os.environ.get('EB_EP_SLOTS'), 'api_slots':os.environ.get('EB_API_SLOTS'), 'count':count,'workers':workers,'api_calls':0,'data_origin':'synthetic_engineering_test'}
    try:
        barrier=threading.Barrier(count)
        def submit(i):barrier.wait();return call(owners[i],'/api/paired',payloads[i])
        with concurrent.futures.ThreadPoolExecutor(count) as pool:receipts=list(pool.map(submit,range(count)))
        assert all(r[0]==202 for r in receipts),receipts
        ids=[r[1]['id'] for r in receipts];assert len(set(ids))==count
        elapsed=sorted(r[2] for r in receipts)
        report['submit_seconds']={'p50':elapsed[len(elapsed)//2],'p95':elapsed[min(len(elapsed)-1,int(len(elapsed)*.95))],'max':max(elapsed)}
        assert len(server.store.db.jobs())==count
        with concurrent.futures.ThreadPoolExecutor(count) as pool:
            duplicates=list(pool.map(lambda i:call(owners[i],'/api/paired',payloads[i]),range(count)))
        assert all(r[1]['id']==ids[i] for i,r in enumerate(duplicates))
        assert call(owners[0],'/api/jobs/'+ids[-1])[0]==404
        assert call(owners[0],'/api/paired',{**payloads[0],'ui_version':'changed'})[0]==400
        # Persisted running request is recovered as queued; this models an unclean
        # stop after claiming a job but before a usable result was committed.
        job=server.store.jobs[ids[0]];job.update(status='running',attempts=1);server.store.persist(job)
        server.shutdown();server.server_close();server.store.db.close()
        server=make_server(port,root,workers=workers,disable_planning=True)
        server.planning_disabled=False
        assert all(j['status']=='queued' for j in server.store.jobs.values())
        server.store.worker_command=lambda folder:[sys.executable,str(ROOT/'deploy/ep_fixture_worker.py'),str(folder)]
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        started=time.perf_counter();server.store.pool.resume();peak_active=0;scored=set();status_bytes=0
        ep_peak=[0];monitor_stop=threading.Event()
        def monitor():
            while not monitor_stop.wait(.02):
                busy=0
                for path in Path(os.environ.get('EB_RESOURCE_DIR',str(root/'unused'))).glob('ep_*.lock'):
                    with path.open('a') as f:
                        try:fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
                        except BlockingIOError:busy+=1
                        else:fcntl.flock(f,fcntl.LOCK_UN)
                ep_peak[0]=max(ep_peak[0],busy)
        monitor_thread=threading.Thread(target=monitor,daemon=True);monitor_thread.start()
        while time.perf_counter()-started<300:
            with server.store.lock:
                peak_active=max(peak_active,len(server.store.processes))
                states={j['id']:j['status'] for j in server.store.jobs.values()}
            assert not any(s in {'failed','timeout','interrupted'} for s in states.values()),states
            for i,jid in enumerate(ids):
                if states[jid]=='complete' and jid not in scored:
                    code,j,_=call(owners[i],'/api/jobs/'+jid);assert code==200
                    r=j['result'];assert r['timings']['llm']['call_count']==0
                    feedback={'choice':'reject','score':3.75,'comfort_score':2.5,'energy_score':4.1,'vpp_score':2.25,'comment':'并发工程测试评分，不是真人回答。',**{k:r[k] for k in ('display_hash','original_plan_hash','proposal_plan_hash')}}
                    code,receipt,_=call(owners[i],'/api/jobs/'+jid+'/decision',feedback);assert code==200 and receipt['saved']
                    assert call(owners[i],'/api/jobs/'+jid+'/decision',feedback)[1]['duplicate']
                    assert call(owners[i],'/api/jobs/'+jid+'/decision',{**feedback,'score':1})[0]==400
                    candidate=server.store.db.document(jid,'sft_candidate.json')
                    assert candidate['target_source']=='engineering_test'
                    assert json.loads(candidate['messages'][-1]['content'])['score']==3.75
                    scored.add(jid)
            if len(scored)==count:break
            # All participants poll in parallel, including while others save scores.
            with concurrent.futures.ThreadPoolExecutor(count) as pool:
                statuses=list(pool.map(lambda i:call(owners[i],'/api/jobs/'+ids[i]+'/status'),range(count)))
            assert all(s[0]==200 for s in statuses)
            status_bytes=max(status_bytes,max(len(json.dumps(s[1]).encode()) for s in statuses))
            print(json.dumps({'done':len(scored),'active_peak':peak_active,'seconds':round(time.perf_counter()-started,1)}),flush=True)
            time.sleep(1)
        assert len(scored)==count and peak_active<=workers
        monitor_stop.set();monitor_thread.join()
        if os.environ.get('EB_RESOURCE_DIR'):assert 0<ep_peak[0]<=int(os.environ['EB_EP_SLOTS'])
        report['observed_ep_slots_peak']=ep_peak[0]
        report.update(status='passed',completed=len(scored),compute_and_feedback_seconds=time.perf_counter()-started,peak_active=peak_active,max_status_bytes=status_bytes,restart_recovered=count,duplicate_submissions_deduplicated=count,decimal_feedback_saved=count,cross_session_access_denied=True)
        backup=root/'verified-backup.sqlite3';server.store.db.backup(backup)
        with sqlite3.connect(backup) as db:
            assert db.execute('SELECT count(*) FROM jobs').fetchone()[0]==count
            assert db.execute("SELECT count(*) FROM documents WHERE name='decision.json'").fetchone()[0]==count
        report['backup_verified']=True
        write_json(root/'load_report.json',report);print(json.dumps(report),flush=True)
    finally:
        if 'monitor_stop' in locals():monitor_stop.set()
        server.shutdown();server.store.stopping=True;server.store.pool.stopped=True
        from server import stop_process
        for p in list(server.store.processes.values()):stop_process(p)
        server.store.pool.shutdown();server.server_close();server.store.db.close()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);p.add_argument('--count',type=int,default=50);p.add_argument('--workers',type=int,default=2);a=p.parse_args();main(a.out,a.count,a.workers)
