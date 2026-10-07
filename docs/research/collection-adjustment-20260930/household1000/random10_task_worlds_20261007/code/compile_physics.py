"""Bind all configured EB devices to one thermal world and explicit meters.

AC uses the pinned EB DX curves/rated parameters in a direct zone unit.
Tank uses a native well-mixed thermal state; EB's heater readiness proxy is
never promoted to delivered water temperature. EV/shiftable power comes from
the exact pinned EB program, with nonoverlapping separate background loads.
"""
import copy, datetime as dt, re, subprocess, time
from common import *
from programs import compact
SOURCE_HVAC=UP/'experiments/models/family_home/family_simple_3day.idf'
SOURCE_ROWS=parse(SOURCE_HVAC)
DX=next(r for r in SOURCE_ROWS if r[0]=='Coil:Cooling:DX:SingleSpeed')
FAN=next(r for r in SOURCE_ROWS if r[0]=='Fan:OnOff')
CURVES=[r for r in SOURCE_ROWS if r[0].startswith('Curve:')]
SOURCE_FLOOR_AREA=0.
for r in SOURCE_ROWS:
    if r[0]=='BuildingSurface:Detailed' and r[2]=='Floor' and r[6]=='Ground':
        p=[list(map(float,r[i:i+3])) for i in range(len(r)-12,len(r),3)]
        SOURCE_FLOOR_AREA+=abs(sum(p[i][0]*p[(i+1)%len(p)][1]-p[(i+1)%len(p)][0]*p[i][1] for i in range(len(p))))/2

def add_ac(rows,w,columns,schedule_names):
    a=w['assets']['ac']
    if not a['present']:return
    rid=a['room_id'];prefix='v14_ac';area=next(r['thermal_reference_area_m2'] for r in w['layout']['rooms'] if r['room_id']==rid)
    scale=area/SOURCE_FLOOR_AREA;flow=float(get(DX,'rated_air_flow_rate'))*scale
    curve_names={r[1]:prefix+'_'+r[1] for r in CURVES}
    for row in CURVES:rows.append([curve_names.get(x,x) for x in row])
    fan=copy.deepcopy(FAN);fan[1]=prefix+'_fan';put(fan,'availability_schedule_name','v14_all');put(fan,'maximum_flow_rate',flow)
    put(fan,'availability_schedule_name','v14_cooling_season');put(fan,'air_inlet_node_name',prefix+'_mixed');put(fan,'air_outlet_node_name',prefix+'_coil_inlet');put(fan,'end_use_subcategory','target_reference_AC_fan')
    fan=[curve_names.get(x,x) for x in fan];rows.append(fan)
    coil=copy.deepcopy(DX);coil[1]=prefix+'_coil';put(coil,'availability_schedule_name','v14_cooling_season');put(coil,'air_inlet_node_name',prefix+'_coil_inlet');put(coil,'air_outlet_node_name',prefix+'_supply')
    put(coil,'gross_rated_total_cooling_capacity',float(get(DX,'gross_rated_total_cooling_capacity'))*scale);put(coil,'rated_air_flow_rate',flow)
    coil=[curve_names.get(x,x) for x in coil];rows.append(coil)
    rows.extend([
      obj('OutdoorAir:Mixer',{'name':prefix+'_mixer','mixed_air_node_name':prefix+'_mixed','outdoor_air_stream_node_name':prefix+'_outside','relief_air_stream_node_name':prefix+'_relief','return_air_stream_node_name':prefix+'_return'}),
      ['OutdoorAir:Node',prefix+'_outside',-1],
      obj('ZoneHVAC:WindowAirConditioner',{'name':prefix+'_unit','availability_schedule_name':'v14_cooling_season','maximum_supply_air_flow_rate':flow,'maximum_outdoor_air_flow_rate':0,
          'air_inlet_node_name':prefix+'_return','air_outlet_node_name':prefix+'_supply','outdoor_air_mixer_object_type':'OutdoorAir:Mixer','outdoor_air_mixer_name':prefix+'_mixer',
          'supply_air_fan_object_type':'Fan:OnOff','supply_air_fan_name':prefix+'_fan','cooling_coil_object_type':'Coil:Cooling:DX:SingleSpeed','dx_cooling_coil_name':prefix+'_coil',
          'supply_air_fan_operating_mode_schedule_name':'v14_zero','fan_placement':'BlowThrough','cooling_convergence_tolerance':.001}),
])


