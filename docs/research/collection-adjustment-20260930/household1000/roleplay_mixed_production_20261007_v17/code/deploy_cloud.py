"""Update only the existing fifty-household engineering preview, retain rollback."""
import grp,hashlib,json,os,pwd,subprocess,tarfile
from pathlib import Path
MANIFEST='34d2fdd32016f7017e367e15f22f6a4030d7b8446550c876221f8ce38be138f0'
ARCHIVE='d1d738efd3beeaa08c3a7e6c8787f34c4b6de8d20c1185114f13f9357d630d4f'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
archive=Path('/root/frontend_mixed50.tar.gz');assert sha(archive)==ARCHIVE
old=Path('/opt/energybridge-household50/releases/dfbce7a4a81cc512');new=old.parent/MANIFEST[:16]
unit=Path('/etc/systemd/system/energybridge-household50-test.service');text=unit.read_text()
old_data='/var/lib/energybridge-household50/dfbce7a4a81cc5121b06e38e0527d3ff0f37daa0ed8bab30f792ca094614ea98'
assert str(old) in text and old_data in text and '--port 18775' in text and not new.exists()
new.mkdir()
with tarfile.open(archive) as t:
 assert all(not Path(m.name).is_absolute() and '..' not in Path(m.name).parts and not m.issym() and not m.islnk() for m in t.getmembers())
 t.extractall(new)
assert sha(new/'DEPLOY_MANIFEST.json')==MANIFEST
for n,h in json.loads((new/'DEPLOY_MANIFEST.json').read_text())['files'].items():assert sha(new/n)==h,n
uid=pwd.getpwnam('ebjoint').pw_uid;gid=grp.getgrnam('ebjoint').gr_gid
for p in [new,*new.rglob('*')]:os.chown(p,0,gid);p.chmod(0o750 if p.is_dir() else 0o640)
data=Path('/var/lib/energybridge-household50')/MANIFEST;data.mkdir(mode=0o700);os.chown(data,uid,gid)
backup=Path('/var/backups/energybridge-household50-test')/MANIFEST[:16];backup.mkdir();(backup/'unit.before').write_text(text)
unit.write_text(text.replace(str(old),str(new)).replace(old_data,str(data)))
try:
 subprocess.run(['systemctl','daemon-reload'],check=True);subprocess.run(['systemctl','restart','energybridge-household50-test'],check=True)
 subprocess.run(['curl','--noproxy','*','--fail','--retry','5','--retry-all-errors','--retry-delay','1','--max-time','10','-sS','https://47.85.194.154/household50/api/health'],check=True)
except Exception:
 unit.write_text(text);subprocess.run(['systemctl','daemon-reload'],check=True);subprocess.run(['systemctl','restart','energybridge-household50-test'],check=True);raise
record={'status':'mixed_proposals_deployed','url':'https://47.85.194.154/household50','manifest_sha256':MANIFEST,'release':str(new),'data_root':str(data),'old_release_and_engineering_DB_preserved':True,'original_questionnaire_services_unchanged':True,'design_labels_not_served':True,'human_collection_release':False,'training_release':False}
(backup/'DEPLOY_RECORD.json').write_text(json.dumps(record,indent=2)+'\n');print(json.dumps(record))
