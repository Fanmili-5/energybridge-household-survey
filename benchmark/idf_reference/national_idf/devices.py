"""Physics and selection contracts for all six device classes.

Published equipment points, generic engine mechanics and engineering assumptions
are intentionally separate. No acceptance or response labels are produced.
"""
from __future__ import annotations
import copy
import math
import numpy as np
from .common import ROOT, require, read, digest, sha

BTU_H_TO_W = 0.2930710701722222
DEVICE_CLASSES = {'air_conditioner','washer','dryer','dishwasher','water_heater','ev'}


def performance_reference():
    source=ROOT/'data/source/documents/mitsubishi_FS12_submittal.pdf'
    # Page 1, MAXIMUM capacity and corresponding total electrical input at each DB.
    # Rated capacity is not mixed with maximum capacity in the fitted map.
    temps_F=[-13,5,17,47];capacity_Btu_h=[11000,14690,17300,21000];power_W=[1680,1910,1980,1980]
    return {'id':'FS12_manufacturer_maximum_points_reference',
      'manufacturer_document_sha256':sha(source),
      'source_url':'https://www.mitsubishitechinfo.ca/sites/default/files/SB_MSZ-FS12NA-U1_MUZ-FS12NAH-U1_202401.pdf',
      'locator':'page1;heating maximum capacity and maximum input;indoor70F;outdoor_DB_and_stated_WB',
      'outdoor_C':[(v-32)*5/9 for v in temps_F],
      'maximum_heating_W':[v*BTU_H_TO_W for v in capacity_Btu_h],
      'maximum_total_power_W':power_W,'indoor_reference_C':(70-32)*5/9,
      'heating_operating_min_C':-25,'heating_operating_max_C':(75-32)*5/9,
      'cooling_reference':{'outdoor_C':35,'indoor_DB_C':(80-32)*5/9,
         'indoor_WB_C':(67-32)*5/9,'max_capacity_W':13600*BTU_H_TO_W,'max_total_power_W':1150,
         'min_capacity_W':2500*BTU_H_TO_W,'min_total_power_W':170},
      'minimum_heating_reference':{'outdoor_C':(47-32)*5/9,'capacity_W':3700*BTU_H_TO_W,'power_W':280},
      'electrical_market':'208_230V_60Hz_Canadian_reference;not_China_market_ownership_or_certification',
      'not_proven':['complete_inverter_map','part_load_performance_at_all_temperatures',
        'OEM_transient_control','defrost_cycle_calibration','Chinese_household_field_calibration']}


def select_hvac(design_loads:dict, profile:dict, *, margin=1.1, max_units_per_zone=8):
    """Select before operation/controls; never inspect A/B effects or answers."""
    t=design_loads['heating_design_C'];xs=profile['outdoor_C']
    require(xs[0]<=t<=profile.get('heating_operating_max_C',xs[-1]),'DESIGN_TEMPERATURE_OUTSIDE_CAPACITY_DATA',t)
    # Warmer design days use the last measured capacity, not extrapolated output.
    # This is a declared conservative sizing bound, not a new manufacturer point.
    evaluation_C=min(t,xs[-1])
    qheat=float(np.interp(evaluation_C,xs,profile['maximum_heating_W']))
    qcool=profile['cooling_reference']['max_capacity_W']
    result={}
    for zone,load in design_loads['zones'].items():
        require(all(math.isfinite(load[k])and load[k]>=0 for k in ['heating_W','cooling_W']),
                'INVALID_DESIGN_LOAD',zone)
        n=max(1,math.ceil(margin*max(load['heating_W']/qheat,load['cooling_W']/qcool)))
        require(n<=max_units_per_zone,'INSTALLATION_CAPACITY_UNRESOLVED',[zone,n])
        result[zone]={'parallel_reference_units':n,'reference_profile_id':profile['id'],
          'design_loads':load,'design_temperature_C':t,'capacity_at_design_W':qheat*n,
          'capacity_evaluation_C':evaluation_C,
          'warm_design_uses_last_published_capacity_bound':t>xs[-1],
          'cooling_reference_max_W':qcool*n,'margin':margin,
          'count_is_capacity_equivalent_not_manufacturer_multi_split_design':True}
    return {'zones':result,'selection_inputs_sha256':digest({'loads':design_loads,'profile':profile,
      'margin':margin,'max_units_per_zone':max_units_per_zone}),
      'selection_reads_operation_or_AB':False,'supplemental_heat_default_W':0}


