"""Compile complete paired IDF inputs on Linux. Deliberately contains no EP runner."""
import collections, concurrent.futures, copy, datetime as dt, math
from common import *
from plans import make_A
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
def signals(w,p,side):
    date=dt.date.fromisoformat(p['date']);start=date-dt.timedelta(days=7);devices=w['parameter_pack']['devices']
    sig={d['asset_id']:[0.]*1440 for d in devices};draw=[0.]*1440;evstates={d['asset_id']:.85 for d in devices if 'ev' in d['types']}
    for d in devices:
        if 'ac' in d['types']:sig[d['asset_id']+':available']=[0.]*1440
    diagnostics=[]
    for day in range(10):
        dat=start+dt.timedelta(days=day)
        if day in [7,8,9]:
            plan=p[side];needs=p['needs_A'];offset=(day-7)*1440
        else:
            needs,plan,_,_=make_A(w,dat);offset=0
        tasks=plan['tasks'];controls=plan['controls']
        for slot in range(144):
            minute=offset+slot*10;ix=day*144+slot
            for d in devices:
                aid=d['asset_id'];ks=d['types'];value=0.
                if 'ac' in ks:
                    c=next((c for c in controls if c['asset_id']==aid and c['start_min']<=minute<c['end_min']),None)
                    value=c['value_C'] if c else 50.
                    sig[aid+':available'][ix]=int(c is not None)
                elif 'water_heater' in ks:
                    c=next((c for c in controls if c['asset_id']==aid and c['start_min']<=minute<c['end_min']),None)
                    value=c['value_C'] if c else 10.
                elif 'ev' in ks:
                    cfg=d['parameters'];soc=evstates[aid]
                    trip=next((n for n in needs if n['kind']=='ev' and n['trip_departure_min']==minute),None)
                    if trip:
                        required=trip['quantity']/cfg['capacity_kwh'];shortfall=max(0.,required-soc)
                        diagnostics.append({'date':dat.isoformat(),'trip_energy_shortfall_kWh':shortfall*cfg['capacity_kwh'],'SOC_before':soc})
                        # Physical empty battery is preserved as a shortfall; no hidden minimum-SOC clipping.
                        soc=max(0.,soc-required)
                    c=next((c for c in controls if c['asset_id']==aid and c['start_min']<=minute<c['end_min']),None)
                    if c:
                        kwh=min(cfg['charger_kw']/6,max(0.,cfg['target_soc']-soc)*cfg['capacity_kwh']/cfg.get('efficiency',.92))
                        value=kwh*6*1000;soc+=kwh*cfg.get('efficiency',.92)/cfg['capacity_kwh']
                    evstates[aid]=soc
                else:
                    t=next((t for t in tasks if t['asset_id']==aid and t['start_min']<=minute<t['end_min']),None)
                    if t:value=(d['parameters'][t['kind']]['power_kw'] if 'washer' in ks else d['parameters']['power_kw'])*1000
                sig[aid][ix]=value
            if any(n['kind']=='water_heater' and n['release_min']<=minute<n['deadline_min'] for n in needs):draw[ix]=3/(.000141975*60000)
    sig['mixed_water_draw']=draw
    return sig,start,diagnostics
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
        put(coil,'gross_rated_cooling_cop',q['cooling_W']/(q['rated_electric_W']-fanW))
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
def compile_one(w,p,side,background):
    signals_data,start,ev_diagnostics=signals(w,p,side);rows=copy.deepcopy(background)
    remove={'People','Lights','ElectricEquipment','WaterHeater:Mixed','WaterHeater:Stratified','RunPeriod','Output:Variable','Output:Meter','OutputControl:Files',
        'ZoneControl:Thermostat','ThermostatSetpoint:DualSetpoint','ThermostatSetpoint:SingleHeating','ZoneControl:Humidistat','ZoneHVAC:IdealLoadsAirSystem','ZoneHVAC:EquipmentList','ZoneHVAC:EquipmentConnections','Site:WaterMainsTemperature'}
    rows=[r for r in rows if r[0] not in remove]
    for r in rows:
        if r[0]=='Timestep':r[1]=6
    end=start+dt.timedelta(days=9)
    rows += [obj('RunPeriod',{'name':'v16_seven_common_prior_days_plus_target_and_recovery','begin_month':start.month,'begin_day_of_month':start.day,'begin_year':start.year,'end_month':end.month,'end_day_of_month':end.day,'end_year':end.year,
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
    # Stable weekly room occupancy; source density is distinct from named EB devices.
    for room in w['layout']['rooms']:
        rid=room['room_id'];area=room['thermal_reference_area_m2'];share=1/len(room['using_household_ids']) if w['household_id'] in room['using_household_ids'] else 0
        light_values=[]
        for day in range(10):
            weekday=(start+dt.timedelta(days=day)).weekday()
            for slot in range(144):
                calendars=[m['weekly_calendar'][weekday]['intervals'] for m in w['members']]
                awake_home=any(x['location']=='home' and x['activity']!='sleep_rest' for calendar in calendars for x in calendar if x['start_h']<=slot/6<x['end_h'])
                light_values.append(int(awake_home and share>0))
        light_schedule='v16_light_clock_'+rid;rows.append(['Schedule:Compact',light_schedule,'v16_fraction']+compact(light_values,start))
        rows += [obj('Lights',{'name':'v16_light_'+rid,'zone_or_zonelist_or_space_or_spacelist_name':rid,'schedule_name':light_schedule,'design_level_calculation_method':'LightingLevel',
            'lighting_level':area*(1.8 if room['census_room_class']=='corridor' else 4.2)*share,'return_air_fraction':0,'fraction_radiant':.4,'fraction_visible':.2,'fraction_replaceable':1,'end_use_subcategory':'allocated_reference_lighting'}),
            obj('ElectricEquipment',{'name':'v16_background_'+rid,'zone_or_zonelist_or_space_or_spacelist_name':rid,'schedule_name':'v16_all','design_level_calculation_method':'EquipmentLevel',
                'design_level':area*.5*(5 if room['census_room_class']=='kitchen' else 2)*share,'fraction_latent':0,'fraction_radiant':.3,'fraction_lost':0,'end_use_subcategory':'separate_fixed_reference_background'})]
    for m in w['members']:
        rid=m['reference_home_room_id'];vs=[]
        for day in range(10):
            weekday=(start+dt.timedelta(days=day)).weekday();calendar=m['weekly_calendar'][weekday]['intervals']
            for slot in range(144):
                x=next(x for x in calendar if x['start_h']<=slot/6<x['end_h']);vs.append(int(x['location']=='home'))
        name='v16_person_'+m['local_id'];rows.append(['Schedule:Compact',name,'v16_fraction']+compact(vs,start))
        rows.append(obj('People',{'name':name,'zone_or_zonelist_or_space_or_spacelist_name':rid,'number_of_people_schedule_name':name,'number_of_people_calculation_method':'People','number_of_people':1,'fraction_radiant':.3,'sensible_heat_fraction':'Autocalculate','activity_level_schedule_name':'v16_person_W'}))
    if not w['operating_context']['operators'][0]['resident']:
        # Availability is not occupancy. Model the nonresident only during saved
        # handling operations, in the device room; never add them to roster N.
        oid=w['operating_context']['operators'][0]['operator_id'];visits=collections.defaultdict(lambda:[0.]*1440)
        for rid in sorted({d['room_id'] for d in w['parameter_pack']['devices'] if set(d['types'])&{'washer','dishwasher'}}):visits[rid]=[0.]*1440
        for day in range(10):
            dat=start+dt.timedelta(days=day)
            if day>=7:plan=p[side];offset=(day-7)*1440
            else:_,plan,_,_=make_A(w,dat);offset=0
            ts={t['need_id']:t for t in plan['tasks']};device_by_id={d['asset_id']:d for d in w['parameter_pack']['devices']}
            for op in plan['operations']:
                if op['operator_id']!=oid or op['need_id'] not in ts:continue
                rid=device_by_id[ts[op['need_id']]['asset_id']]['room_id']
                for slot in range(144):
                    if op['start_min']<=offset+slot*10<op['end_min']:visits[rid][day*144+slot]=1.
        for rid,vs in visits.items():
            name='v16_external_visit_'+rid;rows.append(['Schedule:Compact',name,'v16_fraction']+compact(vs,start))
            rows.append(obj('People',{'name':name,'zone_or_zonelist_or_space_or_spacelist_name':rid,'number_of_people_schedule_name':name,'number_of_people_calculation_method':'People','number_of_people':1,'fraction_radiant':.3,'sensible_heat_fraction':'Autocalculate','activity_level_schedule_name':'v16_person_W'}))
    for d in w['parameter_pack']['devices']:
        if set(d['types'])&{'ac','water_heater'}:continue
        rid=d['room_id'] if 'ev' not in d['types'] else w['members'][0]['reference_home_room_id']
        rows.append(obj('ElectricEquipment',{'name':d['asset_id'],'zone_or_zonelist_or_space_or_spacelist_name':rid,'schedule_name':names[d['asset_id']],'design_level_calculation_method':'EquipmentLevel','design_level':1,
            'fraction_latent':0,'fraction_radiant':0 if 'ev' in d['types'] else .3,'fraction_lost':1 if 'ev' in d['types'] else 0,'end_use_subcategory':'target_'+('_'.join(d['types']))}))
    add_ac(rows,w,names);add_tank(rows,w,names)
    for var in ['Zone Mean Air Temperature','Zone Air Relative Humidity','Zone People Occupant Count','Lights Electricity Energy','Electric Equipment Electricity Energy',
        'Cooling Coil Electricity Energy','Fan Electricity Energy','Water Heater Electricity Energy','Water Heater Tank Temperature','Water Heater Use Side Outlet Temperature',
        'Water Use Equipment Total Volume','Water Use Equipment Hot Water Volume','Water Use Equipment Cold Water Volume','Water Use Equipment Mixed Water Temperature','Zone Ideal Loads Zone Total Heating Energy']:
        rows.append(['Output:Variable','*',var,'Timestep'])
    rows += [['Output:Meter','Electricity:Facility','Timestep'],['Output:SQLite','SimpleAndTabular']]
    seen=set();unique=[]
    for r in rows:
        key=canonical(r)
        if r[0] in ['Output:SQLite','Output:Variable','Output:Meter'] and key in seen:continue
        seen.add(key);unique.append(r)
    path=OUT/'idfs'/w['household_id']/f'{p["round_index"]:02d}_{side}.idf';path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text('! Static EB reference input;EP execution and delivered service remain unverified.\n! parameter_pack_sha256='+w['parameter_pack_sha256']+'\n'+dump(unique))
    return {'side':side,'IDF_path':str(path.relative_to(OUT)),'IDF_sha256':sha(path),'parameter_pack_sha256':w['parameter_pack_sha256'],
        'schedule_signal_sha256':digest(signals_data),'start_date':start.isoformat(),'end_date':end.isoformat(),'EP_started':0,
        'EV_analytic_diagnostics':ev_diagnostics,'signal_names':names,'native_tank_topology':'complete EB DHW plant and mixing equipment;only showers carry target mixed draw',
        'AC_rated_point':'OEM whole-unit power minus EB fan-rated power sets compressor COP;EB curves are an explicit offdesign transfer',
        'background_design':'fixed published-density reference,50%aggregateplug reservation;shared room allocation explicit;not observed actual bills'}
def one(b):
    w=read(OUT/b['world_path']);background=parse(V12/'background_idfs'/f'{w["household_id"]}.idf');records=[]
    for index in range(1,11):
        p=read(OUT/'pairs'/w['household_id']/f'{index:02d}.json')
        records.append({'case_id':p['case_id'],'round_index':index,'pair_sha256':sha(OUT/'pairs'/w['household_id']/f'{index:02d}.json'),
            'A':compile_one(w,p,'A',background),'B':compile_one(w,p,'B',background),'EP_results':None})
    return {'household_id':w['household_id'],'records':records,'weather':b['weather']}
def main():
    school_guard();bs=read(OUT/'WORLD_BINDINGS1000.json')['records'];result=[];failed=[]
    with concurrent.futures.ProcessPoolExecutor(max_workers=16) as pool:
        fs={pool.submit(one,b):b['household_id'] for b in bs}
        for f in concurrent.futures.as_completed(fs):
            try:result.append(f.result())
            except Exception as e:failed.append({'household_id':fs[f],'error':str(e)})
    result.sort(key=lambda x:x['household_id']);save(OUT/'IDF_BINDINGS20000.json',{'households':result,'IDF_count':sum(len(x['records'])*2 for x in result),'failed':failed,'EP_started':0})
    print({'IDFs':sum(len(x['records'])*2 for x in result),'failed':len(failed)},flush=True)
    if failed:raise RuntimeError(str(failed[:10]))
if __name__=='__main__':main()
