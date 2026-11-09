"""Source polygons + six-device inputs -> an EnergyPlus model and complete receipts."""
from __future__ import annotations
import copy
import csv
import datetime as dt
from pathlib import Path
import numpy as np

from .common import ROOT, require, read, save, sha, locked, digest, code_identity, seal
from .idf import Fields, parse, render, objects, one
from .prototypes import extract_unit, scale_geometry
from .weather import audit as weather_audit, match as weather_match
from .scenario import compile_schedules, validate
from .devices import performance_reference
from .airflow import pressure_network


def curve(row, name, coefficients, ymin, ymax):
    # Six Biquadratic coefficients: indoor terms are zero in this explicit reference approximation.
    return ['Curve:Biquadratic',name,coefficients[0],0,0,coefficients[1],coefficients[2],0,
            -30,60,ymin,ymax,.01,10,'Temperature','Temperature','Dimensionless']


def hvac(zone,selected,f:Fields,profile,settings,stress=None):
    src=read(ROOT/'resources/variable_speed_pthp.json');rs=copy.deepcopy(src['rows'])
    prefix='ac_'+zone+'_';names={r[1]:prefix+r[1]for r in rs}
    for r in rs:
        for i,v in enumerate(r[1:],1):
            if v in names:r[i]=names[v]
            elif isinstance(v,str)and v.startswith('Zone1'):r[i]=prefix+v
            elif v=='FanAndCoilAvailSched':r[i]='hvac_available'
            elif v=='ConstantFanSch':r[i]='zero'
    n=selected['parallel_reference_units'];fan_W=30*n;flow=.214*n
    stress=stress or {};power_scale=stress.get('hvac_power_scale',1)
    heat_Q=profile['maximum_heating_W'][-1]-30
    heat_COP=heat_Q/(profile['maximum_total_power_W'][-1]*power_scale-30)
    cool_Q=profile['cooling_reference']['max_capacity_W']+30
    cool_COP=cool_Q/(profile['cooling_reference']['max_total_power_W']*power_scale-30)
    x=np.array(profile['outdoor_C']);q=np.array(profile['maximum_heating_W'])-30
    eir=(np.array(profile['maximum_total_power_W'])*power_scale-30)/q
    cap_coeff=np.polynomial.polynomial.polyfit(x,q/heat_Q,2)
    eir_coeff=np.polynomial.polynomial.polyfit(x,eir*heat_COP,2)
    cap_name=prefix+'sourced_max_capacity';eir_name=prefix+'sourced_max_eir'
    rs +=[curve(None,cap_name,cap_coeff.tolist(),-25,x[-1]),curve(None,eir_name,eir_coeff.tolist(),-25,x[-1])]
    auxiliary_W=settings.get('supplemental_heat_W',0)
    for r in rs:
        k=r[0]
        if k in ('ZoneHVAC:PackagedTerminalHeatPump','Fan:SystemModel','Coil:Heating:Electric'):
            f.set(r,'availability_schedule_name','zero'if k=='Coil:Heating:Electric'and auxiliary_W==0 else'hvac_available')
        if k=='ZoneHVAC:PackagedTerminalHeatPump':
            for key in ('cooling_supply_air_flow_rate','heating_supply_air_flow_rate','no_load_supply_air_flow_rate'):
                f.set(r,key,flow)
            for key in ('cooling_outdoor_air_flow_rate','heating_outdoor_air_flow_rate','no_load_outdoor_air_flow_rate'):
                f.set(r,key,0)
            f.set(r,'supply_air_fan_operating_mode_schedule_name','zero')
        elif k=='Fan:SystemModel':
            f.set(r,'design_maximum_air_flow_rate',flow);f.set(r,'design_electric_power_consumption',fan_W)
            f.set(r,'availability_schedule_name','hvac_available')
        elif k=='Coil:Heating:Electric':f.set(r,'nominal_capacity',auxiliary_W)
        elif k=='Coil:Heating:DX:VariableSpeed':
            f.set(r,'rated_heating_capacity_at_selected_nominal_speed_level',heat_Q*n)
            f.set(r,'rated_air_flow_rate_at_selected_nominal_speed_level',flow)
            f.set(r,'minimum_outdoor_dry_bulb_temperature_for_compressor_operation',-25)
            f.set(r,'outdoor_dry_bulb_temperature_to_turn_on_compressor',-24)
            f.set(r,'crankcase_heater_capacity',0)
            # Explicit generic native defrost mechanism, not fitted OEM cycle behavior.
            f.set(r,'defrost_strategy','ReverseCycle');f.set(r,'defrost_control','OnDemand')
            f.set(r,'defrost_time_period_fraction',.058333)
            f.set(r,'resistive_defrost_heater_capacity',0)
            df=prefix+'defrost_reference'
            f.set(r,'defrost_energy_input_ratio_function_of_temperature_curve_name',df)
            rs.append(['Curve:Biquadratic',df,.1528*stress.get('defrost_eir_scale',1),0,0,0,0,0,-30,60,-30,60,0,1])
            for speed in range(1,11):
                fraction=.176190476+(speed-1)*(1-.176190476)/9
                f.set(r,f'speed_{speed}_reference_unit_gross_rated_heating_capacity',heat_Q*n*fraction)
                f.set(r,f'speed_{speed}_reference_unit_rated_air_flow_rate',flow*(.35+.65*fraction))
                f.set(r,f'speed_{speed}_reference_unit_gross_rated_heating_cop',heat_COP)
                f.set(r,f'speed_{speed}_heating_capacity_function_of_temperature_curve_name',cap_name)
                f.set(r,f'speed_{speed}_energy_input_ratio_function_of_temperature_curve_name',eir_name)
        elif k=='Coil:Cooling:DX:VariableSpeed':
            f.set(r,'gross_rated_total_cooling_capacity_at_selected_nominal_speed_level',cool_Q*n)
            f.set(r,'rated_air_flow_rate_at_selected_nominal_speed_level',flow)
            f.set(r,'crankcase_heater_capacity',0)
            for speed in range(1,11):
                fraction=.183823529+(speed-1)*(1-.183823529)/9
                f.set(r,f'speed_{speed}_reference_unit_gross_rated_total_cooling_capacity',cool_Q*n*fraction)
                f.set(r,f'speed_{speed}_reference_unit_rated_air_flow_rate',flow*(.35+.65*fraction))
                f.set(r,f'speed_{speed}_reference_unit_gross_rated_cooling_cop',cool_COP)
                # Keep the official generic speed-specific SHR. The manufacturer's 0.83
                # is a rated-point quantity and cannot be assigned to maximum capacity.
    rs.append(['OutdoorAir:NodeList',prefix+'Zone1PTHPOAInNode'])
    unit=one(rs,'ZoneHVAC:PackagedTerminalHeatPump')
    supplied=f.get(unit,'air_outlet_node_name');returned=f.get(unit,'air_inlet_node_name')
    rs +=[['ZoneHVAC:EquipmentList',zone+'_equipment','SequentialLoad',unit[0],unit[1],1,1],
          ['ZoneHVAC:EquipmentConnections',zone,zone+'_equipment',supplied,returned,zone+'_air',''],
          ['ThermostatSetpoint:DualSetpoint',zone+'_thermostat','heat_sp','cool_sp'],
          ['ZoneControl:Thermostat',zone+'_control',zone,'dual_control',
           'ThermostatSetpoint:DualSetpoint',zone+'_thermostat']]
    return rs,{'zone':zone,'equipment':unit[1], 'fan':one(rs,'Fan:SystemModel')[1],
      'heating_coil':one(rs,'Coil:Heating:DX:VariableSpeed')[1],
      'cooling_coil':one(rs,'Coil:Cooling:DX:VariableSpeed')[1],
      'supplemental_coil':one(rs,'Coil:Heating:Electric')[1],
      'parallel_reference_units':n,'capacity_fit_coefficients':cap_coeff.tolist(),
      'eir_fit_coefficients':eir_coeff.tolist(),
      'capacity_fit_max_relative_residual':float(max(abs(np.polynomial.polynomial.polyval(x,cap_coeff)*heat_Q-q)/q)),
      'reference_fan_W':fan_W,'hybrid_reference_not_OEM_replica':True,
      'generic_speed_interpolation_and_defrost_require_sensitivity':True,
      'heating_performance_point_bracket_C':[-25,profile['outdoor_C'][-1]],
      'warm_heating_curve_input_clamped_to_last_data_point':True,
      'supplemental_capacity_W':auxiliary_W,'supplemental_source':settings.get('supplemental_heat_source'),
      'cooling_temperature_curves':'unmodified_official_example;not_manufacturer_map'}


