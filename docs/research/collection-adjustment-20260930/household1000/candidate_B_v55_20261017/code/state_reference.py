"""Native A-only event readbacks. No B success or preference labels are inputs."""
from functools import lru_cache
from common import *
@lru_cache(maxsize=6)
def reference_record(hid,date):
    import time
    pointer=OUT/'state_records'/hid/(date+'.json')
    while not pointer.exists():
        full=OUT/'STATE_BINDINGS.json'
        if full.exists():
            data=read(full)
            if data.get('cases')==10000:
                return next(r for r in data['records']if r['household_id']==hid and r['date']==date)
        time.sleep(2)
    return read(pointer)
@lru_cache(maxsize=6)
def state(hid,date):
    r=reference_record(hid,date)
    if not r['passed']:return None
    p=OUT/r['state_path']
    if sha(p)!=r['state_sha256']:raise ValueError('A_EVENT_STATE_BYTES_CHANGED')
    return read(p)
def event_state(source,device,event):
    s=state(source['household_id'],source['date'])
    if not s:return {'status':'unknown','reason':'native_reference_failed','physical_B_effect_known':False}
    aid=device['asset_id'];mapping=s['asset_mapping'][aid];lo,hi=event['start_min'],event['end_min']
    def values(key,var):return [(t,v)for t,v in s['channels'].get(str(key)+'|'+var,[])if lo<=t<hi]
    if 'ac'in device['types']:
        q=mapping['energy_keys'];room=mapping['room_key'];temps=values(room,'Zone Mean Air Temperature')
        heat=values(q['Coil:Heating:DX:SingleSpeed'],'Heating Coil Electricity Energy');supp=values(q['Coil:Heating:Electric'],'Heating Coil Electricity Energy');cool=values(q['Coil:Cooling:DX:SingleSpeed'],'Cooling Coil Electricity Energy')
        heating=sum(v for _,v in heat+supp);cooling=sum(v for _,v in cool)
        mode='mixed'if heating>1 and cooling>1 else 'heating'if heating>1 else 'cooling'if cooling>1 else 'idle'
        active={t for t,v in heat+supp+cool if v>1}
        hs=values(room,'Zone Thermostat Heating Setpoint Temperature');cs=values(room,'Zone Thermostat Cooling Setpoint Temperature')
        # When idle, use the actual indoor distance to current A setpoints;
        # this chooses a request axis, never asserts the compressor is active.
        normal=source['thermal_control_context'][aid]
        mean=sum(v for _,v in temps)/max(1,len(temps));axis=('heating'if heating>cooling else'cooling')if mode!='idle'else('heating'if abs(mean-normal['usual_heating_setpoint_C'])<=abs(mean-normal['usual_cooling_setpoint_C'])else'cooling')
        fields={'mode':mode,'request_axis':axis,'active_minutes':len(active)*10,'heating_kWh':heating/3600000,'cooling_kWh':cooling/3600000,'indoor_temperature_range_C':[min(v for _,v in temps),max(v for _,v in temps)]if temps else None,'indoor_mean_C':mean,'axis_basis':'native_A_coil_energy;idle_axis_from_indoor_distance_to_A_setpoints','timestep_profile':{'indoor_C':temps,'heat_J':heat,'supplement_J':supp,'cool_J':cool}}
    else:
        key=mapping['tank_key'];temps=values(key,'Water Heater Tank Temperature');power=values(key,'Water Heater Heating Rate')
        energy=values(key,'Water Heater Electricity Energy');active={t for t,v in power if v>1}
        fields={'mode':'heating'if active else'idle','request_axis':'heating','active_minutes':len(active)*10,'tank_temperature_range_C':[min(v for _,v in temps),max(v for _,v in temps)]if temps else None,'heater_kWh':sum(v for _,v in energy)/3600000,'timestep_profile':{'tank_C':temps,'heater_W':power},'axis_basis':'native_A_stratified_tank_temperature_and_heating_rate'}
    return {**fields,'status':'native_A_reference','state_sha256':reference_record(source['household_id'],source['date'])['state_sha256'],'scope':s['reference_scope'],'physical_B_effect_known':False}
