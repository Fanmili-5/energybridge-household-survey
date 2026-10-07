"""Execute actual paired component tasks with stipulated operator/service state.
Only explicit metered enduses are labelled; unknown home loads are excluded,
never declared absent. Same pre-event IDF,weather,People/background and state
must match. Event results may be zero/negative and are never filtered out.
"""
import collections,concurrent.futures,copy,re,sqlite3,subprocess
from common import *
ENGINE=Path('/Applications/EnergyPlus-24-1-0/energyplus')
def compact(name,limits,parts):
 row=['Schedule:Compact',name,limits]
 for enddate,points in parts:
  row+=['Through:'+enddate,'For:AllDays','Interpolate:Average']
  for tm,v in points:row+=['Until:'+tm,v]
 return row
def input_rows(record,port,variant,operator):
 rows=parse(V10/record['service_IDF_path']);rows=[z for z in rows if z[0]!='RunPeriod'];rows.append(obj('RunPeriod',{'name':'same_history_single_eventJuly7','begin_month':7,'begin_day_of_month':1,'begin_year':2019,'end_month':7,'end_day_of_month':7,'end_year':2019,'day_of_week_for_start_day':'Monday','use_weather_file_daylight_saving_period':'No','treat_weather_as_actual':'No'}))
 rows += [['ScheduleTypeLimits','eb_fraction',0,1,'Continuous','Dimensionless'],['ScheduleTypeLimits','eb_temperature',0,100,'Continuous','Temperature'],['ScheduleTypeLimits','eb_activity',0,1000,'Continuous','ActivityLevel']]
 # Bind units from consuming object fields, never from numeric values.
 types={}
 for z in rows:
  if z[0] in ['WaterHeater:Mixed','ElectricEquipment']:
   fields=SCHEMA['properties'][z[0]]['legacy_idd']['fields']
   wanted=['setpoint_temperature_schedule_name','cold_water_supply_temperature_schedule_name'] if z[0]=='WaterHeater:Mixed' else ['schedule_name']
   for f in wanted:
    ii=fields.index(f)+1
    if ii<len(z) and z[ii]:types[z[ii]]='eb_temperature' if z[0]=='WaterHeater:Mixed' else 'eb_fraction'
 for z in rows:
  if z[0]=='Schedule:Constant' and z[1] in types:z[2]=types[z[1]]
 c=read(V10/record['service_world_path']);hid=record['household_id'];berth=next(b for b in c['world']['sleep_reference']['berths'] if b['member_id']==operator);rid=berth['room_id']
 # Same one-operator background in both interventions, a declared quiet
 # reference context; not an inferred usual household occupancy timetable.
 rows+=[compact('eb_operator_presence','eb_fraction',[('12/31',[('18:00',0),('24:00',1)])]),['Schedule:Constant','eb_activity120','eb_activity',120.],
  obj('People',{'name':hid+'_scenario_operator','zone_or_zonelist_or_space_or_spacelist_name':rid,'number_of_people_schedule_name':'eb_operator_presence','number_of_people_calculation_method':'People','number_of_people':1,
   'fraction_radiant':.3,'sensible_heat_fraction':'Autocalculate','activity_level_schedule_name':'eb_activity120','enable_ashrae_55_comfort_warnings':'No'})]
 name=port['instance_reference_ID'];sn=name+'_schedule'
 rows=[z for z in rows if not(z[0]=='Schedule:Constant' and z[1]==sn)]
 if port['kind']=='washer':
  times=[('18:50',0),('21:29',1),('24:00',0)] if variant=='baseline' else [('20:00',0),('22:39',1),('24:00',0)]
  rows.append(compact(sn,'eb_fraction',[('7/6',[('24:00',0)]),('7/7',times),('12/31',[('24:00',0)])]));variable='Electric Equipment Electricity Energy'
 else:
  next(z for z in rows if z[0]=='Timestep')[1]=12
  for z in rows:
   if z[0]=='WaterHeater:Mixed' and z[1]==name:
    fields=SCHEMA['properties']['WaterHeater:Mixed']['legacy_idd']['fields'];updates={'peak_use_flow_rate':.03/600,'use_flow_rate_fraction_schedule_name':'eb_draw30L','use_side_effectiveness':1.}
    for k,v in updates.items():
     ii=fields.index(k)+1
     while len(z)<=ii:z.append('')
     z[ii]=v
  points=[('24:00',55)] if variant=='baseline' else [('19:00',55),('20:00',30),('24:00',55)]
  rows.append(compact(sn,'eb_temperature',[('7/6',[('24:00',55)]),('7/7',points),('12/31',[('24:00',55)])]))
  rows.append(compact('eb_draw30L','eb_fraction',[('12/31',[('20:30',0),('20:40',1),('24:00',0)])]));variable='Water Heater Electricity Energy'
  rows += [['Output:Variable',name,n,'Timestep'] for n in ['Water Heater Use Side Outlet Temperature','Water Heater Use Side Mass Flow Rate','Water Heater Tank Temperature']]
  rows += [['Output:Variable',name,n,'Detailed'] for n in ['Water Heater Electricity Energy','Water Heater Heat Loss Energy','Water Heater Use Side Heat Transfer Energy','Water Heater Net Heat Transfer Energy','Water Heater Final Tank Temperature']]
 rows += [['Output:Variable',name,variable,'Timestep'],['Output:Variable','*','Zone Mean Air Temperature','Timestep']]
 return rows,variable
