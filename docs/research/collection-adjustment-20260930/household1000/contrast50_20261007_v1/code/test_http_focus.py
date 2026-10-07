"""Actual server requests for all50 households,500 engineering answers,negative controls."""
import hashlib,json,re,sys,tempfile,threading,uuid
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request,ProxyHandler,build_opener
ROOT=Path(__file__).resolve().parents[1];RELEASE=ROOT/'frontend_release';sys.path.insert(0,str(RELEASE))
from serve50 import MultiServer
server=MultiServer(RELEASE,ROOT/'server_verification_data_focus','https://47.85.194.154',0);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();base=f'http://127.0.0.1:{server.server_port}';client=build_opener(ProxyHandler({}))
def req(path,payload=None,cookie=None,csrf=None,origin='https://47.85.194.154'):
 headers={'Origin':origin,'Content-Type':'application/json'}
 if cookie:headers['Cookie']=cookie
 if csrf:headers['X-EB-CSRF']=csrf
 r=Request(base+path,data=None if payload is None else json.dumps(payload,ensure_ascii=False).encode(),headers=headers)
 try:
  with client.open(r) as x:raw=x.read();return x.status,x.headers, json.loads(raw) if x.headers.get('Content-Type','').startswith('application/json') else raw.decode()
 except HTTPError as e:return e.code,e.headers,json.loads(e.read())
rows=[];checks={}
try:
 assert req('/household50/api/health')[2]['households']==50
 for row in server.index:
  route=row['route'];code,headers,page=req(route+'/');assert code==200
  cookie=headers['Set-Cookie'].split(';')[0];config=json.loads(re.search(r'window.EBLiveConfig=(.*?);?</script>',page)[1]);csrf=config['csrf'];records=json.loads((ROOT/'frontend_test_records_focus'/row['household_id']/'records.json').read_text())
  for i,record in enumerate(records):
   payload={'case_index':i,'record':record,'request_id':str(uuid.uuid4())}
   status,_,saved=req(route+'/api/answers',payload,cookie,csrf);assert status==201 and saved['saved']
   if i==0:
    assert req(route+'/api/answers',payload,cookie,csrf)[2]['duplicate']
    assert req(route+'/api/answers',payload,cookie,csrf,origin='https://invalid.example')[0]==403
    assert req(route+'/api/answers',payload,cookie,None)[0]==403
    invalid={**payload,'case_index':1,'request_id':str(uuid.uuid4())};assert req(route+'/api/answers',invalid,cookie,csrf)[0]==400
  assert req(route+'/BUNDLE.json')[0]==404 and req(route+'/engineering.sqlite3')[0]==404
  rows.append({'household_id':row['household_id'],'saved_engineering_cases':len(records)})
 checks={'idempotent_retry':True,'wrong_origin_rejected':True,'missing_CSRF_rejected':True,'wrong_case_binding_rejected':True,'raw_bundle_and_database_denied':True}
 report={'status':'pass','server_host':'school Linux','households_checked':len(rows),'saved_engineering_answers':sum(x['saved_engineering_cases'] for x in rows),'checks':checks,'records':rows,'human_answers':0,'production_DB_touched':False}
 (ROOT/'HTTP_REVIEW.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');print(json.dumps({k:v for k,v in report.items() if k!='records'},ensure_ascii=False))
finally:server.shutdown();server.server_close();thread.join()
