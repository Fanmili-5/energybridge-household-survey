"""Sequential admission checks, all executed on the school host."""
import platform,subprocess,time
from common import *
def main():
    if sys.platform!='linux':raise SystemExit('school-only interface and EP preflight')
    checks=[]
    for name,args in [('interface',['validate_inputs.py']),('four_household_random10',['produce.py','--pilot','--workers','4']),('calendar_boundaries',['calendar_boundaries.py'])]:
        start=time.monotonic();result=subprocess.run([sys.executable,str(OUT/'code'/args[0]),*args[1:]])
        checks.append({'name':name,'returncode':result.returncode,'elapsed_seconds':round(time.monotonic()-start,3)})
        save(OUT/'SCHOOL_PREFLIGHT.json',{'host':platform.node(),'checks':checks,'complete':len(checks)==3 and all(c['returncode']==0 for c in checks),'annual_runs':0})
        if result.returncode:raise SystemExit(result.returncode)
    print({'school_preflight_complete':True,'random_pairs':40,'additional_boundary_diagnostics':3,'annual_runs':0},flush=True)
if __name__=='__main__':main()
