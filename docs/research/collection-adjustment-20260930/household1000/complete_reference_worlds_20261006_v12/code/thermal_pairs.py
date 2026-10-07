"""Same-state scoped thermal-demand counterfactuals with manual-adult gate.
No thermal kWh is labelled electricity or humanwillingness. All fixed1000
cases retained,including noadult/zero/negative/servicefailure scenarios.
"""
import collections,concurrent.futures,re,sqlite3,subprocess
from common import *
ENGINE=Path('/Applications/EnergyPlus-24-1-0/energyplus')
FAMILIES={}
def build(r):
 hid=r['household_id'];family=FAMILIES[hid];adult=[m['member_id'] for m in family['members'] if m['age_years']>=18];z=parse(OUT/r['IDF_path']);targets=[c['room_id'] for c in r['components'] if c['energy_scope_bucket']=='target_private_reference'];enabled=bool(adult);assert targets
 if enabled:
  z += [['Schedule:Compact','v12_private_event_cool28','eb_occ_temperature','Through:7/19','For:AllDays','Until:24:00',26,'Through:7/20','For:AllDays','Until:19:00',26,'Until:20:00',28,'Until:24:00',26,'Through:12/31','For:AllDays','Until:24:00',26]]
  fs=SCHEMA['properties']['ThermostatSetpoint:DualSetpoint']['legacy_idd']['fields'];idx=fs.index('cooling_setpoint_temperature_schedule_name')+1
  for row in z:
   if row[0]=='ThermostatSetpoint:DualSetpoint' and row[1] in [rid+'_dual' for rid in targets]:row[idx]='v12_private_event_cool28'
 p=OUT/'thermal_shifted_idfs'/(hid+'.idf');p.parent.mkdir(exist_ok=True);p.write_text('! Private-zone coolingbound28C instead26C19to20;manual gate,calorimeter only.\n'+dump(z));return {'household_id':hid,'IDF_path':str(p.relative_to(OUT)),'IDF_sha256':sha(p),'weather':r['weather'],'enabled':enabled,'operator_member_id':adult[0] if enabled else None,'private_reference_rooms':targets,'variant':'shifted','no_adult_shift_is_disabled_not_household_added':not enabled}
def sql_read(p,targets):
 db=sqlite3.connect(p);a=db.execute('SELECT d.KeyValue,d.Name,t.TimeIndex,t.Month,t.Day,t.Hour,t.Minute,r.Value FROM ReportData r JOIN ReportDataDictionary d USING(ReportDataDictionaryIndex) JOIN Time t USING(TimeIndex) WHERE COALESCE(t.WarmupFlag,0)=0 ORDER BY t.TimeIndex').fetchall();db.close();s=collections.defaultdict(dict)
 for k,n,i,m,d,h,mi,v in a:s[n,k][i]=[m,d,h,mi,v]
 rows={str((n,k)):[v for i,v in d.items() if v[:2]==[7,20] and v[2]*60+v[3]<=1140] for (n,k),d in s.items() if n in ['Zone Mean Air Temperature','Zone Air Relative Humidity','Zone People Occupant Count','Zone Ideal Loads Supply Air Total Cooling Energy','Zone Ideal Loads Supply Air Total Heating Energy']};h=hashlib.sha256(json.dumps(rows,sort_keys=True,separators=(',',':')).encode()).hexdigest();cool=sum(v[-1] for (n,k),d in s.items() if n=='Zone Ideal Loads Supply Air Total Cooling Energy' for v in d.values() if v[:2]==[7,20] and 1140<v[2]*60+v[3]<=1200)/3.6e6;heat=sum(v[-1] for (n,k),d in s.items() if n=='Zone Ideal Loads Supply Air Total Heating Energy' for v in d.values() if v[:2]==[7,20] and 1140<v[2]*60+v[3]<=1200)/3.6e6;temp=[v[-1] for (n,k),d in s.items() if n=='Zone Mean Air Temperature' and k in [t.upper() for t in targets] for v in d.values() if v[:2]==[7,20] and 1140<v[2]*60+v[3]<=1200];assert temp
 return {'pre_event_allzone_state_digest':h,'event_whole_dwelling_cooling_kWh_thermal':cool,'event_whole_dwelling_heating_kWh_thermal':heat,'private_event_max_air_C':max(temp),'private_event_min_air_C':min(temp),'eventday_scope':'whole modeled dwelling supply loads;not ownedHVAC electricity or fullcomfort','instantaneous_air_temperature_or_operative_temperature_not_claimed':True}
