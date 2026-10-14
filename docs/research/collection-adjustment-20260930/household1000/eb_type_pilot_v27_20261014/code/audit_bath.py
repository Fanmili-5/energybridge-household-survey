"""Trace the pre-existing calendar at every helper stamp, before it is overwritten."""
import collections,datetime as dt
from common import *
import activity_model as am
def main():
 school_guard(); original=am.stamp;counts=collections.Counter();fail=[];ctx={}
 def witness(grid,a,b,activity,room,location='home'):
  if activity=='child_bathing_assistance':
   for s in range(max(0,a)//10,min(1440,b)//10):
    counts['resident_assistance_slots_checked']+=1;previous=grid[s]
    if previous[0]!='home_free_activity' or previous[2]!='home':fail.append({**ctx,'minute':s*10,'overwritten':previous})
  return original(grid,a,b,activity,room,location)
 am.stamp=witness
 for h in read(OUT/'SELECTION50.json')['records']:
  w=read(OUT/h['world_path'])
  for c in h['rounds']:
   for off in range(3):
    date=dt.date.fromisoformat(c['date'])+dt.timedelta(days=off);ctx={'household_id':h['household_id'],'date':date.isoformat()}
    day=am.build_day(w,date);counts['household_days']+=1
    for ev in day['family_context']['child_bathing_assistance_evidence'].values():
     counts['external_assistance_appointments']+=bool(ev.get('given_exact_external_appointment'))
     if ev['overwrote_work_or_commitment']:fail.append({**ctx,'bad_evidence':ev})
 save(OUT/'BATH_COMMITMENT_AUDIT.json',{'status':'fail' if fail else 'pass','counts':dict(counts),'failures':fail,'EP_runs':0,
  'witness':'read calendar BEFORE stamping assistance, independently of final assistance evidence'})
 print(dict(counts),'failures',len(fail),flush=True)
 if fail:raise RuntimeError(str(fail[:10]))
if __name__=='__main__':main()

