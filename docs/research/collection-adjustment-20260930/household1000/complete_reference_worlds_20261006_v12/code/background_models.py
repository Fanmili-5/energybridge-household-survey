"""Whole-dwelling thermal/lighting/aggregate-plug reference,not realwholebill.
Replace native uniform gain references using published residential densities;
never layer these total plug loads on top of named appliance ports. IdealLoads
is a thermal calorimeter,not electrically identified HVAC. Shared electricity
is an unallocated bucket,not area shares silently interpreted as meter shares.
"""
import collections,concurrent.futures,re,sqlite3,subprocess
from common import *
ENGINE=Path('/Applications/EnergyPlus-24-1-0/energyplus')
WORLD_BINDINGS={}
def compile_model(record):
 hid=record['household_id'];world=read(V10/WORLD_BINDINGS[hid]['service_world_path'])['world'];rows=parse(V11/record['IDF_path'])
 removed=[z for z in rows if z[0] in ['ElectricEquipment','WaterHeater:Mixed','ZoneVentilation:DesignFlowRate','Output:Variable','Output:Meter','RunPeriod']];rows=[z for z in rows if z not in removed]
 for z in rows:
  if z[0]=='Building':z[SCHEMA['properties']['Building']['legacy_idd']['fields'].index('maximum_number_of_warmup_days')+1]=100
  if z[0]=='People':z[SCHEMA['properties']['People']['legacy_idd']['fields'].index('number_of_people_schedule_name')+1]='v12_evening'
 rows += [obj('RunPeriod',{'name':'controlled_July19_20','begin_month':7,'begin_day_of_month':19,'begin_year':2019,'end_month':7,'end_day_of_month':20,'end_year':2019,'day_of_week_for_start_day':'Friday','treat_weather_as_actual':'No'}),
  ['Schedule:Compact','v12_evening','eb_occ_fraction','Through:12/31','For:AllDays','Interpolate:Average','Until:18:00',0,'Until:22:00',1,'Until:24:00',0],
  ['ScheduleTypeLimits','v12_controltype',0,4,'Discrete','Control'],['ScheduleTypeLimits','v12_percent',0,100,'Continuous','Percent'],
  ['Schedule:Constant','v12_heat18','eb_occ_temperature',18],['Schedule:Constant','v12_cool26','eb_occ_temperature',26],['Schedule:Constant','v12_thermotype4','v12_controltype',4],
  ['Schedule:Constant','v12_humid30','v12_percent',30],['Schedule:Constant','v12_humid60','v12_percent',60],
  obj('OutputControl:Files',{'output_eso':'No','output_mtr':'No','output_csv':'No'})]
 components=[];rooms={r['room_id']:r for r in world['rooms']};zones=[z for z in rows if z[0]=='Zone'];assert len(zones)==len(rooms)
 for z in zones:
  rid=z[1];r=rooms[rid];field=z[SCHEMA['properties']['Zone']['legacy_idd']['fields'].index('floor_area')+1];area=r['thermal_reference_area_m2'] if field.lower()=='autocalculate' else float(field);assert area>0
  lightdensity=1.8 if r['census_room_class']=='corridor' else 4.2;equipdensity=5. if r['census_room_class']=='kitchen' else 2.;lightname=rid+'_published_reference_lights';equipname=rid+'_published_aggregate_plugs';hvac=rid+'_ideal_calorimeter'
  rows += [obj('Lights',{'name':lightname,'zone_or_zonelist_or_space_or_spacelist_name':rid,'schedule_name':'v12_evening','design_level_calculation_method':'LightingLevel','lighting_level':area*lightdensity,'return_air_fraction':0,'fraction_radiant':.4,'fraction_visible':.2,'fraction_replaceable':1,'end_use_subcategory':'published_residential_density_reference'}),
   obj('ElectricEquipment',{'name':equipname,'zone_or_zonelist_or_space_or_spacelist_name':rid,'schedule_name':'v12_evening','design_level_calculation_method':'EquipmentLevel','design_level':area*equipdensity,'fraction_latent':0,'fraction_radiant':.3,'fraction_lost':0,'end_use_subcategory':'aggregate_plugs_includes_unknown_appliances_not_added_twice'}),
   obj('ZoneInfiltration:DesignFlowRate',{'name':rid+'_published1ACH_reference','zone_or_zonelist_or_space_or_spacelist_name':rid,'schedule_name':'eb_allhome','design_flow_rate_calculation_method':'AirChanges/Hour','air_changes_per_hour':1,'constant_term_coefficient':1,'temperature_term_coefficient':0,'velocity_term_coefficient':0,'velocity_squared_term_coefficient':0}),
   obj('ThermostatSetpoint:DualSetpoint',{'name':rid+'_dual','heating_setpoint_temperature_schedule_name':'v12_heat18','cooling_setpoint_temperature_schedule_name':'v12_cool26'}),
   obj('ZoneControl:Thermostat',{'name':rid+'_thermo','zone_or_zonelist_name':rid,'control_type_schedule_name':'v12_thermotype4','control_1_object_type':'ThermostatSetpoint:DualSetpoint','control_1_name':rid+'_dual'}),
   obj('ZoneControl:Humidistat',{'name':rid+'_humidistat','zone_name':rid,'humidifying_relative_humidity_setpoint_schedule_name':'v12_humid30','dehumidifying_relative_humidity_setpoint_schedule_name':'v12_humid60'}),
   obj('ZoneHVAC:IdealLoadsAirSystem',{'name':hvac,'availability_schedule_name':'eb_allhome','zone_supply_air_node_name':rid+'_supply','maximum_heating_supply_air_temperature':50,'minimum_cooling_supply_air_temperature':13,'maximum_heating_supply_air_humidity_ratio':.015,'minimum_cooling_supply_air_humidity_ratio':.007,'heating_limit':'NoLimit','cooling_limit':'NoLimit','dehumidification_control_type':'Humidistat','humidification_control_type':'Humidistat','outdoor_air_economizer_type':'NoEconomizer','heat_recovery_type':'None'}),
   ['ZoneHVAC:EquipmentList',rid+'_equipment_list','SequentialLoad','ZoneHVAC:IdealLoadsAirSystem',hvac,1,1],
   obj('ZoneHVAC:EquipmentConnections',{'zone_name':rid,'zone_conditioning_equipment_list_name':rid+'_equipment_list','zone_air_inlet_node_or_nodelist_name':rid+'_supply','zone_air_node_name':rid+'_air','zone_return_air_node_or_nodelist_name':rid+'_return'})]
  users=r['using_household_ids'];bucket='target_private_reference' if users==[hid] else 'auxiliary_private_reference' if len(users)==1 else 'shared_unallocated_reference'
  components.append({'room_id':rid,'input_floor_area_m2':area,'area_metric':'declared thermal centreline floor reference;not H6gross or furniture usablearea','lightdensity_W_m2':lightdensity,'aggregate_plug_density_W_m2':equipdensity,'Light_name':lightname,'aggregate_plug_name':equipname,'ideal_conditioner_name':hvac,'reference_using_household_ids':users,'energy_scope_bucket':bucket,'actual_meter_or_shared_allocation_identified':False,'expected_daily_light_kWh':area*lightdensity*4/1000,'expected_daily_aggregate_plug_kWh':area*equipdensity*4/1000})
 rows += [['Output:Variable','*',n,'Timestep'] for n in ['Lights Electricity Energy','Electric Equipment Electricity Energy','Zone People Occupant Count','Zone Mean Air Temperature','Zone Air Relative Humidity','Zone Ideal Loads Supply Air Total Cooling Energy','Zone Ideal Loads Supply Air Total Heating Energy']]+[['Output:Meter','Electricity:Facility','Timestep']]
 folder=OUT/'background_idfs';folder.mkdir(exist_ok=True);idf=folder/(hid+'.idf');idf.write_text('! Defined whole-dwelling thermal/light/aggregate-plug test;not complete observed home inventory or energybill.\n'+dump(rows))
 return {'household_id':hid,'IDF_path':str(idf.relative_to(OUT)),'IDF_sha256':sha(idf),'weather':record['weather'],'source_model_key':record['source_model_key'],'N_frozen':record['N_conserved'],'components':components,'specific_appliance_objects_removed':sum(z[0] in ['ElectricEquipment','WaterHeater:Mixed'] for z in removed),
  'aggregate_named_appliance_double_count_prevented':True,'all_generated_rooms_background_and_thermal_scope_closed':True,'published_density_source':'Ding_Zhou2020 PDFp6Table1 Wuhanresidentialreference,notChina2020stockdistribution','population_density2m2_person_not_copied':True,
  'infiltration1ACH_source_prototype_not_measured_or_ventilationcompliance':True,'presence18to22_source_is_stipulated_not_diary':True,'temperature18_26_source_values_but24h_idealavailability_is_experiment_not_paperseasonalclock':True,
  'humidity30_60_andthermalgainfractions_are_design':True,'calorimeter_does_not_assert_actual_owned_AC_or_unlimited_hardware':True,'heat_to_electricity_COP_conversion':None,'gas_otherfuel_DHW_lightingfixturemechanics_or_actual_inventory_calibrated':False,'complete_actual_wholehome_IDF':False,'frozen_old_source_ports_linked_not_lost':str((V10/'SERVICE_PORT_BINDINGS.json').relative_to(BASE))}
