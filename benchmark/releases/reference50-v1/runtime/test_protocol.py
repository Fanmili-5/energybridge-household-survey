"""Offline, real HTTP/SQLite regression; all writes stay in temporary fixture DBs."""
import argparse
import copy
import http.client
import json
import tarfile
import tempfile
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from admin import backup,status
from identity import now
from ledger import CollectionStore,NOTICE_VERSION
from make_fixture import make
from release import Release,PREFIX,UI_VERSION
from server import Server

def run(release_path=None):
    with tempfile.TemporaryDirectory(prefix='reference50-protocol-')as temp:
        temp=Path(temp);release=Release(release_path or make(temp));root=temp/'private'
        server=Server(release,root,fixtures=True);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        bad_count=0
        def request(method,path,data=None,headers=None):
            c=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=20)
            c.request(method,PREFIX+path,None if data is None else json.dumps(data,ensure_ascii=False).encode(),headers or{})
            r=c.getresponse();raw=r.read();h=dict(r.getheaders());c.close()
            return r.status,h,json.loads(raw)if h.get('Content-Type','').startswith('application/json')else raw
        def session():
            code,h,state=request('GET','/api/state');assert code==200
            return {'Cookie':h['Set-Cookie'].split(';')[0],'Origin':server.origin,'X-EB-CSRF':state['csrf'],'Content-Type':'application/json'}
        def start(h):
            code,_,value=request('POST','/api/start',{},h);assert code==200,value;return value
        def bad(path,data,h,expected=400):
            nonlocal bad_count
            code,_,value=request('POST',path,data,h);assert code==expected,(code,value);bad_count+=1
        consent={'accept':True,'understood_assigned_role':True,'notice_version':NOTICE_VERSION}
        try:
            h=session();identity=start(h)
            assert start(h)['participant_id']==identity['participant_id']
            initial=request('GET','/api/state',headers=h)[2];assert initial['answers']==initial['drafts']==initial['views']==[]
            assert request('POST','/api/consent',consent,h)[0]==200
            idx=request('GET','/index.json',headers=h)[2];assert len(idx['cases'])==10
            row=idx['cases'][0];model=release.models[row['case_id']]
            shown={'fields':{k:model[k]for k in ['family','request','changes','impacts']},'schedule_seen':True,'schedule_text':model['schedule'],'presented_at':now()}
            binding={'participant_id':identity['participant_id'],'release_sha256':release.signature,'ui_revision':UI_VERSION,'case_id':row['case_id'],'case_sha256':row['sha256']}
            assert request('POST','/api/view',{**binding,'presentation':shown},h)[0]==200
            partial={k:None for k in ['decision','score','comfort_score','energy_score','vpp_score','reason']};partial['score']=2.3
            draft={**binding,'expected_version':0,'expected_answer_revision':0,'response':partial,'presentation':shown}
            assert request('POST','/api/draft',draft,h)[0]==200
            before=request('GET','/api/state',headers=h)[2]
            # Restart before submission: partial drafts and viewed information must both survive.
            server.shutdown();server.server_close();thread.join()
            server=Server(release,root,fixtures=True);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            h2=session();assert request('POST','/api/recover',{'credential':identity['recovery_code']},h2)[0]==200
            recovered=request('GET','/api/state',headers=h2)[2]
            assert recovered['participant_id']==identity['participant_id']and recovered['drafts']==before['drafts']and recovered['views']==before['views']
            assert recovered['answers']==[] and recovered['drafts'][0]['response']['score']==2.3
            assert start(h2)['participant_id']==identity['participant_id']
            values={'decision':'reject','score':1.2,'comfort_score':2.3,'energy_score':3.4,'vpp_score':4.5,'reason':'虚构隔离协议测试，不是真人答案。'}
            closed=copy.deepcopy(shown);closed.update(schedule_seen=False,schedule_text=None)
            payload={**binding,'expected_answer_revision':0,'expected_draft_version':1,'request_id':str(uuid.uuid4()),'response':values,'presentation':closed}
            for field in values:
                broken=copy.deepcopy(payload);broken['response'][field]=None;bad('/api/answers',broken,h2)
            for field in ['participant_id','release_sha256','ui_revision','case_sha256']:
                broken=copy.deepcopy(payload);broken[field]='wrong';bad('/api/answers',broken,h2,409)
            for value in [False,0,5.1,2.33]:
                broken=copy.deepcopy(payload);broken['response']['score']=value;bad('/api/answers',broken,h2)
            bad('/api/answers',payload,dict(h2,Origin='https://invalid.example'),403)
            other=next(r for r in release.records.values()if r['household_id']!=identity['household_id'])
            assert request('GET','/'+other['path'],headers=h2)[0]==403
            broken=copy.deepcopy(payload);broken.update(case_id=other['case_id'],case_sha256=other['sha256']);bad('/api/answers',broken,h2,403)
            broken=copy.deepcopy(payload);broken['objective_results']={'target_met':True};bad('/api/answers',broken,h2)
            code,_,saved=request('POST','/api/answers',payload,h2);assert code==201 and saved['presentation']['schedule_seen']
            assert request('POST','/api/answers',payload,h2)[2]['receipt_id']==saved['receipt_id']
            review={'actor_id':identity['participant_id'],'case_id':row['case_id'],'answer_revision':1,'status':'valid','rule_version':'invented_fixture_rule','reviewer':'fixture_operator','reason':'Only testing revision binding.'}
            assert server.store.review(review)['status']=='valid'
            assert status(server.store)['reviewed_valid_actor_cases']==1
            revised=copy.deepcopy(payload);revised.update(request_id=str(uuid.uuid4()),expected_answer_revision=1,expected_draft_version=2);revised['response']['vpp_score']=1
            assert request('POST','/api/answers',revised,h2)[0]==201
            assert status(server.store)['reviewed_valid_actor_cases']==0
            try:server.store.review(review);raise AssertionError('stale review accepted')
            except ValueError:pass
            with server.store.connect()as db:
                records=[json.loads(r[0])for r in db.execute('select record_json from responses_v69 order by rowid')]
                assert records[0]['objective_results']==records[1]['objective_results']
                assert all(r['human_label_count']==0 and r['input']['expanded_schedule']==model['schedule']for r in records)
            for r in idx['cases'][1:]:
                m=release.models[r['case_id']]
                present={'fields':{k:m[k]for k in ['family','request','changes','impacts']},'schedule_seen':False,'schedule_text':None,'presented_at':now()}
                item={**payload,'case_id':r['case_id'],'case_sha256':r['sha256'],'request_id':str(uuid.uuid4()),'expected_draft_version':0,'presentation':present}
                assert request('POST','/api/answers',item,h2)[0]==201
            assert request('GET','/api/state',headers=h2)[2]['completed_count']==10
            # Simultaneous starts must cover the remaining households and have no 12-position cap.
            sessions=[session()for _ in range(len(release.households)-1)]
            with ThreadPoolExecutor(max_workers=6)as pool:started=list(pool.map(start,sessions))
            assert len({s['household_id']for s in started})==len(release.households)-1
            assert identity['household_id']not in {s['household_id']for s in started}
            assert start(session())['household_id']!=identity['household_id']
            # Idle leases expire only for assignment; no answers or identity are removed.
            with server.store.connect()as db:db.execute('update assignment_leases set active_until=0')
            assert start(session())['household_id']!=identity['household_id']
            final_state=request('GET','/api/state',headers=h2)[2]
            backup_result=backup(root,temp/'backup');assert backup_result['sqlite_integrity']=='ok'
            restored=temp/'restored';restored.mkdir()
            with tarfile.open(temp/'backup/latest.tar.gz')as tar:
                for name in ['formal_responses.sqlite3','credential_pepper']:(restored/name).write_bytes(tar.extractfile(name).read())
            restored_store=CollectionStore(restored,release,fixtures=True)
            restored_session,_=restored_store.session(h2['Cookie'].split('=',1)[1]);assert restored_store.state(restored_session)=={k:v for k,v in final_state.items()if k!='csrf'}
            assert restored_store.export()==[]
            assert request('POST','/api/withdraw',{},h2)[0]==200
            assert status(server.store)['submitted_latest_actor_cases']==0
            bad('/api/recover',{'credential':identity['recovery_code']},session(),403)
            report={'passed':True,'source_households':len(release.households),'source_cases':len(release.records),'questions_per_participant':10,
                    'open_entry_no_invitation_or_twelve_slot_cap':True,'concurrent_household_assignment':True,'complete_case_retained':True,
                    'idle_assignment_does_not_block_replenishment':True,'partial_draft_view_cross_session_restart_backup':True,
                    'version_identity_and_case_guards':True,'mandatory_fields':True,'quality_review_revision_bound':True,
                    'objective_VPP_separate':True,'append_only_revisions_and_idempotency':True,'withdrawal_excluded':True,
                    'negative_requests_rejected':bad_count,'human_labels_created':0,'production_records_written':0}
            print(json.dumps(report));return report
        finally:server.shutdown();server.server_close();thread.join()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--release',type=Path);a=p.parse_args();run(a.release)
