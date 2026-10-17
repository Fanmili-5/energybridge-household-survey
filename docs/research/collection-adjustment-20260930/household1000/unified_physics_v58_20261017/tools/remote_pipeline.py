"""Task-local, resumable execution driver. No scheduler, messages or credentials."""
import json
import os
import subprocess
import sys
import tarfile
import time
import traceback
import shutil
from pathlib import Path

STAGE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(STAGE/'code'))
from core import read,save,sha,physics_hash,code_hash

TASK=Path(os.environ.get('EB_REMOTE_TASK_ROOT','/root/autodl-tmp/eb-ab57-physics'))
ENV=dict(os.environ,OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',EB_REFERENCE_ACH='.35')
STATUS=TASK/'PIPELINE_STATUS.json'

def status(phase,**extra):
    save(STATUS,{'phase':phase,'updated_unix':time.time(),'stage':str(STAGE),**extra})

def run(script,*args,log,diagnostic=False):
    command=[sys.executable,'-B',str(STAGE/script),*map(str,args)]
    status('running_command',command=command,log=str(log))
    with Path(log).open('a')as handle:
        result=subprocess.run(command,cwd=STAGE,env=ENV,stdout=handle,stderr=subprocess.STDOUT)
    if result.returncode:
        if diagnostic and result.returncode==2:
            report=read(STAGE/'INITIALIZATION_REVIEW.json')
            if report['cases']==100 and 'records'in report:
                status('historical_sensitivity_recorded_without_invariance_claim',outside_bounds=sum(not r['within_predeclared_bounds']for r in report['records']))
                return
        raise RuntimeError('COMMAND_FAILED:'+str(result.returncode)+':'+str(command))

def await_run(label,cases):
    path=STAGE/'results'/label/'RUN_BINDINGS.json'
    while not path.exists():status('waiting_for_validation_run',label=label);time.sleep(10)
    result=read(path)
    if result['cases']!=cases or not result['passed']:raise RuntimeError('VALIDATION_RUN_FAILED:'+label)

def main():
    try:
        for label in ('initialization112','initialization224'):await_run(label,100)
        run('code/check_initialization.py','--short','initialization112','--long','initialization224',log=TASK/'initialization_review_fixed.log',diagnostic=True)
        while True:
            valid=True
            for name in ('CROSS_PLATFORM_REVIEW.json','REGRESSION_RESULTS.json'):
                path=STAGE/name
                valid=valid and path.exists()and read(path)['passed']and read(path).get('physics_sha256')==physics_hash()
            if valid:break
            status('waiting_for_matched_platform_and_regression_reports');time.sleep(10)
        # Reuse all100 predeclared short-history test cases by exact request/model
        # fingerprint, including any service failures. Never select by response.
        short=read(STAGE/'results/initialization112/RUN_BINDINGS.json')
        for r in short['records']:
            hid,date=r['case_id'].split('__');src=STAGE/'results/initialization112'/hid/date;dst=STAGE/'results/pilot50'/hid/date
            if not dst.exists():dst.parent.mkdir(parents=True,exist_ok=True);shutil.copytree(src,dst)
        engine=TASK/'runtime/ep24_1/energyplus'
        run('code/run_physics.py','--scope','pilot50','--label','pilot50','--history',112,'--workers',16,'--engine',engine,log=TASK/'pilot50_fixed.log')
        run('code/analyze.py','--label','pilot50','--workers',8,log=TASK/'pilot50_review_fixed.log')
        if (STAGE/'DEFER_FULL1000.json').exists() and read(STAGE/'DEFER_FULL1000.json').get('active'):
            status('original50_only_full1000_deferred_by_user')
            return
        status('pilot_accepted_waiting_for_production_source_lock')
        ready=STAGE/'FULL_RUN_READY.json'
        while not ready.exists():time.sleep(10)
        if (STAGE/'DEFER_FULL1000.json').exists() and read(STAGE/'DEFER_FULL1000.json').get('active'):
            status('original50_only_full1000_deferred_by_user')
            return
        lock=read(ready)
        if lock['physics_sha256']!=physics_hash()or lock['source_code_sha256']!=code_hash():raise RuntimeError('SOURCE_LOCK_MISMATCH')
        if lock['input_manifest_sha256']!=sha(STAGE/'INPUT_MANIFEST.json'):raise RuntimeError('INPUT_LOCK_MISMATCH')
        if lock['history_days']!=112:raise RuntimeError('HISTORY_POLICY_MISMATCH')
        run('code/run_physics.py','--scope','all','--label','all','--history',lock['history_days'],'--workers',16,'--engine',engine,log=TASK/'all.log')
        run('code/analyze.py','--label','all','--workers',8,log=TASK/'all_review.log')
        review=read(STAGE/'results/all/REVIEW.json')
        if not review['passed']or review['counts']['cases']!=10000:raise RuntimeError('FULL_COMMON_STATE_READBACK_FAILED')
        save(STAGE/'COMMON_INITIAL_STATE_REVIEW.json',{'schema':'eb.specified_common_initial_state.v58','passed':True,'cases':10000,
            'scope':'same declared A-history initial state for A and B;not invariance to alternative past histories',
            'physics_sha256':physics_hash(),'history_days':lock['history_days'],'all_predecision_channels_matched':True,
            'tolerance_normalized':1e-7,'full_review_sha256':sha(STAGE/'results/all/REVIEW.json'),
            'historical_sensitivity_report_sha256':sha(STAGE/'INITIALIZATION_REVIEW.json'),
            'historical_pointwise_bounds_all_passed':read(STAGE/'INITIALIZATION_REVIEW.json')['passed']})
        run('code/finalize.py','seal','--workers',8,log=TASK/'seal.log')
        run('code/finalize.py','verify',log=TASK/'verify.log')
        names=['ACCEPTANCE.json','PHYSICAL_BINDINGS10000.json','PHYSICAL_BINDINGS50.json','FINAL_SEAL.json','FINAL_VERIFICATION.json',
               'FILE_MANIFEST.json.gz','INITIALIZATION_REVIEW.json','COMMON_INITIAL_STATE_REVIEW.json','CROSS_PLATFORM_REVIEW.json','REGRESSION_RESULTS.json',
               'REMOTE_ENVIRONMENT.json','TRANSPORT_METADATA_QUARANTINE.json','METHODS.md','REPORT.md','FULL_RUN_READY.json']
        if(STAGE/'PHYSICS_CONTRACT.json').exists():names.append('PHYSICS_CONTRACT.json')
        for label in ('all','pilot50','initialization112','initialization224'):
            names.extend(f'results/{label}/{n}'for n in ('RUN_CONFIG.json','RUN_BINDINGS.json')if(STAGE/f'results/{label}/{n}').exists())
            if(STAGE/f'results/{label}/REVIEW.json').exists():names.append(f'results/{label}/REVIEW.json')
        names.extend(str(p.relative_to(STAGE))for p in (STAGE/'results/all').rglob('PHYSICAL_SUMMARY.json'))
        archive=TASK/'evidence_export.tar.gz'
        status('packaging_complete_evidence')
        with tarfile.open(archive,'w:gz',compresslevel=6)as tar:
            for name in names:tar.add(STAGE/name,arcname=name,recursive=False)
        status('complete',archive=str(archive),archive_sha256=sha(archive),files=len(names),seal_sha256=sha(STAGE/'FINAL_SEAL.json'),
               acceptance=read(STAGE/'ACCEPTANCE.json'))
    except Exception as exc:
        status('needs_repair',error=str(exc),traceback=traceback.format_exc());raise

if __name__=='__main__':main()
