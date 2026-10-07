"""Run final preflight before admitting school-side random10 production."""
import platform,subprocess,time
from common import *
def main():
    if (OUT/'EP_HOLD.json').exists():raise SystemExit('User requested design review before EP;EP_HOLD active')
    if sys.platform!='linux':raise SystemExit('school only')
    start=time.time();status={'host':platform.node(),'started_unix':start,'stage':'preflight','complete':False,'annual_EP_runs':0,'workers_full':32}
    save(OUT/'SCHOOL_PIPELINE_STATUS.json',status)
    for name,args in [('preflight',['preflight.py']),('production1000',['produce.py','--workers','32'])]:
        status['stage']=name;save(OUT/'SCHOOL_PIPELINE_STATUS.json',status)
        result=subprocess.run([sys.executable,str(OUT/'code'/args[0]),*args[1:]])
        if result.returncode:
            status.update({'returncode':result.returncode,'failed_stage':name});save(OUT/'SCHOOL_PIPELINE_STATUS.json',status);raise SystemExit(result.returncode)
    status.update({'stage':'complete','complete':True,'elapsed_seconds':time.time()-start,'returncode':0});save(OUT/'SCHOOL_PIPELINE_STATUS.json',status)
if __name__=='__main__':main()
