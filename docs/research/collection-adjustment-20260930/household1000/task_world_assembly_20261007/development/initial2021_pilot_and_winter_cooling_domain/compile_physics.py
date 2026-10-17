"""Bind all configured EB devices to one thermal world and explicit meters.

AC uses the pinned EB DX curves/rated parameters in a direct zone unit.
Tank uses a native well-mixed thermal state; EB's heater readiness proxy is
never promoted to delivered water temperature. EV/shiftable power comes from
the exact pinned EB program, with nonoverlapping separate background loads.
"""
import collections, copy, csv, datetime as dt, re, sqlite3, subprocess, time
from common import *
from programs import trace, write_schedules, round_spec, START
SOURCE_HVAC=UP/'experiments/models/family_home/family_simple_3day.idf'
SOURCE_ROWS=parse(SOURCE_HVAC)
DX=next(r for r in SOURCE_ROWS if r[0]=='Coil:Cooling:DX:SingleSpeed')
FAN=next(r for r in SOURCE_ROWS if r[0]=='Fan:OnOff')
CURVES=[r for r in SOURCE_ROWS if r[0].startswith('Curve:')]

def add_ac(rows,w,columns,schedule_names):
    a=w['assets']['ac']
    if not a['present']:return
    rid=a['room_id'];prefix='v13_ac';flow=float(get(DX,'rated_air_flow_rate'))
    curve_names={r[1]:prefix+'_'+r[1] for r in CURVES}
    for row in CURVES:rows.append([curve_names.get(x,x) for x in row])
    fan=copy.deepcopy(FAN);fan[1]=prefix+'_fan';put(fan,'availability_schedule_name','v13_all');put(fan,'maximum_flow_rate',flow)
    put(fan,'air_inlet_node_name',prefix+'_mixed');put(fan,'air_outlet_node_name',prefix+'_coil_inlet');put(fan,'end_use_subcategory','target_reference_AC_fan')
    fan=[curve_names.get(x,x) for x in fan];rows.append(fan)
    coil=copy.deepcopy(DX);coil[1]=prefix+'_coil';put(coil,'availability_schedule_name','v13_all');put(coil,'air_inlet_node_name',prefix+'_coil_inlet');put(coil,'air_outlet_node_name',prefix+'_supply')
    coil=[curve_names.get(x,x) for x in coil];rows.append(coil)
    rows.extend([
      obj('OutdoorAir:Mixer',{'name':prefix+'_mixer','mixed_air_node_name':prefix+'_mixed','outdoor_air_stream_node_name':prefix+'_outside','relief_air_stream_node_name':prefix+'_relief','return_air_stream_node_name':prefix+'_return'}),
      ['OutdoorAir:Node',prefix+'_outside',-1],
      obj('ZoneHVAC:WindowAirConditioner',{'name':prefix+'_unit','availability_schedule_name':'v13_all','maximum_supply_air_flow_rate':flow,'maximum_outdoor_air_flow_rate':0,
          'air_inlet_node_name':prefix+'_return','air_outlet_node_name':prefix+'_supply','outdoor_air_mixer_object_type':'OutdoorAir:Mixer','outdoor_air_mixer_name':prefix+'_mixer',
          'supply_air_fan_object_type':'Fan:OnOff','supply_air_fan_name':prefix+'_fan','cooling_coil_object_type':'Coil:Cooling:DX:SingleSpeed','dx_cooling_coil_name':prefix+'_coil',
          'supply_air_fan_operating_mode_schedule_name':'v13_zero','fan_placement':'BlowThrough','cooling_convergence_tolerance':.001}),
      obj('ThermostatSetpoint:SingleCooling',{'name':prefix+'_thermostat','setpoint_temperature_schedule_name':schedule_names['ac_setpoint_C']}),
      ['ScheduleTypeLimits','v13_control',0,4,'Discrete','Control'],['Schedule:Constant','v13_cooling_control','v13_control',2],
      obj('ZoneControl:Thermostat',{'name':prefix+'_control','zone_or_zonelist_name':rid,'control_type_schedule_name':'v13_cooling_control','control_1_object_type':'ThermostatSetpoint:SingleCooling','control_1_name':prefix+'_thermostat'}),
      ['ZoneHVAC:EquipmentList',prefix+'_list','SequentialLoad','ZoneHVAC:WindowAirConditioner',prefix+'_unit',1,1],
      obj('ZoneHVAC:EquipmentConnections',{'zone_name':rid,'zone_conditioning_equipment_list_name':prefix+'_list','zone_air_inlet_node_or_nodelist_name':prefix+'_supply','zone_air_exhaust_node_or_nodelist_name':prefix+'_return','zone_air_node_name':prefix+'_zone_air'})])

