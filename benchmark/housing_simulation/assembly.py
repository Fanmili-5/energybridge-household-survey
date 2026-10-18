"""Deterministic shell-to-world assembly from explicit, cohort-free contracts."""
import copy
import datetime as dt
import shutil
from pathlib import Path

from .components import heat_pump
from .kernel.core_tools import parse_idf
from .pipeline import HERE, bound, digest, fresh, identifier, portable_gzip, read, save, seal, sha, verify

KINDS = {'washer', 'dryer', 'dishwasher', 'ac', 'water_heater', 'ev'}
CONTROL_KIND = {'ac': 'ac_setpoint', 'water_heater': 'tank_setpoint', 'ev': 'ev_charge_window'}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def number(value, label, low=0, high=float('inf'), strict=True):
    require(type(value) in (int, float) and (value > low if strict else value >= low) and value <= high,
            'invalid ' + label)
    return value


def minute(value, label, upper=1440):
    require(type(value) is int and 0 <= value <= upper and value % 10 == 0, 'invalid ten-minute ' + label)
    return value


def interval(item, upper=1440):
    a, z = (minute(item[k], k, upper) for k in ('start_min', 'end_min'))
    require(a < z, 'empty/reversed time interval')
    return a, z


def indexed(items, key):
    require(isinstance(items, list), key + ' list required')
    result = {identifier(x[key]): x for x in items}
    require(len(items) == len(result), 'duplicate ' + key)
    return result


def place(items, room):
    """Grid search with rotation; reserve an access strip, then disjoint rectangles."""
    x0, y0, x1, y1 = room['usable_rect_m']
    placed = []
    for item in items:
        w, h = item['footprint_m']
        for v in (w, h): number(v, 'footprint dimension')
        found = None
        for width, depth in dict.fromkeys(((w, h), (h, w))):
            # Coordinates snap to a declared 0.1m grid relative to usable extent.
            for iy in range(int((y1-y0)*10)+1):
                y = y0 + .8 + iy / 10
                for ix in range(int((x1-x0)*10)+1):
                    x = x0 + ix / 10
                    rect = [x, y, x+width, y+depth]
                    if rect[2] > x1+1e-8 or rect[3] > y1+1e-8:
                        continue
                    if all(rect[2]+.1 <= r['rect_m'][0]+1e-8 or r['rect_m'][2]+.1 <= rect[0]+1e-8 or
                           rect[3]+.1 <= r['rect_m'][1]+1e-8 or r['rect_m'][3]+.1 <= rect[1]+1e-8 for r in placed):
                        found = {**item, 'room_id': room['room_id'], 'rect_m': rect}; break
                if found: break
            if found: break
        require(found is not None, 'NO_INSTALLATION_SPACE:' + item['object_id'])
        placed.append(found)
    return placed


