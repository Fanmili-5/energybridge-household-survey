"""Independent SQL units, metering, state pairing and declared service audit."""
import collections, math, sqlite3
from common import *

def sql_frame(path,frequency='Zone Timestep'):
    db=sqlite3.connect('file:'+str(Path(path).resolve())+'?mode=ro',uri=True)
    rows=db.execute('''SELECT t.SimulationDays,t.Hour,t.Minute,t.Interval,d.KeyValue,d.Name,d.Units,r.Value
      FROM ReportData r JOIN ReportDataDictionary d USING(ReportDataDictionaryIndex) JOIN Time t USING(TimeIndex)
      WHERE t.WarmupFlag=0 AND d.ReportingFrequency=? ORDER BY t.TimeIndex,d.ReportDataDictionaryIndex''',(frequency,)).fetchall();db.close()
    data=collections.defaultdict(dict);units={}
    for day,hour,minute,interval,key,name,unit,value in rows:
        if not math.isfinite(value):raise ValueError('nonfinite physical output')
        slot=round(((day-1)*1440+hour*60+minute)/10)-1
        identity=(name,(key or '').upper());data[slot][identity]=value;units[identity]=unit
    return dict(data),units

def episode_clock(path,start_date):
    import datetime as dt
    db=sqlite3.connect('file:'+str(Path(path).resolve())+'?mode=ro',uri=True)
    days=db.execute('SELECT SimulationDays,Year,Month,Day,count(*) FROM Time WHERE WarmupFlag=0 AND Interval=10 GROUP BY SimulationDays,Year,Month,Day ORDER BY SimulationDays').fetchall();db.close()
    origin=dt.date.fromisoformat(start_date)
    assert len(days)==3,('episode calendar day count',days)
    for i,(simulation_day,engine_year,month,day,count) in enumerate(days):
        expected=origin+dt.timedelta(days=i)
        assert simulation_day==i+1 and (month,day)==(expected.month,expected.day) and count==144,('episode calendar mismatch',days,start_date)
    return {'experimental_origin_date':start_date,'actual_SQL_days':days,'verified_dates':[(origin+dt.timedelta(days=i)).isoformat() for i in range(3)],
        'engine_year_is_internal_typical_weather_calendar_not_observed_year':True}

def check_meter(frame,units,components,program_rows,first_slot=0,last_slot=None):
    max_balance=0.;max_program=0.;energy=collections.Counter();ranges=collections.defaultdict(list);tank_balance=0.
    last_slot=max(frame)+1 if last_slot is None else last_slot
    for slot,values in frame.items():
        if not first_slot<=slot<last_slot:continue
        facility=values['Electricity:Facility',''];total=0.
        for c in components:
            key=(c['variable'],c['key'].upper())
            if key not in values:raise ValueError('missing configured physical meter:'+str(key))
            if units[key]!='J':raise ValueError('electricity output unit mismatch')
            value=values[key];total+=value;energy[c['meter_bucket']+'/'+c['kind']]+=value/3.6e6
            if c['kind'] in ['washer','dishwasher','dryer','ev'] and slot<len(program_rows):
                residual=abs(value-program_rows[slot][c['kind']]*600)
                max_program=max(max_program,residual)
        max_balance=max(max_balance,abs(total-facility))
        for (name,key),value in values.items():
            if name in ['Zone Mean Air Temperature','Zone Air Relative Humidity']:ranges[name].append(value)
        keys=[(n,'V14_WATER_TANK') for n in ['Water Heater Electricity Energy','Water Heater Heat Loss Energy','Water Heater Use Side Heat Transfer Energy','Water Heater Net Heat Transfer Energy']]
        if all(k in values for k in keys):tank_balance=max(tank_balance,abs(values[keys[0]]+values[keys[1]]+values[keys[2]]-values[keys[3]]))
    assert max_balance<1e-4,('electric ledger mismatch',max_balance)
    assert max_program<1e-4,('native program/writeback mismatch',max_program)
    assert tank_balance<1e-4,('tank signed energy ledger mismatch',tank_balance)
    return {'maximum_electricity_ledger_residual_J':max_balance,'maximum_EB_program_meter_residual_J':max_program,'maximum_tank_signed_energy_residual_J':tank_balance,
            'energy_by_scope_kind_kWh':dict(energy),'reported_air_ranges':{k:[min(v),max(v)] for k,v in ranges.items()}}

