"""Reversible EB heat-pump resources and actual EnergyPlus component rows.

The V33 master stays sealed. Derived A worlds retain all geometry and rosters,
add pinned native heating performance, and reprovision reference electrical
branches. Neither this module nor the A generator claims a physical result.
"""
import copy
import re
from common import *

NATIVE=REPO/'upstream_2b17ae6/experiments/models/family_home/family_simple_3day.idf'
SCHEMA_PATH=EP_SCHEMA
SCHEMA=read(SCHEMA_PATH)['properties']
ROWS=[[x.strip()for x in s.split(',')]for s in re.sub(r'!.*','',NATIVE.read_text()).split(';')if s.strip()]

def get(row,key):return row[SCHEMA[row[0]]['legacy_idd']['fields'].index(key)+1]
def put(row,key,value):
    index=SCHEMA[row[0]]['legacy_idd']['fields'].index(key)+1;row.extend(['']*max(0,index+1-len(row)));row[index]=value
def obj(kind,values):
    fields=SCHEMA[kind]['legacy_idd']['fields'];last=max(fields.index(k)for k in values)
    return [kind]+[values.get(f,'')for f in fields[:last+1]]
def native(kind):return copy.deepcopy(next(r for r in ROWS if r[0]==kind))

def configure(old):
    w=copy.deepcopy(old);w['source_V33_world_content_sha256']=old['world_content_sha256'];w.pop('world_content_sha256',None)
    w['source_V33_routine']=copy.deepcopy(old['routine'])
    w['source_V33_generation_manifest']=copy.deepcopy(old['generation_manifest'])
    cooling=native('Coil:Cooling:DX:SingleSpeed');heating=native('Coil:Heating:DX:SingleSpeed');supp=native('Coil:Heating:Electric')
    for d in w['parameter_pack']['devices']:
        if'ac'not in d['types']:continue
        p=d['parameters'];scale=p['cooling_W']/float(get(cooling,'gross_rated_total_cooling_capacity'))
        p['heating']={'capacity_W':float(get(heating,'gross_rated_heating_capacity'))*scale,
            'gross_rated_COP':float(get(heating,'gross_rated_heating_cop')),
            'flow_m3_s':float(get(heating,'rated_air_flow_rate'))*scale,
            'supplemental_electric_W':float(get(supp,'nominal_capacity'))*scale,
            'crankcase_heater_W':float(get(heating,'crankcase_heater_capacity'))*scale,
            'minimum_compressor_outdoor_C':float(get(heating,'minimum_outdoor_dry_bulb_temperature_for_compressor_operation')),
            'native_IDF_sha256':sha(NATIVE),'scale':scale,'capacity_ratio_and_COP_from_pinned_EB':True}
        fan=p['rated_electric_W']-p['cooling_W']/p['gross_rated_COP']
        nominal=p['heating']['capacity_W']/p['heating']['gross_rated_COP']+p['heating']['supplemental_electric_W']+max(0.,fan)
        d['max_electric_kw']=max(d['max_electric_kw'],nominal/1000)
        d['model_family']='EB reversible DX heat-pump reference with native electric supplemental heat'
        d['max_power_status']='reference rating plus full supplemental heater;offdesign peak needs actual EP readback'
    # A16/17-year-old can have explicitly given household appliance duties;
    # this grants no driving licence, control consent or additional B willingness.
    existing={o['operator_id']for o in w['operating_context']['operators']};new_duties=[]
    for m in w['members']:
        if 16<=m['age_years']<18 and m['member_id']not in existing:
            w['operating_context']['operators'].append({'operator_id':m['member_id'],'resident':True,'presence_windows_min':None,
                'appliance_handling_capability_given':True,'evidence':'explicit routine household duty;not inferred licence,preference or B consent',
                'driving_authorization_granted':False,'willingness_to_handle_extra_operations':None})
            new_duties.append({'person_id':m['member_id'],'age':m['age_years'],'routine_appliance_duty_given':True,'driving_authorization_granted':False})
    # Reuse the explicit reference-supply design; heating is no longer hidden
    # in an unmetered ideal-load18C service in rooms served by target AC.
    limits={};branches=[]
    for d in w['parameter_pack']['devices']:
        amps=next(a for a in(10,16,20,25,32,40,63,80)if .220*a>=d['max_electric_kw'])
        limits[d['circuit']]=.220*amps;branches.append({'asset_id':d['asset_id'],'branch':d['circuit'],'reference_current_A':amps,
            'rated_reference_max_kW':d['max_electric_kw'],'on_target_dwelling_main':d['circuit']!='EV_bay'})
    peak=sum(d['max_electric_kw']for d in w['parameter_pack']['devices']if d['circuit']!='EV_bay')+w['parameter_pack']['background_reserved_kw']
    amps=next(a for a in(40,60,80,100,125,160,200,250,315,400,500)if .220*a>=peak)
    w['parameter_pack'].update(circuit_limit_kw=limits,home_service_limit_kw=.220*amps)
    w['installation_contract'].update(dwelling_main_A=amps,connected_reference_peak_kW=peak,branches=branches,
        heating_supply_reprovisioned_as_reference_design=True,actual_installed_supply_observed=False)
    w['normal_A_contract']={'all_owned_functional_classes_daily':True,'daily_mobility_task_given':True,
        'daily_mobility_is_not_a_population_travel_estimate':True,
        'HVAC_modes':['cooling','heating','recirculation_fan'],'usual_heating_setpoint_C':22.,
        'heating_setpoint_evidence':'explicit common winter22C condition,anchored to EB actuator initial22C;not inferred winter preference',
        'source_dates_preserved':True,'new_context_is_declared_daily_benchmark_not_observed_diary':True}
    w['activity_contract'].update(schema='eb.daily_benchmark_activity.v34',
        new_daily_mobility_task='explicit common benchmark demand;existing work/school preserved;otherwise uses a free episode',
        obsolete_weekly_examples_removed=True)
    w['activity_contract']['cooling_reference_modes'].update(awake_setpoint_C=w['role_policy']['thermal']['usual_setpoint_C'],sleep_setpoint_C=w['role_policy']['thermal']['usual_setpoint_C'])
    w['background_context']['normal_A_daily_task_condition']='all configured classes used daily under explicit benchmark tasks;not an observed natural daily-use frequency'
    w['background_context']['routine_teen_appliance_duties']=new_duties
    w['routine'].update(wash_days=list(range(7)),wash_alternate_week_phase=None,wash_batches_each_active_day=1,
        wash_count_reference_per_week=7,additional_batches_rule='actual remaining daily textile mass above4.5kg;not a fixed observed count',
        frequency_rule='user-given daily benchmark task;original transported frequency is retained in source_V33_routine only',
        time_source='V34 dated daily task calendars and continuous annual_A file;old weekly examples removed')
    for m in w['members']:
        m.pop('weekly_calendar',None);m.pop('daily_reference_specs',None)
    for o in w['operating_context']['operators']:o.pop('weekly_windows_min',None)
    w['routine'].pop('weekly_family_context',None)
    w['shared_context'].pop('dated_examples',None)
    if'given_transport_contract'in w:
        t=w['given_transport_contract']
        t['daily_mobility_task_given']=True
        if not t['driver_is_resident']:
            t['external_service_windows_min']=[[360,1320]]
            t['external_service_coverage']='explicit daily benchmark mobility support,06:00–22:00;not an observed service or a generic appliance helper'
        w['given_external_services']['transport_driver']=copy.deepcopy(t)
        for d in w['parameter_pack']['devices']:
            if'ev'in d['types']:d['installation']['trip_source']='explicit V34 daily mobility benchmark task;not inferred observed commuting'
    w['schema']='eb.normal_A_resource_world.v34'
    w['generation_manifest']={'stage':'normal_A_daily_task_resources','rules_sha256':rules_id(),
        'source_V33_world_content_sha256':old['world_content_sha256'],'native_HVAC_source_sha256':sha(NATIVE),
        'human_answers_consulted':False,'B_or_price_event_consulted':False}
    w['downstream_status']={'A':'join this V34 worlds file to annual_A and cases via current A bindings',
        'B':'must_generate_from_new_A','simulation':'new reversible HVAC compilation and physical validation pending',
        'questionnaire':'must_rebuild_after_physics','old_answers':'preserved with original stimuli;not relabelled'}
    w['parameter_pack_sha256']=digest(w['parameter_pack']);w['world_content_sha256']=digest(w)
    return w

