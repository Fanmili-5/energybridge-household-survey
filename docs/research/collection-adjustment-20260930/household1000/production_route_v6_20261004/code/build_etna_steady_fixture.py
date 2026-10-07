"""Independent steady-UA-equivalent ETNA fixture from normative Section13.

This is NOT a detailed16-path Standard140 model or a China IDF validation.
Measured heater OUTPUT is used by the evaluator only, never by input builder.
"""
import csv, datetime as dt, hashlib, io, json, sqlite3, subprocess, zipfile
from pathlib import Path
import numpy as np
import jsonschema

OUT=Path(__file__).resolve().parent.parent
REPO=OUT.parents[4]
ARCHIVE=REPO/'artifacts/private_research/benchmark_foundation_20261004/140-2023-B-AccompanyingFiles-022726.zip'
ENGINE=Path('/Applications/EnergyPlus-24-1-0/energyplus')
SCOPE='ETNA_ET110A1_steady_UA_equivalent_reconstruction; not_full_Standard140_not_China_housing_validation'
UA=dict(north=6.06,east=6.86,south=5.57,west=3.44,ceiling=2.67,floor=6.32)
HI=dict(north=10.5,east=7.,south=7.,west=5.3,ceiling=3.6,floor=5.3)
GUARD=dict(north=3,east=4,south=5,west=6,ceiling=1,floor=2)

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(p,x):p.write_text(json.dumps(x,ensure_ascii=False,indent=2,allow_nan=False)+'\n')

def inputs():
    with zipfile.ZipFile(ARCHIVE) as z:
        name='Accompanying Files/Normative Materials/ET110A-Measurements.csv'
        raw=z.read(name);rows=list(csv.reader(io.StringIO(raw.decode('cp1252'))))
        assert rows[0][10]=='Output' and rows[2][10]=='Qhtr'
        data={dt.datetime.strptime(r[0],'%m/%d/%Y %H:%M'):[float(v.replace(',','')) for v in r[1:11]]
              for r in rows[4:] if r and r[0].strip()}
        weather_name='Accompanying Files/Normative Materials/ET110meteo_within_Melun-071530_MY.2000_v3.epw'
        weather=z.read(weather_name)
    work=OUT/'physical_fixture';work.mkdir(exist_ok=True)
    weather_path=work/'normative_weather.epw';weather_path.write_bytes(weather)
    # Hourly CSV timestamp labels the END of preceding interval. Full leap
    # calendar prevents Jan26 values being shifted to Jan1. Qhtr excluded.
    schedule=work/'inputs_only.csv'
    times=sorted(data);first,last=times[0],times[-1]
    with schedule.open('w',newline='') as f:
        w=csv.writer(f);w.writerow(['Tattic','Tcellar','Tnorth','Teast','Tsouth','Twest','Tcell','Qfan','HWDsafr'])
        for h in range(1,8785):
            t=dt.datetime(2000,1,1)+dt.timedelta(hours=h)
            values=data[max(first,min(last,t))]
            w.writerow(values[:9])
    return work,weather_path,schedule,data,{'archive_sha256':sha(ARCHIVE),'measurement_member':name,
        'measurement_sha256':hashlib.sha256(raw).hexdigest(),'weather_member':weather_name,'weather_sha256':sha(weather_path),
        'schedule_inputs_only_sha256':sha(schedule),'Qhtr_output_excluded_from_all_model_inputs':True,
        'outside_observation_period_schedule_extension':'endpoint_hold_for_initialization_only; scoring_last18_observed_hours',
        'normative_sources':'Section13.2.2.8 measured UA; Figure13-2 geometry; Table13-20 combined film coefficients; Section13.2.2.10 Note4 zero_IR_combined_h_implementation'}