def add_tank(rows,f,case,schedules):
    d=case['environment']['devices']['water_heater'];tank='target_tank'
    peak=max(float(schedules['mixed_demand_L_min'].max()),1)/60000
    rows +=[['Schedule:Constant','hot_draw_fraction','AnyNumber',0]]
    rows +=[f.obj('WaterHeater:Stratified',name=tank,end_use_subcategory='target_water_heater',
      tank_volume=d['volume_m3'],tank_height=d['height_m'],tank_shape='VerticalCylinder',
      maximum_temperature_limit=90,heater_priority_control='MasterSlave',
      heater_1_setpoint_temperature_schedule_name='tank_target',heater_1_deadband_temperature_difference=2,
      heater_1_capacity=d['heater_W'],heater_1_height=0,
      heater_2_setpoint_temperature_schedule_name='tank_target',heater_2_capacity=0,heater_2_height=0,
      heater_fuel_type='Electricity',heater_thermal_efficiency=d['efficiency'],
      ambient_temperature_indicator='Zone',ambient_temperature_zone_name=d['room_id'],
      uniform_skin_loss_coefficient_per_unit_area_to_ambient_temperature=d['skin_loss_W_m2K'],
      skin_loss_fraction_to_zone=1,peak_use_flow_rate=peak,
      use_flow_rate_fraction_schedule_name='hot_draw_fraction',use_side_effectiveness=1,
      use_side_inlet_height=0,use_side_outlet_height=d['height_m'],number_of_nodes=d['nodes'])]
    for name,key,variable in [('tank_top',tank,'Water Heater Temperature Node 1'),
       ('mains_sensor','Environment','Site Mains Water Temperature'),
       ('demand_sensor','mixed_demand_L_min','Schedule Value'),
       ('target_sensor','mixed_target','Schedule Value')]:
        rows.append(['EnergyManagementSystem:Sensor',name,key,variable])
    rows +=[['EnergyManagementSystem:Actuator','hot_draw_actuator','hot_draw_fraction','Schedule:Constant','Schedule Value'],
      ['EnergyManagementSystem:GlobalVariable','mixed_delivery_C','mixed_delivery_m3_s','hot_fraction_value'],
      ['EnergyManagementSystem:Program','mixing_valve',
       'SET hot_fraction_value = 0',
       'IF demand_sensor > 0',
       'IF tank_top > mains_sensor + 0.1',
       'SET hot_fraction_value = (target_sensor - mains_sensor) / (tank_top - mains_sensor)',
       'SET hot_fraction_value = @Min 1 hot_fraction_value',
       'SET hot_fraction_value = @Max 0 hot_fraction_value',
       'ELSE','SET hot_fraction_value = 1','ENDIF',
       'ENDIF',f'SET hot_draw_actuator = demand_sensor * hot_fraction_value / {peak*60000:.12g}',
       'SET mixed_delivery_C = mains_sensor + hot_fraction_value * (tank_top - mains_sensor)',
       'SET mixed_delivery_m3_s = demand_sensor / 60000'],
      ['EnergyManagementSystem:ProgramCallingManager','mixing_control','BeginTimestepBeforePredictor','mixing_valve'],
      ['EnergyManagementSystem:OutputVariable','Mixed Delivery Temperature','mixed_delivery_C','Averaged','ZoneTimestep','','C'],
      ['EnergyManagementSystem:OutputVariable','Mixed Delivery Flow','mixed_delivery_m3_s','Averaged','ZoneTimestep','','m3/s']]
    return {'tank_name':tank,'peak_hot_flow_m3_s':peak,
      'mixing_model':'explicit_EMS_mass_mixing_with_previous_zone_step_top_temperature',
      'mixing_lag_requires_timestep_check':True,'delivery_is_reference_not_reported_satisfaction':True}


