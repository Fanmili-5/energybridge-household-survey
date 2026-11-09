"""Replaceable engineering life/controls, never sampled household behavior."""
from __future__ import annotations
import calendar
import datetime as dt
import numpy as np
from .common import require, digest
from .devices import validate_devices, program_profile, ev_ledger


def engineering_fixture(prototype_id,weather_id,site,zones):
    living,bed1,bed2,bed3,kitchen,bath1,bath2=(zones[i]for i in [4,0,2,3,6,1,5])
    common={'evidence_class':'declared_design','internal_water_heating':True,
      'water_connection':'cold_self_heated','latent_fraction':.03,'radiant_fraction':.1,'lost_fraction':.6}
    devices={
      'air_conditioner':{'evidence_class':'derived_reference','profile_id':'FS12_manufacturer_maximum_points_reference',
        'room_ids':[living,bed1,bed2,bed3],'supplemental_heat_W':0,
        'control':'EnergyPlus_variable_speed_reference;not_OEM_control_replica'},
      'washer':{**common,'room_id':bath1,'phases':[{'duration_min':10,'power_W':100,'water_L':20},
        {'duration_min':20,'power_W':1800,'water_L':0},{'duration_min':30,'power_W':120,'water_L':30}]},
      'dryer':{**common,'room_id':bath2,'technology':'condensing','water_connection':'none',
        'internal_water_heating':False,'lost_fraction':.1,'latent_fraction':.02,
        'phases':[{'duration_min':10,'power_W':1800},{'duration_min':60,'power_W':1600},
                  {'duration_min':10,'power_W':150}]},
      'dishwasher':{**common,'room_id':kitchen,'phases':[{'duration_min':10,'power_W':100,'water_L':4},
        {'duration_min':20,'power_W':1500},{'duration_min':40,'power_W':90,'water_L':6},
        {'duration_min':20,'power_W':1000}]},
      'water_heater':{'evidence_class':'declared_design','room_id':bath2,'volume_m3':.12,
        'height_m':1.0,'heater_W':3000,'efficiency':.98,'skin_loss_W_m2K':1.0,
        'nodes':6,'target_C':55,'mixed_target_C':40,'minimum_delivery_C':38},
      'ev':{'evidence_class':'declared_design','room_id':None,'meter_scope':'target_dwelling',
        'capacity_kWh':60,'initial_SOC':.7,'charger_kW':7,'efficiency':.9,'minimum_SOC':.2}}
    return {'schema':'national_idf.case.v1','case_id':weather_id+'-engineering',
      'environment':{'prototype_id':prototype_id,'weather_id':weather_id,'site':site,
        'xy_scale':1,'unit_zones':zones,'area_basis':'source_thermal_floor_area',
        'supply_capacity_W':25000,'supply_capacity_is_design':True,
        'neighbors':{'winter_C':20,'summer_C':26,'shoulder_C':22,'basis':'declared_conditioned_neighbor_reference'},
        'reference_ach':.35,'airflow_model':'prescribed_infiltration',
        'devices':devices},
      'life':{'basis':'fixed_engineering_test_schedule;not_final_household_generation',
        'maximum_persons':3,'occupancy':[{'room_id':bed1,'start_min':0,'end_min':420,'persons':2,'activity_W':72},
          {'room_id':bed1,'start_min':1320,'end_min':1440,'persons':2,'activity_W':72},
          {'room_id':bed2,'start_min':0,'end_min':420,'persons':1,'activity_W':72},
          {'room_id':bed2,'start_min':1320,'end_min':1440,'persons':1,'activity_W':72},
          {'room_id':living,'start_min':1080,'end_min':1320,'persons':3,'activity_W':108}],
        'lighting_W_m2':6,'misc_W_m2':1,'people_values_basis':'EnergyPlus_adult_reference;activity_mapping_is_design',
        'services_daily':{'washer':{'cycles':1,'release_min':420,'deadline_min':1440},
          'dryer':{'cycles':1,'release_min':420,'deadline_min':1440},
          'dishwasher':{'cycles':1,'release_min':1080,'deadline_min':1440}},
        'mixed_water_daily':[{'start_min':420,'duration_min':10,'liters':40},
          {'start_min':1230,'duration_min':10,'liters':40},{'start_min':1260,'duration_min':10,'liters':40}],
        'ev_daily':{'departure_min':480,'return_min':1080,'traction_kWh':8,'required_departure_SOC':.5}},
      'controls':{'basis':'fixed_component_exerciser;not_final_A_or_B_strategy',
        'heating_C':20,'cooling_C':26,'hvac_available':True,'daily_overrides':[],'dated_overrides':[],
        'tank_target_C':55,'ev_target_SOC':.8,
        'program_starts_daily':{'washer':[1080],'dryer':[1150],'dishwasher':[1260]},
        'program_start_overrides':{},'ev_daily_windows':[{'start_min':0,'end_min':1440}],
        'ev_window_overrides':{}},
      'run':{'start_date':'2025-01-01','end_date':'2025-12-31','solver_step_min':5,
        'reporting':'Hourly','zone_air_algorithm':'AnalyticalSolution','warmup_min_days':14,'warmup_max_days':60},
      'design':{'basis':'independent_design_conditions_and_fixed_design_gains;not_selected_AB_outcomes',
        'heating_C':20,'cooling_C':26,'margin':1.1,'max_units_per_zone':8}}


