"""Literal operator and device execution; independent of resource paths."""
import collections
import bisect
import datetime as dt


def overlap(a,z,b,y):
    return max(a,b)<min(z,y)


def departure_target_times(connections, departures):
    """A home charge target applies to the next departure, not every away leg."""
    ordered = sorted(departures); result = set()
    for a, z in connections.values():
        index = bisect.bisect_left(ordered, z)
        if index < len(ordered):
            result.add(ordered[index])
    return result


def explicit_EV_connections(pack, base):
    """Validate given anchor state and subsequent literal plug/unplug bounds."""
    rows = sorted(pack['EV_physical_connections'], key=lambda c: c['start_min'])
    assets = {d['asset_id'] for d in pack['world']['parameter_pack']['devices'] if d['kind'] == 'ev'}
    limit = (dt.date.fromisoformat(pack['end_exclusive']) - dt.date.fromisoformat(pack['anchor'])).days * 1440
    if len({r['need_id'] for r in rows}) != len(rows):
        raise ValueError('DUPLICATE_EV_PHYSICAL_CONNECTION')
    for index, row in enumerate(rows):
        if row['asset_id'] not in assets:
            raise ValueError('EV_CONNECTION_ASSET_NOT_INSTALLED')
        a, z = row['start_min'], row['end_min']
        if type(a) is not int or type(z) is not int or a % 10 or z % 10 or not 0 <= a <= z <= limit:
            raise ValueError('INVALID_EV_PHYSICAL_CONNECTION_INTERVAL')
        if index and rows[index - 1]['end_min'] > a:
            raise ValueError('OVERLAPPING_EV_PHYSICAL_CONNECTIONS')
        if a == 0:
            if row['origin'] != 'given_anchor_connection':
                raise ValueError('EV_ANCHOR_CONNECTION_MUST_BE_DECLARED')
        elif not any(o['kind'] == 'EV_plug' and o['asset_id'] == row['asset_id'] and o['need_id'] == row['need_id'] and o['end_min'] == a for o in pack['operations']):
            raise ValueError('EV_CONNECTION_HAS_NO_ORIGINAL_PLUG')
        if z < limit and not any(o['kind'] == 'EV_unplug' and o['asset_id'] == row['asset_id'] and o['need_id'] == row['need_id'] and o['start_min'] == z for o in pack['operations']):
            raise ValueError('EV_CONNECTION_HAS_NO_ORIGINAL_UNPLUG')
        for trip in pack['journeys']:
            if overlap(a, z, trip['absolute_departure_min'], trip['absolute_arrival_min']):
                raise ValueError('EV_CONNECTION_OVERLAPS_GIVEN_JOURNEY')
    return {c['need_id']: (c['start_min'] - base, c['end_min'] - base) for c in rows}


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
    collections_by_need={}
    for load in (o for o in plan['operations']if o['kind']=='load'):
        nid=load['need_id'];tasks=[t for t in plan['tasks']if t['need_id']in(nid,nid+':dry')];unload=unloads.get(nid)
        if not tasks:continue
        first=min(t['start_min']for t in tasks);end=max(t['end_min']for t in tasks)
        reasons=set(bad[load['operation_id']])
        if nid in needs and load['start_min']<needs[nid]['release_min']:reasons.add('LOAD_BEFORE_SERVICE_RELEASE')
        if first<load['end_min']:reasons.add('PROGRAM_BEFORE_LOADING')
        if any(overlap(load['start_min'],max(end,unload['end_min']if unload else hi),a,b)for a,b in holds[load['asset_id']]):reasons.add('ASSET_STILL_OCCUPIED')
        for task in tasks:
            prerequisite=task.get('depends_on_need_id')
            if prerequisite and (prerequisite not in collections_by_need or collections_by_need[prerequisite]>load['start_min']):
                reasons.add('PREREQUISITE_NOT_COLLECTED')
        ran=not reasons
        collected=ran and unload is not None and not bad[unload['operation_id']]and unload['start_min']>=end
        if collected:collections_by_need[nid]=unload['end_min']
        if ran:holds[load['asset_id']].append((load['start_min'],unload['end_min']if collected else hi))
        else:
            not_run.update(t['task_id']for t in tasks);failed_ops.add(load['operation_id'])
        if unload and not collected:failed_ops.add(unload['operation_id'])
        if end>=lo and first<hi:batch.append({'need_id':nid,'program_executed':ran,'collected':collected,'reasons':sorted(reasons|set(bad[unload['operation_id']]if unload else ['NO_RETRIEVAL_IN_HORIZON'])),
                                 'requested_program_end_min':end,'requested_retrieval_end_min':unload['end_min']if unload else None})
    failed_ops.update(k for k,v in bad.items()if v)
    return {'tasks':[t for t in plan['tasks']if t['task_id']not in not_run],
            'operations':[o for o in plan['operations']if o['operation_id']not in failed_ops],
            'batches':batch,'operation_failures':{k:sorted(v)for k,v in bad.items()if v},
            'dropped_program_ids':sorted(not_run),'automatic_repair':False}
