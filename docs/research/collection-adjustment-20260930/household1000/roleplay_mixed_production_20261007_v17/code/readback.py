"""Independent actual SQL clock, common-state, metering and delivered-service checks."""
import collections, concurrent.futures, datetime as dt, hashlib, json, math, sqlite3
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];SOURCE=ROOT
def read(p):return json.loads(p.read_text())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(p,v):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v,ensure_ascii=False,sort_keys=True,indent=2)+'\n')
def frame(record):
 path=ROOT/record['SQL_path'];assert sha(path)==record['SQL_sha256']
 db=sqlite3.connect('file:'+str(path)+'?mode=ro',uri=True)
 days=db.execute('SELECT SimulationDays,Year,Month,Day,count(*) FROM Time WHERE WarmupFlag=0 GROUP BY SimulationDays,Year,Month,Day ORDER BY SimulationDays').fetchall()
 data=db.execute('SELECT t.SimulationDays,t.Hour,t.Minute,t.Interval,d.KeyValue,d.Name,d.Units,r.Value FROM ReportData r JOIN ReportDataDictionary d USING(ReportDataDictionaryIndex) JOIN Time t USING(TimeIndex) WHERE t.WarmupFlag=0 AND d.ReportingFrequency="Zone Timestep" ORDER BY t.TimeIndex').fetchall();db.close()
 f=collections.defaultdict(dict);units={}
 for day,hour,minute,interval,key,name,unit,value in data:
  assert interval==10 and math.isfinite(value)
  slot=round(((day-1)*1440+hour*60+minute)/10)-1;identity=(name,(key or '').upper());f[slot][identity]=value;units[identity]=unit
 assert set(f)==set(range(1440)),('incomplete clock',len(f),days)
 return dict(f),units,days

def ledger(f,u):
 energy_names={'Lights Electricity Energy','Electric Equipment Electricity Energy','Cooling Coil Electricity Energy','Fan Electricity Energy','Water Heater Electricity Energy'}
 assert u['Electricity:Facility','']=='J'
 max_residual=max(abs(v['Electricity:Facility','']-sum(value for (name,key),value in v.items() if name in energy_names)) for v in f.values())
 assert max_residual<.001,('electric meter ledger',max_residual)
 return max_residual

def energy(f,start,end):return sum(f[i]['Electricity:Facility',''] for i in range(start,end))/3.6e6

