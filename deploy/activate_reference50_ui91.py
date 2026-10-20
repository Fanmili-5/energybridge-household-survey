"""Activate an authorized sealed UI91 physics release; tar.gz arrives on stdin.

Run as deployment administrator after source checks. Keep all prior services,
release files and ledgers. Credentials are not arguments or archive contents.
"""
import argparse
import json
import os
import pwd
import re
import socket
import sqlite3
import subprocess
import sys
import tarfile
import time
import urllib.request
import urllib.error
from pathlib import Path


def command(*args):
    return subprocess.run(args,check=True,capture_output=True,text=True).stdout


def counts(root):
    with sqlite3.connect('file:'+str(root/'formal_responses.sqlite3')+'?mode=ro',uri=True)as db:
        return {t:db.execute('select count(*)from '+t).fetchone()[0] for t in ('actors','responses_v69','current_drafts','view_history')}


def health(url,signature):
    for _ in range(20):
        try:
            with urllib.request.urlopen(url,timeout=5)as response:value=json.load(response)
            if value['release_sha256']==signature:return value
        except (OSError,ValueError):pass
        time.sleep(.4)
    raise RuntimeError('Collector health/signature mismatch')


def verify_public_body_capacity(origin):
    """Check the proxy accepts the app's bound, without an identity or answer."""
    limit=256*1024
    prefix=b'{"engineering_body_size_probe":"';suffix=b'"}'
    body=prefix+b'x'*(limit-len(prefix)-len(suffix))+suffix
    request=urllib.request.Request(origin+'/household50-current/api/answers',data=body,
        headers={'Content-Type':'application/json','Origin':origin})
    for _ in range(30):
        try:
            with urllib.request.urlopen(request,timeout=15):pass
            raise RuntimeError('Unauthenticated size probe unexpectedly accepted')
        except urllib.error.HTTPError as error:
            if error.code==413:
                error.close()
                time.sleep(.1);continue  # Old Nginx workers may drain during reload.
            try:message=json.loads(error.read()).get('error','')
            finally:error.close()
            if error.code==403 and '会话'in message:
                return {'passed':True,'request_bytes':limit,'unauthenticated_write_rejected':True}
            raise RuntimeError('Size probe did not reach collector session rejection')
    raise RuntimeError('Proxy body limit is below the collector request bound')


