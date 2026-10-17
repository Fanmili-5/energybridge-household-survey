"""Bounded50-only validation driver. No full1000 command or automatic expansion."""
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

STAGE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(STAGE/'code'))
from core import read,save,sha,physics_hash

TASK=Path('/root/autodl-tmp/eb-ab57-physics')
ENV=dict(os.environ,OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1')
ENGINE=TASK/'runtime/ep24_1/energyplus'

def status(phase,**kwargs):
    save(TASK/'v59_VALIDATION_STATUS.json',{'phase':phase,'stage':str(STAGE),'full1000_deferred':True,'updated_unix':time.time(),**kwargs})

def command(script,*args,scale=1,diagnostic=False):
    status('running50_validation',script=script,args=list(map(str,args)),portal_flow_scale=scale)
    env=dict(ENV,EB_PORTAL_FLOW_SCALE=str(scale))
    log=TASK/('v59_'+Path(script).stem+'.log')
    with log.open('a')as f:
        result=subprocess.run([sys.executable,'-B',str(STAGE/script),*map(str,args)],env=env,stdout=f,stderr=subprocess.STDOUT)
    if result.returncode and not(diagnostic and result.returncode==2):
        raise RuntimeError('VALIDATION_COMMAND_FAILED:'+script+':'+str(result.returncode))

def main():
    try:
        manifest=read(STAGE/'INPUT_MANIFEST.json')
        if len(manifest['records'])!=50 or manifest['pairs']!=500:raise ValueError('EXACT50_ONLY')
        status('waiting_for_original500_run')
        path=STAGE/'results/pilot50/RUN_BINDINGS.json'
        while not path.exists():time.sleep(5)
        runs=read(path)
        if not runs['passed']or runs['cases']!=500:raise ValueError('PILOT_RUN_FAILED')
        wanted={r['cases'][i]['case_id']for r in manifest['records']for i in(0,5)}
        for record in runs['records']:
            if record['case_id']not in wanted:continue
            hid,date=record['case_id'].split('__');src=STAGE/record['path'];dst=STAGE/'results/initialization112'/hid/date
            if not dst.exists():dst.parent.mkdir(parents=True,exist_ok=True);shutil.copytree(src,dst)
        command('code/run_physics.py','--scope','initialization','--date-indices','0,5','--history',112,'--label','initialization112','--workers',16,'--engine',ENGINE)
        command('code/run_physics.py','--scope','initialization','--date-indices','0,5','--history',224,'--label','initialization224','--workers',16,'--engine',ENGINE)
        command('code/analyze.py','--label','pilot50','--workers',8)
        command('code/check_initialization.py','--short','initialization112','--long','initialization224',diagnostic=True)
        for label,scale in [('portal_low',.5),('portal_high',2)]:
            command('code/run_physics.py','--scope','initialization','--date-indices',5,'--history',112,'--label',label,'--workers',16,'--engine',ENGINE,scale=scale)
        command('code/check_airflow_sensitivity.py')
        command('code/attach_uncertainty.py')
        # Original first6 cases, selected before outcomes. Same Linux run, not an
        # extra stochastic replicate and not a replacement of any failed case.
        wanted={r['cases'][0]['case_id']for r in manifest['records'][:6]}
        records=[r for r in runs['records']if r['case_id']in wanted]
        for record in records:
            hid,date=record['case_id'].split('__');dst=STAGE/'results/linux_probe112'/hid/date
            if not dst.exists():dst.parent.mkdir(parents=True,exist_ok=True);shutil.copytree(STAGE/record['path'],dst)
        probe=dict(runs,cases=6,records=records,scope='initialization',label='linux_probe112')
        save(STAGE/'results/linux_probe112/RUN_BINDINGS.json',probe)
        save(STAGE/'REMOTE_ENVIRONMENT.json',{'schema':'eb.reference50_compute.v59','engine':str(ENGINE),'engine_sha256':sha(ENGINE),
            'engine_version':subprocess.check_output([str(ENGINE),'--version'],text=True).strip(),
            'physics_sha256':physics_hash(),'scope':'original50households500pairs only','full1000_deferred':True,
            'credentials_included':False})
        status('original50_and_bounded_diagnostics_complete',physics_sha256=physics_hash(),
            review_passed=read(STAGE/'results/pilot50/REVIEW.json')['passed'],
            history_comparisons_robust=read(STAGE/'INITIALIZATION_REVIEW.json')['conditional_comparisons_robust'],
            airflow_comparisons_robust=read(STAGE/'AIRFLOW_SENSITIVITY_REVIEW.json')['conditional_comparisons_robust'])
    except Exception as exc:
        status('needs_repair',error=str(exc));raise

if __name__=='__main__':main()