def service(w,p,side,f):
 out={};devices=w['parameter_pack']['devices'];base=7*144;plan=p[side]
 # Program power is checked against the saved plan, not another generated fixture.
 max_program_residual=0.
 for d in devices:
  if not set(d['types'])&{'washer','dryer','dishwasher'}:continue
  key=('Electric Equipment Electricity Energy',d['asset_id'].upper())
  for slot in range(333):
   t=slot*10;task=next((x for x in plan['tasks'] if x['asset_id']==d['asset_id'] and x['start_min']<=t<x['end_min']),None)
   kw=(d['parameters'][task['kind']]['power_kw'] if 'washer' in d['types'] else d['parameters']['power_kw']) if task else 0
   max_program_residual=max(max_program_residual,abs(f[base+slot][key]-kw*1000*600))
 assert max_program_residual<.001,('program vs actual electricity',max_program_residual)
 out['program_meter_max_residual_J']=max_program_residual
 if w['assets']['water_heater']['present']:
  volume_key=('Water Use Equipment Total Volume','SHOWERS_V16');temp_key=('Water Use Equipment Mixed Water Temperature','SHOWERS_V16')
  draws=[v for i,v in f.items() if base<=i<base+288 and v[volume_key]>1e-10]
  delivered=sum(v[volume_key] for v in draws)*1000;minimum=min(v[temp_key] for v in draws);requested=sum(n['quantity'] for n in p['needs_A'] if n['kind']=='water_heater' and n['release_min']<2880)
  out['hot_water']={'requested_mixed_L_48h':requested,'delivered_mixed_L_48h':delivered,'minimum_timestep_mixed_C':minimum,'target_mixed_C':w['routine']['mixed_target_C'],'quantity_pass':abs(delivered-requested)<.001,'temperature_pass':minimum>=w['routine']['mixed_target_C']-.5,'scope':'timestep-average model mixing delivery; not observed showers or personal comfort'}
 if w['assets']['ac']['present']:
  rooms=sorted({d['room_id'] for d in devices if 'ac' in d['types']});checks=[]
  for room in rooms:
   temperatures=[f[base+i]['Zone Mean Air Temperature',room.upper()] for i in range(288) if any(c['kind']=='ac_setpoint' and c['asset_id'] in {d['asset_id'] for d in devices if d['room_id']==room} and c['start_min']<=i*10<c['end_min'] for c in plan['controls'])]
   if temperatures:checks.append({'room_id':room,'min_C':min(temperatures),'max_C':max(temperatures)})
  out['ac_room_air']=checks
  out['AC_comfort_pass']=None # Air temperature is not a validated personal-comfort judgment.
 evs=[d for d in devices if 'ev' in d['types']]
 if evs:
  d=evs[0];cfg=d['parameters'];soc=.85;trips=[];soc_at={};start=dt.date.fromisoformat(p['date'])-dt.timedelta(days=7)
  for i in range(1440):
   date=start+dt.timedelta(days=i//144);minute=(i%144)*10
   if date.weekday() in w['routine']['EV_trip_days'] and minute==w['routine']['EV_departure_min']:
    req=w['routine']['EV_daily_trip_kWh'];trips.append({'date':date.isoformat(),'minute':minute,'SOC_before':soc,'requested_kWh':req,'energy_shortfall_kWh':max(0.,req-soc*cfg['capacity_kwh'])});soc=max(0.,soc-req/cfg['capacity_kwh'])
   soc+=f[i]['Electric Equipment Electricity Energy',d['asset_id'].upper()]/3.6e6*cfg.get('efficiency',.92)/cfg['capacity_kwh']
   assert -.00001<=soc<=1.00001
   soc_at[i]=soc
  departures=[{'deadline_abs_min':n['departure_min'],'required_SOC':n['required_departure_soc'],'actual_SOC_before_departure':soc_at[base+n['departure_min']//10-1],'requirement_pass':soc_at[base+n['departure_min']//10-1]>=n['required_departure_soc']-1e-6} for n in p['needs_A'] if n['kind']=='ev'];out['EV']={'departure_requirements':departures,'method':'analytic SOC reconstructed from actual modeled EV meter and declared trip withdrawals; vehicle battery is not an EP storage object','trips_in_target48h':[x for x in trips if p['date']<=x['date']<(dt.date.fromisoformat(p['date'])+dt.timedelta(days=2)).isoformat()],'terminal_SOC_48h':soc_at[base+287],'terminal_SOC_service_tail':soc_at[base+332]}
 return out

def one(job):
 h,c,runs=job;hid=h['household_id'];i=c['round_index'];w=read(SOURCE/h['world_path']);pairpath=SOURCE/c['pair_path'];assert sha(pairpath)==c['pair_sha256'];p=read(pairpath)
 A,au,ad=frame(runs['A']);B,bu,bd=frame(runs['B']);origin=dt.date.fromisoformat(c['A']['start_date']);expected=[(j+1,(origin+dt.timedelta(days=j)).year,(origin+dt.timedelta(days=j)).month,(origin+dt.timedelta(days=j)).day,144) for j in range(10)]
 assert ad==bd==expected and au==bu
 decision=7*144+p['decision_abs_min']//10;worst=0.
 for t in range(decision):
  assert A[t].keys()==B[t].keys()
  worst=max(worst,max(abs(A[t][k]-B[t][k]) for k in A[t]))
 assert worst<1e-5,('actual predecision mismatch',hid,i,worst)
 meters={side:ledger(f,u) for side,f,u in [('A',A,au),('B',B,bu)]};services={side:service(w,p,side,f) for side,f in [('A',A),('B',B)]}
 base=7*144;event0=base+p['event_window_min'][0]//10;event1=base+p['event_window_min'][1]//10;scopes={'event':(event0,event1),'48h':(base,base+288),'48h_plus_service_tail':(base,base+333)}
 energies={name:{'A_kWh':energy(A,a,b),'B_kWh':energy(B,a,b),'A_minus_B_kWh':energy(A,a,b)-energy(B,a,b)} for name,(a,b) in scopes.items()}
 state_names={'Zone Mean Air Temperature','Zone Air Relative Humidity','Water Heater Tank Temperature'}
 pre={name+'|'+key:val for (name,key),val in A[decision-1].items() if name in state_names}
 terminal={}
 for label,slot in [('48h',base+287),('service_tail',base+332)]:terminal[label]={name+'|'+key:{'A':A[slot][name,key],'B':B[slot][name,key],'B_minus_A':B[slot][name,key]-A[slot][name,key]} for name,key in A[slot] if name in state_names}
 result={'schema':'eb.pilot50.actual_pair.v1','household_id':hid,'round_index':i,'date':c['date'],'source_pair_sha256':c['pair_sha256'],'world_sha256':h['world_sha256'],'actual_calendar_days':ad,'maximum_predecision_output_difference':worst,'meter_residual_J':meters,'predecision_state':pre,'electricity':energies,'services':services,'terminal_states':terminal,'SQL_bindings':runs,'technical_pass':True,'design_condition':p['design_condition'],'constraint_assessment':p['constraint_assessment'],'counterfactual_requested_controls_not_observed_execution':True,'comfort_calibrated':False,'human_answers':0}
 rp=ROOT/'readback'/hid/f'{i:02d}.json';save(rp,result)
 return {'household_id':hid,'round_index':i,'date':c['date'],'result_path':str(rp.relative_to(ROOT)),'result_sha256':sha(rp),'maximum_predecision_output_difference':worst,'maximum_meter_residual_J':max(meters.values()),'hot_water_temperature_failure':{s:services[s].get('hot_water',{}).get('temperature_pass') is False for s in ['A','B']}}
if __name__=='__main__':
 import sys
 assert sys.platform=='linux'
 sel=read(ROOT/'SELECTION50.json');runs={(r['household_id'],r['round_index'],r['arm']):r for r in read(ROOT/'CURRENT_EP_RESULTS.json')['records']};jobs=[(h,c,{a:runs[h['household_id'],c['round_index'],a] for a in ['A','B']}) for h in sel['records'] for c in h['rounds']]
 results=[];errors=[]
 with concurrent.futures.ProcessPoolExecutor(max_workers=16) as pool:
  fs={pool.submit(one,j):j for j in jobs}
  for f in concurrent.futures.as_completed(fs):
   try:results.append(f.result())
   except Exception as e:h,c,_=fs[f];errors.append({'household_id':h['household_id'],'round_index':c['round_index'],'error':repr(e)})
   
 results.sort(key=lambda r:(r['household_id'],r['round_index']))
 report={'households':50,'pairs_requested':500,'pairs_checked':len(results),'failures':errors,'calendar_exact':not errors,'maximum_predecision_output_difference':max((r['maximum_predecision_output_difference'] for r in results),default=None),'maximum_meter_residual_J':max((r['maximum_meter_residual_J'] for r in results),default=None),'hot_water_temperature_failure_counts':{s:sum(r['hot_water_temperature_failure'][s] for r in results) for s in ['A','B']},'records':results,'human_answers':0,'physical_calibration_complete':False}
 save(ROOT/'READBACK_REVIEW.json',report);print(json.dumps({k:v for k,v in report.items() if k!='records'},ensure_ascii=False),flush=True)
 if errors:sys.exit(2)
