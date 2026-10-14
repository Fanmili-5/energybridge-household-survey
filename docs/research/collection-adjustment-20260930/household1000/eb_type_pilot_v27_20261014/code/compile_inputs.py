"""Compile complete paired IDF inputs on Linux. Deliberately contains no EP runner."""
import calendar as gregorian, collections, concurrent.futures, copy, datetime as dt, math
from common import *
from plans import make_A
from activity_model import dated,resident_slot
from execution import realize,common_care_bookings,post_operation_care
SCHEMA=read(SCHEMA_PATH)['properties']
NATIVE=parse(UP/'experiments/models/family_home/family_simple_3day.idf')
DX=next(r for r in NATIVE if r[0]=='Coil:Cooling:DX:SingleSpeed')
FAN=next(r for r in NATIVE if r[0]=='Fan:OnOff')
CURVES=[r for r in NATIVE if r[0].startswith('Curve:')]
def get(r,k):
    i=SCHEMA[r[0]]['legacy_idd']['fields'].index(k)+1
    return r[i] if i<len(r) else ''
def put(r,k,v):
    i=SCHEMA[r[0]]['legacy_idd']['fields'].index(k)+1;r.extend(['']*max(0,i+1-len(r)));r[i]=v
def obj(kind,values):
    fs=SCHEMA[kind]['legacy_idd']['fields'];last=max(fs.index(k) for k in values)
    return [kind]+[values.get(f,'') for f in fs[:last+1]]