def compile_idf(w,binding,schedule_path,columns,path,end_date,base_schedule=None,base_columns=None):
    source=V12/'background_idfs'/f"{w['household_id']}.idf";rows=parse(source)
    remove={'People','ElectricEquipment','Lights','WaterHeater:Mixed','RunPeriod','Output:Variable','Output:Meter','OutputControl:Files','ZoneControl:Thermostat','ThermostatSetpoint:DualSetpoint','ZoneControl:Humidistat','ZoneHVAC:IdealLoadsAirSystem','ZoneHVAC:EquipmentList','ZoneHVAC:EquipmentConnections'}
    rows=[r for r in rows if r[0] not in remove]
    for r in rows:
        if r[0]=='Timestep':r[1]=6
    rows.extend([
        obj('RunPeriod',{'name':'v13_common_history','begin_month':7,'begin_day_of_month':1,'begin_year':2021,'end_month':end_date.month,'end_day_of_month':end_date.day,'end_year':end_date.year,
             'day_of_week_for_start_day':'Thursday','use_weather_file_holidays_and_special_days':'No','use_weather_file_daylight_saving_period':'No','treat_weather_as_actual':'No'}),
        ['ScheduleTypeLimits','v13_fraction',0,1,'Continuous','Dimensionless'],['ScheduleTypeLimits','v13_power',0,20000,'Continuous','Power'],['ScheduleTypeLimits','v13_temperature',-60,200,'Continuous','Temperature'],
        ['Schedule:Constant','v13_all','v13_fraction',1],['Schedule:Constant','v13_zero','v13_fraction',0],['Schedule:Constant','v13_person_W','v13_power',109.44444444444444],['Schedule:Constant','v13_water_inlet','v13_temperature',15],
        ['Schedule:Compact','v13_first20','v13_fraction','Through:6/30','For:AllDays','Until:24:00',0,'Through:7/20','For:AllDays','Until:24:00',1,'Through:12/31','For:AllDays','Until:24:00',0]])
    schedule_names={}
    def add_file(signal,p,col):
        name='v13_signal_'+signal;limit='v13_temperature' if signal.endswith('_C') else 'v13_fraction' if signal.startswith(('person_','light_','background_','water_draw')) else 'v13_power'
        rows.append(obj('Schedule:File',{'name':name,'schedule_type_limits_name':limit,'file_name':str(p.resolve()),'column_number':col,'rows_to_skip_at_top':1,'number_of_hours_of_data':8760,
              'column_separator':'Comma','interpolate_to_timestep':'No','minutes_per_item':10,'adjust_schedule_for_daylight_savings':'No'}));schedule_names[signal]=name
    for signal,col in columns.items():add_file(signal,schedule_path,col)
    if base_schedule is not None:
        for signal,col in base_columns.items():
            if signal not in columns:add_file(signal,base_schedule,col)
    components=[];rid_index={r['room_id']:r for r in w['layout']['rooms']}
    for rid,r in rid_index.items():
        area=r['thermal_reference_area_m2'];density=1.8 if r['census_room_class']=='corridor' else 4.2;plug=.5*(5. if r['census_room_class']=='kitchen' else 2.)
        rows.extend([
          obj('Lights',{'name':'v13_light_'+rid,'zone_or_zonelist_or_space_or_spacelist_name':rid,'schedule_name':schedule_names['light_'+rid],'design_level_calculation_method':'LightingLevel',
              'lighting_level':area*density,'return_air_fraction':0,'fraction_radiant':.4,'fraction_visible':.2,'fraction_replaceable':1,'end_use_subcategory':'reference_lights'}),
          obj('ElectricEquipment',{'name':'v13_background_'+rid,'zone_or_zonelist_or_space_or_spacelist_name':rid,'schedule_name':schedule_names['background_'+rid],'design_level_calculation_method':'EquipmentLevel',
              'design_level':area*plug,'fraction_latent':0,'fraction_radiant':.3,'fraction_lost':0,'end_use_subcategory':'separate_fixed_reference_background'})])
        bucket='target_private_reference' if r['using_household_ids']==[w['household_id']] else 'shared_unallocated_reference' if w['household_id'] in r['using_household_ids'] else 'auxiliary_reference'
        components.extend([{'kind':'light','key':'v13_light_'+rid,'variable':'Lights Electricity Energy','meter_bucket':bucket},{'kind':'background','key':'v13_background_'+rid,'variable':'Electric Equipment Electricity Energy','meter_bucket':bucket}])
        for m in w['members']:
            signal='person_'+m['local_id']+'_'+rid
            if signal not in schedule_names:continue
            rows.append(obj('People',{'name':'v13_'+signal,'zone_or_zonelist_or_space_or_spacelist_name':rid,'number_of_people_schedule_name':schedule_names[signal],
              'number_of_people_calculation_method':'People','number_of_people':1,'fraction_radiant':.3,'sensible_heat_fraction':'Autocalculate','activity_level_schedule_name':'v13_person_W'}))
    for kind in ['washer','dishwasher','dryer','ev']:
        a=w['assets'][kind]
        if not a['present']:continue
        rid=a['room_id'] if kind!='ev' else w['members'][0]['reference_home_room_id'];key='v13_device_'+kind
        rows.append(obj('ElectricEquipment',{'name':key,'zone_or_zonelist_or_space_or_spacelist_name':rid,'schedule_name':schedule_names[kind],'design_level_calculation_method':'EquipmentLevel','design_level':1,
             'fraction_latent':0,'fraction_radiant':.3 if kind!='ev' else 0,'fraction_lost':1 if kind=='ev' else 0,'end_use_subcategory':'target_reference_'+kind}))
        components.append({'kind':kind,'key':key,'variable':'Electric Equipment Electricity Energy','meter_bucket':'target_household_reference'})
    tank=w['assets']['water_heater']
    if tank['present']:
        rows.append(obj('WaterHeater:Mixed',{'name':'v13_water_tank','tank_volume':.06,'setpoint_temperature_schedule_name':schedule_names['tank_setpoint_C'],'deadband_temperature_difference':2,
            'maximum_temperature_limit':80,'heater_control_type':'Cycle','heater_maximum_capacity':tank['config']['rated_kw']*1000,'heater_fuel_type':'Electricity','heater_thermal_efficiency':1,
            'ambient_temperature_indicator':'Zone','ambient_temperature_zone_name':tank['room_id'],'off_cycle_loss_coefficient_to_ambient_temperature':1.5,'off_cycle_loss_fraction_to_zone':1,
            'on_cycle_loss_coefficient_to_ambient_temperature':1.5,'on_cycle_loss_fraction_to_zone':1,'peak_use_flow_rate':.00005,'use_flow_rate_fraction_schedule_name':schedule_names['water_draw_fraction'],
            'cold_water_supply_temperature_schedule_name':'v13_water_inlet','use_side_effectiveness':1,'end_use_subcategory':'target_reference_water_heater'}))
        components.append({'kind':'water_heater','key':'v13_water_tank','variable':'Water Heater Electricity Energy','meter_bucket':'target_household_reference'})
    add_ac(rows,w,columns,schedule_names)
    if w['assets']['ac']['present']:
        components.extend([{'kind':'ac_coil','key':'v13_ac_coil','variable':'Cooling Coil Electricity Energy','meter_bucket':'target_household_reference'},
                           {'kind':'ac_fan','key':'v13_ac_fan','variable':'Fan Electricity Energy','meter_bucket':'target_household_reference'}])
    variables=['Zone Mean Air Temperature','Zone Air Relative Humidity','Zone People Occupant Count','Lights Electricity Energy','Electric Equipment Electricity Energy','Cooling Coil Electricity Energy','Fan Electricity Energy',
               'Water Heater Electricity Energy','Water Heater Tank Temperature','Water Heater Use Side Outlet Temperature','Water Heater Use Side Mass Flow Rate','Water Heater Heating Energy','Water Heater Heat Loss Energy','Water Heater Use Side Heat Transfer Energy']
    rows.extend([obj('Output:Variable',{'key_value':'*','variable_name':v,'reporting_frequency':'Timestep','schedule_name':'v13_first20'}) for v in variables])
    rows.extend([obj('Output:Variable',{'key_value':'*','variable_name':v,'reporting_frequency':'Hourly'}) for v in variables[:8]])
    rows.extend([['Output:Meter','Electricity:Facility','Hourly'],['Output:Meter','Electricity:Facility','Timestep'],['Output:SQLite','SimpleAndTabular'],
       obj('OutputControl:Files',{k:'Yes' if k in ['output_sqlite','output_eio','output_end'] else 'No' for k in SCHEMA['properties']['OutputControl:Files']['legacy_idd']['fields']})])
    # Old source output objects must not create duplicated meter frequencies.
    seen=set();unique=[]
    for r in rows:
        marker=canonical(r)
        if r[0] in ['Output:SQLite','Output:Meter','Output:Variable'] and marker in seen:continue
        seen.add(marker);unique.append(r)
    path.parent.mkdir(parents=True,exist_ok=True);path.write_text('! EB-six-device coherent reference world;not observed national end-use validation.\n'+dump(unique))
    return {'household_id':w['household_id'],'world_content_sha256':w['world_content_sha256'],'IDF_path':str(path.relative_to(OUT)),'IDF_sha256':sha(path),'weather':binding['weather'],
            'physical_components':components,'source_background_IDF_sha256':sha(source),'source_DX_HVAC_path':str(SOURCE_HVAC),'source_DX_HVAC_sha256':sha(SOURCE_HVAC),
            'AC_topology_adaptation':'direct zone cooling unit using exact EB DX/fan/curve reference values;not actual installed window/split hardware identity',
            'tank_state_source':'native EnergyPlus wellmixed thermal model;EB2kW input plus declared60L/UA1.5/reference draw',
            'ideal_loads_removed':True,'named_and_background_meter_scopes_separate':True,'end_date':end_date.isoformat(),'input_schedule_path':str(schedule_path.relative_to(OUT)),'input_schedule_sha256':sha(schedule_path)}