def run(task):
 record,port,variant,operator=task;hid=record['household_id'];name=port['instance_reference_ID'];folder=OUT/'event_runs'/(hid+'_'+port['kind']+'_'+variant);folder.mkdir(parents=True,exist_ok=True);rows,var=input_rows(record,port,variant,operator);idf=folder/'input.idf';idf.write_text('! Paired declared component event;not empirical home electricity or actor answer.\n'+dump(rows));runfolder=folder/'run';runfolder.mkdir(exist_ok=True)
 prior=read(OUT/'INITIAL_EVENT_RUN_INPUT_LOCK.json')['files'] if (OUT/'INITIAL_EVENT_RUN_INPUT_LOCK.json').exists() else {};rel=str(folder.relative_to(OUT));sqlpath=runfolder/'eplusout.sql'
 if rel in prior and prior[rel]['IDF_sha256']==sha(idf) and prior[rel]['SQL_sha256']==sha(sqlpath) and prior[rel]['engine_sha256']==sha(ENGINE) and prior[rel]['weather_sha256']==sha(record['weather']['path']):returncode=0
 else:
  r=subprocess.run([str(ENGINE),'-w',record['weather']['path'],'-d',str(runfolder),str(idf)],capture_output=True,text=True,timeout=300);(runfolder/'console.txt').write_text(r.stdout+'\n'+r.stderr);returncode=r.returncode
 err=(runfolder/'eplusout.err').read_text();sf=re.findall(r'\*\*\s*(?:Severe|Fatal)\s*\*\*([^\n]*)',err);assert returncode==0 and not sf,err
 db=sqlite3.connect(runfolder/'eplusout.sql');data=db.execute('SELECT d.KeyValue,d.Name,d.Units,d.ReportingFrequency,t.Month,t.Day,t.Hour,t.Minute,r.Value FROM ReportData r JOIN ReportDataDictionary d USING(ReportDataDictionaryIndex) JOIN Time t USING(TimeIndex) WHERE COALESCE(t.WarmupFlag,0)=0 ORDER BY d.Name,d.KeyValue,t.TimeIndex').fetchall();db.close();series=collections.defaultdict(list)
 for key,n,u,f,m,d,h,minute,v in data:series[key,n,u,f].append([m,d,h,minute,v])
 interval_minutes=5 if port['kind']=='water_heater' else 15
 energy=next(v for (k,n,u,f),v in series.items() if k==name.upper() and n==var and f=='Zone Timestep');final=[v for v in energy if v[:2]==[7,7]];assert len(final)==1440//interval_minutes
 event=[v for v in final if 19*60<v[2]*60+v[3]<=20*60];E=sum(v[-1] for v in final)/3.6e6;eventE=sum(v[-1] for v in event)/3.6e6
 if port['kind']=='washer':assert abs(E-.72)<1e-9
 service=None
 if port['kind']=='water_heater':
  temps=next(v for (k,n,u,f),v in series.items() if k==name.upper() and n=='Water Heater Use Side Outlet Temperature' and f=='Zone Timestep');flows=next(v for (k,n,u,f),v in series.items() if k==name.upper() and n=='Water Heater Use Side Mass Flow Rate' and f=='Zone Timestep');assert len(temps)==len(flows)
  drawn=[(t,f) for t,f in zip(temps,flows) if t[:2]==[7,7] and f[-1]>0];assert drawn
  mass=sum(f[-1]*(interval_minutes*60) for t,f in drawn);service={'draw_reference_m3':.03,'delivered_mass_kg_reported':mass,'timestep_minutes':interval_minutes,'draw_clock_boundary_aligned':True,'timestep_averaging_not_instantaneous_outlet_minimum':True,
   'min_draw_timestep_average_outlet_C':min(t[-1] for t,f in drawn),'requested_min_reference_outlet_C':40.,'timestep_average_service_threshold_met':min(t[-1] for t,f in drawn)>=40.}
 checkpoint=18*60 if port['kind']=='washer' else 19*60
 states=[{'key':k,'variable':n,'unit':u,'values':[v for v in vals if v[:2]==[7,7] and v[2]*60+v[3]<=checkpoint]} for (k,n,u,f),vals in series.items() if f=='Zone Timestep' and n in ['Zone Mean Air Temperature','Water Heater Tank Temperature',var]]
 meta={'household_id':hid,'kind':port['kind'],'instance_reference_ID':name,'variant':variant,'operator_reference_ID':operator,'meter_variable':var,
  'day_energy_kWh':E,'event19to20_kWh':eventE,'service':service,'pre_intervention_states':states,'matched_checkpoint_min':checkpoint,'warnings':re.findall(r'\*\*\s*Warning\s*\*\*([^\n]*)',err),'severe_fatal':0,
  'thermal_energy_balance_series':[{'variable':n,'unit':u,'frequency':f,'values':[v for v in vals if v[:2]==[7,7]]} for (k,n,u,f),vals in series.items() if k==name.upper() and f=='HVAC System Timestep' and n in ['Water Heater Electricity Energy','Water Heater Heat Loss Energy','Water Heater Use Side Heat Transfer Energy','Water Heater Net Heat Transfer Energy','Water Heater Final Tank Temperature']],
  'IDF_path':str(idf.relative_to(OUT)),'IDF_sha256':sha(idf),'SQL_path':str((runfolder/'eplusout.sql').relative_to(OUT)),'SQL_sha256':sha(runfolder/'eplusout.sql'),
  'weather_path':record['weather']['path'],'weather_sha256':record['weather']['sha256'],'engine_sha256':sha(ENGINE),'scope':'specific component meter only;other modeled ports excluded from reported task energy'}
 return meta
