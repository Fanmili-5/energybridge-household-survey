"""Separate diagnostic dates; never replace the frozen random target dates."""
import datetime as dt, platform
from common import *
from programs import round_spec
from produce import one_case,LOADED_CODE

def main():
    if sys.platform!='linux':raise SystemExit('Boundary prechecks belong on school Linux')
    binding=next(b for b in read(OUT/'WORLD_BINDINGS1000.json')['records'] if b['household_id']=='ordinary-v6-0216');source=read(OUT/binding['world_path']);output=[]
    for date in ['2025-01-01','2025-12-31','2025-07-07']:
        w=json.loads(canonical(source));w['random10_date_selection']['dates'][0]['date']=date
        w['random10_task_families'][0]=['washer','dryer','dishwasher','water_heater','ev','ac']
        case=round_spec(w,1);case['diagnostic_only']=True;case['sampling_world_unchanged']=True
        signature=digest({'diagnostic':case,'code':LOADED_CODE,'engine':sha(ENGINE)})
        output.append(one_case(binding,w,case,signature,'boundary_'+date))
    save(OUT/'SCHOOL_CALENDAR_BOUNDARY_CHECKS.json',{'host':platform.node(),'diagnostic_cases':output,'random_dates_replaced':0,'formal_human_answers':0})
    print({'calendar_boundary_pairs':len(output),'random_dates_replaced':0},flush=True)
if __name__=='__main__':main()
