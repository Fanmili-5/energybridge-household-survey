"""Run every unique (partial-service IDF,weather) input, with scoped readbacks.
No absent model port is interpreted as household zero consumption.
"""
import collections,concurrent.futures,math,re,sqlite3,subprocess
from common import *
ENGINE=Path('/Applications/EnergyPlus-24-1-0/energyplus')
def main():
 guard();body=read(OUT/'SERVICE_PORT_BINDINGS.json');records=body['records'];groups=collections.defaultdict(list)
 for r in records:
  assert sha(OUT/r['service_IDF_path'])==r['service_IDF_sha256'] and sha(r['weather']['path'])==r['weather']['sha256']
  groups[r['service_IDF_sha256']+'__'+r['weather']['sha256']].append(r)
 (OUT/'runs').mkdir(exist_ok=True);prior={r['group_key']:r for r in read(OUT/'JOINT_RUNTIME_RESULTS.json')['unique_runs']} if (OUT/'JOINT_RUNTIME_RESULTS.json').exists() else {}
 def run(item):
  key,refs=item;r=refs[0];folder=OUT/'runs'/key[:24];folder.mkdir(exist_ok=True);sql=folder/'eplusout.sql';old=prior.get(key)
  if old and old['engine_sha256']==sha(ENGINE) and sql.exists() and old['SQL_sha256']==sha(sql):return old
  result=subprocess.run([str(ENGINE),'-w',r['weather']['path'],'-d',str(folder),str(OUT/r['service_IDF_path'])],capture_output=True,text=True,timeout=300)
  (folder/'console.txt').write_text(result.stdout+'\n'+result.stderr);err=(folder/'eplusout.err').read_text() if (folder/'eplusout.err').exists() else '';fatal=re.findall(r'\*\*\s*(?:Severe|Fatal)\s*\*([^\n]*)',err);warnings=re.findall(r'\*\*\s*Warning\s*\*\*([^\n]*)',err)
  if result.returncode or fatal:return {'group_key':key,'household_IDs':[x['household_id'] for x in refs],'returncode':result.returncode,'fatal_severe':fatal,'warnings':warnings,'failed':True,'error_path':str(folder/'eplusout.err')}
  db=sqlite3.connect(sql);data=db.execute('SELECT d.KeyValue,d.Name,d.Units,r.Value,t.Hour,t.Minute FROM ReportData r JOIN ReportDataDictionary d USING(ReportDataDictionaryIndex) JOIN Time t USING(TimeIndex) WHERE COALESCE(t.WarmupFlag,0)=0 ORDER BY d.KeyValue,d.Name,t.TimeIndex').fetchall();db.close();series=collections.defaultdict(list)
  for keyname,name,unit,v,h,m in data:series[keyname,name,unit].append(v)
  temperatures={k[0]:v for k,v in series.items() if k[1]=='Zone Mean Air Temperature'};assert temperatures and all(len(v)==24 and all(math.isfinite(x) for x in v) for v in temperatures.values())
  case=read(OUT/r['service_world_path']);ports=case['service_model']['instantiated_reference_ports'];enduses=[];total=0.
  for p in ports:
   variable='Water Heater Electricity Energy' if p['kind']=='water_heater' else 'Electric Equipment Electricity Energy';vv=series[p['instance_reference_ID'].upper(),variable,'J'];assert len(vv)==24
   E=sum(vv)/3.6e6;assert math.isfinite(E) and E>=0
   if p['kind']=='refrigerator':assert abs(E-.65)<1e-9,'label_mean_daily_energy_readback'
   if p['kind']=='washer':assert abs(E)<1e-10,'idle_reference_washer_not_inferred_daily_task'
   enduses.append({'instance_reference_ID':p['instance_reference_ID'],'kind':p['kind'],'energy_kWh':E});total+=E
  facility=next((sum(v)/3.6e6 for k,v in series.items() if k[1]=='Electricity:Facility'),None)
  if ports:assert facility is not None and abs(total-facility)<1e-8,'partial_reference_meter_partition'
  else:assert facility is None,'no_models_does_not_emit_false_household_zero_meter'
  return {'group_key':key,'household_IDs':[x['household_id'] for x in refs],'source_service_IDF':r['service_IDF_path'],'source_IDF_sha256':r['service_IDF_sha256'],
    'weather_path':r['weather']['path'],'weather_sha256':r['weather']['sha256'],'engine_sha256':sha(ENGINE),'returncode':0,'fatal_severe':[],
    'warnings':warnings,'run_path':str(folder.relative_to(OUT)),'SQL_sha256':sha(sql),'zone_temperature_24h_C':temperatures,
    'covered_enduse_energy_kWh':enduses,'covered_port_electricity_kWh':facility,
    'not_total_household_electricity_or_empirical_comfort':True,'failed':False}
 results=[]
 with concurrent.futures.ThreadPoolExecutor(4) as pool:
  for i,r in enumerate(pool.map(run,groups.items())):
   results.append(r)
   if (i+1)%100==0:print({'unique_runs_finished':i+1,'planned':len(groups),'failed':sum(r['failed'] for r in results)},flush=True)
 summary={'households_covered':sum(len(r['household_IDs']) for r in results),'unique_inputs_run':len(results),'unique_run_failures':sum(r['failed'] for r in results),
   'severe_fatal_count':sum(len(r['fatal_severe']) for r in results),'warning_entries':sum(len(r['warnings']) for r in results),
   'warning_types':dict(collections.Counter(w for r in results for w in r['warnings'])),
   'reference_ports_daily_meter_partition_verified':sum(bool(r.get('covered_enduse_energy_kWh')) for r in results),
   'scope':'joint geometry+facility rights+source parameters+exposure with partial reference device inventory;no People/HVAC/fullwholehome claims',
   'complete_household_IDFs':0,'human_answers':0,'empirical_household_energy_calibrated':False}
 save(OUT/'JOINT_RUNTIME_RESULTS.json',{'unique_runs':results,'summary':summary});print(json.dumps(summary,ensure_ascii=False))
 assert not summary['unique_run_failures'] and summary['households_covered']==1000
if __name__=='__main__':main()
