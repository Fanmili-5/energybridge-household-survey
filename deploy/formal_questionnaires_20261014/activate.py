"""Cloud-side activation. Preserve engineering data and all formal responses."""
import argparse,hashlib,http.client,json,os,pwd,shutil,sqlite3,subprocess,time
from datetime import datetime,timezone
from pathlib import Path

def run(*args):return subprocess.run(args,check=True,capture_output=True,text=True).stdout.strip()
def main():
    p=argparse.ArgumentParser();p.add_argument('--runtime',type=Path,required=True);p.add_argument('--release50',type=Path,required=True);p.add_argument('--release950',type=Path);a=p.parse_args()
    import sys;sys.path.insert(0,str(a.runtime))
    from server import Release
    r50=Release(a.release50);r950=Release(a.release950)if a.release950 else None
    for r in[r50]+([r950]if r950 else[]):
        for name in r.manifest['files']:r.file(name)
    root=Path('/var/lib/energybridge-role-collection');root.mkdir(mode=0o700,exist_ok=True);account=pwd.getpwnam('ebjoint');os.chown(root,account.pw_uid,account.pw_gid)
    data=root/'collection_v1';data.mkdir(mode=0o700,exist_ok=True);os.chown(data,account.pw_uid,account.pw_gid)
    for r in[r50]+([r950]if r950 else[]):
        private=root/'operator_invites';private.mkdir(mode=0o700,exist_ok=True);os.chown(private,account.pw_uid,account.pw_gid)
        file=private/(r.batch+'.csv')
        if not file.exists():run('runuser','-u','ebjoint','--','python3','-B',str(a.runtime/'admin.py'),'provision','--data-root',str(data),'--release',str(r.root),'--output',str(file))
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ');backup=Path('/var/backups/energybridge-role-collection')/stamp;backup.mkdir(parents=True,mode=0o700)
    db=data/'formal_responses.sqlite3'
    with sqlite3.connect('file:'+str(db)+'?mode=ro',uri=True)as src,sqlite3.connect(backup/'formal_responses.sqlite3')as dst:src.backup(dst)
    shutil.copy2(data/'credential_pepper',backup/'credential_pepper');shutil.copytree(root/'operator_invites',backup/'operator_invites')
    unit=Path('/etc/systemd/system/energybridge-role-collection.service');oldunit=unit.read_text()if unit.exists()else None
    snippet=Path('/etc/nginx/snippets/energybridge-household50-test.conf');oldsnippet=snippet.read_text();(backup/'nginx.before').write_text(oldsnippet)
    if oldunit:(backup/'service.before').write_text(oldunit)
    old_test_enabled=subprocess.run(['systemctl','is-enabled','energybridge-household50-test.service'],capture_output=True,text=True).stdout.strip()=='enabled'
    args=['/usr/bin/python3','-B',str(a.runtime/'server.py'),'--release50',str(r50.root),'--data-root',str(data),'--public-origin','https://47.85.194.154','--port','18775']
    if r950:args.extend(['--release950',str(r950.root)])
    content='''[Unit]
Description=EnergyBridge formal household role questionnaires
After=network.target
[Service]
Type=simple
User=ebjoint
Group=ebjoint
UMask=0077
WorkingDirectory='''+str(a.runtime)+'''
ExecStart='''+' '.join(args)+'''
Environment=PYTHONDONTWRITEBYTECODE=1 PYTHONNOUSERSITE=1
Restart=on-failure
RestartSec=3
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths='''+str(data)+'''
InaccessiblePaths=/var/lib/energybridge-household50 /var/lib/energybridge-joint-b /etc/energybridge
RestrictAddressFamilies=AF_INET AF_UNIX
IPAddressDeny=any
IPAddressAllow=localhost
MemoryMax=512M
TasksMax=32
[Install]
WantedBy=multi-user.target
'''
    locations=''
    for prefix in ['/household50']+(['/household950']if r950 else[]):
        locations+='''location ^~ '''+prefix+''' {
 auth_basic off;
 client_max_body_size 8m;
 limit_req zone=eb_general burst=60 nodelay;
 proxy_pass http://127.0.0.1:18775;
 proxy_set_header Host $host;
 proxy_set_header X-Forwarded-Proto https;
 proxy_set_header X-Real-IP $remote_addr;
 proxy_read_timeout 30s;
 add_header Cache-Control "no-store" always;
 add_header Referrer-Policy "no-referrer" always;
}
'''
    try:
        unit.write_text(content);snippet.write_text(locations);run('nginx','-t')
        run('systemctl','disable','--now','energybridge-household50-test.service');run('systemctl','daemon-reload');run('systemctl','enable','energybridge-role-collection.service');run('systemctl','restart','energybridge-role-collection.service')
        health={}
        for _ in range(30):
            try:
                for r in[r50]+([r950]if r950 else[]):
                    c=http.client.HTTPConnection('127.0.0.1',18775,timeout=10);c.request('GET',r.prefix+'/api/health');res=c.getresponse();value=json.loads(res.read());c.close();assert res.status==200 and value['mode']=='formal_role_collection'and value['human_collection_release']and value['release_signature']==r.signature;health[r.batch]=value
                break
            except (OSError,AssertionError,ValueError):time.sleep(.5)
        assert len(health)==(2 if r950 else 1);run('systemctl','reload','nginx')
    except BaseException:
        snippet.write_text(oldsnippet)
        if oldunit:unit.write_text(oldunit);run('systemctl','daemon-reload');run('systemctl','restart','energybridge-role-collection.service')
        else:
            subprocess.run(['systemctl','stop','energybridge-role-collection.service'],capture_output=True);subprocess.run(['systemctl','disable','energybridge-role-collection.service'],capture_output=True)
            if old_test_enabled:run('systemctl','enable','energybridge-household50-test.service')
            run('systemctl','start','energybridge-household50-test.service')
        run('nginx','-t');run('systemctl','reload','nginx');raise
    backupunit=Path('/etc/systemd/system/energybridge-role-collection-backup.service')
    backupunit.write_text('[Unit]\nDescription=Consistent private role collection recovery backup\n[Service]\nType=oneshot\nUMask=0077\nExecStart=/usr/bin/python3 -B '+str(a.runtime/'backup.py')+'\nMemoryMax=256M\nNice=15\nIOSchedulingClass=idle\n')
    timer=Path('/etc/systemd/system/energybridge-role-collection-backup.timer')
    timer.write_text('[Unit]\nDescription=Back up formal role responses every six hours\n[Timer]\nOnBootSec=15min\nOnUnitActiveSec=6h\nPersistent=true\n[Install]\nWantedBy=timers.target\n')
    run('systemctl','daemon-reload');run('systemctl','enable','--now','energybridge-role-collection-backup.timer');run('systemctl','start','energybridge-role-collection-backup.service')
    result={'schema':'eb.formal_questionnaire_activation.v1','activated_at':datetime.now(timezone.utc).isoformat(),'health':health,'backup':str(backup),'consistent_backup_interval_hours':6,
        'engineering_database_migrated_to_formal':False,'old_engineering_release_and_databases_retained':True,'private_invitation_count':50+(950 if r950 else 0),'automatic_training_release':False}
    (backup/'ACTIVATION_RECEIPT.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps(result,ensure_ascii=False))

if __name__=='__main__':main()