def add_heating_boundary(rows,w,schedule_names):
    rows.extend([['Schedule:Constant','v14_heat18','v14_temperature',18],
                 ['ScheduleTypeLimits','v14_control',0,4,'Discrete','Control'],
                 ['Schedule:Constant','v14_heating_control','v14_control',1],
                 ['Schedule:Constant','v14_dual_control','v14_control',4]])
    for r in w['layout']['rooms']:
        rid=r['room_id'];prefix='v14_heat_'+rid;ac=w['assets']['ac']['present'] and w['assets']['ac']['room_id']==rid
        rows.append(obj('ZoneHVAC:IdealLoadsAirSystem',{'name':prefix,'availability_schedule_name':'v14_all',
          'zone_supply_air_node_name':prefix+'_supply','maximum_heating_supply_air_temperature':50,'minimum_cooling_supply_air_temperature':13,
          'maximum_heating_supply_air_humidity_ratio':.015,'minimum_cooling_supply_air_humidity_ratio':.009,
          'heating_limit':'NoLimit','cooling_limit':'LimitCapacity','maximum_total_cooling_capacity':0,
          'heating_availability_schedule_name':'v14_all','cooling_availability_schedule_name':'v14_zero',
          'dehumidification_control_type':'None','humidification_control_type':'None'}))
        thermostat=prefix+'_thermostat'
        rows.append(obj('ThermostatSetpoint:DualSetpoint',{'name':thermostat,'heating_setpoint_temperature_schedule_name':'v14_heat18','cooling_setpoint_temperature_schedule_name':schedule_names['ac_setpoint_C']}) if ac else
                    obj('ThermostatSetpoint:SingleHeating',{'name':thermostat,'setpoint_temperature_schedule_name':'v14_heat18'}))
        rows.append(obj('ZoneControl:Thermostat',{'name':prefix+'_control','zone_or_zonelist_name':rid,
          'control_type_schedule_name':'v14_dual_control' if ac else 'v14_heating_control',
          'control_1_object_type':'ThermostatSetpoint:DualSetpoint' if ac else 'ThermostatSetpoint:SingleHeating','control_1_name':thermostat}))
        equipment=['ZoneHVAC:EquipmentList',prefix+'_list','SequentialLoad']
        if ac:
            equipment+=['ZoneHVAC:WindowAirConditioner','v14_ac_unit',1,2,'','','ZoneHVAC:IdealLoadsAirSystem',prefix,2,1]
            rows.append(['NodeList',prefix+'_inlets','v14_ac_supply',prefix+'_supply'])
        else:equipment+=['ZoneHVAC:IdealLoadsAirSystem',prefix,1,1]
        rows.append(equipment)
        rows.append(obj('ZoneHVAC:EquipmentConnections',{'zone_name':rid,'zone_conditioning_equipment_list_name':prefix+'_list',
          'zone_air_inlet_node_or_nodelist_name':prefix+'_inlets' if ac else prefix+'_supply',
          'zone_air_exhaust_node_or_nodelist_name':'v14_ac_return' if ac else '',
          'zone_air_node_name':prefix+'_zone_air','zone_return_air_node_or_nodelist_name':prefix+'_return'}))

