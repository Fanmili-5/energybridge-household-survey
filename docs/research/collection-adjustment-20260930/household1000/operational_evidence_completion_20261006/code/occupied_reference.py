"""Conserve the frozen roster in a declared, occupied thermal reference.
Read actual bedroom OCCUPANT_GAINS, not ROOM_TYPE_DATA defaults or density.
Fresh-air requirements become an explicitly imposed scenario, not measured
infiltration. Neither this schedule nor the prototype physiology is a diary.
"""
import collections,concurrent.futures,re,sqlite3,subprocess
from common import *
from access_parser_c import AccessParser
ENGINE=Path('/Applications/EnergyPlus-24-1-0/energyplus')
def table(db,name):
 t=db.parse_table(name);return [dict(zip(t,v)) for v in zip(*t.values())]
def source(item):
 assert sha(item['source_path'])==item['source_sha256'];db=AccessParser(item['source_path'])
 rooms={r['ID']:r for r in table(db,'ROOM')};types={r['ID']:r['NAME'] for r in table(db,'ROOM_TYPE_DATA')};dm={r['DIST_MODE_ID']:r for r in table(db,'DIST_MODE')};c=[]
 for o in table(db,'OCCUPANT_GAINS'):
  r=rooms[o['OF_ROOM']];kind=types[r['TYPE']]
  if kind not in ['主卧室','次卧室']:continue
  heat=o['HEAT_PER_PERSON'];damp=o['DAMP_PER_PERSON'];fresh=o['MIN_REQUIRE_FRESH_AIR'];air=dm[o['DIST_MODE']]['DIST_AIR']
  assert 0<heat<500 and 0<=damp<.5 and 0<=fresh<500 and 0<=air<=1,(item['model_key'],o)
  c.append({'native_room_ID':r['ID'],'native_room_name':r['NAME'],'native_room_type':kind,'native_gain_ID':o['GAIN_ID'],'native_gain_row':o,
   'sensible_W_per_reference_person':heat,'moisture_kg_per_hour_per_reference_person':damp,'total_W_per_reference_person':heat+damp*2500/3.6,
   'sensible_fraction':heat/(heat+damp*2500/3.6),'radiant_fraction':round(1-air,3),'fresh_air_requirement_m3_per_hour_per_reference_person':fresh})
 assert c,item['model_key']
 # Deterministic actual bedroom instance, not a population average. All
 # alternatives remain in the export so heterogeneous prototypes are visible.
 c.sort(key=lambda x:(x['native_room_type']!='主卧室',x['native_room_ID'],x['native_gain_ID']))
 return {'model_key':item['model_key'],'source_path':item['source_path'],'source_sha256':item['source_sha256'],'actual_bedroom_gain_instances':c,'reference_selected_gain_ID':c[0]['native_gain_ID'],
  'density_or_source_schedules_not_transferred_to_population_roster':True,'age_specific_metabolism_not_identified':True}