def run(r):
 folder=OUT/'background_runs'/r['household_id'];folder.mkdir(parents=True,exist_ok=True);p=OUT/r['IDF_path'];x=subprocess.run([str(ENGINE),'-w',r['weather']['path'],'-d',str(folder),str(p)],capture_output=True,text=True,timeout=300);(folder/'console.txt').write_text(x.stdout+'\n'+x.stderr);err=(folder/'eplusout.err').read_text();bad=re.findall(r'\*\*\s*(?:Severe|Fatal)\s*\*\*([^\n]*)',err);res={'household_id':r['household_id'],'returncode':x.returncode,'severe_fatal':bad,'warnings':re.findall(r'\*\*\s*Warning\s*\*\*([^\n]*)',err),'IDF_path':r['IDF_path'],'IDF_sha256':sha(p),'weather':r['weather'],'engine_sha256':sha(ENGINE)}
 if bad or x.returncode:return res
 sql=folder/'eplusout.sql';db=sqlite3.connect(sql);data=db.execute('SELECT d.KeyValue,d.Name,t.Month,t.Day,t.TimeIndex,r.Value FROM ReportData r JOIN ReportDataDictionary d USING(ReportDataDictionaryIndex) JOIN Time t USING(TimeIndex) WHERE COALESCE(t.WarmupFlag,0)=0 AND t.Day=20 AND t.Month=7').fetchall();meter=db.execute('SELECT sum(r.VariableValue) FROM ReportMeterData r JOIN ReportMeterDataDictionary d USING(ReportMeterDataDictionaryIndex) JOIN Time t USING(TimeIndex) WHERE d.VariableName="Electricity:Facility" AND COALESCE(t.WarmupFlag,0)=0 AND t.Day=20 AND t.Month=7').fetchone()[0];db.close();sums=collections.defaultdict(float);counts=collections.defaultdict(float);ranges=collections.defaultdict(list)
 for key,n,m,d,i,v in data:
  sums[n,key]+=v
  if n=='Zone People Occupant Count':counts[i]+=v
  if n in ['Zone Mean Air Temperature','Zone Air Relative Humidity']:ranges[n].append(v)
 split=collections.defaultdict(float);expected=0.;actual=0.
 for c in r['components']:
  l=sums['Lights Electricity Energy',c['Light_name'].upper()]/3.6e6;e=sums['Electric Equipment Electricity Energy',c['aggregate_plug_name'].upper()]/3.6e6;assert abs(l-c['expected_daily_light_kWh'])<1e-8 and abs(e-c['expected_daily_aggregate_plug_kWh'])<1e-8;actual+=l+e;expected+=c['expected_daily_light_kWh']+c['expected_daily_aggregate_plug_kWh'];split[c['energy_scope_bucket']]+=l+e
 assert abs(meter/3.6e6-actual)<1e-8 and abs(max(counts.values())-r['N_frozen'])<1e-9 and all(min(abs(x),abs(x-r['N_frozen']))<1e-9 for x in counts.values());res.update({'SQL_path':str(sql.relative_to(OUT)),'SQL_sha256':sha(sql),'modeled_light_plus_aggregate_plug_kWh':actual,'facility_electricity_kWh':meter/3.6e6,'source_scope_buckets_kWh':dict(split),'heat_demand_cooling_kWh_thermal':sum(v for (n,k),v in sums.items() if n=='Zone Ideal Loads Supply Air Total Cooling Energy')/3.6e6,'heat_demand_heating_kWh_thermal':sum(v for (n,k),v in sums.items() if n=='Zone Ideal Loads Supply Air Total Heating Energy')/3.6e6,'N_present_in_stipulated_window':max(counts.values()),'reported_ranges':{k:[min(v),max(v)] for k,v in ranges.items()},'actual_wholehome_bill_or_HVAC_electricity':None});return res