def bind_world(spec, layout):
    hid = spec['household_id']; rooms = {r['room_id']: r for r in layout['rooms']}
    require(hid == layout['target_household_id'], 'shell/world identity mismatch')
    members = indexed(spec['members'], 'member_id')
    contexts = {h['household_id'] for h in layout['households']}
    require({m['household_id'] for m in members.values()} == contexts,
            'complete roster required for every physical household, including shared context')
    require(layout.get('nonresident_external_kitchen_user_context') is None,
            'external kitchen-user geometry requires a separate visit model; unsupported in resident assembler')
    for m in members.values():
        number(m['age_years'], 'age_years', 0, 120, False)
        number(m['hot_water_liters'], 'hot_water_liters', 0, 200, False)
    groups = indexed(spec['sleep_groups'], 'group_id')
    assigned = []; sleep_rooms = {}; assigned_bedrooms=set(); floor_items = {rid: [] for rid in rooms}
    for gid, group in sorted(groups.items()):
        mids = group['member_ids']; require(mids and len(set(mids)) == len(mids), 'invalid sleep group')
        require(set(mids) <= members.keys(), 'unknown sleeping member')
        owners = {members[mid]['household_id'] for mid in mids}
        require(len(owners) == 1, 'sleep group spans households')
        require(type(group['capacity']) is int and len(mids) <= group['capacity'] <= 2, 'bed capacity exceeded')
        candidates = sorted((r for r in rooms.values() if r['census_room_class'] == 'bedroom'
                             and r['using_household_ids'] == list(owners) and r['room_id'] not in assigned_bedrooms), key=lambda r: r['room_id'])
        if group.get('room_id'):
            candidates = [r for r in candidates if r['room_id'] == group['room_id']]
        item = {'object_id': 'bed_' + gid, 'kind': 'bed', 'footprint_m': group['bed_footprint_m'], 'member_ids': mids}
        require(len(item['footprint_m']) == 2, 'bed footprint needs two dimensions')
        require(min(item['footprint_m']) >= (.8 if group['capacity']==1 else 1.2) and max(item['footprint_m'])>=1.8,'bed dimensions below declared reference minimum')
        for room in candidates:
            rid = room['room_id']
            try: place(floor_items[rid] + [item], room)
            except ValueError: continue
            floor_items[rid].append(item)
            assigned_bedrooms.add(rid)
            sleep_rooms.update({mid: rid for mid in mids}); break
        else: raise ValueError('NO_SLEEP_SPACE:' + gid)
        assigned.extend(mids)
    require(sorted(assigned) == sorted(members), 'every resident must have exactly one bed assignment')
    for fixture in indexed(spec['fixtures'],'fixture_id').values():
        rid=fixture['room_id'];require(rid in rooms and rid!='corridor','invalid fixture room')
        require(len(fixture['footprint_m'])==2,'fixture footprint needs two dimensions')
        floor_items[rid].append({'object_id':'fixture_'+fixture['fixture_id'],'kind':fixture['kind'],'footprint_m':fixture['footprint_m']})
    if 'washroom' in rooms:
        require({'toilet_reference','shower_reference'} <= {f['kind']for f in spec['fixtures']if f['room_id']=='washroom'}, 'sanitary fixtures must be declared')
    if any(r['census_room_class']=='kitchen'for r in rooms.values()):
        require({'sink_cooking_reference','refrigerator_reference'} <= {f['kind']for f in spec['fixtures']if f['room_id']=='kitchen'}, 'kitchen fixtures must be declared')
    assets = indexed(spec['devices'], 'asset_id'); roles = {}
    for kind, classes in {'living': ('hall', 'bedroom'), 'bath': ('non_H7_service',), 'kitchen': ('kitchen',)}.items():
        candidates = [r for c in classes for r in sorted(rooms.values(), key=lambda r:r['room_id'])
                      if r['census_room_class'] == c and hid in r['using_household_ids']
                      and (kind != 'bath' or r['room_id'] == 'washroom')]
        roles[kind] = candidates[0]['room_id'] if candidates else None
    for aid, device in assets.items():
        kind = device['kind']; require(kind in KINDS, 'unsupported device kind:' + kind)
        required_connections={'washer':{'electricity','water','drain'},'dryer':{'electricity','exhaust'},
          'dishwasher':{'electricity','water','drain'},'ac':{'electricity','outdoor_heat_exchange'},
          'water_heater':{'electricity','water'},'ev':{'electricity','dedicated_parking'}}[kind]
        require(required_connections<=set(device['connections']), 'installation service connections incomplete:'+aid)
        device['types'] = [kind]
        require(set(device['using_household_ids']) <= contexts and device['using_household_ids'], 'invalid device ownership')
        location = device['placement']
        if kind == 'ev':
            require(location == 'exterior', 'EV must be exterior'); device['room_id'] = None
        else:
            selector = device['room']
            if selector.startswith('$sleep:'):
                rid = sleep_rooms[selector.split(':',1)[1]]
            else: rid = roles.get(selector[1:]) if selector.startswith('$') else selector
            require(rid in rooms, 'unresolved installation room:' + aid)
            require(set(device['using_household_ids']) <= set(rooms[rid]['using_household_ids']), 'device room access denied')
            device['room_id'] = rid
            require(location in ('floor', 'wall'), 'unsupported placement')
            if location == 'floor':
                require(len(device['footprint_m']) == 2, 'device footprint needs two dimensions')
                floor_items[rid].append({'object_id': 'asset_'+aid, 'kind': kind, 'footprint_m': device['footprint_m']})
            else:
                number(device['mount_width_m'], 'mount_width_m')
        p = device['parameters']
        number(p['nameplate_W'], 'nameplate_W', 0, 50000)
        if kind in ('washer','dryer','dishwasher'):
            number(p['power_kw'], 'power_kw', 0, 20)
            require(p['power_kw']*1000 <= p['nameplate_W'], 'program exceeds nameplate')
            require(device['placement']=='floor', 'program appliance must be floor mounted')
        elif kind == 'ac':
            for k in ('cooling_capacity_W','heating_capacity_W','cooling_COP','heating_COP','air_flow_m3_s','fan_power_W','fan_pressure_Pa'):
                number(p[k], k)
            number(p['sensible_heat_ratio'], 'sensible_heat_ratio', 0, 1)
            for k in ('supplemental_capacity_W','defrost_capacity_W'): number(p[k],k,0,10000,False)
            require(max(p['cooling_capacity_W']/p['cooling_COP'],p['heating_capacity_W']/p['heating_COP'])+
                    p['fan_power_W']+p['supplemental_capacity_W']+p['defrost_capacity_W'] <= p['nameplate_W'], 'HVAC nameplate bound too small')
        elif kind == 'water_heater':
            for k in ('volume_m3','height_m','heater_capacity_W','maximum_C','deadband_C','skin_loss_W_m2K'): number(p[k],k)
            number(p['efficiency'],'efficiency',0,1)
            require(type(p['number_of_nodes']) is int and 2 <= p['number_of_nodes'] <= 12, 'invalid tank node count')
            require(p['heater_capacity_W'] <= p['nameplate_W'], 'tank exceeds nameplate')
        elif kind == 'ev':
            for k in ('charger_kw','capacity_kwh'):number(p[k],k)
            for k in ('efficiency','target_soc'):number(p[k],k,0,1)
            number(p['minimum_soc'],'minimum_soc',0,p['target_soc'],False)
            number(p['initial_energy_kwh'],'initial_energy_kwh',0,p['capacity_kwh'],False)
            require(p['charger_kw']*1000 <= p['nameplate_W'], 'charger exceeds nameplate')
    require(sum('ev' in d['types'] for d in assets.values()) <= 1, 'one EV supported per physical world')
    require(sum('water_heater' in d['types'] for d in assets.values()) <= 1, 'one tank supported per physical world')
    placements = [p for rid in sorted(rooms) for p in place(floor_items[rid], rooms[rid])]
    wall = {}
    for d in assets.values():
        if d['placement']=='wall': wall[d['room_id']] = wall.get(d['room_id'],0) + d['mount_width_m'] + .1
    for rid, width in wall.items():
        rect=rooms[rid]['usable_rect_m']; require(width <= 2*((rect[2]-rect[0])+(rect[3]-rect[1]))-.8, 'wall mounting budget exceeded')
    supply = spec['electrical_supply_W']; number(supply, 'electrical_supply_W')
    background = spec['background']
    for k in ('lighting_W_m2','misc_W_m2','refrigerator_W','cooking_W'): number(background[k], k, 0, 10000, False)
    passive = sum(r['thermal_reference_area_m2'] for r in rooms.values())*(background['lighting_W_m2']+background['misc_W_m2'])+background['refrigerator_W']+background['cooking_W']
    passive += spec['exhaust_power_budget_W']; number(spec['exhaust_power_budget_W'],'exhaust_power_budget_W',0,10000,False)
    ventilation=read(HERE/'reference_environment.json')['spot_exhaust']
    fan_bound=(ventilation['bathroom_cfm']*int('washroom'in rooms)+ventilation['kitchen_cfm']*int(any(r['census_room_class']=='kitchen'for r in rooms.values())))*ventilation['background_fan_W_per_cfm']
    require(spec['exhaust_power_budget_W']>=fan_bound,'exhaust power budget below configured fans')
    require(sum(d['parameters']['nameplate_W'] for d in assets.values())+passive <= supply, 'ELECTRICAL_NAMEPLATE_SUM_EXCEEDS_SUPPLY')
    for m in members.values():
        rights=m['can_operate_asset_ids']; require(set(rights) <= assets.keys(), 'unknown operator asset')
        require(not rights or m['age_years']>=16, 'operator below declared reference age16')
        require(all(m['household_id'] in assets[aid]['using_household_ids'] for aid in rights), 'operator lacks household asset access')
    layout['complete_household_energy_world'] = True; layout['actor_ready'] = True
    for h in layout['households']:
        h['resident_count_observed']=None
        h['resident_count_declared']=sum(m['household_id']==h['household_id'] for m in members.values())
    return {'layout':layout,'members':list(members.values()),'sleep_room_by_member':sleep_rooms,
            'parameter_pack':{'devices':list(assets.values())}, 'activity_contract':{'room_map':roles},
            'routine':{'mixed_target_C':spec['hot_water_minimum_C']}, 'placements':placements,
            'installation_policy':'rectangular_grid_0.1m_gap_0.1m_access_strip_0.8m;wall_width_budget;not_code_compliance',
            'electrical':{'supply_W':supply,'nameplate_plus_background_W':sum(d['parameters']['nameplate_W']for d in assets.values())+passive},
            'input_kind':'declared_reference_household;not_survey_observation'}


