"""Exercise new Lasa native scalar U/SC reference and .86/.87 sensitivity.
Existing V8 geometry is held fixed; this is an empty-shell engineering test.
"""
import collections,concurrent.futures,copy,hashlib,json,math,re,sqlite3,subprocess,sys
from pathlib import Path
OUT=Path(__file__).resolve().parent.parent;BASE=OUT.parent;V7=BASE/'idf_joint_production_20261005';V8=BASE/'household_housing_evidence_20261006'
sys.path.insert(0,str(V7/'code'));sys.path.insert(0,str(V8/'code'))
import compile_reference_idfs as compiler
from mixed_sleep import choose
ENGINE=Path('/Applications/EnergyPlus-24-1-0/energyplus')
def read(p):return json.loads(p.read_text())
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def save(name,d):(OUT/name).write_text(json.dumps(d,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
def main():
 if (OUT/'PACKAGE_MANIFEST.json').exists():raise SystemExit('sealed')
 pp={p['slot_id']:p for p in read(V7/'HOUSEHOLDS1000_JOINT_GEOMETRY_CANDIDATE.json')['profiles']}
 existing=[r for r in read(V8/'REGIONAL_PILOT_RESULTS.json')['cases'] if r['model_key'].startswith('Low_Lasa_') and r['season']=='winter'];hid=max({r['household_id'] for r in existing},key=lambda h:(pp[h]['family']['resident_count'],h));existing=[r for r in existing if r['household_id']==hid]
 save('GLAZING_PILOT_SELECTION.json',{'household_id':hid,'criterion':'maximum resident count among already sealed V8 Tibet pilot profiles, before new outputs',
  'source_case_paths':[str(V8/r['case_path']) for r in existing],'seasons':['winter','summer'],'SC_reference_constants':[.87,.86],
  'coverage_engineering_test_not_population_sample_or_blind_holdout':True})
 planned=[];original=compiler.assemblies
 try:
  for case in existing:
   source=read(V8/case['case_path']);p=pp[hid];world=source['world'];key=case['model_key'];bundle=read(OUT/'assemblies'/(key+'.json'))
   for factor in [.87,.86]:
    a=copy.deepcopy(bundle);t=a['glazing_provenance'][0]
    for row in a['rows']:
     if row[0]=='WindowMaterial:SimpleGlazingSystem':row[3]=str(t['native_type_SC']*factor)
    compiler.assemblies=lambda a=a:a;rows,meta=compiler.model(world);sleep=choose(p,world,rows,.6,True)
    for season,month,weekday in [('winter',1,'Monday'),('summer',7,'Sunday')]:
     rr=copy.deepcopy(rows);period=next(r for r in rr if r[0]=='RunPeriod');period[2:8]=[str(month),'1','2007',str(month),'1','2007'];period[8]=weekday
     folder=OUT/'glazing_pilot'/(key+'__'+str(factor)+'__'+season);folder.mkdir(parents=True,exist_ok=True);path=folder/'input.idf';path.write_text('! Native scalar window reference; empty shell; not household ground truth.\n'+compiler.dump(rr))
     planned.append({'case_id':folder.name,'household_id':hid,'native_model_key':key,'SC_constant':factor,'season':season,'IDF_path':str(path),'IDF_sha256':sha(path),
       'geometry_source_case':str(V8/case['case_path']),'source_world_preserved':True,'weather':case['weather'],
       'constructive_mixed_sleep0_6m_witness':sleep['found'],'native_scalar_U_W_m2K':t['native_type_U_W_m2K'],'reference_SHGC':t['native_type_SC']*factor,
       'comparison_old_held_glazing_in_V8_not_overwritten':True,'N_H6_H7_q_preserved':True,
       'complete_household_IDF':False,'empirical_window_model_validated':False})
 finally:compiler.assemblies=original
 save('GLAZING_PILOT_BINDINGS.json',{'cases':planned,'runtime_planned':len(planned)})
 def run(c):
  path=Path(c['IDF_path']);folder=path.parent/'run';folder.mkdir(exist_ok=True)
  assert sha(Path(c['weather']['path']))==c['weather']['sha256']
  r=subprocess.run([str(ENGINE),'-w',c['weather']['path'],'-d',str(folder),str(path)],capture_output=True,text=True,timeout=180);(folder/'console.txt').write_text(r.stdout+'\n'+r.stderr)
  err=(folder/'eplusout.err').read_text();fatal=re.findall(r'\*\*\s*(?:Severe|Fatal)\s*\*\*([^\n]*)',err);warnings=re.findall(r'\*\*\s*Warning\s*\*\*([^\n]*)',err)
  assert r.returncode==0 and not fatal,err
  db=sqlite3.connect(folder/'eplusout.sql');data=db.execute('SELECT d.KeyValue,r.Value,t.Hour FROM ReportData r JOIN ReportDataDictionary d USING(ReportDataDictionaryIndex) JOIN Time t USING(TimeIndex) WHERE d.Name=? AND COALESCE(t.WarmupFlag,0)=0 ORDER BY d.KeyValue,t.TimeIndex',('Zone Mean Air Temperature',)).fetchall();db.close()
  by=collections.defaultdict(list)
  for n,v,h in data:by[n].append(v)
  assert all(len(v)==24 and all(math.isfinite(x) for x in v) for v in by.values())
  return {**c,'returncode':r.returncode,'severe_fatal':len(fatal),'warnings':warnings,'SQL_sha256':sha(folder/'eplusout.sql'),
    'hourly_zone_temperatures_C':dict(by),'engineering_run_not_energy_stock_or_occupancy_validation':True}
 with concurrent.futures.ThreadPoolExecutor(4) as pool:results=list(pool.map(run,planned))
 differences=[]
 for key in sorted({r['native_model_key'] for r in results}):
  for season in ['winter','summer']:
   a=next(r for r in results if r['native_model_key']==key and r['season']==season and r['SC_constant']==.87);b=next(r for r in results if r['native_model_key']==key and r['season']==season and r['SC_constant']==.86)
   differences.append({'model_key':key,'season':season,'max_abs_same_geometry_zone_hourly_temperature_difference_C':max(abs(x-y) for n in a['hourly_zone_temperatures_C'] for x,y in zip(a['hourly_zone_temperatures_C'][n],b['hourly_zone_temperatures_C'][n]))})
 report={'cases':results,'SC_constant_sensitivity':differences,'empty_shell_runs':len(results),'severe_fatal':sum(r['severe_fatal'] for r in results),
  'warning_entries':sum(len(r['warnings']) for r in results),'engine_sha256':sha(ENGINE),'new_household_full_energy_validated':False}
 save('GLAZING_PILOT_RESULTS.json',report);print(json.dumps({k:v for k,v in report.items() if k!='cases'},ensure_ascii=False))
if __name__=='__main__':main()
