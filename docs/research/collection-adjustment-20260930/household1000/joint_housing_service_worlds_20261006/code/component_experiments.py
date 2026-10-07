"""Paired washing-clock and ground-boundary experiments in executed worlds.
All action context here is experimentally stipulated, never surveyed consent.
"""
import collections,copy,math,re,sqlite3,subprocess,sys
from common import *
from service_ports import parse
from device_contract import clock_errors
from assemble_worlds import exposure
import compile_reference_idfs as compiler
ENGINE=Path('/Applications/EnergyPlus-24-1-0/energyplus')
def dump(rows):return '\n'.join(',\n  '.join(str(v) for v in r)+';' for r in rows)+'\n'
def schedule(name,start,interpolation):
 end=start+159
 def tm(v):return f'{int(v)//60:02d}:{int(v)%60:02d}'
 return ['Schedule:Compact',name,'wash_fraction','Through:12/31','For:AllDays','Interpolate:'+interpolation,'Until:'+tm(start),0.,'Until:'+tm(end),1.,'Until:24:00',0.]
def run(path,weather):
 folder=path.parent/'run';folder.mkdir(exist_ok=True);r=subprocess.run([str(ENGINE),'-w',weather,'-d',str(folder),str(path)],capture_output=True,text=True,timeout=300);(folder/'console.txt').write_text(r.stdout+'\n'+r.stderr)
 err=(folder/'eplusout.err').read_text();fatal=re.findall(r'\*\*\s*(?:Severe|Fatal)\s*\*\*([^\n]*)',err);assert r.returncode==0 and not fatal,err
 db=sqlite3.connect(folder/'eplusout.sql');data=db.execute('SELECT d.KeyValue,d.Name,d.Units,r.Value,t.Hour FROM ReportData r JOIN ReportDataDictionary d USING(ReportDataDictionaryIndex) JOIN Time t USING(TimeIndex) WHERE COALESCE(t.WarmupFlag,0)=0 ORDER BY d.Name,d.KeyValue,t.TimeIndex').fetchall();db.close();series=collections.defaultdict(list)
 for k,n,u,v,h in data:series[k,n,u].append((h,v))
 return series,{'IDF_sha256':sha(path),'SQL_sha256':sha(folder/'eplusout.sql'),'returncode':0,'severe_fatal':0,
  'warnings':re.findall(r'\*\*\s*Warning\s*\*\*([^\n]*)',err),'run_path':str(folder.relative_to(OUT))}