def control(record, assets, upper=1440):
    interval(record, upper); aid=record['asset_id']; require(aid in assets, 'unknown control asset')
    kind=assets[aid]['kind']; require(CONTROL_KIND.get(kind)==record['kind'], 'control/device type mismatch')
    if kind=='ac':
        number(record['heating_setpoint_C'],'heating setpoint',5,35,False)
        number(record['cooling_setpoint_C'],'cooling setpoint',15,40,False)
        require(record['heating_setpoint_C'] < record['cooling_setpoint_C'], 'thermostat deadband required')
        require(record['fan_operating_mode'] in (0,1), 'fan mode must be0/1')
    elif kind=='water_heater': number(record['value_C'],'tank setpoint',10,assets[aid]['parameters']['maximum_C'],False)
    else: number(record['stop_at_target_soc'],'target SOC',0,1)


def calendar_for(member, day, spec, world):
    template=spec['calendars'][member['calendar_id']]
    source=template.get('date_overrides',{}).get(str(day),template['weekend' if day.weekday()>=5 else 'weekday'])
    out=[]; last=0
    for e in source:
        a,z=interval(e);require(a==last,'calendar must cover each day exactly without gaps/overlaps');last=z
        e=copy.deepcopy(e)
        if e['location']=='home':
            key=e['room']
            rid=world['sleep_room_by_member'][member['member_id']] if key=='$sleep' else world['activity_contract']['room_map'].get(key[1:]) if key.startswith('$') else key
            rooms={r['room_id']:r for r in world['layout']['rooms']}
            require(rid in rooms and member['household_id'] in rooms[rid]['using_household_ids'], 'calendar room access denied')
            e['room_id']=rid
        else:require(e['location']=='away' and not e.get('room'), 'away event cannot bind a room')
        require(type(e['available_for_operation']) is bool, 'explicit operation availability required')
        require(not e['available_for_operation'] or (e['location']=='home' and not e['activity'].startswith('sleep') and e['activity']!='bath'), 'invalid operation availability')
        out.append(e)
    require(last==1440,'calendar must end at1440')
    return out


