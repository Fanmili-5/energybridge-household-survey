import hashlib,json,os,grp,pwd,subprocess,tarfile
from pathlib import Path
manifest_sha='553417ee57a2dc32688d3e17c1385eb83d2f8f8a416be6beaae5beb0abbbb751';archive_sha='22c78ae0af24ccb0a05f9ef27d996061759b373af7ce40b83556b4d7b928c191'
a=Path('/root/energybridge-household50-test-553417ee57a2dc32.tar.gz');old=Path('/opt/energybridge-household50/releases/a259201be6c112ec');new=old.parent/'553417ee57a2dc32';unit=Path('/etc/systemd/system/energybridge-household50-test.service');data=Path('/var/lib/energybridge-household50')/manifest_sha
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
assert sha(a)==archive_sha and not new.exists();text=unit.read_text();assert str(old) in text and '--port 18775' in text
new.mkdir()
with tarfile.open(a) as t:
 assert all(not m.name.startswith('/') and '..' not in Path(m.name).parts and not m.issym() and not m.islnk() for m in t.getmembers());t.extractall(new)
assert sha(new/'DEPLOY_MANIFEST.json')==manifest_sha
for name,h in json.loads((new/'DEPLOY_MANIFEST.json').read_text())['files'].items():assert sha(new/name)==h,name
gid=grp.getgrnam('ebjoint').gr_gid;uid=pwd.getpwnam('ebjoint').pw_uid
for p in [new,*new.rglob('*')]:os.chown(p,0,gid);p.chmod(0o750 if p.is_dir() else 0o640)
data.mkdir(mode=0o700);os.chown(data,uid,gid)
backup=Path('/var/backups/energybridge-household50-test/553417ee57a2dc32');backup.mkdir();(backup/'unit.before').write_text(text)
unit.write_text(text.replace(str(old),str(new)).replace('/var/lib/energybridge-household50/a259201be6c112ec6b18aa847195fa4fdc3317319f68667c2b9841976ef4e5fa',str(data)))
try:
 subprocess.run(['systemctl','daemon-reload'],check=True);subprocess.run(['systemctl','restart','energybridge-household50-test'],check=True)
 subprocess.run(['curl','--noproxy','*','--fail','--retry','5','--retry-all-errors','--retry-delay','1','--max-time','10','-sS','https://47.85.194.154/household50/api/health'],check=True)
except Exception:
 unit.write_text(text);subprocess.run(['systemctl','daemon-reload'],check=True);subprocess.run(['systemctl','restart','energybridge-household50-test'],check=True);raise
r={'status':'corrected_projection_deployed','url':'https://47.85.194.154/household50','manifest_sha256':manifest_sha,'release':str(new),'engineering_data_root':str(data),'source_household_anchors_preserved_new_contexts_and_EP_results':True,'original_services_unchanged':True,'human_collection_release':False,'training_release':False};(backup/'DEPLOY_RECORD.json').write_text(json.dumps(r,indent=2)+'\n');print(json.dumps(r))
