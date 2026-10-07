"""Bounded school-only execution of the fifty frozen household inputs."""
import argparse, concurrent.futures, hashlib, json, os, re, subprocess, sys, time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT.parent/'joint_static_production_20261007_v16'
ENGINE=Path('/home/hku_user3/energybridge-compute/EnergyPlus-24-1-0/energyplus')
def read(p):return json.loads(p.read_text())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(p,v):
 p.parent.mkdir(parents=True,exist_ok=True);q=p.with_suffix(p.suffix+'.tmp');q.write_text(json.dumps(v,ensure_ascii=False,sort_keys=True,indent=2)+'\n');q.replace(p)
def run(job):
 hh,case,arm=job;hid=hh['household_id'];i=case['round_index'];input_file=SOURCE/case[arm]['IDF_path'];weather=Path(hh['weather']['path']);out=ROOT/'runs'/hid/f'{i:02d}_{arm}';record=out/'RUN_RECORD.json'
 signature={'IDF_sha256':case[arm]['IDF_sha256'],'weather_sha256':hh['weather']['sha256'],'engine_sha256':sha(ENGINE),'runner_sha256':sha(Path(__file__))}
 if record.exists():
  old=read(record)
  if old.get('signature')==signature and old.get('runtime_pass') and sha(out/'eplusout.sql')==old['SQL_sha256']:return old
 assert sha(input_file)==signature['IDF_sha256'] and sha(weather)==signature['weather_sha256']
 out.mkdir(parents=True,exist_ok=True);started=time.monotonic()
 env={**os.environ,'OMP_NUM_THREADS':'1','OPENBLAS_NUM_THREADS':'1'}
 try:
  p=subprocess.run([str(ENGINE),'-w',str(weather),'-d',str(out),str(input_file)],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,env=env,timeout=1200)
  (out/'engine.log').write_text(p.stdout);err=(out/'eplusout.err').read_text(errors='replace') if (out/'eplusout.err').exists() else ''
  severe=[x.strip() for x in err.splitlines() if re.search(r'\*\*\s*(Severe|Fatal)\s*\*\*',x)]
  ok=p.returncode==0 and not severe and (out/'eplusout.sql').exists()
  result={'household_id':hid,'round_index':i,'date':case['date'],'arm':arm,'signature':signature,'returncode':p.returncode,'runtime_pass':ok,'severe_fatal':severe,'warning_count':len(re.findall(r'\*\*\s*Warning\s*\*\*',err)),'elapsed_seconds':round(time.monotonic()-started,3),'SQL_path':str((out/'eplusout.sql').relative_to(ROOT)) if ok else None,'SQL_sha256':sha(out/'eplusout.sql') if ok else None,'engine_host':'school Linux'}
 except Exception as e:result={'household_id':hid,'round_index':i,'arm':arm,'signature':signature,'runtime_pass':False,'error':str(e),'elapsed_seconds':round(time.monotonic()-started,3)}
 save(record,result);return result
if __name__=='__main__':
 ap=argparse.ArgumentParser();ap.add_argument('--first-case',action='store_true');ap.add_argument('--workers',type=int,default=16);a=ap.parse_args()
 assert sys.platform=='linux' and ENGINE.is_file()
 selection=read(ROOT/'SELECTION50.json');auth=read(ROOT/'EXECUTION_AUTHORIZATION.json');assert auth['selection_sha256']==sha(ROOT/'SELECTION50.json') and auth['EP_scope_hold_lifted_for_selected50'] and not auth['full1000_EP_authorized']
 assert len(selection['records'])==50 and selection['pairs']==500
 jobs=[(h,c,arm) for h in selection['records'] for c in h['rounds'] for arm in ('A','B')]
 if a.first_case:jobs=jobs[:2]
 outputs=[];t0=time.monotonic()
 with concurrent.futures.ThreadPoolExecutor(max_workers=a.workers) as pool:
  for r in pool.map(run,jobs):
   outputs.append(r)
   if len(outputs)%20==0 or not r['runtime_pass'] or len(outputs)==len(jobs):print(json.dumps({'finished':len(outputs),'planned':len(jobs),'failed':sum(not x['runtime_pass'] for x in outputs),'last_case':[r['household_id'],r['round_index'],r['arm']],'elapsed_seconds':round(time.monotonic()-t0,1)},ensure_ascii=False),flush=True)
   save(ROOT/('FIRST_EP_REVIEW.json' if a.first_case else 'EP_RUN_REVIEW.json'),{'requested_runs':len(jobs),'complete':len(outputs)==len(jobs),'finished_runs':len(outputs),'passed_runs':sum(x['runtime_pass'] for x in outputs),'failed_runs':sum(not x['runtime_pass'] for x in outputs),'records':outputs,'elapsed_seconds':round(time.monotonic()-t0,1),'selection_sha256':sha(ROOT/'SELECTION50.json'),'human_answers':0,'model_API_calls':0})
 if any(not r['runtime_pass'] for r in outputs):sys.exit(2)