def validate(case):
    require(case.get('schema')=='national_idf.case.v1','CASE_SCHEMA')
    require(set(case)>={'environment','life','controls','run','design'},'THREE_INPUT_SECTIONS_REQUIRED')
    # Field-level source availability is checked by the compiler, not guessed here.
    e,l,c,r=case['environment'],case['life'],case['controls'],case['run']
    validate_devices(e['devices'])
    for name in ['washer','dryer','dishwasher','water_heater']:
        require(e['devices'][name]['room_id']in e['unit_zones'],'DEVICE_ROOM_UNKNOWN',name)
    require(set(e['devices']['air_conditioner']['room_ids'])<=set(e['unit_zones']),'HVAC_ROOM_UNKNOWN')
    require(c['heating_C']<c['cooling_C'],'CROSSED_SETPOINTS')
    require(r['solver_step_min']in (1,2,5,10,15),'SOLVER_STEP')
    require(r['reporting']in ('Hourly','Timestep'),'REPORTING_FREQUENCY')
    require(r.get('zone_air_algorithm','AnalyticalSolution')=='AnalyticalSolution','ZONE_AIR_ALGORITHM_NOT_ADMITTED')
    begin=dt.date.fromisoformat(r['start_date']);end=dt.date.fromisoformat(r['end_date'])
    require(begin<=end and begin.year==end.year and not calendar.isleap(begin.year),'RUN_CALENDAR_SUPPORTED')
    for field in ['program_start_overrides','ev_window_overrides']:
        for date,value in c.get(field,{}).items():
            require(dt.date.fromisoformat(date).year==begin.year,'CONTROL_DATE_OUTSIDE_CALENDAR',date)
            if field=='program_start_overrides':require(set(value)<={'washer','dryer','dishwasher'},'UNKNOWN_PROGRAM_COMMAND')
    starts=c.get('program_starts_daily',l.get('programs_daily',{}))
    require(set(starts)=={'washer','dryer','dishwasher'},'PROGRAM_START_COMMANDS_REQUIRED')
    for daily in [starts,*c.get('program_start_overrides',{}).values()]:
        for values in daily.values():
            require(all(isinstance(v,int)and 0<=v<1440 and v%10==0 for v in values),'PROGRAM_DAILY_START_GRID')
    people=np.zeros(1440)
    for p in l['occupancy']:
        require(p['room_id']in e['unit_zones']and 0<=p['start_min']<p['end_min']<=1440
                and p['start_min']%10==0 and p['end_min']%10==0
                and p['persons']>=0 and p['activity_W']>0,'OCCUPANCY_EVENT')
        people[p['start_min']:p['end_min']]+=p['persons']
    require(float(people.max())<=l['maximum_persons'],'PERSON_DOUBLE_COUNT')
    require(r['warmup_max_days']>=r['warmup_min_days'],'WARMUP_INTERVAL')
    return {'environment_hash':digest(e),'life_hash':digest(l),'controls_hash':digest(c),
            'design_inputs_hash':digest({'environment':e,'design':case['design']})}