def validate_devices(devices):
    require(set(devices)==DEVICE_CLASSES,'SIX_DEVICE_CLASSES_REQUIRED',sorted(set(devices)))
    for name,d in devices.items():
        require(d.get('evidence_class')in ('source_parameter','derived_reference','declared_design'),
                'DEVICE_EVIDENCE_REQUIRED',name)
    ac=devices['air_conditioner']
    require(ac['profile_id']=='FS12_manufacturer_maximum_points_reference','UNSUPPORTED_HVAC_PROFILE')
    require(bool(ac['room_ids'])and len(set(ac['room_ids']))==len(ac['room_ids']),'HVAC_INSTALLATION_ROOMS')
    for name in ['washer','dryer','dishwasher']:
        d=devices[name];require(d['water_connection']in ('cold_self_heated','tank_hot','none'),
                               'APPLIANCE_WATER_CONNECTION',name)
        if d['water_connection']=='tank_hot':
            require(not d.get('internal_water_heating',False),'DOUBLE_WATER_HEATING',name)
        for p in d['phases']:
            require(p['duration_min']>0 and p['duration_min']%10==0 and p['power_W']>=0,
                    'PROGRAM_PHASE',name)
            require(p.get('water_L',0)>=0,'NEGATIVE_PROGRAM_WATER',name)
        require(d['latent_fraction']>=0 and d['radiant_fraction']>=0 and d['lost_fraction']>=0
                and sum(d[k]for k in ['latent_fraction','radiant_fraction','lost_fraction'])<=1,
                'APPLIANCE_HEAT_FRACTIONS',name)
    require(devices['dryer']['technology']in ('vented','condensing','heat_pump'), 'DRYER_TECHNOLOGY')
    if devices['dryer']['technology']=='vented':
        require(devices['dryer'].get('exhaust_flow_m3_s',0)>0 and devices['dryer'].get('fan_input_W',0)>0
                and devices['dryer'].get('phases_exclude_exhaust_fan')is True,'VENTED_DRYER_EXHAUST_CONTRACT')
    require(devices['ev']['room_id']is None and devices['ev']['meter_scope']=='target_dwelling',
            'EV_MUST_BE_OUTSIDE_IN_TARGET_METER')
    require(devices['air_conditioner'].get('supplemental_heat_W',0)==0 or
            devices['air_conditioner'].get('supplemental_heat_source'),'UNSOURCED_AUXILIARY_HEAT')
    require(devices['air_conditioner'].get('supplemental_heat_W',0)>=0,'NEGATIVE_AUXILIARY_HEAT')
    for name in ['washer','dryer','dishwasher','water_heater']:
        require(isinstance(devices[name].get('room_id'),str),'DEVICE_INSTALLATION_REQUIRED',name)
    tank=devices['water_heater']
    require(tank['nodes']==6 and tank['volume_m3']>0 and tank['height_m']>0 and tank['heater_W']>=0
            and 0<tank['efficiency']<=1 and tank['skin_loss_W_m2K']>=0,'TANK_PARAMETERS')
    require(0<devices['ev']['efficiency']<=1 and devices['ev']['capacity_kWh']>0
            and 0<=devices['ev']['initial_SOC']<=1 and devices['ev']['charger_kW']>=0,'EV_PARAMETERS')


def program_profile(device, starts, minutes):
    p=np.zeros(minutes);water=np.zeros(minutes);occupied=np.zeros(minutes,dtype=bool);records=[]
    for start in starts:
        require(isinstance(start,int)and start%10==0,'PROGRAM_START_GRID',start)
        at=start
        for phase in device['phases']:
            end=at+phase['duration_min']
            require(0<=at<end<=minutes,'PROGRAM_OUTSIDE_RUN',[start,end])
            require(not occupied[at:end].any(),'DEVICE_PROGRAM_OVERLAP',start)
            occupied[at:end]=True
            p[at:end]=phase['power_W'];water[at:end]=phase.get('water_L',0)/phase['duration_min']
            at=end
        records.append({'start_min':start,'end_min':at,'expected_kWh':sum(
            phase['power_W']*phase['duration_min']/60000 for phase in device['phases'])})
    return p,water,records