def model(schedule,timestep):
    x,y,h=3.5,4.655,2.565
    points={
      'north':[(x,y,h),(0,y,h),(0,y,0),(x,y,0)],
      'east':[(x,0,h),(x,y,h),(x,y,0),(x,0,0)],
      'south':[(0,0,h),(x,0,h),(x,0,0),(0,0,0)],
      'west':[(0,y,h),(0,0,h),(0,0,0),(0,y,0)],
      'ceiling':[(0,y,h),(0,0,h),(x,0,h),(x,y,h)],
      'floor':[(0,0,0),(0,y,0),(x,y,0),(x,0,0)]}
    area=dict(north=x*h,south=x*h,east=y*h,west=y*h,floor=x*y,ceiling=x*y)
    m={'Version':{'v':{'version_identifier':'24.1'}},'Timestep':{'dt':{'number_of_timesteps_per_hour':timestep}},
       'Building':{'ETNA':{'north_axis':30,'terrain':'Country','solar_distribution':'MinimalShadowing'}},
       'GlobalGeometryRules':{'rules':{'starting_vertex_position':'UpperLeftCorner','vertex_entry_direction':'Counterclockwise','coordinate_system':'Relative'}},
       'SimulationControl':{'control':{'do_zone_sizing_calculation':'No','do_system_sizing_calculation':'No','do_plant_sizing_calculation':'No','run_simulation_for_sizing_periods':'No','run_simulation_for_weather_file_run_periods':'Yes'}},
       'RunPeriod':{'observations':{'begin_month':1,'begin_day_of_month':26,'begin_year':2000,'end_month':2,'end_day_of_month':11,'end_year':2000,
                                  'use_weather_file_daylight_saving_period':'No','use_weather_file_holidays_and_special_days':'No'}},
       'Zone':{'cell':{'ceiling_height':h,'floor_area':x*y,'volume':x*y*h}},
       'Schedule:File':{},'Schedule:Constant':{'heating_control':{'hourly_value':1}},
       'Material:NoMass':{},'Construction':{},'BuildingSurface:Detailed':{},
       'SurfaceProperty:OtherSideCoefficients':{},'SurfaceProperty:ConvectionCoefficients':{},
       'ZoneHVAC:IdealLoadsAirSystem':{'heater':{'zone_supply_air_node_name':'supply','maximum_heating_supply_air_temperature':50,
          'heating_limit':'NoLimit','cooling_limit':'LimitCapacity','maximum_sensible_cooling_capacity':0,'dehumidification_control_type':'None','humidification_control_type':'None'}},
       'ZoneHVAC:EquipmentConnections':{'connection':{'zone_name':'cell','zone_conditioning_equipment_list_name':'equipment','zone_air_node_name':'air','zone_air_inlet_node_or_nodelist_name':'supply','zone_return_air_node_or_nodelist_name':'return'}},
       'ZoneHVAC:EquipmentList':{'equipment':{'equipment':[{'zone_equipment_object_type':'ZoneHVAC:IdealLoadsAirSystem','zone_equipment_name':'heater','zone_equipment_cooling_sequence':1,'zone_equipment_heating_or_no_load_sequence':1}]}},
       'ThermostatSetpoint:SingleHeating':{'temperature':{'setpoint_temperature_schedule_name':'Tcell'}},
       'ZoneControl:Thermostat':{'thermostat':{'zone_or_zonelist_name':'cell','control_type_schedule_name':'heating_control','control_1_object_type':'ThermostatSetpoint:SingleHeating','control_1_name':'temperature'}},
       'ElectricEquipment':{'circulation_fan':{'zone_or_zonelist_or_space_or_spacelist_name':'cell','schedule_name':'Qfan',
          'design_level_calculation_method':'EquipmentLevel','design_level':1,'fraction_latent':0,'fraction_radiant':0,'fraction_lost':0}},
       'Output:SQLite':{'sql':{'option_type':'SimpleAndTabular'}},'Output:Variable':{}}
    for j,name in enumerate(['Tattic','Tcellar','Tnorth','Teast','Tsouth','Twest','Tcell','Qfan','HWDsafr'],1):
        m['Schedule:File'][name]={'file_name':str(schedule),'column_number':j,'rows_to_skip_at_top':1,
          'number_of_hours_of_data':8784,'column_separator':'Comma','interpolate_to_timestep':'No','minutes_per_item':60,'adjust_schedule_for_daylight_savings':'No'}
    for name in points:
        R=area[name]/UA[name]-1/HI[name]-1/18
        assert R>0
        # EnergyPlus24.1 schema excludes exact zero; normative Note4 permits
        # the lowest supported emittance for combined-h input implementations.
        m['Material:NoMass'][name]={'roughness':'Smooth','thermal_resistance':R,'thermal_absorptance':1e-8,'solar_absorptance':0,'visible_absorptance':0}
        m['Construction'][name]={'outside_layer':name}
        m['BuildingSurface:Detailed'][name]={'surface_type':name.title() if name in ['floor','ceiling'] else 'Wall','construction_name':name,'zone_name':'cell',
          'outside_boundary_condition':'OtherSideCoefficients','outside_boundary_condition_object':name,'sun_exposure':'NoSun','wind_exposure':'NoWind','number_of_vertices':4,
          'vertices':[dict(vertex_x_coordinate=a,vertex_y_coordinate=b,vertex_z_coordinate=c) for a,b,c in points[name]]}
        m['SurfaceProperty:OtherSideCoefficients'][name]={'combined_convective_radiative_film_coefficient':18,
          'constant_temperature_coefficient':1,'external_dry_bulb_temperature_coefficient':0,'ground_temperature_coefficient':0,'wind_speed_coefficient':0,
          'zone_air_temperature_coefficient':0,'constant_temperature_schedule_name':list(m['Schedule:File'])[GUARD[name]-1]}
        m['SurfaceProperty:ConvectionCoefficients'][name]={'surface_name':name,'convection_coefficient_1_location':'Inside','convection_coefficient_1_type':'Value','convection_coefficient_1':HI[name]}
    for i,var in enumerate(['Zone Ideal Loads Supply Air Sensible Heating Rate','Zone Mean Air Temperature','Schedule Value']):
        m['Output:Variable'][str(i)]={'key_value':'*','variable_name':var,'reporting_frequency':'Hourly'}
    schema=json.loads((ENGINE.parent/'Energy+.schema.epJSON').read_text());jsonschema.validate(m,schema)
    return m,{'dimension_m':[x,y,h],'rectangular_surface_area_m2':area,'measured_surface_UA_W_per_K':UA,'inside_combined_h_W_per_m2K':HI,
              'outside_combined_h_W_per_m2K':18,'IR_emittance':1e-8,'thermal_mass':'discarded_in_steady_equivalent_fixture',
              'south_rectangular_area_minus_published_table_m2':area['south']-8.9755,'no_infiltration_or_occupants':True}