def activate(signature,previous,origin,port=18793,service_name='energybridge-current50-ui91-physics',previous_private_port=None):
    assert re.fullmatch('[a-f0-9]{64}',signature) and re.fullmatch('[a-f0-9]{64}',previous)
    assert 18793<=port<=18799 and re.fullmatch(r'energybridge-current50-[a-z0-9-]+',service_name)
    if previous_private_port is None:health(origin+'/household50-current/api/health',previous)
    else:
        assert 18791<=previous_private_port<=18799 and previous_private_port!=port
        health(f'http://127.0.0.1:{previous_private_port}/household50-current/api/health',previous)
        try:urllib.request.urlopen(origin+'/household50-current/',timeout=10)
        except urllib.error.HTTPError as e:assert e.code==503 and '问卷暂未开放' in e.read().decode()
        else:raise RuntimeError('Expected paused public entry before zero-unknown replacement')
    base=Path('/opt/energybridge-current50')/signature[:20];base.mkdir(mode=0o755,exist_ok=True)
    with tarfile.open(fileobj=sys.stdin.buffer,mode='r|gz')as archive:
        for member in archive:
            target=base/member.name
            assert member.isfile() and target.resolve().is_relative_to(base) and member.name.split('/')[0]in ('release','runtime')
            target.parent.mkdir(parents=True,exist_ok=True,mode=0o755);raw=archive.extractfile(member).read()
            if target.exists():assert target.read_bytes()==raw,'Refusing to overwrite different staged bytes'
            else:
                with target.open('xb')as f:f.write(raw)
            target.chmod(0o644)
    sys.path.insert(0,str(base/'runtime'));from release import Release
    release=Release(base/'release');assert release.signature==signature
    assert release.manifest['schema']=='eb.reference_benchmark.release.v2' and release.manifest['new_EP_runs']==1000
    assert release.manifest['presentation_revision']=='eb.questionnaire50.refined.v91.newAB.v1'
    assert len(release.records)==500 and len(release.households)==50
    assert release.manifest.get('formal_collection_ready') is True,'Formal release has not passed zero-unknown readiness'
    assert release.manifest.get('physical_statuses')=={'computed':500},'Formal collection cannot contain unavailable consequences'
    assert release.manifest.get('assignment_policy',{}).get('version')=='system_assigned_stable_participant_optional_rounds.v1','Formal collection requires verified system assignment and multi-round identity'
    for cid,row in release.records.items():
        _,case=release.case(cid,row['household_id'])
        assert case.get('outcome_status')=='computed' and isinstance(case.get('impact'),dict),'Missing case consequences'
    account=pwd.getpwnam('ebjoint');root=Path('/var/lib/energybridge-current50/collection_ui91_physics')/signature[:20]
    snapshots=Path('/var/backups/energybridge-current50')/signature[:20]
    for p in (root,snapshots):
        p.mkdir(parents=True,exist_ok=True,mode=0o700);p.chmod(0o700);os.chown(p,account.pw_uid,account.pw_gid)
    old=[]
    for parent in ('collection_v69','collection_v4_proposal','collection_ui91_physics'):
        for p in sorted((Path('/var/lib/energybridge-current50')/parent).glob('*')):
            if not(p/'formal_responses.sqlite3').exists():continue
            before=counts(p);snapshot=snapshots/'before-switch'/parent/p.name;snapshot.mkdir(parents=True,mode=0o700)
            runtime=Path('/opt/energybridge-current50')/p.name/'runtime/admin.py'
            backup=json.loads(command('/usr/bin/python3','-B',str(runtime),'backup','--data-root',str(p),'--output',str(snapshot)))
            assert backup['sqlite_integrity']=='ok';old.append({'root':str(p),'counts_before':before,'backup':backup})
    with socket.socket()as s:s.bind(('127.0.0.1',port))
    unit=Path('/etc/systemd/system')/(service_name+'.service')
    backup=unit.with_name(service_name+'-backup.service');timer=unit.with_name(service_name+'-backup.timer')
    assert not unit.exists(),'A different UI91 service already exists;review it rather than overwrite'
    service=f'''[Unit]
Description=EnergyBridge frozen reference50 UI91 paired physics collection
After=network.target
[Service]
Type=simple
User=ebjoint
Group=ebjoint
WorkingDirectory={base/'runtime'}
ExecStart=/usr/bin/python3 -B {base/'runtime/server.py'} --release {base/'release'} --data-root {root} --public-origin {origin} --port {port}
Restart=on-failure
RestartSec=3
UMask=0077
NoNewPrivileges=yes
PrivateTmp=yes
ProtectSystem=strict
ProtectHome=yes
ReadWritePaths={root}
InaccessiblePaths=-/var/lib/energybridge-role-collection -/var/lib/energybridge-current50/collection_v69 -/var/lib/energybridge-current50/collection_v4_proposal
RestrictAddressFamilies=AF_INET AF_UNIX
MemoryMax=768M
TasksMax=64
[Install]
WantedBy=multi-user.target
'''
    backup_text=f'''[Unit]
Description=Private consistent UI91 collection backup
After={unit.name}
[Service]
Type=oneshot
User=ebjoint
Group=ebjoint
UMask=0077
ExecStart=/usr/bin/python3 -B {base/'runtime/admin.py'} backup --data-root {root} --output {snapshots/'rolling'}
NoNewPrivileges=yes
PrivateTmp=yes
ProtectSystem=strict
ProtectHome=yes
ReadWritePaths={root} {snapshots}
'''
    timer_text='''[Unit]
Description=UI91 collection backup every six hours
[Timer]
OnBootSec=5min
OnUnitActiveSec=6h
Persistent=true
[Install]
WantedBy=timers.target
'''
    snippet=Path('/etc/nginx/snippets/energybridge-household50-test.conf');original=snippet.read_bytes()
    pattern=r'# BEGIN CURRENT50 (?:V4PROPOSAL|UI91PHYSICS)\n.*?# END CURRENT50 (?:V4PROPOSAL|UI91PHYSICS)';blocks=re.findall(pattern,original.decode(),re.S);assert len(blocks)==1
    (snapshots/'nginx-before.conf').write_bytes(original)
    try:
        for p,text in ((unit,service),(backup,backup_text),(timer,timer_text)):p.write_text(text)
        command('systemctl','daemon-reload');command('systemctl','start',unit.name)
        private=health(f'http://127.0.0.1:{port}/household50-current/api/health',signature)
        assert private['presentation_revision']==release.manifest['presentation_revision']
        assert private['assignment_policy']==release.manifest['assignment_policy']['version'] and private['questions_per_round']==10
        assert not any(counts(root).values()),'New ledger must be empty before public activation'
        changed=f'''# BEGIN CURRENT50 UI91PHYSICS
location ^~ /household50-current {{
 auth_basic off;
 client_max_body_size 256k;
 proxy_pass http://127.0.0.1:{port};
 proxy_set_header Host $host;
 proxy_set_header X-Real-IP $remote_addr;
 proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
 proxy_set_header X-Forwarded-Proto $scheme;
 proxy_read_timeout 30s;
}}
# END CURRENT50 UI91PHYSICS'''
        snippet.write_text(original.decode().replace(blocks[0],changed,1));command('nginx','-t');command('systemctl','reload','nginx')
        public=health(origin+'/household50-current/api/health',signature)
        body_capacity=verify_public_body_capacity(origin)
        for prior in old:
            prior['counts_after']=counts(Path(prior['root']))
            assert all(prior['counts_after'][k]>=v for k,v in prior['counts_before'].items()),'Old records decreased'
        command('systemctl','start',backup.name);command('systemctl','enable',unit.name,timer.name);command('systemctl','start',timer.name)
        report={'passed':True,'release_sha256':signature,'previous_release_sha256':previous,'public_health':public,
            'public_body_capacity':body_capacity,
            'prior_ledgers':old,'new_ledger_counts_after_activation':counts(root),'old_services_stopped':False,
            'backup_active':True,'human_answers_created_by_deployment':0,'full1000_deferred':True}
        (base/'ACTIVATION.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');return report
    except BaseException:
        snippet.write_bytes(original)
        try:command('nginx','-t');command('systemctl','reload','nginx');command('systemctl','stop',unit.name)
        except Exception:pass
        raise


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--release-sha256',required=True);p.add_argument('--previous-release-sha256',required=True);p.add_argument('--origin',required=True)
    p.add_argument('--port',type=int,default=18793);p.add_argument('--service-name',default='energybridge-current50-ui91-physics');p.add_argument('--previous-private-port',type=int);a=p.parse_args()
    print(json.dumps(activate(a.release_sha256,a.previous_release_sha256,a.origin,a.port,a.service_name,a.previous_private_port),ensure_ascii=False))
