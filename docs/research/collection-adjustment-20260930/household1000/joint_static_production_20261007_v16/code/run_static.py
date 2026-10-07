"""Allowlisted static production only;EP user hold is required throughout."""
import subprocess, time
from common import *
def main():
    school_guard();started=time.time()
    steps=['refresh_worlds','produce_pairs','native_interface','counterexamples','compile_inputs','review_all','review_geometry','project_collection']
    status={'started_unix':started,'EP_started':0,'complete':False,'steps':[]}
    for name in steps:
        status['stage']=name;save(OUT/'STATIC_PIPELINE_STATUS.json',status)
        with (OUT/(name+'.log')).open('w') as log:
            r=subprocess.run([sys.executable,str(OUT/'code'/(name+'.py'))],stdout=log,stderr=subprocess.STDOUT)
        status['steps'].append({'name':name,'returncode':r.returncode})
        if r.returncode:
            status['failed_stage']=name;save(OUT/'STATIC_PIPELINE_STATUS.json',status);raise SystemExit(r.returncode)
    status['stage']='r72_adapter';save(OUT/'STATIC_PIPELINE_STATUS.json',status)
    with (OUT/'r72_adapter.log').open('w') as log:r=subprocess.run([os.environ.get('EB_STATIC_NODE','node'),str(OUT/'code/check_r72.js')],stdout=log,stderr=subprocess.STDOUT)
    status['steps'].append({'name':'r72_adapter','returncode':r.returncode})
    status.update(complete=r.returncode==0,elapsed_seconds=time.time()-started,stage='static_complete' if r.returncode==0 else 'r72_adapter_failed')
    save(OUT/'STATIC_PIPELINE_STATUS.json',status)
    print(status,flush=True)
    if r.returncode:raise SystemExit(r.returncode)
if __name__=='__main__':main()