def evaluate(folder,data):
    con=sqlite3.connect(folder/'eplusout.sql')
    dictionary=con.execute('SELECT ReportDataDictionaryIndex,KeyValue,Name,Units FROM ReportDataDictionary').fetchall()
    series={}
    for index,key,name,units in dictionary:
        vals={dt.datetime(year,month,day)+dt.timedelta(hours=hour,minutes=minute):value
              for year,month,day,hour,minute,value in con.execute('SELECT t.Year,t.Month,t.Day,t.Hour,t.Minute,r.Value FROM ReportData r JOIN Time t USING(TimeIndex) WHERE r.ReportDataDictionaryIndex=? AND COALESCE(t.WarmupFlag,0)=0',(index,))}
        series[(key,name)]=vals
    con.close()
    start,end=dt.datetime(2000,2,10,16),dt.datetime(2000,2,11,9)
    times=[t for t in sorted(data) if start<=t<=end];assert len(times)==18
    heating=next(v for (key,name),v in series.items() if name=='Zone Ideal Loads Supply Air Sensible Heating Rate')
    air=next(v for (key,name),v in series.items() if name=='Zone Mean Air Temperature')
    pred=[heating[t] for t in times];ref=[data[t][9] for t in times]
    oracle=[sum(UA[n]*(data[t][6]-data[t][GUARD[n]-1]) for n in UA)-data[t][7] for t in times]
    residual={name:max(abs(series[(name.upper(),'Schedule Value')][t]-data[t][j]) for t in times)
              for j,name in enumerate(['Tattic','Tcellar','Tnorth','Teast','Tsouth','Twest','Tcell','Qfan','HWDsafr'])}
    assert max(residual.values())<1e-5
    mean=float(np.mean(pred));reference=float(np.mean(ref));band=[reference*.991,reference*1.009]
    err=(folder/'eplusout.err').read_text();assert '** Severe **' not in err and '**  Fatal  **' not in err
    wrong=mean+np.mean([data[t][7] for t in times])
    return {'scope':SCOPE,'steady_hours':18,'observed_mean_heater_W':reference,'predicted_mean_heater_W':mean,
        'delta_W':mean-reference,'absolute_relative_error':abs(mean-reference)/reference,'measured_source_2sigma_band_W':band,
        'mean_inside_measured_band':band[0]<=mean<=band[1],'hours_inside_average_measurement_band':sum(band[0]<=v<=band[1] for v in pred),
        'analytical_UA_minus_fan_mean_W':float(np.mean(oracle)),'mean_EnergyPlus_minus_analytical_W':float(np.mean(np.array(pred)-oracle)),
        'max_zone_setpoint_residual_K':max(abs(air[t]-data[t][6]) for t in times),'max_input_readback_residuals':residual,
        'negative_control_heater_plus_fan_outside_band':not band[0]<=wrong<=band[1],
        'hourly_predictions_W':pred,'hourly_observations_W':ref,'engine_log_sha256':sha(folder/'eplusout.err'),
        'engine_warning_count':err.count('** Warning **'),'sql_sha256':sha(folder/'eplusout.sql')}

