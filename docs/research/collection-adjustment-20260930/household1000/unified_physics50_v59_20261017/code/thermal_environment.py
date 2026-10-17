"""Declared portals and spot exhaust, without changing appliance requests."""
from core import *

CFM = 0.0004719474432


def add_environment(rows, pack, days, date, executed, obj, schedule):
    policy = read(ROOT/'THERMAL_ENVIRONMENT_POLICY.json')
    scale = float(os.environ.get('EB_PORTAL_FLOW_SCALE', '1'))
    if scale not in (0.5, 1.0, 2.0):
        raise ValueError('UNDECLARED_PORTAL_FLOW_SCALE')
    roominfo = {r['room_id']: r for r in pack['world']['layout']['rooms']}
    private = {r for r,v in roominfo.items() if v['census_room_class']=='bedroom'}
    washroom = pack['world']['activity_contract']['room_map']['bath']
    closed = {d:{r:set() for r in roominfo} for d in days}
    bath_active = {d:set() for d in days}
    kitchen_active = {d:set() for d in days}
    for d in days:
        day = pack['days'][str(d)]
        calendars = {**day['calendars'], **day['shared']['member_calendars']}
        for calendar in calendars.values():
            for event in calendar:
                rid = event.get('room_id')
                if rid not in roominfo or event.get('location')!='home':
                    continue
                minutes = set(range(max(0,event['start_min']), min(1440,event['end_min']),10))
                activity = event.get('activity','')
                if rid in private and (activity.startswith('sleep') or 'nap' in activity):
                    closed[d][rid].update(minutes)
                if rid == washroom:
                    closed[d][rid].update(minutes)
                    bath_active[d].update(minutes)
        for a in day['family']['bath_times_min'].values():
            bath_active[d].update(range(a,a+10,10))
        for a in day['family']['member_dinners_min'].values():
            kitchen_active[d].update(range(a-30,a,10))

    def overrun(source, minutes=20):
        absolute=set()
        for d, times in source.items():
            base=(d-date).days*1440
            for t in times:
                absolute.update(range(base+t,base+t+minutes+10,10))
        return {d:[int((d-date).days*1440+t in absolute) for t in range(0,1440,10)] for d in days}

    portals=[]
    for portal in pack['world']['layout']['access']:
        a,b=portal['from'],portal['to']
        if a not in roominfo or b not in roominfo:
            raise ValueError('PORTAL_ZONE_MISSING')
        flow=portal['width_design_m']*portal['height_design_m']*policy['portals']['reference_open_m3_s_per_m2']*scale
        name='portal_'+digest([a,b])[:12]
        fractions={d:[policy['portals']['reference_closed_fraction'] if t in closed[d][a] or t in closed[d][b] else 1 for t in range(0,1440,10)] for d in days}
        rows.append(schedule(name,fractions))
        rows.append(obj('ZoneCrossMixing',{'name':name,'zone_or_space_name':a,'schedule_name':name,
            'design_flow_rate_calculation_method':'Flow/Zone','design_flow_rate':flow,
            'source_zone_or_space_name':b,'delta_temperature':0}))
        portals.append({'name':name,'from':a,'to':b,'open_flow_m3_s':flow,'closed_flow_fraction':policy['portals']['reference_closed_fraction'],
                        'source_width_m':portal['width_design_m'],'source_height_m':portal['height_design_m']})

    vents=[]
    def vent(name, room, cfm, fractions, separate_fan):
        rows.append(schedule(name,fractions))
        fan=policy['spot_exhaust']['background_fan_W_per_cfm'] if separate_fan else 0
        efficiency=policy['spot_exhaust']['background_fan_total_efficiency']
        rows.append(obj('ZoneVentilation:DesignFlowRate',{
            'name':name,'zone_or_zonelist_or_space_or_spacelist_name':room,'schedule_name':name,
            'design_flow_rate_calculation_method':'Flow/Zone','design_flow_rate':cfm*CFM,
            'ventilation_type':'Exhaust','fan_pressure_rise':fan*efficiency/CFM,
            'fan_total_efficiency':efficiency,'constant_term_coefficient':1,
            'temperature_term_coefficient':0,'velocity_term_coefficient':0,'velocity_squared_term_coefficient':0,
            'minimum_indoor_temperature':-100,'maximum_indoor_temperature':100,'delta_temperature':-100,
            'minimum_outdoor_temperature':-100,'maximum_outdoor_temperature':100,'maximum_wind_speed':40}))
        vents.append({'name':name,'room':room,'cfm':cfm,'separate_fan_W':cfm*fan,
                      'schedule':[[((d-date).days*1440+t),v]for d in days for t,v in zip(range(0,1440,10),fractions[d])if v],
                      'fan_power_in_dryer_meter':not separate_fan})

    kitchen=next((r for r,v in roominfo.items()if v['census_room_class']=='kitchen'),None)
    if washroom in roominfo:
        vent('reference_bath_exhaust',washroom,policy['spot_exhaust']['bathroom_cfm'],overrun(bath_active),True)
    if kitchen:
        vent('reference_kitchen_exhaust',kitchen,policy['spot_exhaust']['kitchen_cfm'],overrun(kitchen_active),True)
    for asset in pack['world']['parameter_pack']['devices']:
        if 'dryer'not in asset['types']:
            continue
        active=set(t for task in executed['tasks']if task['kind']=='dryer'and task['asset_id']==asset['asset_id']for t in range(task['start_min'],task['end_min'],10))
        fractions={d:[int((d-date).days*1440+t in active)for t in range(0,1440,10)]for d in days}
        vent('reference_dryer_exhaust_'+digest(asset['asset_id'])[:10],asset['room_id'],policy['spot_exhaust']['dryer_cfm'],fractions,False)
    for rid in roominfo:
        rows.append(obj('ZoneAirBalance:OutdoorAir',{'name':'combined_air_'+digest(rid)[:10],'zone_name':rid,
            'air_balance_method':'Quadrature','induced_outdoor_air_due_to_unbalanced_duct_leakage':0,'induced_outdoor_air_schedule_name':'always'}))
    return {'policy_sha256':sha(ROOT/'THERMAL_ENVIRONMENT_POLICY.json'),'portal_flow_scale':scale,'portals':portals,'spot_exhaust':vents,
            'door_schedules_from_frozen_A_calendars':True,'no_added_appliance_requests':True,'background_fans_outside_VPP_control':True}