def main():
 guard();WORLD_BINDINGS.update({r['household_id']:r for r in read(V10/'SERVICE_PORT_BINDINGS.json')['records']});records=read(V11/'OCCUPIED_REFERENCE_BINDINGS1000.json')['records'];models=[compile_model(r) for r in records];save(OUT/'BACKGROUND_MODEL_BINDINGS1000.json',{'records':models,'whole_dwelling_reference_scope_models':len(models),'actual_hardware_wholehome_IDFs':0,'source_room_nativeuniformgains_not_transported':True,'unknown_meter_sharing_not_area_equated':True})
 selected=models[:2] if '--first2' in sys.argv else models;result=[]
 with concurrent.futures.ThreadPoolExecutor(4) as pool:
  for i,r in enumerate(pool.map(run,selected)):
   result.append(r)
   if (i+1)%100==0:print({'background_completed':i+1,'planned':len(selected)},flush=True)
 save(OUT/('BACKGROUND_FIRST2.json' if '--first2' in sys.argv else 'BACKGROUND_RUNTIME1000.json'),{'runs':result,'inputs_run':len(result),'failures':[r for r in result if r['severe_fatal'] or r['returncode']],'uniform_model_scope_not_equal_actual_household_completeness':True});print({'run':len(result),'failures':sum(bool(r['severe_fatal'] or r['returncode']) for r in result),'warnings':sum(len(r['warnings']) for r in result)},flush=True)
if __name__=='__main__':main()
