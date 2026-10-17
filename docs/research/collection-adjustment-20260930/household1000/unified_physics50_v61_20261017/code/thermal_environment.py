"""Geometry-linked mixing and exhaust with an explicit makeup-air path.

Native zone mass conservation transports entry/corridor makeup air through the
declared portals to the exhaust rooms; passive two-way exchange stays separate.
No minimum temperature cutoff, extra heat or schedule rescue is introduced.
"""
import collections
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
    root = next((r for r,v in roominfo.items() if v['census_room_class']=='corridor'), None)
    if root is None:
        raise ValueError('MAKEUP_ENTRY_CORRIDOR_MISSING')
    adjacency = collections.defaultdict(list)
    for portal in pack['world']['layout']['access']:
        adjacency[portal['from']].append(portal['to'])
        adjacency[portal['to']].append(portal['from'])
    parent = {root: None}
    queue = collections.deque([root])
    while queue:
        a = queue.popleft()
        for b in sorted(adjacency[a]):
            if b not in parent:
                parent[b] = a
                queue.append(b)
    if set(parent) != set(roominfo):
        raise ValueError('DISCONNECTED_MAKEUP_AIR_PORTALS')
    fans_by_room=collections.defaultdict(list)
    transfers=[]
    def vent(name, room, cfm, fractions, separate_fan):
        rows.append(schedule(name,fractions))
        fan=policy['spot_exhaust']['background_fan_W_per_cfm'] if separate_fan else 0
        efficiency=policy['spot_exhaust']['background_fan_total_efficiency']
        rows.append(obj('Fan:ZoneExhaust',{
            'name':name,'availability_schedule_name':name,'fan_total_efficiency':efficiency,
            'pressure_rise':fan*efficiency/CFM,'maximum_flow_rate':cfm*CFM,
            'air_inlet_node_name':name+'_inlet','air_outlet_node_name':name+'_outlet',
            'end_use_subcategory':'reference_background_exhaust',
            'flow_fraction_schedule_name':name,'system_availability_manager_coupling_mode':'Decoupled'}))
        fans_by_room[room].append(name)
        destination=room
        while parent[destination] is not None:
            source=parent[destination]
            transfer=name+'_transfer_'+digest([source,destination])[:8]
            rows.append(obj('ZoneMixing',{'name':transfer,'zone_or_space_name':destination,
                'schedule_name':name,'design_flow_rate_calculation_method':'Flow/Zone',
                'design_flow_rate':cfm*CFM,'source_zone_or_space_name':source,'delta_temperature':-100}))
            transfers.append({'name':transfer,'from':source,'to':destination,'for_exhaust':name,'design_flow_m3_s':cfm*CFM})
            destination=source
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
    # Include unconditioned network rooms in the native mass ledger. EP24.1
    # crashes on empty equipment lists despite accepting them in its schema;
    # a permanently-off zero-flow/zero-power node registers a source-only zone.
    connections={r[1]:r for r in rows if r[0]=='ZoneHVAC:EquipmentConnections'}
    lists={r[1]:r for r in rows if r[0]=='ZoneHVAC:EquipmentList'}
    nodes={r[1]:r for r in rows if r[0]=='NodeList'}
    for rid in roominfo:
        if rid not in connections:
            prefix='air_balance_'+digest(rid)[:10]
            equipment=['ZoneHVAC:EquipmentList',prefix+'_equipment','SequentialLoad']
            connection=['ZoneHVAC:EquipmentConnections',rid,prefix+'_equipment','','',prefix+'_air','']
            rows.extend([equipment,connection]);connections[rid]=connection;lists[equipment[1]]=equipment
        connection=connections[rid];equipment=lists[connection[2]]
        fans=list(fans_by_room[rid])
        if not fans and len(equipment)==3:
            name='mass_ledger_registration_'+digest(rid)[:10]
            rows.append(obj('Fan:ZoneExhaust',{'name':name,'availability_schedule_name':'zero',
                'fan_total_efficiency':0.6,'pressure_rise':0,'maximum_flow_rate':0,
                'air_inlet_node_name':name+'_inlet','air_outlet_node_name':name+'_outlet',
                'system_availability_manager_coupling_mode':'Decoupled','end_use_subcategory':'zero_mass_ledger_registration'}))
            fans.append(name)
        if fans:
            name='exhaust_nodes_'+digest(rid)[:10]
            prior=connection[4]
            prior_nodes=nodes[prior][2:] if prior in nodes else [prior] if prior else []
            rows.append(['NodeList',name,*prior_nodes,*[fan+'_inlet' for fan in fans]])
            connection[4]=name
            first=(len(equipment)-3)//6+1
            for seq, fan in enumerate(fans,first):equipment.extend(['Fan:ZoneExhaust',fan,seq,seq,'',''])
    rows.append(obj('ZoneAirMassFlowConservation',{
        'adjust_zone_mixing_and_return_for_air_mass_flow_balance':'AdjustMixingOnly',
        'infiltration_balancing_method':'AddInfiltrationFlow','infiltration_balancing_zones':'MixingSourceZonesOnly'}))
    return {'policy_sha256':sha(ROOT/'THERMAL_ENVIRONMENT_POLICY.json'),'portal_flow_scale':scale,'portals':portals,'spot_exhaust':vents,
            'makeup_entry_zone':root,'makeup_transfers':transfers,
            'makeup_model':'native mass conservation;additional entry/corridor infiltration feeds directed portal transfers and exhaust',
            'all_zones_registered_for_mass_balance':True,
            'door_schedules_from_frozen_A_calendars':True,'no_added_appliance_requests':True,'background_fans_outside_VPP_control':True}
