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


def activate(signature,previous,origin):
    assert re.fullmatch('[a-f0-9]{64}',signature) and re.fullmatch('[a-f0-9]{64}',previous)
    health(origin+'/household50-current/api/health',previous)
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
    account=pwd.getpwnam('ebjoint');root=Path('/var/lib/energybridge-current50/collection_ui91_physics')/signature[:20]
    snapshots=Path('/var/backups/energybridge-current50')/signature[:20]
    for p in (root,snapshots):
        p.mkdir(parents=True,exist_ok=True,mode=0o700);p.chmod(0o700);os.chown(p,account.pw_uid,account.pw_gid)
    old=[]
    for parent in ('collection_v69','collection_v4_proposal'):
        for p in sorted((Path('/var/lib/energybridge-current50')/parent).glob('*')):
            if not(p/'formal_responses.sqlite3').exists():continue
            before=counts(p);snapshot=snapshots/'before-switch'/parent/p.name;snapshot.mkdir(parents=True,mode=0o700)
            runtime=Path('/opt/energybridge-current50')/p.name/'runtime/admin.py'
            backup=json.loads(command('/usr/bin/python3','-B',str(runtime),'backup','--data-root',str(p),'--output',str(snapshot)))
            assert backup['sqlite_integrity']=='ok';old.append({'root':str(p),'counts_before':before,'backup':backup})
    with socket.socket()as s:s.bind(('127.0.0.1',18793))
    unit=Path('/etc/systemd/system/energybridge-current50-ui91-physics.service')
    backup=unit.with_name('energybridge-current50-ui91-physics-backup.service');timer=unit.with_name('energybridge-current50-ui91-physics-backup.timer')
    assert not unit.exists(),'A different UI91 service already exists;review it rather than overwrite'
    service=f'''[Unit]
Description=EnergyBridge frozen reference50 UI91 paired physics collection
After=network.target
[Service]
Type=simple
User=ebjoint
Group=ebjoint
WorkingDirectory={base/'runtime'}
ExecStart=/usr/bin/python3 -B {base/'runtime/server.py'} --release {base/'release'} --data-root {root} --public-origin {origin} --port 18793
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
    pattern=r'# BEGIN CURRENT50 V4PROPOSAL\n.*?# END CURRENT50 V4PROPOSAL';blocks=re.findall(pattern,original.decode(),re.S);assert len(blocks)==1
    (snapshots/'nginx-before.conf').write_bytes(original)
    try:
        for p,text in ((unit,service),(backup,backup_text),(timer,timer_text)):p.write_text(text)
        command('systemctl','daemon-reload');command('systemctl','start',unit.name)
        private=health('http://127.0.0.1:18793/household50-current/api/health',signature)
        assert private['presentation_revision']==release.manifest['presentation_revision']
        assert not any(counts(root).values()),'New ledger must be empty before public activation'
        changed=blocks[0].replace('V4PROPOSAL','UI91PHYSICS').replace('18792','18793')
        snippet.write_text(original.decode().replace(blocks[0],changed,1));command('nginx','-t');command('systemctl','reload','nginx')
        public=health(origin+'/household50-current/api/health',signature)
        for prior in old:
            prior['counts_after']=counts(Path(prior['root']))
            assert all(prior['counts_after'][k]>=v for k,v in prior['counts_before'].items()),'Old records decreased'
        command('systemctl','start',backup.name);command('systemctl','enable',unit.name,timer.name);command('systemctl','start',timer.name)
        report={'passed':True,'release_sha256':signature,'previous_release_sha256':previous,'public_health':public,
            'prior_ledgers':old,'new_ledger_counts_after_activation':counts(root),'old_services_stopped':False,
            'backup_active':True,'human_answers_created_by_deployment':0,'full1000_deferred':True}
        (base/'ACTIVATION.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');return report
    except BaseException:
        snippet.write_bytes(original)
        try:command('nginx','-t');command('systemctl','reload','nginx');command('systemctl','stop',unit.name)
        except Exception:pass
        raise


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--release-sha256',required=True);p.add_argument('--previous-release-sha256',required=True);p.add_argument('--origin',required=True);a=p.parse_args()
    print(json.dumps(activate(a.release_sha256,a.previous_release_sha256,a.origin),ensure_ascii=False))
