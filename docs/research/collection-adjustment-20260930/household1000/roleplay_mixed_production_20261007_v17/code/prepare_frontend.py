"""Original renderer, blinded design metadata, isolated engineering save checks."""
import hashlib,json,shutil,subprocess,sys,tarfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
if __name__=='__main__':
 assert sys.platform=='linux'
 release=ROOT/'frontend_release'
 if release.exists():
  old=ROOT/'development/frontend_before_metadata_blinding';old.parent.mkdir(exist_ok=True);assert not old.exists();release.rename(old)
 subprocess.run(['python3',str(ROOT/'code/build_site.py')],check=True)
 shutil.copy2(ROOT/'code/serve50.py',release/'serve50.py')
 node=ROOT.parents[6]/'node-v20.19.0-linux-x64/bin/node';assert node.is_file()
 version=subprocess.check_output([str(node),'--version'],text=True).strip();assert version=='v20.19.0'
 subprocess.run([str(node),str(ROOT/'code/bind_frontend.js'),str(release)],check=True)
 index=json.loads((release/'INDEX50.json').read_text());conditions=[]
 for row in index['households']:
  text=(release/'households'/row['household_id']/'index.html').read_text()
  assert 'design_condition' not in text and 'constraint_assessment' not in text
  for f in (ROOT/'pairs'/row['household_id']).glob('*.json'):
   p=json.loads(f.read_text());conditions.append({'case_id':p['case_id'],'pair_sha256':sha(f),'design_condition':p['design_condition'],'assessment':p['constraint_assessment']})
 (ROOT/'PRIVATE_CONDITION_INDEX.json').write_text(json.dumps({'scope':'analysis metadata only;not served to actors or model inputs','records':conditions},ensure_ascii=False,indent=2)+'\n')
 records=ROOT/'frontend_test_records_blinded'
 subprocess.run([str(node),str(ROOT/'code/test_render.js'),str(release),str(records)],check=True)
 shutil.copy2(records/'RENDER_REVIEW.json',ROOT/'RENDER_REVIEW.json')
 subprocess.run(['python3',str(ROOT/'code/test_http_focus.py')],check=True)
 files={str(f.relative_to(release)):sha(f) for f in sorted(release.rglob('*')) if f.is_file()}
 manifest={'scope':'mixed50 original frontend engineering-only;design labels excluded;human labels absent','files':files}
 (release/'DEPLOY_MANIFEST.json').write_text(json.dumps(manifest,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n')
 archive=ROOT/'frontend_mixed50.tar.gz'
 with tarfile.open(archive,'w:gz') as t:
  for f in sorted(release.rglob('*')):
   if f.is_file():t.add(f,arcname=str(f.relative_to(release)))
 ready={'manifest_sha256':sha(release/'DEPLOY_MANIFEST.json'),'archive_sha256':sha(archive),'files':len(files),'design_metadata_not_served_or_in_model_input':True,'node_version':version}
 (ROOT/'DEPLOY_READY.json').write_text(json.dumps(ready,indent=2)+'\n');print(json.dumps(ready))