def rows_for(record,s):
 c=read(V10/record['service_world_path']);w=c['world'];hid=record['household_id'];z=parse(V10/record['service_IDF_path']);assert not any(x[0]=='People' for x in z)
 z=[x for x in z if x[0]!='RunPeriod'];z.append(obj('RunPeriod',{'name':'declared_allhome_July1to2','begin_month':7,'begin_day_of_month':1,'begin_year':2019,'end_month':7,'end_day_of_month':2,'end_year':2019,'day_of_week_for_start_day':'Monday','treat_weather_as_actual':'No'}))
 z += [['ScheduleTypeLimits','eb_occ_fraction',0,1,'Continuous','Dimensionless'],['ScheduleTypeLimits','eb_occ_activity',0,1000,'Continuous','ActivityLevel'],['Schedule:Constant','eb_allhome','eb_occ_fraction',1],['Schedule:Constant','eb_source_activity','eb_occ_activity',s['total_W_per_reference_person']]]
 # Inherited reference scalar schedules acquire types through their consumer,
 # never by guessing temperature from value or suppressing diagnostics.
 z += [['ScheduleTypeLimits','eb_occ_temperature',0,100,'Continuous','Temperature']];types={}
 for x in z:
  if x[0] in ['ElectricEquipment','WaterHeater:Mixed']:
   fs=SCHEMA['properties'][x[0]]['legacy_idd']['fields']
   for f in (['schedule_name'] if x[0]=='ElectricEquipment' else ['setpoint_temperature_schedule_name','cold_water_supply_temperature_schedule_name']):
    k=fs.index(f)+1
    if k<len(x) and x[k]:types[x[k]]='eb_occ_fraction' if x[0]=='ElectricEquipment' else 'eb_occ_temperature'
 for x in z:
  if x[0]=='Schedule:Constant' and x[1] in types:x[2]=types[x[1]]
 berths=w['sleep_reference']['berths'];members=[]
 for b in berths:
  name=b['member_id']+'_declared_quiet_presence';rid=b['room_id']
  z.append(obj('People',{'name':name,'zone_or_zonelist_or_space_or_spacelist_name':rid,'number_of_people_schedule_name':'eb_allhome','number_of_people_calculation_method':'People','number_of_people':1,
   'fraction_radiant':s['radiant_fraction'],'sensible_heat_fraction':s['sensible_fraction'],'activity_level_schedule_name':'eb_source_activity','enable_ashrae_55_comfort_warnings':'No'}));members.append({'member_id':b['member_id'],'room_id':rid,'People_name':name})
 for rid,n in collections.Counter(b['room_id'] for b in berths).items():
  z.append(obj('ZoneVentilation:DesignFlowRate',{'name':hid+'_'+rid+'_imposed_requirement_air','zone_or_zonelist_or_space_or_spacelist_name':rid,'schedule_name':'eb_allhome','design_flow_rate_calculation_method':'Flow/Zone',
   'design_flow_rate':n*s['fresh_air_requirement_m3_per_hour_per_reference_person']/3600,'ventilation_type':'Natural','constant_term_coefficient':1,'temperature_term_coefficient':0,'velocity_term_coefficient':0,'velocity_squared_term_coefficient':0,
   'minimum_indoor_temperature':-100,'maximum_indoor_temperature':100,'delta_temperature':-100,'minimum_outdoor_temperature':-100,'maximum_outdoor_temperature':100,'maximum_wind_speed':40}))
 z += [['Output:Variable','*',v,'Timestep'] for v in ['Zone People Occupant Count','Zone People Total Heating Rate','Zone People Sensible Heating Rate','Zone People Latent Gain Rate','Zone Ventilation Standard Density Volume Flow Rate','Zone Mean Air Temperature','Zone Air Humidity Ratio']]
 return z,members
def main():
 guard();refs=read(V8/'NATIVE_REFERENCE_REGISTRY.json')['models']+read(V8/'ADDITIONAL_REGIONAL_REFERENCES.json')['models']
 with concurrent.futures.ThreadPoolExecutor(4) as pool:sources=list(pool.map(source,refs))
 save(OUT/'NATIVE_OCCUPANT_SOURCE189.json',{'models':sources,'actual_tables':'ROOM + ROOM_TYPE_DATA.ID/NAME + OCCUPANT_GAINS.OF_ROOM + DIST_MODE','conversion_primary':'V10 pinned destep conv-people.R53–118 and conv-outdoor-air.R;2500kJ/kg reference latent heat',
  'new_person_schedule':'all roster members quiet at assigned berth rooms throughout this experimental run;not sleeping activity claim or observed time use','fresh_air_reference':'source requirement imposed as a constant fan-free airflow scenario;not measured natural ventilation or code compliance'})
 catalog={x['model_key']:x for x in sources};records=[];(OUT/'occupied_idfs').mkdir(exist_ok=True)
 for r in read(V10/'SERVICE_PORT_BINDINGS.json')['records']:
  s=catalog[r['source_model_key']]['actual_bedroom_gain_instances'][0];rows,members=rows_for(r,s);p=OUT/'occupied_idfs'/(r['household_id']+'.idf');p.write_text('! Declared all-home quiet reference;auxiliary households unspecified and not simulated residents.\n'+dump(rows))
  records.append({'household_id':r['household_id'],'members':members,'N_conserved':len(members),'source_model_key':r['source_model_key'],'source_gain_ID':s['native_gain_ID'],'source_thermal_parameters':s,
   'IDF_path':str(p.relative_to(OUT)),'IDF_sha256':sha(p),'weather':r['weather'],'allhome_schedule_experiment_not_source_diary':True,'auxiliary_household_residents_not_identified_and_excluded_from_this_test_condition':True,
   'unknown_lighting_cooking_hardware_not_modelled_and_not_assumed_absent':True,'complete_wholehome_energy_IDF':False})
 save(OUT/'OCCUPIED_REFERENCE_BINDINGS1000.json',{'records':records,'households':len(records),'People_roster_instances':sum(x['N_conserved'] for x in records),'source_models':len(sources),'experimental_presence_and_air_delivery_not_field_observations':True})
 print({'occupied_reference_IDFs':len(records),'roster_People':sum(x['N_conserved'] for x in records),'native_models':len(sources)},flush=True)
if __name__=='__main__':main()