def ev_ledger(config, intervals, trips, minutes, step=10,charging_windows=None):
    require(minutes%step==0,'EV_TIME_GRID')
    cap=config['capacity_kWh'];energy=config['initial_SOC']*cap
    require(0<=energy<=cap,'EV_INITIAL_STATE')
    n=minutes//step;p=np.zeros(n);states=[];failures=[];trip_map={}
    for t in trips:
        require(t['departure_min']%step==0,'EV_TRIP_GRID')
        require(t['traction_kWh']>=0 and 0<=t.get('required_departure_SOC',config['minimum_SOC'])<=1,
                'EV_TRIP_ENERGY_OR_TARGET')
        trip_map.setdefault(t['departure_min'],[]).append(t)
    require(all(0<=r['start_min']<r['end_min']<=minutes and r['start_min']%step==0
                and r['end_min']%step==0 for r in intervals),'EV_CONNECTION_GRID')
    connection=np.full(n,-1,dtype=int);away=np.zeros(n,dtype=bool)
    for index,span in enumerate(intervals):
        a,b=span['start_min']//step,span['end_min']//step
        require(np.all(connection[a:b]==-1),'EV_OVERLAPPING_CONNECTIONS')
        connection[a:b]=index
    for trip in trips:
        require(0<=trip['departure_min']<trip['return_min']<=minutes,'EV_TRIP_INTERVAL')
        away[trip['departure_min']//step:trip['return_min']//step]=True
    require(not np.any((connection>=0)&away),'EV_CHARGING_DURING_TRIP')
    allowed=np.ones(n,dtype=bool)if charging_windows is None else np.zeros(n,dtype=bool)
    targets=np.full(n,1.)
    if charging_windows is not None:
        for window in charging_windows:
            a,b=window['start_min']//step,window['end_min']//step
            require(0<=a<b<=n and window['start_min']%step==0 and window['end_min']%step==0,
                    'EV_CONTROL_WINDOW_GRID')
            require(0<=window.get('target_SOC',1)<=1,'EV_CHARGE_TARGET')
            allowed[a:b]=True;targets[a:b]=window.get('target_SOC',1)
    for i in range(n):
        t=i*step
        for trip in trip_map.get(t,[]):
            target=trip.get('required_departure_SOC',config['minimum_SOC'])*cap
            if energy+1e-9<target:failures.append({'minute':t,'kind':'departure_target_shortfall','kWh':target-energy})
            if energy+1e-9<trip['traction_kWh']:
                failures.append({'minute':t,'kind':'trip_energy_unavailable','kWh':trip['traction_kWh']-energy})
                # Physical trip does not execute; do not invent energy or silently clip the battery.
                continue
            energy-=trip['traction_kWh']
        if connection[i]>=0 and allowed[i]:
            span=intervals[connection[i]]
            target=targets[i]if charging_windows is not None else span.get('target_SOC',1)
            need=max(0,target*cap-energy)
            grid=min(config['charger_kW']*step/60,need/config['efficiency'])
            p[i]=grid*60000/step;energy+=grid*config['efficiency']
        states.append(energy)
    traction=sum(t['traction_kWh']for t in trips)-sum(
        t['traction_kWh']for t in trips if any(f['kind']=='trip_energy_unavailable'and f['minute']==t['departure_min']for f in failures))
    grid_kWh=float(p.sum()*step/60000)
    residual=energy-config['initial_SOC']*cap-grid_kWh*config['efficiency']+traction
    return {'power_W':p.tolist(),'energy_kWh':states,'grid_kWh':grid_kWh,'traction_kWh':traction,
            'final_kWh':energy,'balance_residual_kWh':residual,'failures':failures,
            'availability_without_connection_intervals':int(sum(allowed&(connection<0))),
            'connection_is_separate_from_control_availability':True}