def compile_idf(w,binding,schedule_data,path,start_date,case=None,desired_rows=None):
    start_date=dt.date.fromisoformat(start_date) if isinstance(start_date,str) else start_date
    end_date=start_date+dt.timedelta(days=2)
    assert len(schedule_data)==432,'exactly three episode days required'
    source=V12/'background_idfs'/f"{w['household_id']}.idf";rows=parse(source)
    remove={'People','ElectricEquipment','Lights','WaterHeater:Mixed','RunPeriod','Output:Variable','Output:Meter','OutputControl:Files','ZoneControl:Thermostat','ThermostatSetpoint:DualSetpoint','ZoneControl:Humidistat','ZoneHVAC:IdealLoadsAirSystem','ZoneHVAC:EquipmentList','ZoneHVAC:EquipmentConnections'}
    rows=[r for r in rows if r[0] not in remove]
    for r in rows:
        if r[0]=='Timestep':r[1]=6
    rows.extend([
        obj('RunPeriod',{'name':'v14_random_target_common_history','begin_month':start_date.month,'begin_day_of_month':start_date.day,
             'end_month':end_date.month,'end_day_of_month':end_date.day,
             'day_of_week_for_start_day':start_date.strftime('%A'),'use_weather_file_holidays_and_special_days':'No','use_weather_file_daylight_saving_period':'No','treat_weather_as_actual':'No'}),
        ['ScheduleTypeLimits','v14_fraction',0,1,'Continuous','Dimensionless'],['ScheduleTypeLimits','v14_power',0,20000,'Continuous','Power'],['ScheduleTypeLimits','v14_temperature',-60,200,'Continuous','Temperature'],
        ['Schedule:Constant','v14_all','v14_fraction',1],['Schedule:Constant','v14_zero','v14_fraction',0],['Schedule:Constant','v14_person_W','v14_power',109.44444444444444],['Schedule:Constant','v14_water_inlet','v14_temperature',15],
        ['Schedule:Compact','v14_cooling_season','v14_fraction','Through:4/30','For:AllDays','Until:24:00',0,'Through:9/30','For:AllDays','Until:24:00',1,'Through:12/31','For:AllDays','Until:24:00',0]])
    schedule_names={};columns=list(schedule_data[0])
    for signal in columns:
        name='v14_signal_'+signal;limit='v14_temperature' if signal.endswith('_C') else 'v14_fraction' if signal.startswith(('person_','light_','background_','water_draw')) else 'v14_power'
        rows.append(['Schedule:Compact',name,limit]+compact(signal,[r[signal] for r in schedule_data],start_date))
        schedule_names[signal]=name
    actuated=['washer','dishwasher','dryer','ev','tank_setpoint_C','ac_setpoint_C']
    program=['SET v14_act_'+k+' = Null' for k in actuated]+['SET v14_slot_end = (Hour * 6) + TimeStepNum']
    for signal in actuated:
        rows.append(['EnergyManagementSystem:Actuator','v14_act_'+signal,schedule_names[signal],'Schedule:Compact','Schedule Value'])
    if case:
        day=case['context']['day_index_from_A_start']
        assert desired_rows is not None
        # Schedule Value sensors at this callpoint report the previous sample;
        # compile the exact EB-produced values directly rather than shifting the intended task clock.
        program += ['IF WarmupFlag == 0']
        for d in range(day,case['context']['evaluation_end_day_index']+1):
            date_d=start_date+dt.timedelta(days=d);first=round(case['context']['decision_h']*6) if d==day else 0
            program.append(f'IF (Month == {date_d.month}) && (DayOfMonth == {date_d.day})')
            for signal in columns:
                if signal not in actuated:continue
                groups=[];begin=first;values=[row[signal] for row in desired_rows[d*144:(d+1)*144]]
                for slot in range(first+1,145):
                    if slot==144 or values[slot]!=values[begin]:groups.append((begin,slot,values[begin]));begin=slot
                for j,(begin,end,value) in enumerate(groups):
                    program.append(('IF' if j==0 else 'ELSEIF')+f' (v14_slot_end > {begin}) && (v14_slot_end <= {end})')
                    literal=f'{value:.15f}'.rstrip('0').rstrip('.')
                    program.append(f'SET v14_act_{signal} = {literal}')
                program.append('ENDIF')
            program.append('ENDIF')
        program.append('ENDIF')
    rows.extend([['EnergyManagementSystem:Program','v14_task_actuation']+program,
                 ['EnergyManagementSystem:ProgramCallingManager','v14_task_call','BeginZoneTimestepBeforeInitHeatBalance','v14_task_actuation']])
    components=[];rid_index={r['room_id']:r for r in w['layout']['rooms']}
    for rid,r in rid_index.items():
        area=r['thermal_reference_area_m2'];density=1.8 if r['census_room_class']=='corridor' else 4.2;plug=.5*(5. if r['census_room_class']=='kitchen' else 2.)
        rows.extend([
          obj('Lights',{'name':'v14_light_'+rid,'zone_or_zonelist_or_space_or_spacelist_name':rid,'schedule_name':schedule_names['light_'+rid],'design_level_calculation_method':'LightingLevel',
              'lighting_level':area*density,'return_air_fraction':0,'fraction_radiant':.4,'fraction_visible':.2,'fraction_replaceable':1,'end_use_subcategory':'reference_lights'}),
          obj('ElectricEquipment',{'name':'v14_background_'+rid,'zone_or_zonelist_or_space_or_spacelist_name':rid,'schedule_name':schedule_names['background_'+rid],'design_level_calculation_method':'EquipmentLevel',
              'design_level':area*plug,'fraction_latent':0,'fraction_radiant':.3,'fraction_lost':0,'end_use_subcategory':'separate_fixed_reference_background'})])
        bucket='target_private_reference' if r['using_household_ids']==[w['household_id']] else 'shared_unallocated_reference' if w['household_id'] in r['using_household_ids'] else 'auxiliary_reference'
        components.extend([{'kind':'light','key':'v14_light_'+rid,'variable':'Lights Electricity Energy','meter_bucket':bucket},{'kind':'background','key':'v14_background_'+rid,'variable':'Electric Equipment Electricity Energy','meter_bucket':bucket}])
        for m in w['members']:
            signal='person_'+m['local_id']+'_'+rid
            if signal not in schedule_names:continue
            rows.append(obj('People',{'name':'v14_'+signal,'zone_or_zonelist_or_space_or_spacelist_name':rid,'number_of_people_schedule_name':schedule_names[signal],
              'number_of_people_calculation_method':'People','number_of_people':1,'fraction_radiant':.3,'sensible_heat_fraction':'Autocalculate','activity_level_schedule_name':'v14_person_W'}))
    for kind in ['washer','dishwasher','dryer','ev']:
        a=w['assets'][kind]
        if not a['present']:continue
        rid=a['room_id'] if kind!='ev' else w['members'][0]['reference_home_room_id'];key='v14_device_'+kind
        rows.append(obj('ElectricEquipment',{'name':key,'zone_or_zonelist_or_space_or_spacelist_name':rid,'schedule_name':schedule_names[kind],'design_level_calculation_method':'EquipmentLevel','design_level':1,
             'fraction_latent':0,'fraction_radiant':.3 if kind!='ev' else 0,'fraction_lost':1 if kind=='ev' else 0,'end_use_subcategory':'target_reference_'+kind}))
        components.append({'kind':kind,'key':key,'variable':'Electric Equipment Electricity Energy','meter_bucket':'target_household_reference'})
    tank=w['assets']['water_heater']
    if tank['present']:
        rows.append(obj('WaterHeater:Mixed',{'name':'v14_water_tank','tank_volume':.06,'setpoint_temperature_schedule_name':schedule_names['tank_setpoint_C'],'deadband_temperature_difference':2,
            'maximum_temperature_limit':80,'heater_control_type':'Cycle','heater_maximum_capacity':tank['config']['rated_kw']*1000,'heater_fuel_type':'Electricity','heater_thermal_efficiency':1,
            'ambient_temperature_indicator':'Zone','ambient_temperature_zone_name':tank['room_id'],'off_cycle_loss_coefficient_to_ambient_temperature':1.5,'off_cycle_loss_fraction_to_zone':1,
            'on_cycle_loss_coefficient_to_ambient_temperature':1.5,'on_cycle_loss_fraction_to_zone':1,'peak_use_flow_rate':.00005,'use_flow_rate_fraction_schedule_name':schedule_names['water_draw_fraction'],
            'cold_water_supply_temperature_schedule_name':'v14_water_inlet','use_side_effectiveness':1,'end_use_subcategory':'target_reference_water_heater'}))
        components.append({'kind':'water_heater','key':'v14_water_tank','variable':'Water Heater Electricity Energy','meter_bucket':'target_household_reference'})
    add_ac(rows,w,columns,schedule_names)
    add_heating_boundary(rows,w,schedule_names)
    if w['assets']['ac']['present']:
        components.extend([{'kind':'ac_coil','key':'v14_ac_coil','variable':'Cooling Coil Electricity Energy','meter_bucket':'target_household_reference'},
                           {'kind':'ac_fan','key':'v14_ac_fan','variable':'Fan Electricity Energy','meter_bucket':'target_household_reference'}])
    variables=['Zone Mean Air Temperature','Zone Air Relative Humidity','Zone People Occupant Count','Lights Electricity Energy','Electric Equipment Electricity Energy','Cooling Coil Electricity Energy','Fan Electricity Energy',
               'Water Heater Electricity Energy','Water Heater Tank Temperature','Water Heater Use Side Outlet Temperature','Water Heater Use Side Mass Flow Rate','Water Heater Heating Energy','Water Heater Heat Loss Energy','Water Heater Use Side Heat Transfer Energy','Water Heater Net Heat Transfer Energy','Water Heater Final Tank Temperature','Zone Ideal Loads Zone Total Heating Energy']
    variables=[v for v in variables if not v.startswith('Water Heater') or tank['present']]
    variables=[v for v in variables if not v.startswith(('Cooling Coil','Fan ')) or w['assets']['ac']['present']]
    rows.extend([obj('Output:Variable',{'key_value':'*','variable_name':v,'reporting_frequency':'Timestep'}) for v in variables])
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
            'control_execution':'same nominal A schedules and initialization;exact EB values actuated after decision at BeginZoneTimestepBeforeInitHeatBalance,before internal gains;integer zone interval end=Hour*6+TimeStepNum,lower exclusive upper inclusive;three distinct month/day conditions',
            'calendar_binding':'experimental dates use2025 roster weekdays;typical EPW uses month/day and correct origin weekday without actual-weather year;EP24.1 chooses a compatible nonleap internal year;SQL clock is independently checked against all three month/day dates',
            'AC_capacity_airflow_scaling':'served thermal floor area / source EB ground-floor footprint;explicit similarity design,not rated hardware observation or source autocalculated floor sum',
            'source_EB_ground_footprint_area_m2':SOURCE_FLOOR_AREA,
            'tank_state_source':'native EnergyPlus wellmixed thermal model;EB2kW input plus declared60L/UA1.5/reference draw',
            'ideal_cooling_removed_heating_external_reference':True,'named_and_background_meter_scopes_separate':True,'start_date':start_date.isoformat(),'end_date':end_date.isoformat(),'days':3,'nominal_schedule_content_sha256':digest(schedule_data),'background_thermal_boundary':w['background_thermal_boundary']}