def compile_schedules(case):
    validate(case)
    year=dt.date.fromisoformat(case['run']['start_date']).year
    days=365;minutes=days*1440;n=minutes//10
    e,l,c=case['environment'],case['life'],case['controls'];z=e['unit_zones'];devices=e['devices']
    schedules={'always':np.ones(n),'zero':np.zeros(n),'heat_sp':np.full(n,c['heating_C'],dtype=float),
      'cool_sp':np.full(n,c['cooling_C'],dtype=float),'hvac_available':np.full(n,float(c['hvac_available'])),
      'tank_target':np.full(n,c['tank_target_C'],dtype=float),'mixed_target':np.full(n,devices['water_heater']['mixed_target_C'])}
    neighbors=[]
    for day in range(days):
        m=(dt.date(year,1,1)+dt.timedelta(days=day)).month
        k='winter_C'if m in [11,12,1,2,3]else'summer_C'if m in [6,7,8,9]else'shoulder_C'
        neighbors.extend([e['neighbors'][k]]*144)
    schedules['neighbor_temperature']=np.array(neighbors)
    for room in z:
        person=np.zeros(144);activity=np.full(144,108.);light=np.zeros(144)
        for p in l['occupancy']:
            if p['room_id']==room:
                a,b=p['start_min']//10,p['end_min']//10;person[a:b]+=p['persons'];activity[a:b]=p['activity_W']
                if p['activity_W']>72:light[a:b]=1
        schedules['people_'+room]=np.tile(person,days)
        schedules['activity_'+room]=np.tile(activity,days)
        schedules['light_'+room]=np.tile(light,days)
    for override in c['daily_overrides']:
        require(override['field']in ['heat_sp','cool_sp','hvac_available','tank_target'],'UNKNOWN_CONTROL_OVERRIDE')
        require(0<=override['start_min']<override['end_min']<=1440 and override['start_min']%10==0
                and override['end_min']%10==0,'CONTROL_GRID')
        for day in range(days):
            schedules[override['field']][day*144+override['start_min']//10:day*144+override['end_min']//10]=override['value']
    for override in c.get('dated_overrides',[]):
        require(override['field']in ['heat_sp','cool_sp','hvac_available','tank_target'],'UNKNOWN_CONTROL_OVERRIDE')
        d=dt.date.fromisoformat(override['date'])
        require(d.year==year and 0<=override['start_min']<override['end_min']<=1440
                and override['start_min']%10==0 and override['end_min']%10==0,'DATED_CONTROL_GRID')
        day=(d-dt.date(year,1,1)).days
        schedules[override['field']][day*144+override['start_min']//10:day*144+override['end_min']//10]=override['value']
    require(np.all(schedules['heat_sp']<schedules['cool_sp']),'CROSSED_SETPOINTS')
    programs={};water_L_min=np.zeros(n);service_diagnostics=[]
    default_starts=c.get('program_starts_daily',l.get('programs_daily',{}))
    for name in ['washer','dryer','dishwasher']:
        starts=[]
        for day in range(days):
            date=(dt.date(year,1,1)+dt.timedelta(days=day)).isoformat()
            daily=c.get('program_start_overrides',{}).get(date,{}).get(name,default_starts[name])
            starts +=[day*1440+s for s in daily]
            need=l.get('services_daily',{}).get(name)
            if need:
                duration=sum(p['duration_min']for p in devices[name]['phases'])
                issues=[]
                if len(daily)<need['cycles']:issues.append('missing_cycles')
                if any(s<need['release_min']or s+duration>need['deadline_min']for s in daily):issues.append('service_window_violation')
                if issues:service_diagnostics.append({'date':date,'device':name,'issues':issues})
        power,water,records=program_profile(devices[name],starts,minutes)
        schedules[name+'_power_W']=power.reshape(-1,10).mean(axis=1)
        if name=='dryer'and devices[name]['technology']=='vented':
            schedules['dryer_running']=(schedules[name+'_power_W']>0).astype(float)
        if devices[name]['water_connection']=='tank_hot': water_L_min+=water.reshape(-1,10).mean(axis=1)
        programs[name]=records
    for day in range(days):
        date=(dt.date(year,1,1)+dt.timedelta(days=day)).isoformat()
        for draw in l.get('mixed_water_overrides',{}).get(date,l['mixed_water_daily']):
            require(0<=draw['start_min']<draw['start_min']+draw['duration_min']<=1440 and draw['liters']>=0
                    and draw['start_min']%10==0 and draw['duration_min']%10==0,'WATER_DRAW_GRID')
            a=day*144+draw['start_min']//10;b=a+draw['duration_min']//10
            water_L_min[a:b]+=draw['liters']/draw['duration_min']
    schedules['mixed_demand_L_min']=water_L_min
    ev=devices['ev'];daily=l['ev_daily']
    # Each explicitly connected evening is followed by a morning departure; day1 starts connected.
    intervals=[{'start_min':0,'end_min':daily['departure_min'],'target_SOC':c['ev_target_SOC']}]
    trips=[]
    for day in range(days):
        start=day*1440
        trips.append({k:v+start if k in ['departure_min','return_min']else v for k,v in daily.items()})
        intervals.append({'start_min':start+daily['return_min'],
          'end_min':min(minutes,(day+1)*1440+daily['departure_min']),'target_SOC':c['ev_target_SOC']})
    windows=[]
    for day in range(days):
        date=(dt.date(year,1,1)+dt.timedelta(days=day)).isoformat()
        daily=c.get('ev_window_overrides',{}).get(date,c.get('ev_daily_windows',[{'start_min':0,'end_min':1440}]))
        for span in daily:
            require(0<=span['start_min']<span['end_min']<=1440,'EV_DAILY_WINDOW')
            windows.append({'start_min':day*1440+span['start_min'],'end_min':day*1440+span['end_min'],
                            'target_SOC':span.get('target_SOC',c['ev_target_SOC'])})
    ledger=ev_ledger(ev,intervals,trips,minutes,charging_windows=windows)
    schedules['ev_power_W']=np.array(ledger['power_W'])
    return schedules,{'programs':programs,'service_diagnostics':service_diagnostics,
      'physical_loads_follow_explicit_start_commands':True,
      'manual_loading_permissions_not_inferred':True,
      'ev':{k:v for k,v in ledger.items()if k not in ['power_W','energy_kWh']},
      'ev_energy_kWh':ledger['energy_kWh'],'schedule_calendar_year':year,
      'calendar_year_is_not_observed_weather_year':True}