def run(r):
 folder=OUT/'thermal_shifted_runs'/r['household_id'];folder.mkdir(parents=True,exist_ok=True);x=subprocess.run([str(ENGINE),'-w',r['weather']['path'],'-d',str(folder),str(OUT/r['IDF_path'])],capture_output=True,text=True,timeout=300);(folder/'console.txt').write_text(x.stdout+'\n'+x.stderr);err=(folder/'eplusout.err').read_text();bad=re.findall(r'\*\*\s*(?:Severe|Fatal)\s*\*\*([^\n]*)',err);d={**r,'returncode':x.returncode,'severe_fatal':bad,'warnings':re.findall(r'\*\*\s*Warning\s*\*\*([^\n]*)',err),'engine_sha256':sha(ENGINE)}
 if bad or x.returncode:return d
 p=folder/'eplusout.sql';d.update({'SQL_path':str(p.relative_to(OUT)),'SQL_sha256':sha(p),'weather_sha256':sha(r['weather']['path']),**sql_read(p,r['private_reference_rooms'])});return d
def main():
 guard();FAMILIES.update({x['slot_id']:x['family'] for x in read(V7/'HOUSEHOLDS1000_JOINT_GEOMETRY_CANDIDATE.json')['profiles']});models=read(OUT/'BACKGROUND_MODEL_BINDINGS1000.json')['records'];tasks=[build(r) for r in models];save(OUT/'THERMAL_PAIR_BINDINGS1000.json',{'records':tasks,'manual_enabled':sum(r['enabled'] for r in tasks),'no_adult_gate_disabled':sum(not r['enabled'] for r in tasks),'temperature_action_is_declared_idealboundary_not_actual_hardware':True})
 selected=tasks[:2] if '--first2' in sys.argv else tasks;results=[]
 with concurrent.futures.ThreadPoolExecutor(4) as pool:
  for i,r in enumerate(pool.map(run,selected)):
   results.append(r)
   if (i+1)%100==0:print({'thermal_shifted_completed':i+1,'planned':len(selected)},flush=True)
 baseline={r['household_id']:r for r in read(OUT/('BACKGROUND_FIRST2.json' if '--first2' in sys.argv else 'BACKGROUND_RUNTIME1000.json'))['runs']};pairs=[]
 for b in results:
  a=baseline[b['household_id']]
  if b['severe_fatal'] or b['returncode'] or a['severe_fatal'] or a['returncode']:continue
  aa=sql_read(OUT/a['SQL_path'],b['private_reference_rooms']);assert aa['pre_event_allzone_state_digest']==b['pre_event_allzone_state_digest'],'unpairedthermalstate:'+b['household_id'];delta=aa['event_whole_dwelling_cooling_kWh_thermal']-b['event_whole_dwelling_cooling_kWh_thermal'];assert b['private_event_max_air_C']<=28.5
  if not b['enabled']:assert abs(delta)<1e-9
  pairs.append({'household_id':b['household_id'],'manual_gate_enabled':b['enabled'],'pre_event_same_state':True,'event_cooling_demand_change_kWh_thermal':delta,'event_electricity_change_kWh':None,'air_temperature_reference_threshold_C':28.5,'reference_air_service_met':b['private_event_max_air_C']<=28.5,'actual_comfort_or_acceptance':None,'zero_negative_and_disabled_case_retained':True})
 save(OUT/('THERMAL_FIRST2.json' if '--first2' in sys.argv else 'THERMAL_PAIR_RESULTS1000.json'),{'runs':results,'pairs':pairs,'paired_scope':'twoJulytestdays,samegeometry/People/lights/plug/airflow/idealboundary history,privatecooling26to28 at19to20','thermal_demand_never_relabelled_as_HVAC_electricity':True,'failures':[r for r in results if r['severe_fatal'] or r['returncode']],'all_fixed_roles_retained':True});print({'runs':len(results),'pairs':len(pairs),'failures':len(results)-len(pairs)},flush=True)
if __name__=='__main__':main()
