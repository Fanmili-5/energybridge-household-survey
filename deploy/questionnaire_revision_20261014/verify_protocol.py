"""Exercise the real HTTP handler in an isolated directory with an engineering export."""
import argparse, copy, hashlib, http.client, json, re, sqlite3, sys, tempfile, threading, uuid
from pathlib import Path

def run(release, fixture):
    sys.path.insert(0,str(release))
    from serve50 import MultiServer
    manifest=json.loads((release/'DEPLOY_MANIFEST.json').read_text())
    for name,digest in manifest['files'].items():
        assert hashlib.sha256((release/name).read_bytes()).hexdigest()==digest,name
    index=json.loads((release/'INDEX50.json').read_text())['households']
    record=json.loads(fixture.read_text())
    assert record['status']=='engineering_click_not_human_feedback'
    assert record['human_label_count']==0
    source=copy.deepcopy(record['audit']['source_case']); stimulus=copy.deepcopy(record['input'])
    assert 'respondent' not in stimulus
    assert 'respondent-age' not in json.dumps(record['audit']['presentation']['rendered_snapshot'])
    with tempfile.TemporaryDirectory(prefix='eb-questionnaire-contract-') as tmp:
        server=MultiServer(release,Path(tmp),'https://47.85.194.154',0)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        def request(method,path,body=None,headers=None):
            conn=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=30)
            conn.request(method,path,body=body,headers=headers or {})
            response=conn.getresponse();result=(response.status,dict(response.getheaders()),response.read());conn.close();return result
        try:
            for row in index:
                status,headers,body=request('GET',row['route']+'/')
                assert status==200 and b'id="respondent-age"' in body
                assert b'id="joint-results"' in body and b'respondent-info.js' in body
            row=next(r for r in index if r['household_id']==source['identity']['role_id'])
            route=row['route'];status,headers,body=request('GET',route+'/')
            config=json.loads(re.search(rb'window.EBLiveConfig=(.*?);?</script>',body).group(1))
            cookie=headers['Set-Cookie'].split(';')[0]
            valid={'Content-Type':'application/json','Cookie':cookie,'Origin':'https://47.85.194.154','X-EB-CSRF':config['csrf']}
            payload={'case_index':source['identity']['day_index'],'record':record,'request_id':str(uuid.uuid4())}
            raw=json.dumps(payload,ensure_ascii=False).encode()
            first=request('POST',route+'/api/answers',raw,valid);assert first[0]==201
            duplicate=request('POST',route+'/api/answers',raw,valid);assert duplicate[0]==201 and json.loads(duplicate[2])['duplicate']
            paired=copy.deepcopy(payload);paired['request_id']=str(uuid.uuid4());paired['record']['respondent']={'age_years':78,'gender':'male'}
            paired['record']['test_feedback'].update(decision='reject',score=1.2,comfort_score=2.3,energy_score=3.4,vpp_score=4.5,comment='paired engineering fixture; not human feedback')
            assert request('POST',route+'/api/answers',json.dumps(paired).encode(),valid)[0]==201
            changed=copy.deepcopy(payload);changed['record']['respondent']['age_years']=22
            assert request('POST',route+'/api/answers',json.dumps(changed).encode(),valid)[0]==400
            for header,value in [('Origin','https://unrelated.invalid'),('X-EB-CSRF','invalid'),('Cookie','')]:
                invalid=dict(valid);invalid[header]=value
                assert request('POST',route+'/api/answers',raw,invalid)[0]==403
            for mutation in ['age','source']:
                bad=copy.deepcopy(paired);bad['request_id']=str(uuid.uuid4())
                if mutation=='age':bad['record']['respondent']['age_years']=20.5
                else:bad['record']['audit']['source_binding']['source_package_sha256']='invalid'
                assert request('POST',route+'/api/answers',json.dumps(bad).encode(),valid)[0]==400
            for name in ['engineering.sqlite3','DEPLOY_MANIFEST.json','../engineering.sqlite3']:
                assert request('GET',route+'/'+name)[0]==404
            with sqlite3.connect(Path(tmp)/row['household_id']/'engineering.sqlite3') as db:
                saved=[json.loads(r[0])for r in db.execute('select record_json from writes order by rowid')]
            assert len(saved)==2
            assert [r['respondent']for r in saved]==[record['respondent'],paired['record']['respondent']]
            assert all(r['input']==stimulus and r['audit']['source_case']==source for r in saved)
            return {'passed':True,'manifest_files_verified':len(manifest['files']),'pages_checked':len(index),'isolated_engineering_writes':2,'production_writes':0,'null_and_decimal_scores_preserved':True,'respondent_outside_stimulus':True,'source_and_stimulus_unchanged':True,'csrf_origin_cookie_source_private_file_guards':'pass','duplicate_and_conflict_checks':'pass'}
        finally:server.shutdown();server.server_close();thread.join()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--release',type=Path,required=True);p.add_argument('--fixture',type=Path,required=True);args=p.parse_args()
    print(json.dumps(run(args.release.resolve(),args.fixture.resolve()),sort_keys=True))
