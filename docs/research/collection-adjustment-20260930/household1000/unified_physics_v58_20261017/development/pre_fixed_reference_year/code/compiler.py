"""One model for shell, dated people, executed programs, EV, HVAC and hot water.

Source requests are immutable. An unavailable loading operation does not create
an electrically running machine. Failed retrieval leaves that machine occupied;
there is no invented recovery visit. Weather-based mains and native EB thermal
fractions are reference assumptions, never household calibration.
"""
import collections
import copy
import math
from functools import lru_cache
from core import *

@lru_cache(maxsize=1)
def fields():return read(ROOT/'inputs/schema_fields.json.gz')

@lru_cache(maxsize=1)
def native():return read(ROOT/'inputs/native_rows.json.gz')

def put(row,key,value):
    i=fields()[row[0]].index(key)+1
    row.extend(['']*max(0,i+1-len(row)));row[i]=value

def obj(kind,values):
    names=fields()[kind];last=max(names.index(k)for k in values)
    return [kind]+[values.get(k,'')for k in names[:last+1]]

def reverse_paired_constructions(rows):
    """Opposite faces of an interzone wall must see reversed layer ordering."""
    byname={r[1].lower():r for r in rows if r[0]=='BuildingSurface:Detailed'}
    constructions={r[1].lower():r for r in rows if r[0]=='Construction'}
    f=fields()['BuildingSurface:Detailed'];idx=lambda k:f.index(k)+1
    handled=set();changes=[];add=[]
    for name,r in sorted(byname.items()):
        if r[idx('outside_boundary_condition')].lower()!='surface':continue
        othername=r[idx('outside_boundary_condition_object')].lower()
        if othername not in byname or name in handled:continue
        other=byname[othername];first=constructions[r[idx('construction_name')].lower()]
        second=constructions[other[idx('construction_name')].lower()]
        if [x.lower()for x in first[2:]]!=[x.lower()for x in reversed(second[2:])]:
            revname=first[1]+'_v58_reverse'
            if revname.lower()not in constructions:
                rev=['Construction',revname,*reversed(first[2:])];add.append(rev);constructions[revname.lower()]=rev
            put(other,'construction_name',revname)
            changes.append({'surface':other[1],'paired_surface':r[1],'derived_construction':revname,'geometry_or_requests_changed':False})
        handled.update((name,othername))
    rows.extend(add)
    return changes

def schedule(name,days,default=0):
    """Correct annual ordering even when a replay spans December/January."""
    ordered=sorted((dt.date(2024,d.month,d.day),v)for d,v in days.items())
    row=['Schedule:Compact',name,'any'];previous=dt.date(2024,1,1)
    for date,values in ordered:
        if date>previous:
            gap=date-dt.timedelta(days=1)
            row.extend([f'Through: {gap.month}/{gap.day}','For: AllDays','Until: 24:00',default])
        row.extend([f'Through: {date.month}/{date.day}','For: AllDays'])
        for i,v in enumerate(values):
            if i==143 or v!=values[i+1]:
                end=(i+1)*10
                row.extend([f'Until: {end//60:02d}:{end%60:02d}',v])
        previous=date+dt.timedelta(days=1)
    if previous<=dt.date(2024,12,31):row.extend(['Through: 12/31','For: AllDays','Until: 24:00',default])
    return row

@lru_cache(maxsize=40)
def weather_statistics(path):
    monthly=collections.defaultdict(list)
    for line in Path(path).read_text().splitlines()[8:]:
        v=line.split(',')
        if len(v)>7:
            t=float(v[6])
            if -90<t<70:monthly[int(v[1])].append(t)
    if len(monthly)!=12:raise ValueError('INCOMPLETE_EPW_TEMPERATURES')
    means=[sum(v)/len(v)for v in monthly.values()]
    return {'annual_average_C':sum(sum(v)for v in monthly.values())/sum(map(len,monthly.values())),
            'monthly_mean_range_C':max(means)-min(means),
            'method':'EnergyPlus Site:WaterMainsTemperature Correlation;EPW annual mean and monthly range',
            'measured_local_mains':False}

