"""Small real-shell heating/cooling/large-family functional checks, not full A/B physics."""
import sys,subprocess,json,hashlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
STAGE=Path(__file__).resolve().parents[1]
CASES=[('ordinary-v6-0001','2025-03-15'),('ordinary-v6-0001','2025-08-06'),('ordinary-v6-0102','2025-03-19'),('ordinary-v6-0661','2025-01-20')]
def run(case):
 h,d=case;r=subprocess.run([sys.executable,'-B',str(STAGE/'tools/thermal_probe.py'),'--household',h,'--date',d],capture_output=True,text=True)
 try:result=json.loads(r.stdout.strip().splitlines()[-1])
 except Exception:result={'passed':False,'output':r.stdout[-1000:],'error':r.stderr[-1500:]}
 return {'household_id':h,'date':d,**result}
def main():
 with ThreadPoolExecutor(max_workers=2)as pool:results=list(pool.map(run,CASES))
 for result in results:
  labels=[]
  if result.get('folder'):
   err=(STAGE/result['folder']/'out/eplusout.err').read_text()
   if 'same materials in the reverse order'in err:labels.append('inherited_asymmetric_interzone_construction')
   if 'AHRI test condition due to curve out of bound'in err:labels.append('inherited_AHRI_rating_curve_domain')
   if 'condenser inlet dry-bulb temperature below 0 C'in err:labels.append('low_outdoor_temperature_cooling_requires_physical_followup')
  result['warning_categories']=labels
 report={'warning_categories_require_followup':True,'completed':all(x['passed']for x in results),'probe_count':len(results),'results':results,'full_physical_acceptance':False,'scope':'actual-shell native HVAC functional checks only;not appliance/hotwater delivery,B dynamics or consent validation'}
 (STAGE/'THERMAL_FUNCTIONAL_CHECK.json').write_text(json.dumps(report,ensure_ascii=False,sort_keys=True,indent=2)+'\n');print(json.dumps(report,ensure_ascii=False))
 if not report['completed']:raise SystemExit(2)
if __name__=='__main__':main()