def main():
 guard();tasks=[];held=[]
 for r in read(V10/'SERVICE_PORT_BINDINGS.json')['records']:
  case=read(V10/r['service_world_path']);adult=case['world']['operator_context']['adult_reference_candidates']
  for p in case['service_model']['instantiated_reference_ports']:
   if p['kind'] not in ['washer','water_heater']:continue
   if not adult:held.append({'household_id':r['household_id'],'kind':p['kind'],'reason':'no_reference_adult;no_nonresident_assistance_invented'});continue
   tasks.extend((r,p,variant,adult[0]) for variant in ['baseline','shifted'])
 save(OUT/'EVENT_SELECTION.json',{'task_count':len(tasks)//2,'engine_runs':len(tasks),'held':held,'selection':'all eligible V10 wash/tank ports,not positive-response selection',
  'explicit_context':'operator grants permission and is present;one same quiet operator120W background;not observed diary or consent','water_service_reference':'30L nominal internal draw at20:30to20:40,40C timestep-average threshold;not actual shower/fixture or measured use',
  'thermal_background':'others unmodelled;not household absence assertion','intervention':'manual before-start wash delay or defer tank heating19to20;scope-only reference implementation'})
 results=[]
 with concurrent.futures.ThreadPoolExecutor(4) as pool:
  for i,r in enumerate(pool.map(run,tasks)):
   results.append(r)
   if (i+1)%50==0:print({'component_runs_finished':i+1,'planned':len(tasks)},flush=True)
 grouped=collections.defaultdict(dict)
 for r in results:grouped[r['household_id'],r['kind']][r['variant']]=r
 pairs=[]
 for (hid,kind),v in grouped.items():
  a,b=v['baseline'],v['shifted'];assert a['pre_intervention_states']==b['pre_intervention_states'],'pre_intervention_not_paired:'+hid
  pairs.append({'household_id':hid,'kind':kind,'event_energy_change_kWh_baseline_minus_shifted':a['event19to20_kWh']-b['event19to20_kWh'],
   'day_energy_change_kWh_baseline_minus_shifted':a['day_energy_kWh']-b['day_energy_kWh'],'pre_intervention_histories_verified_equal':True,'matched_checkpoint_min':a['matched_checkpoint_min'],
   'shifted_reference_service_threshold_met':b['service']['timestep_average_service_threshold_met'] if b['service'] else True,'not_actor_willingness_or_empirical_delivery':True})
 save(OUT/'EVENT_RESULTS.json',{'runs':results,'pairs':pairs,'held':held,'paired_case_count':len(pairs),'unique_households_with_tasks':len({r['household_id'] for r in pairs}),
  'all_results_retained_including_zero_negative_or_service_failures':True,'other_unknown_home_loads_not_assumed_zero':True,
  'operator_and_task_states_are_experiment_not_observed_source':True,'whole_household_energy_and_human_answers_not_admitted':True})
 print({'cases':len(pairs),'households':len({r['household_id'] for r in pairs}),'runs':len(results),'held':len(held),'positive_event_delta':sum(r['event_energy_change_kWh_baseline_minus_shifted']>1e-9 for r in pairs),'service_failures':sum(not r['shifted_reference_service_threshold_met'] for r in pairs)})
if __name__=='__main__':main()
