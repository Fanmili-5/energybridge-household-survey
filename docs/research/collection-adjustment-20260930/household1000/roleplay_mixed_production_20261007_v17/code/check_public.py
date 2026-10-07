import concurrent.futures,json,re,hashlib
from pathlib import Path
from urllib.request import Request,ProxyHandler,build_opener
origin='https://47.85.194.154';release=Path('/opt/energybridge-household50/releases/34d2fdd32016f701');index=json.loads((release/'INDEX50.json').read_text())['households']
def one(row):
 opener=build_opener(ProxyHandler({}))
 with opener.open(origin+row['route']+'/',timeout=15) as response:page=response.read().decode();assert response.status==200
 cases=json.loads(re.search(r'id="joint-cases-data"[^>]*>(.*?)</script>',page,re.S)[1]);hashes=json.loads(re.search(r'id="source-hashes-data"[^>]*>(.*?)</script>',page,re.S)[1]);assert len(cases)==10 and hashes==row['case_hashes']
 assert all(c['identity']['role_id']==row['household_id'] for c in cases)
 return {'household_id':row['household_id'],'cases':10,'HTTP':200,'source_bindings_match':True}
with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:rows=list(pool.map(one,index))
for route in ['/','/joint-b','/household50/api/health']:
 with build_opener(ProxyHandler({})).open(origin+route,timeout=15) as r:assert r.status==200
report={'status':'pass','public_origin':origin,'households':len(rows),'actual_bound_pairs':sum(r['cases'] for r in rows),'original_root_and_joint_b_HTTP':200,'records':rows,'human_collection_release':False,'training_release':False,'manifest_sha256':hashlib.sha256((release/'DEPLOY_MANIFEST.json').read_bytes()).hexdigest()}
p=Path('/var/backups/energybridge-household50-test/34d2fdd32016f701/PUBLIC_HTTP_REVIEW.json');p.write_text(json.dumps(report,indent=2)+'\n');print({k:v for k,v in report.items() if k!='records'})