def run(binding,folder):
    folder.mkdir(parents=True,exist_ok=True);start=time.monotonic();r=subprocess.run([str(ENGINE),'-w',binding['weather']['path'],'-d',str(folder),str(OUT/binding['IDF_path'])],capture_output=True,text=True,timeout=1800)
    (folder/'console.txt').write_text(r.stdout+'\n'+r.stderr);err=(folder/'eplusout.err').read_text() if (folder/'eplusout.err').exists() else r.stderr
    result={**binding,'returncode':r.returncode,'severe_fatal':re.findall(r'\*\*\s*(?:Severe|Fatal)\s*\*\*([^\n]*)',err),
            'warnings':re.findall(r'\*\*\s*Warning\s*\*\*([^\n]*)',err),'elapsed_seconds':round(time.monotonic()-start,3),'engine_sha256':sha(ENGINE),'run_directory':str(folder.relative_to(OUT))}
    sql=folder/'eplusout.sql'
    if sql.exists():result.update({'SQL_path':str(sql.relative_to(OUT)),'SQL_sha256':sha(sql),'SQL_bytes':sql.stat().st_size})
    save(folder/'RUN_RECORD.json',result);return result

def pilot(hid='ordinary-v6-0002'):
    guard();binding=next(x for x in read(OUT/'WORLD_BINDINGS1000.json')['records'] if x['household_id']==hid);w=read(OUT/binding['world_path']);a=trace(w);sp=OUT/'schedules'/hid/'A.csv';cols=write_schedules(w,a,sp)
    save(OUT/'programs'/hid/'A_PROGRAM_LEDGER.json',{k:v for k,v in a.items() if k!='rows'});b=compile_idf(w,binding,sp,cols,OUT/'idfs'/hid/'A.idf',dt.date(2022,6,30));r=run(b,OUT/'runs'/hid/'A');save(OUT/'PILOT_ANNUAL.json',r);print({k:v for k,v in r.items() if k in ['returncode','severe_fatal','warnings','elapsed_seconds','SQL_bytes']},flush=True)
if __name__=='__main__':pilot(sys.argv[1] if len(sys.argv)>1 else 'ordinary-v6-0002')
