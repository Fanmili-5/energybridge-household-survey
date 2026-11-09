"""CASE.v3 date-specific views; source demands are not repeated implicitly."""
from copy import deepcopy
import datetime as dt
from .common import require

def dates(case):
 a=dt.date.fromisoformat(case['run']['start_date']);z=dt.date.fromisoformat(case['run']['end_date'])
 return [(a+dt.timedelta(days=i)).isoformat() for i in range((z-a).days+1)]

def view(case,date):
 require(case['schema']=='national_idf.case.v3','DATED_CASE_SCHEMA')
 require(date in case['life']['by_date'],'DATED_CASE_DATE_MISSING',date)
 daily=case['life']['by_date'][date];c=deepcopy(case);c['schema']='national_idf.case.v2';c['life'].pop('by_date')
 life=c['life'];life['occupancy']=[]
 # Use the existing exact-overlap People interpretation, never round a life clock.
 life['occupancy_weekly']={str(i):deepcopy(daily['occupancy']) for i in range(7)}
 life.pop('occupancy_recovery_weekly',None)
 life['mixed_water_daily']=deepcopy(daily['mixed_water']);life['mixed_water_overrides']={}
 life['services_daily']=deepcopy(daily['services']);life['ev_connection_daily']=deepcopy(daily['ev_connections'])
 life['ev_daily']=deepcopy(daily['ev_trip']) if daily['ev_trip'] is not None else dict(departure_min=0,return_min=10,traction_kWh=0,required_departure_SOC=0)
 begin,end=c['run']['start_date'],c['run']['end_date']
 for key in ['program_start_overrides','ev_window_overrides']:
  c['controls'][key]={d:v for d,v in c['controls'].get(key,{}).items() if begin<=d<=end}
 c['controls']['dated_overrides']=[r for r in c['controls'].get('dated_overrides',[]) if begin<=r['date']<=end]
 return c