def main():
 guard();rr=read(OUT/'SERVICE_PORT_BINDINGS.json')['records'];selected=None
 for r in rr:
  case=read(OUT/r['service_world_path']);ports=case['service_model']['instantiated_reference_ports'];washer=next((p for p in ports if p['kind']=='washer'),None)
  if washer and case['world']['operator_context']['adult_reference_candidates']:selected=(r,case,washer);break
 assert selected;r,case,washer=selected;job={'release_min':18*60,'duration_min':159,'deadline_min':24*60};operation={'reference_operator_ID':case['world']['operator_context']['adult_reference_candidates'][0],
  'experiment_declares_manual_permission_and_presence_at_start':True,'observed_permission_or_willingness':False,'source_job_clock_observed':False}
 negatives=[]
 for name,start,present,permission,active in [('late',23*60,True,True,False),('no_operator',20*60,False,True,False),('no_permission',20*60,True,False,False),('active_cycle_cut',20*60,True,True,True)]:
  e=clock_errors(job,start,present,permission,active);negatives.append({'injection':name,'rejected':bool(e),'reasons':e})
 cycles=[]
 for name,start,interpolation in [('baseline',18*60+50,'Average'),('shifted',20*60,'Average'),('negative_default_No',18*60+50,'No')]:
  assert not clock_errors(job,start,True,True,False);rows=parse(OUT/r['service_IDF_path']);sn=washer['instance_reference_ID']+'_schedule';rows=[z for z in rows if not(z[0]=='Schedule:Constant' and z[1]==sn)];rows.append(['ScheduleTypeLimits','wash_fraction',0.,1.,'Continuous','Dimensionless']);rows.append(schedule(sn,start,interpolation))
  folder=OUT/'component_experiments'/name;folder.mkdir(parents=True,exist_ok=True);path=folder/'input.idf';path.write_text('! Declared reference wash-clock experiment.\n'+dump(rows));series,meta=run(path,r['weather']['path'])
  vals=series[washer['instance_reference_ID'].upper(),'Electric Equipment Electricity Energy','J'];assert len(vals)==24
  E=sum(v for h,v in vals)/3.6e6;event=sum(v for h,v in vals if h==20)/3.6e6
  cycles.append({'case':name,'start_min':start,'interpolation':interpolation,'wash_cycle_energy_kWh':E,'event19to20_energy_kWh':event,
    'relative_cycle_energy_error_vs_OEM_test':abs(E-.72)/.72,**meta})
 assert abs(cycles[0]['wash_cycle_energy_kWh']-.72)<1e-9 and abs(cycles[1]['wash_cycle_energy_kWh']-.72)<1e-9
 assert cycles[2]['relative_cycle_energy_error_vs_OEM_test']>.001,'default_schedule_sampling_should_fail_energy_oracle'
 save(OUT/'WASH_CLOCK_EXPERIMENT.json',{'household_id':r['household_id'],'operation_context':operation,'task':job,'cases':cycles,'negative_legality_controls':negatives,
  'event_reduction_kWh':cycles[0]['event19to20_energy_kWh']-cycles[1]['event19to20_energy_kWh'],
  'full_cycle_energy_not_reduced_by_shift':True,'constant_mean_power_kernel_not_measured_peak_or_wholehouse_energy':True,
  'source_cycle_reference':'sealedV9 OEM Miele WTD160 Chinese manual p82','schedule_authority':'EnergyPlus24.1 IO reference1.8.11.1.6,Average vsNo',
  'physical_execution_not_human_consent_or_behavior':True})
 if '--wash-only' in sys.argv:
  print(json.dumps({'wash_runs':3,'baseline_kWh':cycles[0]['wash_cycle_energy_kWh'],'shifted_kWh':cycles[1]['wash_cycle_energy_kWh'],'negative_defaultNo_energy_error':cycles[2]['relative_cycle_energy_error_vs_OEM_test']}));return
 # Ground sensitivity in two already instantiated one-storey reference worlds;
 # no household/source model selection based on sensitivity outputs.
 one=[r for r in rr if r['one_storey_roof_ground']];chosen=[min(one,key=lambda r:r['household_id']),max(one,key=lambda r:r['household_id'])]
 save(OUT/'GROUND_EXPERIMENT_SELECTION.json',{'household_IDs':[r['household_id'] for r in chosen],
  'criterion':'lexicographically first/last fixed one-storey profiles,not representative sample',
  'scenarios':['baseline','soil_k0_5','soil_k1_5','side_exposed','initial10C'],'summer_day_reference':True})
 ground=[];original=compiler.assemblies
 try:
  for r in chosen:
   c=read(OUT/r['world_path']);w=c['world'];a=read(c['source_bundle_path']);compiler.assemblies=lambda a=a:a;base,meta=compiler.model(w)
   results=[]
   for label,factor,side,initial in [('baseline',1.,False,20.),('soil_k0_5',.5,False,20.),('soil_k1_5',1.5,False,20.),('side_exposed',1.,True,20.),('initial10C',1.,False,10.)]:
    rows,b=exposure(base,w,w['stock_reference_features'],a,side,factor,initial);folder=OUT/'ground_experiments'/(r['household_id']+'_'+label);folder.mkdir(parents=True,exist_ok=True);path=folder/'input.idf';path.write_text('! Declared ground/boundary sensitivity,empty shell.\n'+dump(rows));series,metadata=run(path,r['weather']['path'])
    temperatures={key[0]:[v for h,v in vals] for key,vals in series.items() if key[1]=='Zone Mean Air Temperature'};assert all(len(v)==24 for v in temperatures.values());results.append({'scenario':label,'temperature_C_24h':temperatures,'boundary':b,**metadata})
   reference=results[0]['temperature_C_24h']
   for result in results:result['max_abs_zone_hourly_difference_from_baseline_C']=max(abs(a-b) for n in reference for a,b in zip(reference[n],result['temperature_C_24h'][n]))
   ground.append({'household_id':r['household_id'],'cases':results})
 finally:compiler.assemblies=original
 save(OUT/'GROUND_SENSITIVITY.json',{'worlds':ground,'runs':sum(len(r['cases']) for r in ground),'empirical_soil_ground_water_or_house_calibration':False,
  'scenario_choices_are_design_not_confidence_intervals':True,'official_Kiva_solver_validation_not_validation_of_our_parameters':True})
 print(json.dumps({'wash_runs':3,'baseline_kWh':cycles[0]['wash_cycle_energy_kWh'],'shifted_kWh':cycles[1]['wash_cycle_energy_kWh'],
  'defaultNo_energy_error':cycles[2]['relative_cycle_energy_error_vs_OEM_test'],'ground_runs':10},ensure_ascii=False))
if __name__=='__main__':main()