def compact(values,start):
    # Only a short episode is simulated. The calendar filler has no observational status.
    bydate={dt.date(2025,(start+dt.timedelta(days=d)).month,(start+dt.timedelta(days=d)).day):values[d*144:(d+1)*144] for d in range(len(values)//144)}
    out=[];last=0;fill=values[0]
    for day,vs in sorted(bydate.items()):
        doy=day.timetuple().tm_yday
        if doy>last+1:out+=['Through:'+(day-dt.timedelta(days=1)).strftime('%m/%d'),'For:AllDays','Until:24:00',fill]
        out+=['Through:'+day.strftime('%m/%d'),'For:AllDays'];a=0
        for e in range(1,145):
            if e==144 or vs[e]!=vs[a]:out+=['Until:%02d:%02d'%((e*10)//60,(e*10)%60),vs[a]];a=e
        last=doy
    if last<365:out+=['Through:12/31','For:AllDays','Until:24:00',fill]
    return out
def signals(w,p,side,prior_days=7):
    date=dt.date.fromisoformat(p['date']);start=date-dt.timedelta(days=prior_days);days=prior_days+3
    full_needs,full_A,full_ws,_=make_A(w,start,days=days);origin=prior_days*1440
    target_need_ids={n['need_id'] for n in p['needs_A']}
    plan={key:[x for x in full_A[key] if (x['need_id'] not in target_need_ids if key=='operations' else (x['need_id'] not in target_need_ids if key=='tasks' else x['service_date'] not in {n['need_id'].split(':')[0] for n in p['needs_A']}))]
          +[{**x,'start_min':x['start_min']+origin,'end_min':x['end_min']+origin} for x in p[side][key]]
          for key in ('tasks','controls','operations')}
    reference_A={key:[x for x in full_A[key] if (x['need_id'] not in target_need_ids if key=='operations' else (x['need_id'] not in target_need_ids if key=='tasks' else x['service_date'] not in {n['need_id'].split(':')[0] for n in p['needs_A']}))] +[{**x,'start_min':x['start_min']+origin,'end_min':x['end_min']+origin} for x in p['A'][key]] for key in ('tasks','controls','operations')}
    for oid,windows in p['world']['operator_windows'].items():
        full_ws.setdefault(oid,[]).extend([[a+origin,b+origin] for a,b in windows])
    execution=realize(w,plan,full_ws,full_needs,horizon_min=days*1440)
    plan['requested_tasks']=plan['tasks'];plan['requested_operations']=plan['operations']
    plan['tasks']=execution['realized_tasks'];plan['operations']=execution['physical_visit_operations']
    plan['execution']=execution
    plan['common_A_care_bookings']=common_care_bookings(w,start,reference_A,days)
    plan['post_operation_care_gaps']=post_operation_care(w,start,plan,plan['common_A_care_bookings'],days)
    # Carry preceding-night programs and controls across midnight. Target plans
    # replace only target-origin actions; no daily reset or dropped prior tail.
    devices=w['parameter_pack']['devices'];sig={d['asset_id']:[0.]* (days*144) for d in devices};draw=[0.]*(days*144)
    evstates={d['asset_id']:w['reference_initial_states']['EV_SOC'] for d in devices if 'ev' in d['types']};diagnostics=[];ev_traces={aid:[] for aid in evstates};away_until={aid:-1 for aid in evstates}
    for d in devices:
        if 'ac' in d['types']:sig[d['asset_id']+':available']=[0.]*(days*144)
    trips={n['trip_departure_min']:n for n in full_needs if n['kind']=='ev'}
    target_draws=[{**n,'release_min':n['release_min']+origin,'deadline_min':n['deadline_min']+origin} for n in p['needs_A'] if n['kind']=='water_heater']
    draws=[n for n in full_needs if n['kind']=='water_heater' and (n['need_id'] not in target_need_ids)]+target_draws
    for ix in range(days*144):
        minute=ix*10;dat=start+dt.timedelta(days=ix//144)
        for d in devices:
            aid=d['asset_id'];ks=d['types'];value=0.
            if 'ac' in ks:
                c=next((c for c in plan['controls'] if c['asset_id']==aid and c['start_min']<=minute<c['end_min']),None)
                value=c['value_C'] if c else 50.;sig[aid+':available'][ix]=int(c is not None)
            elif 'water_heater' in ks:
                c=next((c for c in plan['controls'] if c['asset_id']==aid and c['start_min']<=minute<c['end_min']),None)
                value=c['value_C'] if c else 10.
            elif 'ev' in ks:
                value=execution['vehicle_causal_trace']['grid_W'][aid][ix]
                ev_traces[aid].append(execution['vehicle_causal_trace']['SOC_after_step'][aid][ix])
            else:
                t=next((t for t in plan['tasks'] if t['asset_id']==aid and t['start_min']<=minute<t['end_min']),None)
                if t:value=(d['parameters'][t['kind']]['power_kw'] if 'washer' in ks else d['parameters']['power_kw'])*1000
            sig[aid][ix]=value
        flow=sum(n['quantity']/((n['deadline_min']-n['release_min'])*60)/1000 for n in draws if n['release_min']<=minute<n['deadline_min'])
        draw[ix]=flow/.000141975
    diagnostics=[{**x,'date':(start+dt.timedelta(days=x['absolute_min']//1440)).isoformat(),'minute':x['absolute_min']%1440} for x in execution['vehicle_causal_trace']['diagnostics'] if 0<=x['absolute_min']<days*1440]
    sig['mixed_water_draw']=draw
    plan['EV_SOC_after_step']=ev_traces
    plan['EV_unmodelled_alternative_transport_after_failure']=True
    return sig,start,diagnostics,plan
def spatial_ledger(w,p,side,start,days,prior_days,continuous_plan):
    rooms=[r['room_id'] for r in w['layout']['rooms']]
    count=days*144
    resident={m['member_id']:{rid:[0.]*count for rid in rooms} for m in w['members']}
    external={};lighting={rid:[0.]*count for rid in rooms};resident_totals=[0.]*count
    for day in range(days):
        dat=start+dt.timedelta(days=day);context=dated(w,dat)
        plan=continuous_plan;offset=day*1440
        localops=[{**o,'start_min':o['start_min']-offset,'end_min':o['end_min']-offset} for o in plan['operations']]
        for slot in range(144):
            ix=day*144+slot
            for m in w['members']:
                location=resident_slot(w,context,m['member_id'],slot,localops,plan['tasks'])
                if location['location']=='home':
                    rid=location['room_id'];assert rid in rooms
                    resident[m['member_id']][rid][ix]=1.;resident_totals[ix]+=1.
                    if location['activity'] not in ('sleep_rest','day_nap'):lighting[rid][ix]=1.
            visits=[v for v in context['external_visits'] if v['start_min']<=slot*10<v['end_min']]
            for b in continuous_plan.get('common_A_care_bookings',[]):
                if b['start_min']<=offset+slot*10<b['end_min']:
                    child=next((m for m in w['members'] if m['age_years']<6 and resident_slot(w,context,m['member_id'],slot,localops,plan['tasks'])['location']=='home'),None)
                    if child:visits.append({'person_id':b['person_id'],'room_id':resident_slot(w,context,child['member_id'],slot,localops,plan['tasks'])['room_id']})
            for o in localops:
                if o['operator_id'] in resident or o['kind'].startswith('EV_') or not o['start_min']<=slot*10<o['end_min']:continue
                t=next((t for t in plan['tasks'] if t['need_id']==o['need_id']),None)
                if t:
                    d=next(d for d in w['parameter_pack']['devices'] if d['asset_id']==t['asset_id'])
                    visits.append({'person_id':o['operator_id'],'room_id':d['room_id']})
            seen={}
            for visit in visits:
                mid=visit['person_id'];rid=visit['room_id']
                # A helper cannot become multiple thermal people through duplicated visit rows.
                if mid in seen and seen[mid]!=rid:raise ValueError('EXTERNAL_HELPER_DOUBLE_LOCATION:'+mid)
                seen[mid]=rid
                if mid not in external:external[mid]={r:[0.]*count for r in rooms}
                external[mid][rid][ix]=1.;lighting[rid][ix]=1.
            assert resident_totals[ix]<=w['N']
    for mid,byroom in resident.items():assert all(sum(vs[ix] for vs in byroom.values())<=1 for ix in range(count))
    return {'resident_occupancy':resident,'external_occupancy':external,'resident_total':resident_totals,'lighting':lighting,
        'source':'same dated calendar and actual saved side operations; visitors separated from rosterN',
        'metabolic_power':'retained EB109.444W reference per person; not body-age calibrated'}
def add_ac(rows,w,names):
    cn={r[1]:'v16_curve_'+r[1] for r in CURVES}
    rows.extend([[cn.get(x,x) for x in r] for r in CURVES])
    equipment=collections.defaultdict(list);inlets=collections.defaultdict(list);returns=collections.defaultdict(list)
    for i,d in enumerate(w['parameter_pack']['devices']):
        if 'ac' not in d['types']:continue
        q=d['parameters'];rid=d['room_id'];prefix='v16_AC_'+str(i);flow=q['flow_m3_h']/3600
        fan=copy.deepcopy(FAN);fan[1]=prefix+'_fan';put(fan,'availability_schedule_name',names[d['asset_id']+':available']);put(fan,'maximum_flow_rate',flow)
        put(fan,'air_inlet_node_name',prefix+'_mixed');put(fan,'air_outlet_node_name',prefix+'_coil_inlet');put(fan,'end_use_subcategory','target_AC_fan')
        coil=copy.deepcopy(DX);coil[1]=prefix+'_coil';put(coil,'availability_schedule_name',names[d['asset_id']+':available']);put(coil,'gross_rated_total_cooling_capacity',q['cooling_W']);put(coil,'rated_air_flow_rate',flow)
        fanW=float(get(FAN,'pressure_rise'))*flow/float(get(FAN,'fan_total_efficiency'))
        put(coil,'gross_rated_cooling_cop',q['gross_rated_COP'])
        put(coil,'air_inlet_node_name',prefix+'_coil_inlet');put(coil,'air_outlet_node_name',prefix+'_supply');coil=[cn.get(x,x) for x in coil]
        rows+=[fan,coil,obj('OutdoorAir:Mixer',{'name':prefix+'_mixer','mixed_air_node_name':prefix+'_mixed','outdoor_air_stream_node_name':prefix+'_outside','relief_air_stream_node_name':prefix+'_relief','return_air_stream_node_name':prefix+'_return'}),['OutdoorAir:Node',prefix+'_outside',-1],
            obj('ZoneHVAC:WindowAirConditioner',{'name':prefix+'_unit','availability_schedule_name':names[d['asset_id']+':available'],'maximum_supply_air_flow_rate':flow,'maximum_outdoor_air_flow_rate':0,
                'air_inlet_node_name':prefix+'_return','air_outlet_node_name':prefix+'_supply','outdoor_air_mixer_object_type':'OutdoorAir:Mixer','outdoor_air_mixer_name':prefix+'_mixer',
                'supply_air_fan_object_type':'Fan:OnOff','supply_air_fan_name':prefix+'_fan','cooling_coil_object_type':'Coil:Cooling:DX:SingleSpeed','dx_cooling_coil_name':prefix+'_coil',
                'supply_air_fan_operating_mode_schedule_name':'v16_zero','fan_placement':'BlowThrough','cooling_convergence_tolerance':.001})]
        equipment[rid].append(('ZoneHVAC:WindowAirConditioner',prefix+'_unit'));inlets[rid].append(prefix+'_supply');returns[rid].append(prefix+'_return')
    for r in w['layout']['rooms']:
        rid=r['room_id'];prefix='v16_heat_'+rid;eqs=equipment[rid];acs=[d for d in w['parameter_pack']['devices'] if 'ac' in d['types'] and d['room_id']==rid]
        rows.append(obj('ZoneHVAC:IdealLoadsAirSystem',{'name':prefix,'availability_schedule_name':'v16_all','zone_supply_air_node_name':prefix+'_supply',
            'maximum_heating_supply_air_temperature':50,'minimum_cooling_supply_air_temperature':13,'maximum_heating_supply_air_humidity_ratio':.015,'minimum_cooling_supply_air_humidity_ratio':.009,
            'heating_limit':'NoLimit','cooling_limit':'LimitCapacity','maximum_total_cooling_capacity':0,'heating_availability_schedule_name':'v16_all','cooling_availability_schedule_name':'v16_zero','dehumidification_control_type':'None','humidification_control_type':'None'}))
        rows.append(obj('ThermostatSetpoint:DualSetpoint',{'name':prefix+'_sp','heating_setpoint_temperature_schedule_name':'v16_heat18','cooling_setpoint_temperature_schedule_name':names[acs[0]['asset_id']]}) if acs else obj('ThermostatSetpoint:SingleHeating',{'name':prefix+'_sp','setpoint_temperature_schedule_name':'v16_heat18'}))
        rows.append(obj('ZoneControl:Thermostat',{'name':prefix+'_control','zone_or_zonelist_name':rid,'control_type_schedule_name':'v16_dual' if acs else 'v16_heating',
            'control_1_object_type':'ThermostatSetpoint:DualSetpoint' if acs else 'ThermostatSetpoint:SingleHeating','control_1_name':prefix+'_sp'}))
        equipment_row=['ZoneHVAC:EquipmentList',prefix+'_list','SequentialLoad']
        for i,(kind,name) in enumerate(eqs):equipment_row+=[kind,name,i+1,i+2,'','']
        equipment_row+=['ZoneHVAC:IdealLoadsAirSystem',prefix,len(eqs)+1,1,'',''];rows.append(equipment_row)
        rows.append(['NodeList',prefix+'_inlets']+inlets[rid]+[prefix+'_supply'])
        if returns[rid]:rows.append(['NodeList',prefix+'_exhaust']+returns[rid])
        rows.append(obj('ZoneHVAC:EquipmentConnections',{'zone_name':rid,'zone_conditioning_equipment_list_name':prefix+'_list','zone_air_inlet_node_or_nodelist_name':prefix+'_inlets',
            'zone_air_exhaust_node_or_nodelist_name':prefix+'_exhaust' if returns[rid] else '', 'zone_air_node_name':prefix+'_zone_air','zone_return_air_node_or_nodelist_name':prefix+'_return'}))
def add_tank(rows,w,names):
    tank=next((d for d in w['parameter_pack']['devices'] if 'water_heater' in d['types']),None)
    if not tank:return
    types={'Branch','BranchList','Connector:Splitter','Connector:Mixer','ConnectorList','Pipe:Adiabatic','Pump:VariableSpeed','PlantLoop','PlantEquipmentList','PlantEquipmentOperation:HeatingLoad','PlantEquipmentOperationSchemes','SetpointManager:Scheduled','WaterUse:Equipment','WaterUse:Connections','WaterHeater:Stratified'}
    mapping={'EWH_Setpoint_Control':names[tank['asset_id']],'EWH_Availability_Control':'v16_all','BA_shower_sch':names['mixed_water_draw'],'BA_sink_sch':'v16_zero','BA_bath_sch':'v16_zero','SSBWaterTempSchedule':'v16_mixedtemp'}
    for source in NATIVE:
        if source[0] not in types or source[1].startswith('Air Loop'):continue
        r=[mapping.get(x,x.replace('_unit1','_v16')) for x in source]
        if r[0]=='WaterHeater:Stratified':
            put(r,'ambient_temperature_zone_name',tank['room_id']);put(r,'end_use_subcategory','target_electric_hot_water')
            put(r,'tank_volume',tank['parameters']['volume_m3']);put(r,'heater_1_capacity',tank['parameters']['heater_capacity_W'])
            put(r,'maximum_temperature_limit',tank['parameters']['maximum_C'])
        if r[0]=='WaterUse:Equipment':
            put(r,'zone_name',tank['room_id']);put(r,'target_temperature_schedule_name','v16_mixedtemp')
            put(r,'cold_water_supply_temperature_schedule_name','v16_inlet15')
            put(r,'sensible_fraction_schedule_name','v16_zero');put(r,'latent_fraction_schedule_name','v16_zero')
        if r[0]=='WaterUse:Connections':put(r,'cold_water_supply_temperature_schedule_name','v16_inlet15')
        rows.append(r)
    rows.append(['Site:WaterMainsTemperature','Schedule','v16_inlet15'])
def compile_one(w,p,side,background,prior_days=7,inlet='fixed15',variant='base7',weather_path=None):
    signals_data,start,ev_diagnostics,continuous_plan=signals(w,p,side,prior_days);days=prior_days+3;rows=copy.deepcopy(background)
    remove={'People','Lights','ElectricEquipment','WaterHeater:Mixed','WaterHeater:Stratified','RunPeriod','Output:Variable','Output:Meter','OutputControl:Files',
        'ZoneControl:Thermostat','ThermostatSetpoint:DualSetpoint','ThermostatSetpoint:SingleHeating','ZoneControl:Humidistat','ZoneHVAC:IdealLoadsAirSystem','ZoneHVAC:EquipmentList','ZoneHVAC:EquipmentConnections','Site:WaterMainsTemperature'}
    rows=[r for r in rows if r[0] not in remove]
    for r in rows:
        if r[0]=='Timestep':r[1]=6
    end=start+dt.timedelta(days=days-1);requested_end=end
    if weather_path:
        headers=Path(weather_path).read_text().splitlines()[:8]
        leap=next(h.split(',')[1].strip().lower() for h in headers if h.startswith('HOLIDAYS/DAYLIGHT SAVING'))
        if start.year!=end.year and gregorian.isleap(start.year) and start.month>2 and leap=='no':requested_end=end+dt.timedelta(days=1)
    rows += [obj('RunPeriod',{'name':'v18_continuous_common_prior_target_recovery','begin_month':start.month,'begin_day_of_month':start.day,'begin_year':start.year,'end_month':requested_end.month,'end_day_of_month':requested_end.day,'end_year':requested_end.year,
        'day_of_week_for_start_day':start.strftime('%A'),'use_weather_file_holidays_and_special_days':'No','use_weather_file_daylight_saving_period':'No','treat_weather_as_actual':'No'}),
        ['ScheduleTypeLimits','v16_fraction',0,1,'Continuous','Dimensionless'],['ScheduleTypeLimits','v16_temperature',-60,200,'Continuous','Temperature'],['ScheduleTypeLimits','v16_power',0,30000,'Continuous','Power'],
        ['ScheduleTypeLimits','v16_control',0,4,'Discrete','Control'],['Schedule:Constant','v16_all','v16_fraction',1],['Schedule:Constant','v16_zero','v16_fraction',0],
        ['Schedule:Constant','v16_heat18','v16_temperature',18],['Schedule:Constant','v16_inlet15','v16_temperature',15],['Schedule:Constant','v16_mixedtemp','v16_temperature',40.5555555555556],
        ['Schedule:Constant','v16_dual','v16_control',4],['Schedule:Constant','v16_heating','v16_control',1],['Schedule:Constant','v16_person_W','v16_power',109.44444444444444]]
    names={}
    for i,(aid,vs) in enumerate(signals_data.items()):
        name='v16_signal_'+str(i);names[aid]=name
        d=next((d for d in w['parameter_pack']['devices'] if d['asset_id']==aid),None)
        limit='v16_fraction' if aid=='mixed_water_draw' or aid.endswith(':available') else 'v16_temperature' if set(d['types'])&{'ac','water_heater'} else 'v16_power'
        rows.append(['Schedule:Compact',name,limit]+compact(vs,start))
    # Dated person->room authority, including the saved side's handling operations.
    spatial=spatial_ledger(w,p,side,start,days,prior_days,continuous_plan)
    for room in w['layout']['rooms']:
        rid=room['room_id'];area=room['thermal_reference_area_m2'];share=1/len(room['using_household_ids']) if w['household_id'] in room['using_household_ids'] else 0
        light_schedule='v19_light_clock_'+rid
        rows.append(['Schedule:Compact',light_schedule,'v16_fraction']+compact(spatial['lighting'][rid],start))
        rows += [obj('Lights',{'name':'v19_light_'+rid,'zone_or_zonelist_or_space_or_spacelist_name':rid,'schedule_name':light_schedule,'design_level_calculation_method':'LightingLevel',
            'lighting_level':area*(1.8 if room['census_room_class']=='corridor' else 4.2)*share,'return_air_fraction':0,'fraction_radiant':.4,'fraction_visible':.2,'fraction_replaceable':1,'end_use_subcategory':'allocated_reference_lighting'}),
            obj('ElectricEquipment',{'name':'v19_background_'+rid,'zone_or_zonelist_or_space_or_spacelist_name':rid,'schedule_name':'v16_all','design_level_calculation_method':'EquipmentLevel',
            'design_level':area*.5*(5 if room['census_room_class']=='kitchen' else 2)*share,'fraction_latent':0,'fraction_radiant':.3,'fraction_lost':0,'end_use_subcategory':'separate_fixed_reference_background'})]
    for mid,byroom in spatial['resident_occupancy'].items():
        for rid,vs in byroom.items():
            if not any(vs):continue
            name='v19_person_'+mid.split('-')[-1]+'_'+rid
            rows.append(['Schedule:Compact',name,'v16_fraction']+compact(vs,start))
            rows.append(obj('People',{'name':name,'zone_or_zonelist_or_space_or_spacelist_name':rid,'number_of_people_schedule_name':name,
                'number_of_people_calculation_method':'People','number_of_people':1,'fraction_radiant':.3,'sensible_heat_fraction':'Autocalculate','activity_level_schedule_name':'v16_person_W'}))
    for ix,(mid,byroom) in enumerate(spatial['external_occupancy'].items()):
        for rid,vs in byroom.items():
            if not any(vs):continue
            name='v19_external_'+str(ix)+'_'+rid
            rows.append(['Schedule:Compact',name,'v16_fraction']+compact(vs,start))
            rows.append(obj('People',{'name':name,'zone_or_zonelist_or_space_or_spacelist_name':rid,'number_of_people_schedule_name':name,
                'number_of_people_calculation_method':'People','number_of_people':1,'fraction_radiant':.3,'sensible_heat_fraction':'Autocalculate','activity_level_schedule_name':'v16_person_W'}))
    for d in w['parameter_pack']['devices']:
        if set(d['types'])&{'ac','water_heater'}:continue
        rid=d['room_id'] if 'ev' not in d['types'] else w['members'][0]['reference_home_room_id']
        rows.append(obj('ElectricEquipment',{'name':d['asset_id'],'zone_or_zonelist_or_space_or_spacelist_name':rid,'schedule_name':names[d['asset_id']],'design_level_calculation_method':'EquipmentLevel','design_level':1,
            'fraction_latent':0,'fraction_radiant':0 if 'ev' in d['types'] else .3,'fraction_lost':1 if 'ev' in d['types'] else 0,'end_use_subcategory':'target_'+('_'.join(d['types']))}))
    add_ac(rows,w,names);add_tank(rows,w,names)
    if inlet=='seasonal':
        # EnergyPlus Correlation is a declared sensitivity assumption; use EPW
        # hourly dry-bulb annual mean and monthly mean range, not a claimed city pipe measurement.
        import csv
        with Path(weather_path).open() as f:
            for _ in range(8):next(f)
            bymonth=collections.defaultdict(list)
            for r in csv.reader(f):bymonth[int(r[1])].append(float(r[6]))
        means=[sum(v)/len(v) for v in bymonth.values()];annual=sum(sum(v) for v in bymonth.values())/sum(map(len,bymonth.values()))
        rows=[r for r in rows if not (r[0]=='Site:WaterMainsTemperature' or r[0]=='Schedule:Constant' and r[1]=='v16_inlet15')]
        rows.append(['Site:WaterMainsTemperature','Correlation','',annual,max(means)-min(means)])
        # All cold-water boundaries defer to the same site model; no residual15C supply schedule.
        for r in rows:
            if r[0] in ('WaterUse:Equipment','WaterUse:Connections'):put(r,'cold_water_supply_temperature_schedule_name','')
    if weather_path:
        header=Path(weather_path).open().readline().strip().split(',')
        for r in rows:
            if r[0]=='Site:Location':r[1:]=['v18_EPW_site',header[6],header[7],header[8],header[9]]

    for var in ['Site Outdoor Air Drybulb Temperature','Site Outdoor Air Wetbulb Temperature','Site Outdoor Air Humidity Ratio','Site Outdoor Air Barometric Pressure',
        'Zone Mean Air Temperature','Zone Air Relative Humidity','Zone People Occupant Count','Lights Electricity Energy','Electric Equipment Electricity Energy',
        'Cooling Coil Electricity Energy','Fan Electricity Energy','Water Heater Electricity Energy','Water Heater Tank Temperature','Water Heater Use Side Outlet Temperature',
        'Zone People Occupant Count','Schedule Value','Water Use Equipment Total Volume','Water Use Equipment Hot Water Volume','Water Use Equipment Cold Water Volume','Water Use Equipment Mixed Water Temperature','Zone Ideal Loads Zone Total Heating Energy']:
        rows.append(['Output:Variable','*',var,'Timestep'])
    rows += [['Output:Meter','Electricity:Facility','Timestep'],['Output:SQLite','SimpleAndTabular']]
    seen=set();unique=[]
    for r in rows:
        key=canonical(r)
        if r[0] in ['Output:SQLite','Output:Variable','Output:Meter'] and key in seen:continue
        seen.add(key);unique.append(r)
    path=OUT/'idfs'/variant/w['household_id']/f'{p["round_index"]:02d}_{side}.idf';path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_name(path.name+'.tmp.'+str(__import__('os').getpid()));temporary.write_text('! Static EB reference input;EP execution and delivered service remain unverified.\n! parameter_pack_sha256='+w['parameter_pack_sha256']+'\n'+dump(unique));temporary.replace(path)
    signal_path=OUT/'input_ledgers'/variant/w['household_id']/f'{p["round_index"]:02d}_{side}.json'
    save(signal_path,{'start_date':start.isoformat(),'days':days,'prior_days':prior_days,'signals':signals_data,'EV_diagnostics':ev_diagnostics,'spatial':spatial,'continuous_operations':continuous_plan['operations'],'execution':continuous_plan['execution'],'common_A_care_bookings':continuous_plan['common_A_care_bookings'],'post_operation_care_gaps':continuous_plan['post_operation_care_gaps'],'EV_SOC_after_step':continuous_plan['EV_SOC_after_step']})
    return {'side':side,'IDF_path':str(path.relative_to(OUT)),'IDF_sha256':sha(path),'parameter_pack_sha256':w['parameter_pack_sha256'],
        'schedule_signal_sha256':digest(signals_data),'start_date':start.isoformat(),'end_date':end.isoformat(),'EP_started':0,
        'EV_analytic_diagnostics':ev_diagnostics,'signal_names':names,'native_tank_topology':'complete EB DHW plant and mixing equipment;only showers carry target mixed draw',
        'AC_rated_point':'complete pinned EB native DX COP,SHR,flow/capacity ratio,fan andHPAC curves;capacity-scaled generic reference,not a Haier variable-speed performance model',
        'prior_days':prior_days,'inlet_assumption':inlet,'physical_variant':variant,
        'requested_RunPeriod_end':requested_end.isoformat(),'calendar_bridge_applied':requested_end!=end,
        'signal_ledger_path':str(signal_path.relative_to(OUT)),'signal_ledger_sha256':sha(signal_path),
        'background_design':'fixed published-density reference,50%aggregateplug reservation;shared room allocation explicit;not observed actual bills'}
def one(b):
    w=read(OUT/b['world_path']);background=parse(V12/'background_idfs'/f'{w["household_id"]}.idf');records=[]
    for index in range(1,11):
        p=read(OUT/'pairs'/w['household_id']/f'{index:02d}.json')
        records.append({'case_id':p['case_id'],'round_index':index,'pair_sha256':sha(OUT/'pairs'/w['household_id']/f'{index:02d}.json'),
            'A':compile_one(w,p,'A',background,weather_path=b['weather']['path']),'B':compile_one(w,p,'B',background,weather_path=b['weather']['path']),'EP_results':None})
    return {'household_id':w['household_id'],'records':records,'weather':b['weather']}
def main():
    school_guard();bs=read(OUT/'WORLD_BINDINGS50.json')['records'];result=[];failed=[]
    with concurrent.futures.ProcessPoolExecutor(max_workers=16) as pool:
        fs={pool.submit(one,b):b['household_id'] for b in bs}
        for f in concurrent.futures.as_completed(fs):
            try:result.append(f.result())
            except Exception as e:failed.append({'household_id':fs[f],'error':str(e)})
    result.sort(key=lambda x:x['household_id']);save(OUT/'IDF_BINDINGS1000.json',{'households':result,'IDF_count':sum(len(x['records'])*2 for x in result),'failed':failed,'EP_started':0})
    print({'IDFs':sum(len(x['records'])*2 for x in result),'failed':len(failed)},flush=True)
    if failed:raise RuntimeError(str(failed[:10]))
if __name__=='__main__':main()