def merged_plan(pack,pair,side,lo,hi):
    anchor=offset(pair['date'],pack['anchor'])
    result={}
    annual_controls=[c for d in pack['days'].values()for c in d['controls']]
    for key,original,idkey in [('tasks',pack['tasks'],'task_id'),('operations',pack['operations'],'operation_id')]:
        replacement={x[idkey]:x for x in pair[side][key]}
        result[key]=[copy.deepcopy(x) for x in original if x[idkey]not in replacement and overlap(x['start_min']-anchor,x['end_min']-anchor,lo,hi)]
        for x in result[key]:x['start_min']-=anchor;x['end_min']-=anchor
        result[key]+=[copy.deepcopy(x)for x in replacement.values()if overlap(x['start_min'],x['end_min'],lo,hi)]
    bounds={}
    for c in pair['A']['controls']+pair[side]['controls']:
        key=(c['asset_id'],c['kind']);a,z=bounds.get(key,(c['start_min'],c['end_min']))
        bounds[key]=(min(a,c['start_min']),max(z,c['end_min']))
    result['controls']=[]
    for c in annual_controls:
        a=c['start_min']-anchor;z=c['end_min']-anchor
        if not overlap(a,z,lo,hi):continue
        key=(c['asset_id'],c['kind'])
        intervals=[(a,z)]
        if key in bounds:
            left,right=bounds[key]
            intervals=[(a,min(z,left)),(max(a,right),z)]
        result['controls'].extend({**c,'start_min':x,'end_min':y}for x,y in intervals if x<y and overlap(x,y,lo,hi))
    result['controls']+=[copy.deepcopy(c)for c in pair[side]['controls']if overlap(c['start_min'],c['end_min'],lo,hi)]
    for key in result:result[key].sort(key=lambda x:(x['start_min'],x.get('operation_id',x.get('task_id',x.get('need_id','')))))
    return result