def main():
    work,weather,schedule,data,locks=inputs();results=[]
    for timestep in [6,12]:
        model_json,parameters=model(schedule,timestep);path=work/f'etna_UA_equivalent_{timestep}.epJSON';save(path,model_json)
        folder=work/f'run_{timestep}';folder.mkdir(exist_ok=True)
        command=[str(ENGINE),'-w',str(weather),'-d',str(folder),str(path)]
        process=subprocess.run(command,capture_output=True,text=True);(folder/'command_stdout.txt').write_text(process.stdout+'\n'+process.stderr)
        if process.returncode:raise RuntimeError('EnergyPlus failed; inspect '+str(folder/'eplusout.err'))
        result=evaluate(folder,data);result.update(timesteps_per_hour=timestep,input_epJSON_sha256=sha(path));results.append(result)
    change=abs(results[1]['predicted_mean_heater_W']-results[0]['predicted_mean_heater_W'])/results[1]['predicted_mean_heater_W']
    report={'scope':SCOPE,'source_locks':locks,'parameters':parameters,'engine_version':'24.1.0','new_independent_EnergyPlus_runs':2,'runs':results,
      'time_step_refinement_relative_mean_change':change,'time_step_refinement_below_informative_point_one_percent':change<.001,
      'calibration_to_measured_output_performed':False,'informative_example_IDF_copied_or_run':False,
      'all_six_Standard140_ETNA_cases_completed':False,'detailed_16_path_construction_validated':False,'national_household_IDF_bindings_validated':0}
    save(OUT/'ETNA_INDEPENDENT_STEADY_RESULT.json',report)
    print(json.dumps({k:report[k] for k in ['scope','new_independent_EnergyPlus_runs','time_step_refinement_relative_mean_change']},indent=2))
    print(json.dumps([{k:r[k] for k in ['timesteps_per_hour','predicted_mean_heater_W','observed_mean_heater_W','mean_inside_measured_band']} for r in results],indent=2))

if __name__=='__main__':main()
