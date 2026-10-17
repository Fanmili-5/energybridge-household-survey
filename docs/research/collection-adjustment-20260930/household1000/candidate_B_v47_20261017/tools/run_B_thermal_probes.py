"""Two actual B47 native-shell thermal request probes; no full B physical claim."""
from pathlib import Path
import json,sys,subprocess,concurrent.futures
STAGE=Path(__file__).resolve().parents[1]
def read(p):return json.loads(p.read_text())
def main():
    samples={}
    for row in read(STAGE/'PAIR_BINDINGS10000.json')['records']:
        for rr in row['rounds']:
            p=read(STAGE/rr['path'])
            for ch in p['proposal']['changes']:
                z=ch.get('preconditioning')
                if z and z['phases']:
                    direction=next(e['direction']for e in p['VPP_events']if e['event_id']==ch['selected_event_id'])
                    if direction=='down'or any(any(ph['A_permission_added_minutes_by_asset'].values())for ph in z['phases']):samples.setdefault(direction,(row['household_id'],p['date']))
        if len(samples)==2:break
    if len(samples)!=2:raise ValueError('MISSING_UP_OR_DOWN_PRECONDITIONING_PROBE')
    def run(item):
        direction,(hid,date)=item;r=subprocess.run([sys.executable,'-B',str(STAGE/'tools/thermal_probe.py'),'--household',hid,'--date',date],capture_output=True,text=True)
        try:z=json.loads(r.stdout.strip().splitlines()[-1])
        except Exception:z={'passed':False,'error':r.stderr[-1500:],'output':r.stdout[-1000:]}
        return {'direction':direction,'household_id':hid,'date':date,**z}
    with concurrent.futures.ThreadPoolExecutor(max_workers=2)as pool:results=list(pool.map(run,samples.items()))
    report={'completed':all(z['passed']for z in results),'probe_count':len(results),'results':results,'scope':'real B thermal request schedules on native A46 shells and seven-day common history;other B appliance/hotwater changes omitted','full_physical_acceptance':False,'warnings_require_physical_followup':True}
    (STAGE/'B_THERMAL_FUNCTIONAL_CHECK.json').write_text(json.dumps(report,ensure_ascii=False,sort_keys=True,indent=2)+chr(10));print(json.dumps(report,ensure_ascii=False))
    if not report['completed']:raise SystemExit(2)
if __name__=='__main__':main()
