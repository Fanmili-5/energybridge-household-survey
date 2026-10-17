"""Install the exact tested fifty-household engineering payload on the original host."""
import grp,hashlib,json,os,pwd,shutil,subprocess,tarfile
from pathlib import Path
EXPECTED_ARCHIVE='43e23178fc848521c57d60a5c929688c6c91b1d5a8cf39953b5f01d6d99e2b1e';EXPECTED_MANIFEST='2574214eac5db5ec9dcb8eb8ddcfb5eeda4d09393a3d18071a50235689d617f8'
archive=Path('/root/energybridge-household50-test-2574214eac5db5ec.tar.gz');release=Path('/opt/energybridge-household50/releases/2574214eac5db5ec');data=Path('/var/lib/energybridge-household50');unit=Path('/etc/systemd/system/energybridge-household50-test.service');snippet=Path('/etc/nginx/snippets/energybridge-household50-test.conf');nginx=Path('/etc/nginx/sites-available/energybridge');backup=Path('/var/backups/energybridge-household50-test/2574214eac5db5ec')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
assert sha(archive)==EXPECTED_ARCHIVE
assert subprocess.run(['systemctl','is-active','--quiet','energybridge']).returncode==0
assert subprocess.run(['systemctl','is-active','--quiet','energybridge-joint-b']).returncode==0
assert not release.exists() and not unit.exists() and not snippet.exists()
release.mkdir(parents=True)
with tarfile.open(archive) as tar:
 assert all(not m.name.startswith('/') and '..' not in Path(m.name).parts and not m.issym() and not m.islnk() for m in tar.getmembers())
 tar.extractall(release)
manifest=release/'DEPLOY_MANIFEST.json';assert sha(manifest)==EXPECTED_MANIFEST
for name,h in json.loads(manifest.read_text())['files'].items():assert sha(release/name)==h,name
user=pwd.getpwnam('ebjoint');group=grp.getgrnam('ebjoint')
for p in [release,*release.rglob('*')]:os.chown(p,0,group.gr_gid);p.chmod(0o750 if p.is_dir() else 0o640)
data.mkdir(mode=0o700);os.chown(data,user.pw_uid,group.gr_gid)
unit.write_text(f'''[Unit]
Description=EnergyBridge fifty-household original-frontend engineering test
After=network.target
[Service]
Type=simple
User=ebjoint
Group=ebjoint
UMask=0077
WorkingDirectory={release}
ExecStart=/usr/bin/python3 -B {release}/serve50.py --release {release} --data-root {data} --public-origin https://47.85.194.154 --port 18775
Environment=PYTHONDONTWRITEBYTECODE=1 PYTHONNOUSERSITE=1
Restart=on-failure
RestartSec=3
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths={data}
InaccessiblePaths=/var/lib/energybridge-joint-b /var/lib/energybridge/demo_20260911/jobs /etc/energybridge
RestrictAddressFamilies=AF_INET AF_UNIX
IPAddressDeny=any
IPAddressAllow=localhost
MemoryMax=384M
TasksMax=32
[Install]
WantedBy=multi-user.target
''')
subprocess.run(['systemctl','daemon-reload'],check=True);subprocess.run(['systemctl','start','energybridge-household50-test'],check=True)
subprocess.run(['curl','--fail','--max-time','10','http://127.0.0.1:18775/household50/api/health'],check=True)
backup.mkdir(parents=True);shutil.copy2(nginx,backup/'nginx.before');old_hash=sha(nginx)
snippet.write_text('''location ^~ /household50 {
 auth_basic off;
 client_max_body_size 2m;
 limit_req zone=eb_general burst=60 nodelay;
 proxy_pass http://127.0.0.1:18775;
 proxy_set_header Host $host;
 proxy_set_header X-Forwarded-Proto https;
 proxy_read_timeout 30s;
 add_header Cache-Control "no-store" always;
 add_header Referrer-Policy "no-referrer" always;
}
''')
text=nginx.read_text();marker=' client_max_body_size 32k;';assert text.count(marker)==1
nginx.write_text(text.replace(marker,marker+'\n include /etc/nginx/snippets/energybridge-household50-test.conf;',1))
try:
 subprocess.run(['nginx','-t'],check=True);subprocess.run(['systemctl','reload','nginx'],check=True)
 for url in ['https://47.85.194.154/household50/api/health','https://47.85.194.154/','https://47.85.194.154/joint-b']:
  subprocess.run(['curl','--fail','--max-time','15','-sS','-o','/dev/null',url],check=True)
except Exception:
 shutil.copy2(backup/'nginx.before',nginx);subprocess.run(['nginx','-t'],check=True);subprocess.run(['systemctl','reload','nginx'],check=True);raise
record={'status':'deployed_and_HTTP_checked','url':'https://47.85.194.154/household50','manifest_sha256':EXPECTED_MANIFEST,'nginx_before_sha256':old_hash,'nginx_after_sha256':sha(nginx),'service':'energybridge-household50-test','original_services_kept_running':True,'human_collection_release':False,'training_release':False,'data_root':str(data),'original_answer_DB_touched':False}
(backup/'DEPLOY_RECORD.json').write_text(json.dumps(record,indent=2)+'\n');print(json.dumps(record))
