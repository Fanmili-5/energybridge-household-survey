"""HTTP acceptance with invented actors in an isolated fixture database only."""
import argparse,copy,hashlib,http.client,json,re,sqlite3,tempfile,threading,uuid
from pathlib import Path
from server import Server,Release,COOKIE
from store import UI_VERSION,NOTICE_VERSION

def run(release_path,fixture):
    release=Release(release_path);record=json.loads(fixture.read_text());hid=record['audit']['source_case']['identity']['role_id']
    row=next(r for r in release.rows.values()if r['household_id']==hid);route=row['route'];batch=release.batch;prefix=release.prefix
    for name,digest in release.manifest['files'].items():assert hashlib.sha256((release.root/name).read_bytes()).hexdigest()==digest
    record.update(schema='eb.role_response.v1',questionnaire_ui_version=UI_VERSION,status='participant_submitted_role_response',collection_release=True)
    record['response']=record.pop('test_feedback');record.pop('formal_export_eligible',None)
    with tempfile.TemporaryDirectory(prefix='eb-formal-fixtures-')as tmp:
        server=Server([release],Path(tmp),'https://47.85.194.154',0,fixtures=True);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        token='invented-fixture-invitation-00000001';other='invented-fixture-invitation-00000002';otherrow=next(r for r in release.rows.values()if r['household_id']!=hid)
        server.store.provision([('fixture-one',batch,hid,token),('fixture-two',batch,otherrow['household_id'],other)])
        def request(method,path,data=None,headers=None):
            c=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=20);raw=None if data is None else json.dumps(data,ensure_ascii=False).encode();c.request(method,path,raw,headers or {});r=c.getresponse();result=(r.status,dict(r.getheaders()),r.read());c.close();return result
        def session():
            status,headers,body=request('GET',prefix+'/api/session');assert status==200;state=json.loads(body);return {'Cookie':headers['Set-Cookie'].split(';')[0],'Content-Type':'application/json','Origin':'https://47.85.194.154','X-EB-CSRF':state['csrf']}
        try:
            assert request('GET',route+'/')[0]==302
            h=session();claim=request('POST',prefix+'/api/claim',{'credential':token},h);assert claim[0]==200;identity=json.loads(claim[2]);recovery=identity['recovery_code'];assert recovery
            page=request('GET',route+'/',headers=h);assert page[0]==200 and b'EBFormalConfig' in page[2]
            assert request('GET',otherrow['route']+'/',headers=h)[0]==403
            payload={'case_index':0,'record':record,'request_id':str(uuid.uuid4())}
            assert request('POST',route+'/api/answers',payload,h)[0]==403,'consent must precede saving'
            notice={'accept':True,'understood_assigned_role':True,'notice_version':NOTICE_VERSION}
            assert request('POST',prefix+'/api/consent',notice,h)[0]==200
            wrong=dict(h,Origin='https://unrelated.invalid');assert request('POST',route+'/api/answers',payload,wrong)[0]==403
            wrong=dict(h,**{'X-EB-CSRF':'invalid'});assert request('POST',route+'/api/answers',payload,wrong)[0]==403
            first=request('POST',route+'/api/answers',payload,h)
            assert first[0]==201,first[2].decode();first=json.loads(first[2])
            retry=request('POST',route+'/api/answers',payload,h);assert retry[0]==201 and json.loads(retry[2])['receipt_id']==first['receipt_id']
            altered=copy.deepcopy(payload);altered['record']['respondent']['age_years']=78
            assert request('POST',route+'/api/answers',altered,h)[0]==400
            altered['request_id']=str(uuid.uuid4());altered['record']['response'].update(decision='reject',score=1.2,comfort_score=2.3,energy_score=3.4,vpp_score=4.5,comment='invented engineering fixture; no human answer')
            assert request('POST',route+'/api/answers',altered,h)[0]==201
            for what in ['input_hash','source','age']:
                bad=copy.deepcopy(altered);bad['request_id']=str(uuid.uuid4())
                if what=='input_hash':bad['record']['input']['fields']['home-intro']='tampered'
                elif what=='source':bad['record']['audit']['source_binding']['source_package_sha256']='invalid'
                else:bad['record']['respondent']['age_years']=False
                assert request('POST',route+'/api/answers',bad,h)[0]==400,what
            state=json.loads(request('GET',prefix+'/api/session',headers=h)[2]);assert len(state['answers'])==1 and state['answers'][0]['feedback']['score']==1.2
            h2=session();assert request('POST',prefix+'/api/claim',{'credential':token},h2)[0]==403
            resumed=request('POST',prefix+'/api/claim',{'credential':recovery},h2);assert resumed[0]==200 and json.loads(resumed[2])['participant_id']==identity['participant_id']
            state2=json.loads(request('GET',prefix+'/api/session',headers=h2)[2]);assert state2['answers']==state['answers']
            assert request('GET',route+'/formal_responses.sqlite3',headers=h)[0]==404
            with server.store.connect()as db:
                stored=[json.loads(r[0])for r in db.execute('select record_json from answers order by rowid')]
            assert len(stored)==2 and all(r['human_label_count']==0 and r['label_origin']=='engineering_fixture'for r in stored)
            assert stored[0]['input']==stored[1]['input'] and stored[0]['audit']['source_case']==stored[1]['audit']['source_case']
            assert all(r['audit']['collection_linkage']['participant_id']==identity['participant_id']for r in stored)
            assert server.store.export()==[],'fixtures must not enter formal export'
            withdrawn=request('POST',prefix+'/api/withdraw',{},h2);assert withdrawn[0]==200
            assert request('POST',route+'/api/answers',dict(payload,request_id=str(uuid.uuid4())),h)[0]==403
            assert request('POST',prefix+'/api/claim',{'credential':recovery},session())[0]==403
            assert server.store.export()==[]
            return {'passed':True,'batch':batch,'manifest_files_checked':len(release.manifest['files']),'invitation_assignment_consent_recovery_withdrawal':'pass','source_and_model_input_guards':'pass','metadata_null_decimal_revision_idempotency':'pass','fixtures_excluded_from_formal_export':True,'human_answers_generated':0,'production_records_written':0}
        finally:server.shutdown();server.server_close();thread.join()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--release',type=Path,required=True);p.add_argument('--fixture',type=Path,required=True);a=p.parse_args();print(json.dumps(run(a.release,a.fixture),sort_keys=True))