def run(binding,folder):
    if (OUT/'EP_HOLD.json').exists():raise RuntimeError('User hold: review matching,device coverage,and A/B plans before any EP execution')
    if sys.platform!='linux':raise RuntimeError('EP execution is authorized on school Linux only')
    folder.mkdir(parents=True,exist_ok=True);start=time.monotonic();r=subprocess.run([str(ENGINE),'-w',binding['weather']['path'],'-d',str(folder),str(OUT/binding['IDF_path'])],capture_output=True,text=True,timeout=1800)
    (folder/'console.txt').write_text(r.stdout+'\n'+r.stderr);err=(folder/'eplusout.err').read_text() if (folder/'eplusout.err').exists() else r.stderr
    result={**binding,'returncode':r.returncode,'severe_fatal':re.findall(r'\*\*\s*(?:Severe|Fatal)\s*\*\*([^\n]*)',err),
            'warnings':re.findall(r'\*\*\s*Warning\s*\*\*([^\n]*)',err),'elapsed_seconds':round(time.monotonic()-start,3),'engine_sha256':sha(ENGINE),'run_directory':str(folder.relative_to(OUT))}
    sql=folder/'eplusout.sql'
    if sql.exists():result.update({'SQL_path':str(sql.relative_to(OUT)),'SQL_sha256':sha(sql),'SQL_bytes':sql.stat().st_size})
    save(folder/'RUN_RECORD.json',result);return result