def build_pack(spec, world, shell, weather_sha):
    anchor=dt.date.fromisoformat(spec['anchor']); end=dt.date.fromisoformat(spec['end_exclusive'])
    require(1 <= (end-anchor).days <= 730,'calendar coverage must be1..730days')
    members={m['member_id']:m for m in world['members']};assets={d['asset_id']:d for d in world['parameter_pack']['devices']}
    services=indexed(spec['services'],'service_id')
    for s in services.values():
        require(s['asset_id'] in assets and s['kind'] in ('washer','dryer','dishwasher') and assets[s['asset_id']]['kind']==s['kind'],'service/device mismatch')
        require(s['operator_id'] in members and s['asset_id'] in members[s['operator_id']]['can_operate_asset_ids'],'service operator not authorized')
        for k in ('start_min','duration_min','retrieval_min','release_min','deadline_min'):minute(s[k], k)
        require(10 <= s['start_min'] and s['duration_min']>0 and s['release_min'] <= s['start_min']-10 and s['start_min']+s['duration_min'] <= s['retrieval_min'] and s['retrieval_min']+10 <= s['deadline_min'] <=1440,'invalid service timing')
        require(s['weekdays'] and set(s['weekdays']) <= set(range(7)), 'invalid service weekdays')
        if s.get('after_service_id'):
            parent=services.get(s['after_service_id'])
            require(parent is not None and parent['kind']=='washer' and s['kind']=='dryer' and set(s['weekdays'])<=set(parent['weekdays']), 'invalid washer/dryer dependency')
    for c in spec['controls']:control(c,assets)
    for aid in assets:
        cc=sorted((c for c in spec['controls']if c['asset_id']==aid),key=lambda c:c['start_min'])
        require(all(a['end_min']<=b['start_min']for a,b in zip(cc,cc[1:])), 'overlapping baseline controls')
        if assets[aid]['kind'] in ('ac','water_heater'):require(cc and cc[0]['start_min']==0 and cc[-1]['end_min']==1440 and all(a['end_min']==b['start_min']for a,b in zip(cc,cc[1:])),'HVAC/tank controls require complete daily coverage')
    pack={'household_id':spec['household_id'],'anchor':str(anchor),'end_exclusive':str(end),'world':world,
          'days':{},'tasks':[],'operations':[],'HVAC':[],'journeys':[],'EV_battery_energy_events':[],
          'weather':'inputs/weather.epw','weather_sha256':weather_sha,'shell_rows':parse_idf(shell.read_text()),
          'source_shell_sha256':sha(shell),'hot_water_model':'standalone_hot_outlet',
          'background':spec['background'],'service_needs':[]}
    fields=read(HERE/'resources/schema_fields.json')
    pack['HVAC']=[heat_pump(d,fields)for d in assets.values()if d['kind']=='ac']
    day=anchor
    while day<end:
        base=(day-anchor).days*1440
        calendars={mid:calendar_for(m,day,spec,world)for mid,m in members.items()}
        windows={mid:[[e['start_min'],e['end_min']]for e in cal if e['available_for_operation']]for mid,cal in calendars.items()}
        baths={};dinners={};water=[]
        for mid,cal in calendars.items():
            for e in cal:
                if e['activity']=='bath':
                    require(mid not in baths,'one daily bath event per member supported'); baths[mid]=e['start_min']
                    if members[mid]['hot_water_liters']:
                        require(any(d['kind']=='water_heater'for d in assets.values()),'hot-water need without installed tank')
                        water.append({'need_id':str(day)+':bath:'+mid,'release_min':base+e['start_min'],'deadline_min':base+e['end_min'],
                                      'quantity':members[mid]['hot_water_liters'],'minimum_C':spec['hot_water_minimum_C'],'quantity_unit':'hot_outlet_liters'})
                if e['activity']=='dinner':dinners[mid]=e['start_min']
        daycontrols=[{**c,'start_min':base+c['start_min'],'end_min':base+c['end_min']}for c in spec['controls']]
        target=spec['household_id']
        pack['days'][str(day)]={'controls':daycontrols,
            'calendars':{mid:cal for mid,cal in calendars.items()if members[mid]['household_id']==target},
            'operator_windows':windows,'family':{'bath_times_min':baths,'member_dinners_min':dinners},'water_needs':water,
            'shared':{'member_calendars':{mid:cal for mid,cal in calendars.items()if members[mid]['household_id']!=target},'facility_reservations':[]}}
        reservations=copy.deepcopy(spec.get('facility_reservations',{}).get(str(day),[]))
        for r in reservations:
            interval(r);require(r['room_id'] in {x['room_id']for x in world['layout']['rooms']},'unknown reservation room')
        reservations += [{'room_id':e['room_id'],'start_min':e['start_min'],'end_min':e['end_min'],'source':'resident_bath_calendar'}
                         for cal in calendars.values()for e in cal if e['activity']=='bath']
        pack['days'][str(day)]['shared']['facility_reservations']=reservations
        # Bathroom occupancy is exclusive; household context never disappears from heat balance.
        bath_events=[(e['start_min'],e['end_min'])for cal in calendars.values()for e in cal if e['activity']=='bath']
        require(all(b<=c or d<=a for i,(a,b)in enumerate(bath_events)for c,d in bath_events[i+1:]),'overlapping bathroom calendars')
        for sid,s in services.items():
            if day.weekday()not in s['weekdays']:continue
            nid=str(day)+':'+sid;aid=s['asset_id'];room=assets[aid]['room_id']
            pack['tasks'].append({'task_id':nid+':program','need_id':nid,'service_id':sid,'asset_id':aid,'kind':s['kind'],'start_min':base+s['start_min'],'end_min':base+s['start_min']+s['duration_min']})
            if s.get('after_service_id'):pack['tasks'][-1]['depends_on_need_id']=str(day)+':'+s['after_service_id']
            for kind,a in [('load',s['start_min']-10),('unload',s['retrieval_min'])]:
                pack['operations'].append({'operation_id':nid+':'+kind,'need_id':nid,'asset_id':aid,'room_id':room,'operator_id':s['operator_id'],'kind':kind,'start_min':base+a,'end_min':base+a+10,'service_id':sid})
            pack['service_needs'].append({'need_id':nid,'service_id':sid,'release_min':base+s['release_min'],'deadline_min':base+s['deadline_min']})
        day+=dt.timedelta(days=1)
    ev=next((d for d in assets.values()if d['kind']=='ev'),None)
    require(bool(ev)==('ev_connection'in spec),'EV asset/connection contract mismatch')
    states={}
    if ev:
        p=ev['parameters'];r=spec['ev_connection'];mid=r['operator_id']
        require(r['anchor_state']=='plugged','explicit plugged EV anchor state required')
        require(ev['asset_id'] in members[mid]['can_operate_asset_ids'],'EV operator not authorized')
        plug=minute(r['plug_min'],'plug_min');unplug=minute(r['unplug_min'],'unplug_min')
        require(plug>=unplug+10 and plug<=1420,'EV reference connection must be overnight')
        for trip in r['journeys']:
            minute(trip['departure_min'],'departure_min');number(trip['traction_kWh'],'traction_kWh')
            require(unplug+10<=trip['departure_min']<=plug,'trip overlaps physical EV connection')
        require(len({t['departure_min']for t in r['journeys']})==len(r['journeys']),'duplicate EV departure')
        for i in range((end-anchor).days):
            base=i*1440;date=anchor+dt.timedelta(days=i);nid=str(date)+':EV'
            for kind,a in [('EV_plug',base+plug),('EV_unplug',base+1440+unplug)]:
                pack['operations'].append({'operation_id':nid+':'+kind,'need_id':nid,'asset_id':ev['asset_id'],'room_id':'exterior','operator_id':mid,'kind':kind,'start_min':a,'end_min':a+10})
            for trip in r['journeys']:pack['journeys'].append({**trip,'absolute_departure_min':base+trip['departure_min']})
            for c in pack['days'][str(date)]['controls']:
                if c['kind']=='ev_charge_window':c['need_id']=nid if c['start_min']-base>=plug else str(date-dt.timedelta(days=1))+':EV'
        energy=p['initial_energy_kwh'];trips={t['absolute_departure_min']:t for t in pack['journeys']}
        for t in range((end-anchor).days*1440):
            if t%10:continue
            states[t]=energy
            if t in trips:
                require(energy+1e-8>=trips[t]['traction_kWh'],'baseline EV trip is unexecutable');energy-=trips[t]['traction_kWh']
            local=t%1440;date=anchor+dt.timedelta(days=t//1440)
            cs=[c for c in pack['days'][str(date)]['controls']if c['kind']=='ev_charge_window'and c['start_min']<=t<c['end_min']]
            if cs and (local>=plug+10 or local<unplug):
                inc=min(p['charger_kw']*p['efficiency']/6,max(0,cs[0]['stop_at_target_soc']*p['capacity_kwh']-energy))
                if inc:pack['EV_battery_energy_events'].append({'kind':'charge','start_min':t,'end_min':t+10,'battery_kWh':inc});energy+=inc
    pack['operations'].sort(key=lambda x:(x['start_min'],x['operation_id']))
    return pack,states


def make_pair(case, spec, pack, states):
    day=dt.date.fromisoformat(case['date']);anchor=dt.date.fromisoformat(pack['anchor']);base=(day-anchor).days*1440
    require(pack['anchor']<=case['date']<pack['end_exclusive'],'pair date outside calendar')
    a={key:[{**t,'start_min':t['start_min']-base,'end_min':t['end_min']-base}for t in pack[key]if base<=t['start_min']<base+1440]for key in ('tasks','operations')}
    # EV physical operations are immutable: only charging controls may differ.
    a['operations']=[o for o in a['operations']if not o['kind'].startswith('EV_')]
    a['controls']=[{**c,'start_min':c['start_min']-base,'end_min':c['end_min']-base}for c in pack['days'][case['date']]['controls']]
    b=copy.deepcopy(a);seen=set()
    for change in case['service_shifts']:
        sid=change['service_id'];shift=change['shift_min']
        require(sid not in seen and type(shift)is int and shift%10==0,'duplicate or invalid service shift');seen.add(sid)
        changed=[t for key in ('tasks','operations')for t in b[key]if t.get('service_id')==sid]
        require(changed,'shift references service absent on case date')
        for t in changed:
            require(t['start_min']>=480 and t['start_min']+shift>=480,'intervention changes pre-notice events')
            t['start_min']+=shift;t['end_min']+=shift;interval(t)
    assets={d['asset_id']:d for d in pack['world']['parameter_pack']['devices']}
    seen_controls=[]
    for override in case['control_overrides']:
        control(override,assets);require(override['start_min']>=480,'control override before notice480')
        require(all(c['asset_id']!=override['asset_id'] or c['end_min']<=override['start_min'] or c['start_min']>=override['end_min']for c in seen_controls),'overlapping control overrides')
        seen_controls.append(override)
        aid=override['asset_id'];new=[]
        for c in b['controls']:
            if c['asset_id']!=aid or c['end_min']<=override['start_min'] or c['start_min']>=override['end_min']:new.append(c);continue
            if c['start_min']<override['start_min']:new.append({**c,'end_min':override['start_min']})
            if c['end_min']>override['end_min']:new.append({**c,'start_min':override['end_min']})
        c=copy.deepcopy(override)
        if c['kind']=='ev_charge_window':
            plug=spec['ev_connection']['plug_min'];require(c['start_min']>=plug+10,'EV intervention must follow same-day plug')
            c['need_id']=case['date']+':EV'
        b['controls']=new+[c]
    for side in (a,b):
        for key in side:side[key].sort(key=lambda c:(c['start_min'],c['asset_id']))
    pair={'case_id':identifier(case['case_id']),'household_id':spec['household_id'],'date':case['date'],'A':a,'B':b,
          'needs_A':[{**n,'release_min':n['release_min']-base,'deadline_min':n['deadline_min']-base}for n in pack['service_needs']],
          'schedule_hashes':{'A':digest(a),'B':digest(b)},'EV_continuous_reference':{'status':'not_installed'}}
    ev=next((d for d in assets.values()if d['kind']=='ev'),None)
    if ev:
        p=ev['parameters'];pair['EV_continuous_reference']={'status':'installed','initial_energy_kWh':states[base+480],
          'efficiency':p['efficiency'],'target_SOC':p['target_soc'],'capacity_kWh':p['capacity_kwh'],'minimum_SOC':p['minimum_soc'],'charger_kW':p['charger_kw']}
    pair['source_pair_sha256']=digest(pair)
    return pair


def assemble(config, shells, weather, output):
    """Retain failed households, export admitted worlds and content-bound compiler jobs."""
    from jsonschema import Draft202012Validator, FormatChecker
    job=read(config);input_sha=sha(config)
    validator=Draft202012Validator(read(HERE/'WORLD.schema.json'),format_checker=FormatChecker())
    errors=sorted(validator.iter_errors(job),key=lambda e:str(list(e.absolute_path)))
    require(not errors,'WORLD_SCHEMA:'+('/'.join(map(str,errors[0].absolute_path))+':'+errors[0].message if errors else ''))
    shell_manifest=verify(shells);shells=Path(shells).resolve();weather=Path(weather).resolve()
    shell_manifest_sha=sha(shells/'MANIFEST.json');weather_sha=sha(weather)
    households=indexed(job['households'],'household_id')
    require(households,'empty household batch')
    case_ids=[identifier(c['case_id'])for h in households.values()for c in h['cases']]
    require(len(case_ids)==len(set(case_ids)) and case_ids,'empty or duplicate global case ids')
    out=fresh(output);(out/'inputs').mkdir()
    save(out/'assembly_input.json',job)
    header=weather.read_text().splitlines()[0].split(',')
    require(header[0]=='LOCATION' and len(header)>=10,'invalid EPW location header')
    weather_location={'city':header[1],'region':header[2],'country':header[3],'data_source':header[4],'station':header[5],
                      'latitude':float(header[6]),'longitude':float(header[7]),'utc_offset':float(header[8])}
    (out/'inputs/schema_fields.json.gz').write_bytes(portable_gzip((HERE/'resources/schema_fields.json').read_bytes()))
    shutil.copyfile(weather,out/'inputs/weather.epw');shutil.copyfile(HERE/'reference_environment.json',out/'THERMAL_ENVIRONMENT_POLICY.json')
    # Background gains remain per-household; these rows only carry explicit heat fractions.
    gains=[['Lights','reference_light','','','Watts/Area','',1]]
    for kind,name in [('washer','clotheswasher1'),('dryer','electric_dryer1'),('dishwasher','dishwasher1'),('misc','IECC_Adj1'),('refrigerator','refrigerator1'),('cooking','electric_range1')]:
        fractions=job['thermal_fractions'][kind]
        require(len(fractions)==3 and all(type(v)in(int,float) and 0<=v<=1 for v in fractions) and sum(fractions)<=1,'invalid latent/radiant/lost fractions')
        gains.append(['ElectricEquipment',name,'','','EquipmentLevel',1,1,'',*fractions])
    save(out/'inputs/native_rows.json.gz',{'gains':gains,'tank':[],'provenance':'explicit project reference fractions;not empirical household fits'})
    records=[];pairs=[]
    known={r['household_id']:r['status']for r in shell_manifest['records']}
    for hid,original in households.items():
        try:
            require(known.get(hid)=='shell_compiled','no admitted shell for household')
            spec=copy.deepcopy(original);world=bind_world(spec,read(shells/hid/'layout.json'))
            number(spec['hot_water_minimum_C'],'hot_water_minimum_C',10,60,False)
            pack,states=build_pack(spec,world,shells/hid/'shell.idf',sha(weather))
            candidates=[make_pair(c,spec,pack,states)for c in spec['cases']]
            # Execute every baseline operation through the same literal executor used by the compiler.
            from .validation import check_baseline
            check_baseline(pack,candidates,job['settings'])
            folder=out/'households'/hid;save(folder/'world.json',world);save(folder/'physics.json.gz',pack)
            for pair in candidates:
                cp=out/'pairs'/(pair['case_id']+'.json.gz');save(cp,pair)
                pairs.append({'id':pair['case_id'],'household':{'path':str((folder/'physics.json.gz').relative_to(out)),'sha256':sha(folder/'physics.json.gz')},
                              'pair':{'path':str(cp.relative_to(out)),'sha256':sha(cp)}})
            records.append({'household_id':hid,'status':'assembled','resident_count':len(world['members']),'device_count':len(spec['devices']),
                            'case_count':len(candidates),'complete_context_roster':True,'baseline_execution_checked':True})
        except (ValueError,KeyError,TypeError,IndexError)as e:
            records.append({'household_id':hid,'status':'rejected','reason':str(e)})
    resources={p:sha(out/p)for p in ('inputs/schema_fields.json.gz','inputs/native_rows.json.gz','THERMAL_ENVIRONMENT_POLICY.json')}
    save(out/'physics_job.json',{'schema':'eb.housing_physics.input.v1','resource_root':'.','resources':resources,'settings':job['settings'],'pairs':pairs})
    verify(shells);require(sha(weather)==sha(out/'inputs/weather.epw')==weather_sha,'weather changed during assembly')
    require(sha(config)==input_sha and sha(shells/'MANIFEST.json')==shell_manifest_sha,'assembly input changed during execution')
    return seal(out,{'schema':'eb.housing_world.assembly.v1','input_sha256':input_sha,'shell_manifest_sha256':shell_manifest_sha,
        'weather_sha256':sha(weather),'weather_location':weather_location,'declared_weather_source':job['weather_source'],'records':records,'households_requested':len(households),
        'case_count':len(pairs),'component_factory_sha256':sha(HERE/'components.py'),'world_schema_sha256':sha(HERE/'WORLD.schema.json'),
        'official_heat_pump_sha256':sha(HERE/'resources/heat_pump.json'),'historical_cohort_required':False,'automatic_repair':False})