def compile_case(case:dict,out:Path,engine:Path,selection:dict|None=None,*,sizing=False,mode='formal'):
    from .governance import guard_case
    guard_case(case,mode)
    engine=engine.resolve()
    import jsonschema
    jsonschema.Draft202012Validator(read(ROOT/'configs/CASE.schema.json'),
                                  format_checker=jsonschema.FormatChecker()).validate(case)
    require(not out.exists(),'OUTPUT_EXISTS',str(out));out.mkdir(parents=True)
    hashes=validate(case);f=Fields(engine/'Energy+.schema.epJSON')
    prototypes=read(ROOT/'configs/prototypes.json')['records']
    matches=[p for p in prototypes if p['id']==case['environment']['prototype_id']]
    require(len(matches)==1,'PROTOTYPE_NOT_REGISTERED');p=matches[0]
    require(p['conversion_admitted'],'PROTOTYPE_CONVERSION_NOT_ADMITTED')
    require(set(case['environment']['unit_zones'])==set(p['unit_zone_names']),
            'UNIT_CONFIGURATION_NOT_REGISTERED','register_and_verify_new_floor_or_exposure_combinations_separately')
    source=locked(p['converted'],ROOT);native=locked(p['source'],ROOT)
    audit_path=locked(p['conversion_audit'],ROOT)
    require(read(audit_path)['passed'],'PROTOTYPE_AUDIT_FAILED')
    require(case['environment']['site']['city']==p['city'],'CROSS_CITY_PROTOTYPE_NOT_ALLOWED')
    registry=[r for r in read(ROOT/'configs/weather_registry.json')['records']if r.get('status')=='acquired']
    # Exact registered identity, then location/terrain matching; there is no nearest-city fallback.
    matches=[r for r in registry if r['id']==case['environment']['weather_id']]
    require(len(matches)==1,'WEATHER_NOT_REGISTERED');w=matches[0]
    wm=weather_match(case['environment']['site'],[w],ROOT)
    require(wm['selected']==w['id'],'WEATHER_NOT_ADMITTED',wm)
    weather=locked(w,ROOT)
    original=parse(source.read_text())
    original=scale_geometry(original,case['environment']['xy_scale'],p['admitted_xy_scale_range'])
    rooms=read(audit_path)['source']['rooms'];storeys=read(audit_path)['source']['storeys']
    by_name={r['NAME']:r for r in rooms};by_storey={s['ID']:s for s in storeys}
    selected_storeys={by_name[z]['OF_STOREY']for z in case['environment']['unit_zones']}
    require(len(selected_storeys)==1,'SINGLE_STOREY_UNIT_REQUIRED')
    st=by_storey[next(iter(selected_storeys))];numbers=sorted(s['NO']for s in storeys)
    position='ground'if st['NO']==numbers[0]else'top'if st['NO']==numbers[-1]else'middle'
    if 'floor_position'in case['environment']:
        require(case['environment']['floor_position']==position,'DECLARED_FLOOR_POSITION_MISMATCH')
    rows,geometry=extract_unit(original,case['environment']['unit_zones'],f,
                              ground_model=case['environment'].get('ground_model'))
    geometry['floor_position']=position
    geometry['source_storey_multiplier']=st['MULTIPLE']
    geometry['source_equivalent_layer_not_identified_actual_floor']=True
    area_m2=sum(float(r[10])for r in objects(rows,'Zone'))
    geometry['source_thermal_floor_area_m2']=area_m2
    if 'area_m2'in case['environment']:
        require(abs(case['environment']['area_m2']-area_m2)<=max(.01,area_m2*.001),
                'AREA_OUTSIDE_SOURCE_DOMAIN',[case['environment']['area_m2'],area_m2])
    if not sizing:
        require(case['life']['maximum_persons']<=area_m2*case['design'].get('people_per_m2',.03)+1e-8,
                'INDEPENDENT_DESIGN_UPDATE_REQUIRED','declared_people_envelope_exceeded')
        require(case['life']['lighting_W_m2']<=case['design'].get('lighting_W_m2',6)
                and case['life']['misc_W_m2']<=case['design'].get('misc_W_m2',1),
                'INDEPENDENT_DESIGN_UPDATE_REQUIRED','internal_gain_envelope_exceeded')
    stress=case['environment'].get('parameter_stress',{})
    if stress:
        require(case['run'].get('purpose')=='registered_sensitivity','PARAMETER_STRESS_REQUIRES_PROTOCOL')
        for k,v in stress.items():require(k in ('material_mass_scale','material_conductivity_scale','window_SHGC_scale','hvac_power_scale','defrost_eir_scale')
                                         and .5<=v<=1.5,'PARAMETER_STRESS_DOMAIN',k)
        for row in rows:
            if row[0]=='Material':
                row[4]=float(row[4])*stress.get('material_conductivity_scale',1)
                row[6]=float(row[6])*stress.get('material_mass_scale',1)
            elif row[0]=='WindowMaterial:SimpleGlazingSystem':
                row[3]=float(row[3])*stress.get('window_SHGC_scale',1)
                require(0<=row[3]<=1,'STRESS_SHGC_OUT_OF_RANGE')
    schedules,ledger=compile_schedules(case)
    design_days=[]
    if sizing:
        for info in w.get('design_day_files',[]):
            ddy=locked(info,ROOT)
            all_days=objects(parse(ddy.read_text(errors='replace')),'SizingPeriod:DesignDay')
            heating=[d for d in all_days if 'Htg'in d[1]and'99.6'in d[1]]
            cooling=[d for d in all_days if 'Clg'in d[1]and '.4%'in d[1]and'DB=>MWB'in d[1]]
            if heating and cooling:design_days=[heating[0],cooling[0]];break
        require(len(design_days)==2,'DESIGN_DAYS_REQUIRED')
        schedules['heat_sp'][:]=case['design']['heating_C']
        schedules['cool_sp'][:]=case['design']['cooling_C']
        schedules['hvac_available'][:]=1
        # Independent design gains, never reuse operating appliance times or control proposals.
        for name in list(schedules):
            if name.startswith(('people_','light_')) or name.endswith('_power_W') or name in ('mixed_demand_L_min','dryer_running'):
                schedules[name][:]=0
        cooling_day=design_days[1]
        day=(dt.date(2025,int(cooling_day[2]),int(cooling_day[3]))-dt.date(2025,1,1)).days
        source_zones={r[1]:r for r in objects(rows,'Zone')}
        for z in source_zones:
            schedules['people_'+z][day*144:(day+1)*144]=float(source_zones[z][10])*case['design'].get('people_per_m2',.03)
            schedules['activity_'+z][:]=108
            schedules['light_'+z][day*144:(day+1)*144]=1
    start=dt.date.fromisoformat(case['run']['start_date']);end=dt.date.fromisoformat(case['run']['end_date'])
    building=copy.deepcopy(one(rows,'Building'));building[1]=case['case_id']
    f.set(building,'maximum_number_of_warmup_days',case['run']['warmup_max_days'])
    f.set(building,'minimum_number_of_warmup_days',case['run']['warmup_min_days'])
    rows=[r for r in rows if r[0]not in ('Building','Version')]
    engine_pin=read(ROOT/'configs/engine.json')
    rows +=[['Version',engine_pin.get('idf_version','24.1')],building,
      ['Timestep',60//case['run']['solver_step_min']],
      ['ZoneAirHeatBalanceAlgorithm','AnalyticalSolution'],
      ['SimulationControl','No','No','No','Yes'if sizing else'No','No'if sizing else'Yes'],
      ['RunPeriod',case['case_id'],start.month,start.day,start.year,end.month,end.day,end.year,
       start.strftime('%A'),'No','No','No','Yes','Yes'],
      ['ScheduleTypeLimits','AnyNumber'],['ScheduleTypeLimits','ControlType',0,4,'Discrete'],
      ['Schedule:Constant','dual_control','ControlType',4],
      ['Schedule:Constant','outdoor_co2_ppm','AnyNumber',case['environment'].get('outdoor_co2_ppm',420)],
      ['ZoneAirContaminantBalance','Yes','outdoor_co2_ppm','No'],
      ['Output:SQLite','SimpleAndTabular'],['Output:Table:SummaryReports','AllSummary'],
      ['Output:VariableDictionary','IDF'],['Output:Diagnostics','DisplayExtraWarnings']]
    rows+=design_days
    rows.append(f.obj('OutputControl:Files',output_csv='No',output_mtr='No',output_eso='No',
      output_eio='Yes',output_sqlite='Yes',output_rdd='Yes',output_mdd='Yes',output_end='Yes'))
    schedule_names=sorted(schedules)
    csvpath=out/'schedules.csv'
    matrix=np.column_stack([schedules[k]for k in schedule_names])
    np.savetxt(csvpath,matrix,delimiter=',',fmt='%.9g',header=','.join(schedule_names),comments='')
    for col,name in enumerate(schedule_names,1):
        rows.append(f.obj('Schedule:File',name=name,schedule_type_limits_name='AnyNumber',
          file_name=str(csvpath.resolve()),column_number=col,rows_to_skip_at_top=1,
          number_of_hours_of_data=8760,column_separator='Comma',interpolate_to_timestep='No',minutes_per_item=10,
          adjust_schedule_for_daylight_savings='No'))
    zones={r[1]:r for r in objects(rows,'Zone')}
    for z,zr in zones.items():
        rows +=[f.obj('People',name='people_'+z,zone_or_zonelist_or_space_or_spacelist_name=z,
          number_of_people_schedule_name='people_'+z,number_of_people_calculation_method='People',
          number_of_people=1,fraction_radiant=.3,sensible_heat_fraction='Autocalculate',
          activity_level_schedule_name='activity_'+z,carbon_dioxide_generation_rate=3.82e-8),
          ['Lights','lights_'+z,z,'light_'+z,'Watts/Area','',case['design'].get('lighting_W_m2',6)if sizing else case['life']['lighting_W_m2'],'',0,.4,.2,1,'target_lighting'],
          ['ElectricEquipment','misc_'+z,z,'light_'+z,'Watts/Area','',case['design'].get('misc_W_m2',1)if sizing else case['life']['misc_W_m2'],'',0,.3,0,'target_misc'],
          ['ZoneInfiltration:DesignFlowRate','infiltration_'+z,z,'always','AirChanges/Hour','','','',
           case['environment']['reference_ach'],1,0,0,0]]
    devices=case['environment']['devices'];equipment={};profile=performance_reference()
    controlled=devices['air_conditioner']['room_ids']
    if sizing:
        for z in controlled:
            rows +=[f.obj('ZoneHVAC:IdealLoadsAirSystem',name='sizing_'+z,availability_schedule_name='always',
              zone_supply_air_node_name=z+'_supply',maximum_heating_supply_air_temperature=50,
              minimum_cooling_supply_air_temperature=12,maximum_heating_supply_air_humidity_ratio=.015,
              minimum_cooling_supply_air_humidity_ratio=.009,heating_limit='NoLimit',cooling_limit='NoLimit',
              dehumidification_control_type='None',humidification_control_type='None'),
              ['ZoneHVAC:EquipmentList',z+'_equipment','SequentialLoad','ZoneHVAC:IdealLoadsAirSystem','sizing_'+z,1,1],
              ['ZoneHVAC:EquipmentConnections',z,z+'_equipment',z+'_supply','',z+'_air',z+'_return'],
              ['ThermostatSetpoint:DualSetpoint',z+'_thermostat','heat_sp','cool_sp'],
              ['ZoneControl:Thermostat',z+'_control',z,'dual_control','ThermostatSetpoint:DualSetpoint',z+'_thermostat']]
    else:
        require(selection is not None,'SIZING_RECEIPT_REQUIRED')
        require(selection['design_environment_hash']==hashes['design_inputs_hash'],'SIZING_INPUTS_CHANGED')
        for z in controlled:
            new,receipt=hvac(z,selection['zones'][z],f,profile,devices['air_conditioner'],stress);rows+=new;equipment[z]=receipt
        require(not objects(rows,'ZoneHVAC:IdealLoadsAirSystem'),'IDEAL_HEATING_IN_OPERATIONAL_MODEL')
    for name in ['washer','dryer','dishwasher']:
        d=devices[name]
        rows +=[['ElectricEquipment','target_'+name,d['room_id'],name+'_power_W','EquipmentLevel',1,'','',
                 d['latent_fraction'],d['radiant_fraction'],d['lost_fraction'],'target_'+name]]
    if devices['dryer']['technology']=='vented':
        d=devices['dryer'];flow=d['exhaust_flow_m3_s']
        rows +=[f.obj('Fan:ZoneExhaust',name='target_dryer_exhaust',availability_schedule_name='dryer_running',
          fan_total_efficiency=.6,pressure_rise=d['fan_input_W']*.6/flow,maximum_flow_rate=flow,
          air_inlet_node_name='dryer_exhaust_inlet',air_outlet_node_name='dryer_exhaust_outlet',
          end_use_subcategory='target_dryer_exhaust'),
          f.obj('ZoneAirMassFlowConservation',adjust_zone_mixing_and_return_for_air_mass_flow_balance='AdjustMixingOnly',
          infiltration_balancing_method='AddInfiltrationFlow',infiltration_balancing_zones='AllZones')]
        # A standalone exhaust fan is still zone equipment; do not leave its inlet unbound.
        z=d['room_id'];eq=next((r for r in objects(rows,'ZoneHVAC:EquipmentList')if r[1]==z+'_equipment'),None)
        if eq is None:
            rows +=[['ZoneHVAC:EquipmentList',z+'_equipment','SequentialLoad','Fan:ZoneExhaust','target_dryer_exhaust',1,1],
              ['ZoneHVAC:EquipmentConnections',z,z+'_equipment','','dryer_exhaust_inlet',z+'_air','']]
        else:
            eq.extend(['','','Fan:ZoneExhaust','target_dryer_exhaust',2,2])
            conn=next(r for r in objects(rows,'ZoneHVAC:EquipmentConnections')if r[1]==z)
            existing=conn[4];rows.append(['NodeList',z+'_all_exhaust_nodes',existing,'dryer_exhaust_inlet'])
            conn[4]=z+'_all_exhaust_nodes'
    # Lost EV heat is outside the dwelling; its electricity remains on the target meter.
    rows +=[['ElectricEquipment','target_ev',devices['air_conditioner']['room_ids'][0],
             'ev_power_W','EquipmentLevel',1,'','',0,0,1,'target_ev']]
    weather_report=wm['considered'][0]['audit'];means=weather_report['daily_mean_dry_C']
    daily_by_month={m:[v for k,v in means.items()if int(k[:2])==m]for m in range(1,13)}
    annual_mean=float(np.mean(list(means.values())))
    monthly=[float(np.mean(v))for v in daily_by_month.values()]
    rows +=[['Site:WaterMainsTemperature','Correlation','',annual_mean,max(monthly)-min(monthly)]]
    tank=None if sizing else add_tank(rows,f,case,schedules)
    frequency=case['run']['reporting']
    variables=['Site Outdoor Air Drybulb Temperature','Site Mains Water Temperature',
      'Facility Total Electricity Demand Rate',
      'Zone Mean Air Temperature','Zone Air Relative Humidity','Zone Air CO2 Concentration','Zone People Occupant Count',
      'Zone Air Heat Balance Internal Convective Heat Gain Rate','Zone Air Heat Balance Surface Convection Rate',
      'Zone Air Heat Balance Interzone Air Transfer Rate','Zone Air Heat Balance Outdoor Air Transfer Rate',
      'Zone Air Heat Balance System Air Transfer Rate','Zone Air Heat Balance System Convective Heat Gain Rate',
      'Zone Air Heat Balance Air Energy Storage Rate',
      'Zone Infiltration Mass Flow Rate','Zone Infiltration Sensible Heat Gain Energy',
      'Zone Infiltration Sensible Heat Loss Energy','Electric Equipment Electricity Energy',
      'Lights Electricity Energy','Water Heater Electricity Energy','Water Heater Use Side Heat Transfer Energy',
      'Water Heater Heating Energy','Water Heater Heat Loss Energy','Water Heater Net Heat Transfer Energy',
      'Water Heater Source Side Heat Transfer Energy','Water Heater Venting Heat Transfer Energy',
      'Water Heater Off Cycle Parasitic Tank Heat Transfer Energy','Water Heater On Cycle Parasitic Tank Heat Transfer Energy',
      'Water Heater Use Side Mass Flow Rate','Water Heater Use Side Outlet Temperature',
      'Water Heater Temperature Node 1','Water Heater Temperature Node 6',
      'Mixed Delivery Temperature','Mixed Delivery Flow']
    if sizing:variables+=['Zone Ideal Loads Supply Air Sensible Heating Rate','Zone Ideal Loads Supply Air Total Cooling Rate']
    else:variables+=['Heating Coil Electricity Energy','Cooling Coil Electricity Energy',
      'Fan Electricity Energy','Heating Coil Heating Energy','Cooling Coil Total Cooling Energy',
      'Heating Coil Defrost Electricity Energy','Heating Coil Runtime Fraction','Cooling Coil Runtime Fraction']
    water_fine={'Site Mains Water Temperature','Water Heater Use Side Mass Flow Rate',
      'Water Heater Use Side Outlet Temperature','Mixed Delivery Temperature','Mixed Delivery Flow',
      'Water Heater Temperature Node 1','Water Heater Temperature Node 6'}
    if sizing:variables=[v for v in variables if not v.startswith(('Water Heater','Mixed Delivery'))]
    for variable in variables:rows +=[['Output:Variable','*',variable,'Timestep'if variable in water_fine or variable=='Facility Total Electricity Demand Rate'else frequency]]
    if not sizing:rows +=[['Output:Variable','hot_draw_fraction','Schedule Value','Timestep']]
    for name in ['heat_sp','cool_sp','hvac_available']:rows +=[['Output:Variable',name,'Schedule Value',frequency]]
    airflow={'model':'prescribed_infiltration','reference_ach':case['environment']['reference_ach']}
    require(case['environment']['airflow_model']in ('prescribed_infiltration','pressure_network'),
            'UNSUPPORTED_AIRFLOW_MODEL')
    if case['environment']['airflow_model']=='pressure_network':
        rows,airflow=pressure_network(rows,f,case['environment']['reference_ach'])
        for variable in ['AFN Zone Infiltration Mass Flow Rate','AFN Zone Mixing Mass Flow Rate',
                         'AFN Linkage Node 1 to Node 2 Mass Flow Rate','AFN Linkage Node 2 to Node 1 Mass Flow Rate']:
            rows +=[['Output:Variable','*',variable,frequency]]
    rows +=[['Output:Meter',m,frequency]for m in ['Electricity:Facility','Heating:Electricity',
      'Cooling:Electricity','Fans:Electricity','WaterSystems:Electricity',
      'InteriorEquipment:Electricity','InteriorLights:Electricity']]
    if not sizing:
        for sub in ['target_washer','target_dryer','target_dishwasher','target_ev','target_misc']:
            rows +=[['Output:Meter',sub+':InteriorEquipment:Electricity',frequency]]
    (out/'model.idf').write_text(render(rows))
    save(out/'case.json',case);save(out/'execution_ledger.json',ledger)
    receipt={'schema':'national_idf.compilation.v1','case_id':case['case_id'],**hashes,
      'execution_mode':'engineering_reference','formal_admitted':False,
      'historical_lineage':'archive/pre_governance_20261023/SNAPSHOT.json',
      'mode':'ideal_load_sizing_diagnostic_only'if sizing else'operational_six_devices',
      'source_native_sha256':sha(native),'source_converted_sha256':sha(source),
      'prototype_audit_sha256':sha(audit_path),'weather':{'path':str(weather),'sha256':sha(weather),
        'identity':weather_report['identity'],'registry_record':w},
      'geometry':geometry,'equipment':equipment,'water_heater':tank,'profile':profile,
      'airflow':airflow,
      'parameter_stress':stress,'initial_state_basis':'native_warmup;not_asserted_observed_initial_temperature',
      'model_sha256':sha(out/'model.idf'),'schedules_sha256':sha(csvpath),
      'engine_schema_sha256':sha(engine/'Energy+.schema.epJSON'),
      'engine_idd_sha256':sha(engine/'Energy+.idd'),'expected_engine_sha256':sha(engine/'energyplus'),
      'engine_overlay_identity':digest(engine_pin.get('numerical_patch')),
      'sizing_design_days':[{'name':d[1],'outdoor_design_C':float(d[5])}for d in design_days],
      'code_identity':code_identity(),'selection':selection,'run':case['run'],
      'unvalidated_assumptions':['prescribed_neighbor_temperature','source_unit_membership_is_engineering_declaration',
        'infiltration_0.35ACH_not_measured','appliance_phase_powers_and_heat_fractions',
        'generic_variable_speed_and_defrost_map','manufacturer_reference_not_China_market_calibration',
        'mixing_valve_one_zone_step_lag'],
      'source_native_energy_comparison':'not_available','empirical_calibration':False,
      'family_or_AB_generator_imported':False,'human_labels_created':0}
    save(out/'COMPILATION.json',receipt)
    for module in (ROOT/'national_idf').glob('*.py'):
        destination=out/'_code'/module.name;destination.parent.mkdir(exist_ok=True)
        destination.write_bytes(module.read_bytes())
    seal(out,{'schema':'national_idf.compiled_manifest.v1','compilation_sha256':sha(out/'COMPILATION.json')})
    return receipt