def components(w):
    result=[]
    for d in w['parameter_pack']['devices']:
        if'ac'not in d['types']:continue
        q=d['parameters'];h=q['heating'];prefix='v34_'+digest(d['asset_id'])[:12]
        names={k:prefix+'_'+k for k in('available','cool_sp','heat_sp','fan_mode')}
        curves={r[1]:prefix+'_'+r[1]for r in ROWS if r[0].startswith('Curve:')}
        rows=[[curves.get(v,v)for v in r]for r in ROWS if r[0].startswith('Curve:')]
        fan=native('Fan:OnOff');fan[1]=prefix+'_fan'
        for key,value in {'availability_schedule_name':names['available'],'maximum_flow_rate':q['flow_m3_h']/3600,
                          'air_inlet_node_name':prefix+'_mixed','air_outlet_node_name':prefix+'_fan_out','end_use_subcategory':'target_AC_fan'}.items():put(fan,key,value)
        cool=native('Coil:Cooling:DX:SingleSpeed');cool[1]=prefix+'_cool'
        for key,value in {'availability_schedule_name':names['available'],'gross_rated_total_cooling_capacity':q['cooling_W'],
            'gross_rated_cooling_cop':q['gross_rated_COP'],'rated_air_flow_rate':q['flow_m3_h']/3600,
            'air_inlet_node_name':prefix+'_fan_out','air_outlet_node_name':prefix+'_cool_out'}.items():put(cool,key,value)
        heat=native('Coil:Heating:DX:SingleSpeed');heat[1]=prefix+'_heat'
        for key,value in {'availability_schedule_name':names['available'],'gross_rated_heating_capacity':h['capacity_W'],
            'gross_rated_heating_cop':h['gross_rated_COP'],'rated_air_flow_rate':h['flow_m3_s'],
            'crankcase_heater_capacity':h['crankcase_heater_W'],
            'air_inlet_node_name':prefix+'_cool_out','air_outlet_node_name':prefix+'_heat_out'}.items():put(heat,key,value)
        supp=native('Coil:Heating:Electric');supp[1]=prefix+'_supp'
        for key,value in {'availability_schedule_name':names['available'],'nominal_capacity':h['supplemental_electric_W'],
            'air_inlet_node_name':prefix+'_heat_out','air_outlet_node_name':prefix+'_supply'}.items():put(supp,key,value)
        rows+=[fan,[curves.get(v,v)for v in cool],[curves.get(v,v)for v in heat],supp]
        rows+=[obj('OutdoorAir:Mixer',{'name':prefix+'_mixer','mixed_air_node_name':prefix+'_mixed','outdoor_air_stream_node_name':prefix+'_outside',
                    'relief_air_stream_node_name':prefix+'_relief','return_air_stream_node_name':prefix+'_return'}),['OutdoorAir:Node',prefix+'_outside',-1]]
        rows.append(obj('ZoneHVAC:PackagedTerminalHeatPump',{'name':prefix+'_unit','availability_schedule_name':names['available'],
            'air_inlet_node_name':prefix+'_return','air_outlet_node_name':prefix+'_supply','outdoor_air_mixer_object_type':'OutdoorAir:Mixer',
            'outdoor_air_mixer_name':prefix+'_mixer','cooling_supply_air_flow_rate':q['flow_m3_h']/3600,
            'heating_supply_air_flow_rate':h['flow_m3_s'],'no_load_supply_air_flow_rate':q['flow_m3_h']/3600,
            'cooling_outdoor_air_flow_rate':0,'heating_outdoor_air_flow_rate':0,'no_load_outdoor_air_flow_rate':0,
            'supply_air_fan_object_type':'Fan:OnOff','supply_air_fan_name':prefix+'_fan',
            'heating_coil_object_type':'Coil:Heating:DX:SingleSpeed','heating_coil_name':prefix+'_heat',
            'cooling_coil_object_type':'Coil:Cooling:DX:SingleSpeed','cooling_coil_name':prefix+'_cool',
            'supplemental_heating_coil_object_type':'Coil:Heating:Electric','supplemental_heating_coil_name':prefix+'_supp',
            'maximum_supply_air_temperature_from_supplemental_heater':50,
            'maximum_outdoor_dry_bulb_temperature_for_supplemental_heater_operation':10,
            'fan_placement':'BlowThrough','supply_air_fan_operating_mode_schedule_name':names['fan_mode']}))
        result.append({'asset_id':d['asset_id'],'room_id':d['room_id'],'rows':rows,'schedule_names':names,
            'zone_supply_node':prefix+'_supply','zone_return_node':prefix+'_return','equipment_name':prefix+'_unit',
            'electricity_outputs_required':['Heating Coil Electricity Energy','Cooling Coil Electricity Energy','Fan Electricity Energy'],
            'ideal_heating_allowed_in_this_AC_room':False,'complete_occupied_IDF_compilation_and_EP_validation':'pending'})
    return result
