"""Activate accepted50 only;pause950,preserve every database row and credential."""
import hashlib,http.client,json,sqlite3,ssl,subprocess,sys
from pathlib import Path
BASE=Path('/opt/energybridge-role-collection');DATA=Path('/var/lib/energybridge-role-collection')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def snapshot():
    with sqlite3.connect('file:'+str(DATA/'collection_v1/formal_responses.sqlite3')+'?mode=ro',uri=True)as db:
        tables=[r[0]for r in db.execute('select name from sqlite_master where type="table" order by name')]
        rows={t:sorted(db.execute('select * from '+t).fetchall(),key=repr)for t in tables}
    return {'hashes':{t:hashlib.sha256(repr(r).encode()).hexdigest()for t,r in rows.items()},'counts':{t:len(r)for t,r in rows.items()},
        'pepper':sha(DATA/'collection_v1/credential_pepper'),'invites':{b:sha(DATA/'operator_invites'/(b+'.csv'))for b in('formal50','formal950')}}
def run(*args):return subprocess.run(args,check=True,capture_output=True,text=True).stdout
def main():
    observed=json.loads(Path('/tmp/SCHOOL_50_ACCEPTANCE_OBSERVED.json').read_text());assert observed['completed_before_school_outage']and observed['baseline_pairs_checked']==500
    m=json.loads(Path('/tmp/RUNTIME_MANIFEST.json').read_text());runtime=BASE/'runtime'/m['signature'][:16]
    for n,h in m['files'].items():assert sha(runtime/n)==h
    release=BASE/'releases'/observed['release_signature'][:16]
    code='''import sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from server import Release
r=Release(Path(sys.argv[2]));assert r.signature==sys.argv[3]
for n in r.manifest['files']:r.file(n)
'''
    run('runuser','-u','ebjoint','--',sys.executable,'-B','-c',code,str(runtime),str(release),observed['release_signature'])
    before=snapshot();Path('/tmp/V30_50_PRE_ACTIVATION_PRIVATE.json').write_text(json.dumps(before,indent=2)+'\n')
    result=json.loads(run(sys.executable,'/tmp/activate.py','--runtime',str(runtime),'--release50',str(release)).splitlines()[-1])
    snippet=Path('/etc/nginx/snippets/energybridge-household50-test.conf');current=snippet.read_text()
    paused='''
location ^~ /household950 {
 auth_basic off;
 default_type text/plain;
 charset utf-8;
 add_header Cache-Control "no-store" always;
 return 503 "950户新版验收已暂停，暂未开放采集。50户正式入口：/household50\n";
}
'''
    try:snippet.write_text(current+paused);run('nginx','-t');run('systemctl','reload','nginx')
    except BaseException:snippet.write_text(current);run('nginx','-t');run('systemctl','reload','nginx');raise
    after=snapshot();assert before==after,'preserve prior database and credentials'
    conn=http.client.HTTPSConnection('127.0.0.1',443,context=ssl._create_unverified_context(),timeout=10)
    conn.request('GET','/household950',headers={'Host':'47.85.194.154'});response=conn.getresponse();body=response.read().decode();assert response.status==503 and'暂停'in body;conn.close()
    assert result['health']['formal50']['release_signature']==observed['release_signature']
    public=http.client.HTTPSConnection('47.85.194.154',443,context=ssl._create_unverified_context(),timeout=10)
    public.request('GET','/household50/api/health');response=public.getresponse();health=json.loads(response.read());assert response.status==200 and health['release_signature']==observed['release_signature'];public.close()
    result.update(scope='formal50_only_950_paused',formal950_public_paused=True,formal950_public_status=503,
        formal950_existing_packages_and_records_preserved=True,prior_database_all_table_contents_unchanged=True,
        private_invitation_files_unchanged=True,credential_pepper_unchanged=True,production_counts=after['counts'],
        active_invitation_count=50,preserved_invitation_count=after['counts']['invitations'],runtime_files_verified=len(m['files']),
        service_user_all50_payload_bytes_verified=True,human_records_created=0,school_observation_sha256=sha(Path('/tmp/SCHOOL_50_ACCEPTANCE_OBSERVED.json')),
        school_original_raw_receipt_download_pending=True,full1000_EP_started=False)
    result['public_HTTPS50_signature_verified']=True
    Path('/tmp/ACTIVATION_RECEIPT50_V30.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps(result,ensure_ascii=False))
if __name__=='__main__':main()