def physical_service(w,frame,day):
    start=day*144;end=(day+2)*144;out={}
    if w['assets']['water_heater']['present']:
        draws=[v for s,v in frame.items() if start<=s<end and v.get(('Water Heater Use Side Mass Flow Rate','V14_WATER_TANK'),0)>1e-9]
        temps=[v['Water Heater Use Side Outlet Temperature','V14_WATER_TANK'] for v in draws]
        mass=sum(v['Water Heater Use Side Mass Flow Rate','V14_WATER_TANK']*600 for v in draws)
        assert len(draws)==2*w['N'],('draw_clock_or_count',len(draws),w['N'])
        out['water_heater']={'requested_nominal_litres_per_day':30*w['N'],'drawn_mass_kg_two_days':mass,'minimum_10minute_average_outlet_C':min(temps),'required_10minute_average_outlet_C':40.,'served':min(temps)>=40.,'not_actual_shower_or_instantaneous_service':True}
    if w['assets']['ac']['present']:
        rid=w['assets']['ac']['room_id'].upper();values=[v['Zone Mean Air Temperature',rid] for s,v in frame.items() if start<=s<end and 18<=((s%144)/6)<22.5]
        upper=w['assets']['ac']['config']['setpoint_preferred_max_c']+w['assets']['ac']['config']['temp_tolerance_c']
        out['ac']={'served_room':rid,'maximum_reference_evening_air_C':max(values),'reference_upper_air_C':upper,'served':max(values)<=upper,'criterion_kind':'declared EB upper temperature plus tolerance reference;not empirical personal comfort','operative_temperature_and_personal_comfort_not_inferred':True}
    return out

def pair(w,case,baseline,shifted,Aframe,Bframe,Aunits,Bunits,Aprogram,Bprogram):
    assert set(Aframe)==set(Bframe)==set(range(432)),('three day output clock',len(Aframe),len(Bframe))
    day=case['context']['day_index_from_A_start'];decision=day*144+round(case['context']['decision_h']*6)
    pre=max((s for s in Bframe if s<decision),default=None);assert pre is not None
    common=sorted(s for s in Bframe if s<decision);worst=0.;state_keys=0
    for slot in common:
        assert Aframe[slot].keys()==Bframe[slot].keys(),('different input/output component scope',w['household_id'])
        for k,value in Bframe[slot].items():worst=max(worst,abs(value-Aframe[slot][k]));state_keys+=1
    assert worst<1e-5,('predecision physical history differs',worst,w['household_id'],case['round_index'])
    assert Aprogram['rows'][:decision]==Bprogram['rows'][:decision]
    event_begin=day*144+18*6;event_end=day*144+19*6;window_begin=day*144;window_end=(day+2)*144
    def electricity(f,start,end):return sum(v['Electricity:Facility',''] for s,v in f.items() if start<=s<end)/3.6e6
    delta=electricity(Aframe,event_begin,event_end)-electricity(Bframe,event_begin,event_end)
    total=electricity(Aframe,window_begin,window_end)-electricity(Bframe,window_begin,window_end)
    checks=check_meter(Bframe,Bunits,shifted['physical_components'],Bprogram['rows'])
    physA=physical_service(w,Aframe,day);physB=physical_service(w,Bframe,day)
    processA=[x for x in Aprogram['service'] if day<=x['day']<day+2];processB=[x for x in Bprogram['service'] if day<=x['day']<day+2]
    before={name+'|'+key:val for (name,key),val in Aframe[pre].items() if name in ['Zone Mean Air Temperature','Zone Air Relative Humidity','Water Heater Final Tank Temperature']}
    clocks={side:episode_clock(OUT/run['SQL_path'],case['context']['episode_start_date']) for side,run in [('A',baseline),('B',shifted)]}
    return {'schema':'eb.random10_pair.v1','household_id':w['household_id'],'round_index':case['round_index'],'date':case['context']['date'],'episode_start_date':case['context']['episode_start_date'],'episode_end_date':case['context']['episode_end_date'],'world_content_sha256':w['world_content_sha256'],'episode_calendar_checks':clocks,
        'A_SQL_path':baseline['SQL_path'],'A_SQL_sha256':baseline['SQL_sha256'],'B_SQL_path':shifted['SQL_path'],'B_SQL_sha256':shifted['SQL_sha256'],
        'paired_history_values_checked':state_keys,'maximum_predecision_output_difference':worst,'predecision_state':before,
        'A_event_kWh':electricity(Aframe,event_begin,event_end),'B_event_kWh':electricity(Bframe,event_begin,event_end),'event_reduction_kWh':delta,
        'A_48h_kWh':electricity(Aframe,window_begin,window_end),'B_48h_kWh':electricity(Bframe,window_begin,window_end),'48h_reduction_kWh':total,
        'A_reference_physical_services':physA,'B_reference_physical_services':physB,'A_program_services':processA,'B_program_services':processB,
        'actor_acceptance':None,'physics_not_human_preference':True,'meter_and_program_checks':checks}