def execute(pack,pair,plan,lo,hi):
    """Literal operation executor, including failed loads and occupied machines."""
    date=dt.date.fromisoformat(pair['date']);bad=collections.defaultdict(set);bookings=collections.defaultdict(list)
    for op in plan['operations']:
        daydate=date+dt.timedelta(days=op['start_min']//1440);d=pack['days'].get(str(daydate));local=op['start_min']%1440
        if d is None or not any(a<=local and local+10<=b for a,b in d['operator_windows'].get(op['operator_id'],[])):
            bad[op['operation_id']].add('OPERATOR_UNAVAILABLE')
        if d:
            blocked=[(x['room_id'],x['start_min'],x['end_min'])for x in d['shared']['facility_reservations']]
            bath=pack['world']['activity_contract']['room_map']['bath']
            blocked +=[(bath,t,t+10)for t in d['family']['bath_times_min'].values()]
            if any(r==op['room_id']and overlap(local,local+10,a,b)for r,a,b in blocked):bad[op['operation_id']].add('FACILITY_RESERVED')
        for minute in range(op['start_min'],op['end_min'],10):
            bookings[('operator',op['operator_id'],minute)].append(op['operation_id'])
            if not op['kind'].startswith('EV_'):bookings[('room',op['room_id'],minute)].append(op['operation_id'])
    for key,ids in bookings.items():
        if len(ids)>1:
            for oid in ids:bad[oid].add(key[0].upper()+'_DOUBLE_BOOKED')
    holds=collections.defaultdict(list);batch=[];not_run=set();failed_ops=set();needs={n['need_id']:n for n in pair['needs_A']}
    unloads={o['need_id']:o for o in plan['operations']if o['kind']=='unload'}
    for load in (o for o in plan['operations']if o['kind']=='load'):
        nid=load['need_id'];tasks=[t for t in plan['tasks']if t['need_id']in(nid,nid+':dry')];unload=unloads.get(nid)
        if not tasks:continue
        first=min(t['start_min']for t in tasks);end=max(t['end_min']for t in tasks)
        reasons=set(bad[load['operation_id']])
        if nid in needs and load['start_min']<needs[nid]['release_min']:reasons.add('LOAD_BEFORE_SERVICE_RELEASE')
        if first<load['end_min']:reasons.add('PROGRAM_BEFORE_LOADING')
        if any(overlap(load['start_min'],max(end,unload['end_min']if unload else hi),a,b)for a,b in holds[load['asset_id']]):reasons.add('ASSET_STILL_OCCUPIED')
        ran=not reasons
        collected=ran and unload is not None and not bad[unload['operation_id']]and unload['start_min']>=end
        if ran:holds[load['asset_id']].append((load['start_min'],unload['end_min']if collected else hi))
        else:
            not_run.update(t['task_id']for t in tasks);failed_ops.add(load['operation_id'])
        if unload and not collected:failed_ops.add(unload['operation_id'])
        if end>=480:batch.append({'need_id':nid,'program_executed':ran,'collected':collected,'reasons':sorted(reasons|set(bad[unload['operation_id']]if unload else ['NO_RETRIEVAL_IN_HORIZON'])),
                                 'requested_program_end_min':end,'requested_retrieval_end_min':unload['end_min']if unload else None})
    failed_ops.update(k for k,v in bad.items()if v)
    return {'tasks':[t for t in plan['tasks']if t['task_id']not in not_run],
            'operations':[o for o in plan['operations']if o['operation_id']not in failed_ops],
            'batches':batch,'operation_failures':{k:sorted(v)for k,v in bad.items()if v},
            'dropped_program_ids':sorted(not_run),'automatic_repair':False}

def day_people(pack,date,ops,rooms):
    d=pack['days'][str(date)];people={r:[0.]*144 for r in rooms};awake={r:[0.]*144 for r in rooms}
    positions={}
    assets={x['asset_id']:x for x in pack['world']['parameter_pack']['devices']}
    calendars={**d['calendars'],**d['shared']['member_calendars']}
    for mid,cal in calendars.items():
        for item in cal:
            for t in range(max(0,item['start_min']),min(1440,item['end_min']),10):
                room=item.get('room_id')if item.get('location')=='home'else None
                activity=item.get('activity','');is_awake=not(activity.startswith('sleep')or'nap'in activity)
                positions[(mid,t)]=(room,is_awake)
    # Declared nonresident visits contribute heat only while actually present.
    visits=d.get('external_visits',[])
    for ix,v in enumerate(visits):
        rid=v.get('room_id');a=v.get('start_min');z=v.get('end_min')
        if rid in people and a is not None and z is not None:
            for t in range(a,z,10):positions[(v.get('person_id','given_visitor_'+str(ix)),t)]=(rid,True)
    # This also represents a nonresident actual handler absent from all resident
    # calendars; a person is counted only once even if a visit already exists.
    for op in ops:
        rid=None if op['kind'].startswith('EV_')else assets[op['asset_id']]['room_id']
        for t in range(max(0,op['start_min']),min(1440,op['end_min']),10):positions[(op['operator_id'],t)]=(rid,True)
    for (_,t),(rid,is_awake)in positions.items():
        if rid in people:
            people[rid][t//10]+=1
            if is_awake:awake[rid][t//10]+=1
    return people,awake

def ev_delivery(pack,pair,side,plan,lo,hi):
    ref=pair['EV_continuous_reference']
    if ref['status']=='not_installed':return {},{'installed':False}
    steps={};base=offset(pair['date'],pack['anchor'])
    for event in pack['EV_battery_energy_events']:
        if event['kind']=='charge':
            a=event['start_min']-base;z=event['end_min']-base
            for t in range(max(lo,a),min(480,z),10):steps[t]=steps.get(t,0)+event['battery_kWh']/(z-a)*10/ref['efficiency']
    device=next(d for d in pack['world']['parameter_pack']['devices']if 'ev'in d['types']);par=device['parameters']
    energy=ref['initial_energy_kWh'];initial=energy;trips={x['absolute_departure_min']-base:x for x in pack['journeys']};triprows=[]
    unplug={o['need_id']:o for o in pack['operations']if o['kind']=='EV_unplug'}
    connections={o['need_id']:(o['end_min']-base,unplug[o['need_id']]['start_min']-base)for o in pack['operations']if o['kind']=='EV_plug'}
    controls=[c for c in plan['controls']if c['kind']=='ev_charge_window'];trace=[];stop=None
    for t in range(480,hi+1,10):
        trip=trips.get(t)
        if trip:
            before=energy;required=trip['traction_kWh'];deficit=max(0,required-before)
            triprows.append({'departure_min':t,'pre_trip_kWh':before,'post_trip_kWh':max(0,before-required),'traction_kWh':required,
                             'target_shortfall_kWh':max(0,ref['target_SOC']*ref['capacity_kWh']-before),
                             'minimum_reserve_shortfall_kWh':max(0,ref['minimum_SOC']*ref['capacity_kWh']-max(0,before-required)),
                             'unserved_traction_kWh':deficit})
            energy=max(0,energy-required)
            if deficit>1e-7:stop=t;trace.append([t,energy]);break
        trace.append([t,energy])
        if t==hi:break
        cs=[c for c in controls if c['start_min']<=t<c['end_min']]
        if len(cs)>1:raise ValueError('OVERLAPPING_EV_CONTROLS')
        if cs:
            c=cs[0];a,z=connections[c['need_id']]
            if a<=t and t+10<=z:
                battery=min(par['charger_kw']*par['efficiency']/6,max(0,c['stop_at_target_soc']*par['capacity_kwh']-energy))
                if battery>1e-10:energy+=battery;steps[t]=battery/par['efficiency']
    return steps,{'installed':True,'trace':trace,'trips':triprows,'stop_at_unexecutable_trip_min':stop,
                  'initial_energy_kWh':initial,'end_energy_kWh':energy,
                  'energy_balance_error_kWh':energy-initial-sum(v*par['efficiency']for t,v in steps.items()if t>=480)+sum(min(x['traction_kWh'],x['pre_trip_kWh'])for x in triprows),
                  'same_physical_connections':True,'future_A_controls_restored':True}

def last_actual_request_change(pair):
    ends=[]
    for key,ident in [('tasks','task_id'),('operations','operation_id')]:
        aa={x[ident]:x for x in pair['A'][key]};bb={x[ident]:x for x in pair['B'][key]}
        for id_ in aa.keys()|bb.keys():
            a=aa.get(id_);b=bb.get(id_)
            sig=lambda x:None if x is None else (x['start_min'],x['end_min'],x['kind'],x['asset_id'])
            if sig(a)!=sig(b):ends.extend(x['end_min']for x in (a,b)if x is not None)
    def states(plan):
        out={}
        for c in plan['controls']:
            kind=c['kind'];keys=('heating_setpoint_C','cooling_setpoint_C','fan_operating_mode')if kind=='ac_setpoint'else('value_C',)if kind=='tank_setpoint'else('stop_at_target_soc',)
            for t in range(max(480,c['start_min']),c['end_min'],10):out[(c['asset_id'],kind,t)]=tuple(c[k]for k in keys)
        return out
    aa=states(pair['A']);bb=states(pair['B'])
    ends.extend(k[2]+10 for k in aa.keys()|bb.keys()if aa.get(k)!=bb.get(k))
    return max(ends)if ends else None

def compile_model(pack,pair,side,folder,history_days=28,tail_days=8):
    date=dt.date.fromisoformat(pair['date']);start=date-dt.timedelta(days=history_days)
    available_start=dt.date.fromisoformat(pack['anchor']);start=max(start,available_start)
    last_change=last_actual_request_change(pair);last_request=max(1920,last_change or 1920)
    tail_end=max(tail_days*1440,last_request+7*1440)
    end=date+dt.timedelta(days=math.ceil(tail_end/1440))
    end=min(end,dt.date.fromisoformat(pack['end_exclusive']))
    lo=(start-date).days*1440;hi=(end-date).days*1440
    days=[start+dt.timedelta(days=i)for i in range((end-start).days)]
    plan=merged_plan(pack,pair,side,lo,hi);executed=execute(pack,pair,plan,lo,hi)
    rows=[copy.deepcopy(r)for r in pack['shell_rows']if r[0]not in('RunPeriod','Timestep','SimulationControl')and not r[0].startswith('Output:')]
    wall_repairs=reverse_paired_constructions(rows)
    # CSWD is a non-leap reference year. Avoid a leap/non-leap crossing in EP's
    # weather-period day count; dated human calendars still use original dates.
    year_shift=1 if start.year==2024 else 0
    rows +=[['Timestep',6],['SimulationControl','No','No','No','No','Yes'],
             ['RunPeriod','unified_AB',start.month,start.day,start.year+year_shift,(end-dt.timedelta(days=1)).month,(end-dt.timedelta(days=1)).day,(end-dt.timedelta(days=1)).year+year_shift,dt.date(start.year+year_shift,start.month,start.day).strftime('%A'),'No','No','No','Yes','Yes'],
             ['ScheduleTypeLimits','any','','','Continuous'],['Schedule:Constant','always','any',1],['Schedule:Constant','zero','any',0],['Schedule:Constant','dual','any',4],['Schedule:Constant','metabolic','any',117.28]]
    rooms=[r['room_id']for r in pack['world']['layout']['rooms']];assets={d['asset_id']:d for d in pack['world']['parameter_pack']['devices']}
    controls=collections.defaultdict(list)
    for c in plan['controls']:controls[(c['asset_id'],c['kind'])].append(c)
    def series(fn):return {day:[fn((day-date).days*1440+t,day,t)for t in range(0,1440,10)]for day in days}
    zones=collections.defaultdict(list);asset_meters={};equipment_names={}
    for package in pack['HVAC']:
        zones[package['room_id']].append(package);rows.extend(copy.deepcopy(package['rows']));aid=package['asset_id']
        cs=controls[(aid,'ac_setpoint')]
        lookup={t:c for c in cs for t in range(max(lo,c['start_min']),min(hi,c['end_min']),10)}
        for key,name in package['schedule_names'].items():
            def value(t,day,local,key=key):
                c=lookup.get(t)
                if key=='available':return int(c is not None)
                if key=='fan_mode':return c.get('fan_operating_mode',0)if c else 0
                return c['heating_setpoint_C']if c and key=='heat_sp'else 5 if key=='heat_sp'else c['cooling_setpoint_C']if c else 50
            rows.append(schedule(name,series(value),5 if key=='heat_sp'else 50 if key=='cool_sp'else 0))
        equipment_names[aid]=package['equipment_name'].upper()
    for room,ps in zones.items():
        prefix='zone_'+digest(room)[:10]
        rows +=[['NodeList',prefix+'_supply']+[p['zone_supply_node']for p in ps],['NodeList',prefix+'_return']+[p['zone_return_node']for p in ps]]
        eq=['ZoneHVAC:EquipmentList',prefix+'_equipment','SequentialLoad']
        for i,p in enumerate(ps,1):eq+=['ZoneHVAC:PackagedTerminalHeatPump',p['equipment_name'],i,i,'','']
        rows +=[eq,['ZoneHVAC:EquipmentConnections',room,prefix+'_equipment',prefix+'_supply',prefix+'_return',prefix+'_air',''],
                 ['ThermostatSetpoint:DualSetpoint',prefix+'_setpoint',ps[0]['schedule_names']['heat_sp'],ps[0]['schedule_names']['cool_sp']],
                 ['ZoneControl:Thermostat',prefix+'_thermostat',room,'dual','ThermostatSetpoint:DualSetpoint',prefix+'_setpoint']]
    # Actual executed handling changes room headcounts; blocked handling does not.
    pp={};aa={}
    for day in days:
        off=(day-date).days*1440
        ops=[{**o,'start_min':o['start_min']-off,'end_min':o['end_min']-off}for o in executed['operations']if overlap(o['start_min'],o['end_min'],off,off+1440)]
        pp[day],aa[day]=day_people(pack,day,ops,rooms)
    for room in rooms:
        name='people_'+digest(room)[:10];rows.append(schedule(name,{d:pp[d][room]for d in days}))
        rows.append(obj('People',{'name':name,'zone_or_zonelist_or_space_or_spacelist_name':room,'number_of_people_schedule_name':name,'number_of_people_calculation_method':'People','number_of_people':1,'fraction_radiant':0,'sensible_heat_fraction':'autocalculate','activity_level_schedule_name':'metabolic','enable_ashrae_55_comfort_warnings':'No'}))
    # Explicit common benchmark boundary, rather than an accidental perfectly
    # sealed dwelling. Historical BA reference, not a local compliance/measurement.
    reference_ach=float(os.environ.get('EB_REFERENCE_ACH','.35'))
    if not 0<reference_ach<=3:raise ValueError('INVALID_REFERENCE_AIR_EXCHANGE')
    for room in rooms:
        rows.append(obj('ZoneInfiltration:DesignFlowRate',{'name':'reference_air_'+digest(room)[:10],
            'zone_or_zonelist_or_space_or_spacelist_name':room,'schedule_name':'always',
            'design_flow_rate_calculation_method':'AirChanges/Hour','air_changes_per_hour':reference_ach,
            'constant_term_coefficient':1,'temperature_term_coefficient':0,'velocity_term_coefficient':0,'velocity_squared_term_coefficient':0}))
    gains={r[1].lower():r for r in native()['gains']if r[0]=='ElectricEquipment'}
    thermal={'washer':'clotheswasher1','dryer':'electric_dryer1','dishwasher':'dishwasher1'}
    for aid,device in assets.items():
        for kind in device['types']:
            if kind not in thermal:continue
            ts=[t for t in executed['tasks']if t['asset_id']==aid and t['kind']==kind]
            name='program_'+digest([aid,kind])[:12];active={t for x in ts for t in range(max(lo,x['start_min']),min(hi,x['end_min']),10)}
            rows.append(schedule(name,series(lambda t,d,l:int(t in active))))
            p=device['parameters'];watts=p.get(kind,p)['power_kw']*1000
            equip=name+'_equipment';source=gains[thermal[kind]]
            rows.append(['ElectricEquipment',equip,device['room_id'],name,'EquipmentLevel',watts,'','',*source[8:11],kind])
            asset_meters[equip.upper()]={'asset_id':aid,'kind':kind,'watts':watts,'thermal_fractions':source[8:11]}
    # EB prototype background powers/fractions are explicit common A/B conditions.
    lighting_density=sum(float(r[6])for r in native()['gains']if r[0]=='Lights')
    for room in pack['world']['layout']['rooms']:
        rid=room['room_id'];area=room['thermal_reference_area_m2'];key=digest(rid)[:10]
        light='lighting_'+key;rows.append(schedule(light,{d:[int(v>0)for v in aa[d][rid]]for d in days}))
        rows.append(['Lights',light+'_equipment',rid,light,'LightingLevel',lighting_density*area,'','','0','0.6','0.2','0','background_lighting'])
        misc='misc_'+key;source=gains['IECC_Adj1'.lower()]
        rows.append(schedule(misc,{d:[.25+.75*int(v>0)for v in aa[d][rid]]for d in days}))
        rows.append(['ElectricEquipment',misc+'_equipment',rid,misc,'EquipmentLevel',float(source[6])*area,'','',*source[8:11],'background_plugs'])
    kitchen=next((r['room_id']for r in pack['world']['layout']['rooms']if r['census_room_class']=='kitchen'),rooms[0])
    for kind,native_name in [('refrigerator','refrigerator1'),('cooking','electric_range1')]:
        source=gains[native_name];name='background_'+kind
        if kind=='refrigerator':sch='always'
        else:
            sch=name+'_schedule'
            def meal(t,d,l):
                dinners=pack['days'][str(d)]['family']['member_dinners_min'].values()
                return int(any(a-30<=l<a for a in dinners))
            rows.append(schedule(sch,series(meal)))
        rows.append(['ElectricEquipment',name,kitchen,sch,'EquipmentLevel',float(source[5]),'','',*source[8:11],'background_'+kind])
    # EV stays outside dwelling heat balance; EP meters delivered AC grid energy.
    ev=pair['EV_continuous_reference'];evsteps,evtrace=ev_delivery(pack,pair,side,plan,lo,hi)
    if ev['status']!='not_installed':
        name='external_EV';power=ev['charger_kW']*1000
        rows.append(schedule(name,series(lambda t,d,l:evsteps.get(t,0)*6000/power)))
        rows.append(['Exterior:FuelEquipment',name,'Electricity',name,power,'external_dedicated_EV'])
    # Native tank/plant with actual mixed-water needs and weather-driven mains.
    tank=next((d for d in assets.values()if 'water_heater'in d['types']),None)
    water_needs=[];tank_name=None
    if tank:
        cs=controls[(tank['asset_id'],'tank_setpoint')];lookup={t:c for c in cs for t in range(max(lo,c['start_min']),min(hi,c['end_min']),10)}
        rows.append(schedule('tank_target',series(lambda t,d,l:lookup[t]['value_C']if t in lookup else 10),10))
        for d in days:
            off=(d-date).days*1440;origin=offset(str(d),pack['anchor'])
            water_needs.extend({**n,'release_min':n['release_min']-origin+off,'deadline_min':n['deadline_min']-origin+off}for n in pack['days'][str(d)]['water_needs'])
        peak=.000141975
        rows.append(schedule('water_draw',series(lambda t,d,l:sum(n['quantity']/((n['deadline_min']-n['release_min'])*60)/1000/peak for n in water_needs if n['release_min']<=t<n['deadline_min']))))
        rows.append(['Schedule:Constant','mixed_target','any',pack['world']['routine']['mixed_target_C']])
        types={'Branch','BranchList','Connector:Splitter','Connector:Mixer','ConnectorList','Pipe:Adiabatic','Pump:VariableSpeed','PlantLoop','PlantEquipmentList','PlantEquipmentOperation:HeatingLoad','PlantEquipmentOperationSchemes','SetpointManager:Scheduled','WaterUse:Equipment','WaterUse:Connections','WaterHeater:Stratified'}
        mapping={'EWH_Setpoint_Control':'tank_target','EWH_Availability_Control':'always','BA_shower_sch':'water_draw','BA_sink_sch':'zero','BA_bath_sch':'zero','SSBWaterTempSchedule':'mixed_target'}
        for source in native()['tank']:
            if source[0]not in types or source[1].startswith('Air Loop'):continue
            r=[mapping.get(x,x.replace('_unit1','_v58'))for x in source]
            if r[0]=='WaterHeater:Stratified':
                tank_name=r[1].upper()
                for k,v in {'ambient_temperature_zone_name':tank['room_id'],'end_use_subcategory':'target_electric_hot_water','tank_volume':tank['parameters']['volume_m3'],'heater_1_capacity':tank['parameters']['heater_capacity_W'],'maximum_temperature_limit':tank['parameters']['maximum_C']}.items():put(r,k,v)
            if r[0]=='WaterUse:Equipment':
                for k,v in {'zone_name':tank['room_id'],'target_temperature_schedule_name':'mixed_target','cold_water_supply_temperature_schedule_name':'','sensible_fraction_schedule_name':'zero','latent_fraction_schedule_name':'zero'}.items():put(r,k,v)
            if r[0]=='WaterUse:Connections':put(r,'cold_water_supply_temperature_schedule_name','')
            rows.append(r)
    stat=weather_statistics(str(ROOT/pack['weather']))
    rows.append(['Site:WaterMainsTemperature','Correlation','',stat['annual_average_C'],stat['monthly_mean_range_C']])
    variables=['Zone Mean Air Temperature','Zone Air Relative Humidity','Zone Mean Radiant Temperature','Zone People Occupant Count',
               'Zone Infiltration Air Change Rate',
               'Zone Packaged Terminal Heat Pump Electricity Energy',
               'Electric Equipment Electricity Energy','Lights Electricity Energy','Site Mains Water Temperature']
    if ev['status']!='not_installed':variables.append('Exterior Equipment Electricity Energy')
    if tank:
        variables +=['Water Heater Electricity Energy','Pump Electricity Energy','Water Heater Tank Temperature',
                     'Water Heater Use Side Outlet Temperature','Water Use Equipment Mixed Water Temperature','Water Use Equipment Total Volume']
        variables +=[f'Water Heater Final Temperature Node {i}'for i in range(1,tank['parameters']['number_of_nodes']+1)]
    for v in variables:rows.append(['Output:Variable','*',v,'Timestep'])
    meters=['Electricity:Facility','Electricity:HVAC','InteriorEquipment:Electricity','InteriorLights:Electricity']
    if tank:meters.append('WaterSystems:Electricity')
    if ev['status']!='not_installed':meters.append('ExteriorEquipment:Electricity')
    for meter in meters:
        rows.append(['Output:Meter',meter,'Timestep'])
    rows +=[['Output:SQLite','SimpleAndTabular'],['Output:VariableDictionary','IDF','Unsorted'],['Output:Diagnostics','DisplayAdvancedReportVariables']]
    # OutputControl:Files defaults differ by engine; retain default engine exports
    # and compact only this newly created job after preserving its SQL and errors.
    rows=[r for r in rows if r[0]!='OutputControl:Files']
    text='\n\n'.join(',\n  '.join(str(v)for v in r)+';'for r in rows)+'\n'
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    (folder/'model.idf').write_text(text)
    meta={'schema':VERSION,'case_id':pair['case_id'],'side':side,'source_pair_sha256':pair['source_pair_sha256'],
          'source_schedule_hash':pair['schedule_hashes'][side],'source_shell_sha256':pack['source_shell_sha256'],
          'weather_sha256':pack['weather_sha256'],'idf_sha256':sha(folder/'model.idf'),'code_sha256':code_hash(),
          'history_days':(date-start).days,'run_interval_min':[lo,hi],'intervention_last_request_min':last_request,
          'actual_intervention_end_min':last_change,
          'nonleap_weather_year_shift':year_shift,'original_human_calendar_dates_preserved':True,
          'derived_interzone_layer_order_repairs':wall_repairs,
          'water_mains':stat,'equipment_meter_mapping':asset_meters,'HVAC_equipment_mapping':equipment_names,
          'reference_air_changes_per_hour':reference_ach,
          'air_exchange_scope':'fixed passive-equivalent reference;NREL/TP-550-35567 historical0.35ACH condition;not measured Chinese leakage or a transplanted native AFN',
          'tank_name':tank_name,'water_needs':water_needs,'execution':executed,'EV_grid_steps':[[t,v]for t,v in sorted(evsteps.items())if 480<=t<hi],
          'EV':evtrace,
          'human_acceptance':None,'schedules_modified':False,
          'reference_background':'pinned EB heat fractions,powers and lighting density;dated occupancy/meal conditions,not measured household gains'}
    save(folder/'INPUT.json.gz',meta)
    return ROOT/pack['weather'],meta
