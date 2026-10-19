"""Declared daily life -> independent service requirements -> normal plan A.

This module imports no event, tariff, B, questionnaire, or physical-outcome code.
Exact calendars and habit parameters are declared scenarios, not inferred diaries.
"""
import collections
import copy
import datetime as dt
import math
from .common import digest

LIFE_VERSION = 'eb.life_to_A.v1'
LIFE_RULES = {'step_min': 10, 'operation_duration_min': 10, 'seed': 20261019,
              'start_deviation_weight': 1.0, 'preload_wait_weight': .4,
              'retrieval_wait_weight': .5}


def require(ok, reason):
    if not ok:
        raise ValueError(reason)


def minute(value, label, upper=2880):
    require(type(value) is int and 0 <= value <= upper and value % 10 == 0, 'INVALID_GRID:' + label)
    return value


def positive(value, label, zero=False):
    require(type(value) in (int, float) and math.isfinite(value) and (value >= 0 if zero else value > 0), 'INVALID_NUMBER:' + label)
    return value


def merge(spans):
    result = []
    for lo, hi in sorted(spans):
        if lo >= hi:
            continue
        if result and lo <= result[-1][1]:
            result[-1][1] = max(result[-1][1], hi)
        else:
            result.append([lo, hi])
    return result


def normalize_world(world):
    """Public spatial interface; all roster and device rights are retained."""
    return {'household_id': world['layout']['target_household_id'],
            'rooms': [{'room_id': r['room_id'], 'using_household_ids': r['using_household_ids']}
                      for r in world['layout']['rooms']],
            'members': copy.deepcopy(world['members']),
            'devices': copy.deepcopy(world['parameter_pack']['devices']),
            'sleep_room_by_member': world['sleep_room_by_member'],
            'room_map': world['activity_contract']['room_map']}


def resolve_room(key, member_id, world):
    if key == '$sleep':
        return world['sleep_room_by_member'][member_id]
    if key.startswith('$sleep:'):
        return world['sleep_room_by_member'][key.split(':', 1)[1]]
    if key.startswith('$'):
        return world['room_map'][key[1:]]
    return key


def dated(template, date):
    require(set(template) <= {'weekday', 'weekend', 'date_overrides'} and {'weekday', 'weekend'} <= set(template), 'UNKNOWN_OR_INCOMPLETE_DAY_TEMPLATE')
    return template.get('date_overrides', {}).get(str(date), template['weekend' if date.weekday() >= 5 else 'weekday'])


def build_days(spec, world):
    anchor, end = map(dt.date.fromisoformat, (spec['anchor'], spec['end_exclusive']))
    require(1 <= (end - anchor).days <= 730, 'INVALID_CALENDAR_COVERAGE')
    members = {m['member_id']: m for m in world['members']}
    require(len(members) == len(world['members']), 'DUPLICATE_MEMBER')
    rooms = {r['room_id']: r for r in world['rooms']}
    require(set(members) == set(spec['member_calendars']), 'COMPLETE_ROSTER_CALENDARS_REQUIRED')
    days = {}
    for i in range((end - anchor).days):
        day, base = anchor + dt.timedelta(days=i), i * 1440
        calendars, windows, reservations, meals, water = {}, {}, [], {}, []
        for mid, member in sorted(members.items()):
            source = dated(spec['member_calendars'][mid], day)
            cal, previous = [], 0
            for original in source:
                row = copy.deepcopy(original)
                require(set(row) == {'start_min', 'end_min', 'location', 'room', 'activity', 'available_for_operation'}, 'UNKNOWN_OR_INCOMPLETE_CALENDAR_FIELD')
                lo, hi = minute(row['start_min'], 'calendar.start', 1440), minute(row['end_min'], 'calendar.end', 1440)
                require(lo == previous and lo < hi, 'CALENDAR_GAP_OR_OVERLAP:' + mid)
                previous = hi
                require(type(row['available_for_operation']) is bool, 'OPERATION_AVAILABILITY_MUST_BE_DECLARED')
                if row['location'] == 'home':
                    rid = resolve_room(row['room'], mid, world)
                    require(rid in rooms and member['household_id'] in rooms[rid]['using_household_ids'], 'CALENDAR_ROOM_ACCESS_DENIED')
                    row['room_id'] = rid
                    if row['activity'].startswith('sleep') or row['activity'] == 'nap':
                        require(rid == world['sleep_room_by_member'][mid], 'SLEEP_REQUIRES_ASSIGNED_BEDROOM')
                else:
                    require(row['location'] == 'away' and not row.get('room'), 'INVALID_AWAY_LOCATION')
                    row['room_id'] = None
                require(not row['available_for_operation'] or (row['location'] == 'home' and not row['activity'].startswith('sleep') and row['activity'] not in ('nap', 'bath', 'care')), 'INVALID_HANDLING_AVAILABILITY')
                if row['activity'] == 'dinner':
                    meals[mid] = row['end_min']
                if row['activity'] == 'bath':
                    require(row['location'] == 'home' and row['room_id'] == world['room_map']['bath'], 'BATH_REQUIRES_BATHROOM')
                    reservations.append({'room_id': row['room_id'], 'start_min': lo, 'end_min': hi,
                                         'source': 'declared_bath', 'member_id': mid})
                    if member['hot_water_liters']:
                        water.append({'need_id': str(day) + ':bath:' + mid, 'requester': mid,
                                      'release_min': base + lo, 'deadline_min': base + hi,
                                      'quantity': member['hot_water_liters'], 'quantity_unit': 'hot_outlet_liters',
                                      'minimum_C': spec['hot_water_minimum_C'], 'origin': 'declared_bath_quantity_and_time'})
                cal.append(row)
            require(previous == 1440, 'CALENDAR_MUST_END_AT_MIDNIGHT')
            calendars[mid] = cal
            windows[mid] = merge([[base + r['start_min'], base + r['end_min']] for r in cal if r['available_for_operation']])
        explicit = copy.deepcopy(spec.get('facility_reservations', {}).get(str(day), []))
        for r in explicit:
            require(r['room_id'] in rooms, 'UNKNOWN_RESERVATION_ROOM')
            require(minute(r['start_min'], 'reservation.start', 1440) < minute(r['end_min'], 'reservation.end', 1440), 'EMPTY_RESERVATION')
        # Bathing is exclusive; no hidden deletion of a shared resident's activity.
        baths = [r for r in reservations if r['source'] == 'declared_bath']
        require(all(b['end_min'] <= a['start_min'] or a['end_min'] <= b['start_min'] for i, a in enumerate(baths) for b in baths[i + 1:]), 'OVERLAPPING_BATHS')
        reservations += explicit
        days[str(day)] = {'base_min': base, 'calendars': calendars, 'operator_windows': windows,
                          'reservations': reservations, 'meal_end_min_by_member': meals, 'water_needs': water}
    return days


class Scheduler:
    """Deterministic greedy scheduling of complete noninterruptible services."""
    def __init__(self, world, days, rules):
        self.world, self.days, self.rules = world, days, rules
        self.members = {m['member_id']: m for m in world['members']}
        self.assets = {d['asset_id']: d for d in world['devices']}
        self.operations, self.tasks = [], []
        self.person_busy, self.room_busy = set(), set()
        self.asset_holds = collections.defaultdict(list)
        self.slots_by_asset = {}
        self.limit = len(days) * 1440

    def allowed(self, member, aid):
        return aid in member['can_operate_asset_ids'] and member['household_id'] in self.assets[aid]['using_household_ids']

    def free(self, t, mid, room, exterior=False):
        if (mid, t) in self.person_busy or (not exterior and (room, t) in self.room_busy):
            return False
        day = next((d for d in self.days.values() if d['base_min'] <= t < d['base_min'] + 1440), None)
        if day is None:
            return False
        return exterior or not any(r['room_id'] == room and r['start_min'] <= t - day['base_min'] < r['end_min'] for r in day['reservations'])

    def slots(self, aid, lo, hi):
        device = self.assets[aid]
        if aid not in self.slots_by_asset:
            values = []
            for day in self.days.values():
                for mid, windows in day['operator_windows'].items():
                    if self.allowed(self.members[mid], aid):
                        for a, z in windows:
                            values.extend((t, mid) for t in range(a, z, 10))
            self.slots_by_asset[aid] = sorted(values)
        room, exterior = device['room_id'], device['kind'] == 'ev'
        return [(t, mid) for t, mid in self.slots_by_asset[aid] if lo <= t and t + 10 <= hi and self.free(t, mid, room, exterior)]

    def reserve(self, aid, need_id, kind, slot):
        t, mid = slot
        device = self.assets[aid]
        self.person_busy.add((mid, t))
        if device['kind'] != 'ev':
            self.room_busy.add((device['room_id'], t))
        row = {'operation_id': need_id + ':' + kind, 'need_id': need_id, 'asset_id': aid,
               'operator_id': mid, 'room_id': device['room_id'] or 'exterior', 'kind': kind,
               'start_min': t, 'end_min': t + 10, 'duration_min': 10}
        self.operations.append(row)
        return row

    def program(self, need, policy, earliest=None):
        aid, nid = need['asset_id'], need['need_id']
        release, deadline = max(need['release_min'], earliest or 0), min(need['deadline_min'], self.limit)
        duration = policy['duration_min']
        loads = self.slots(aid, release, deadline - duration)
        unloads = self.slots(aid, release + duration + 10, deadline)
        best = None
        for start in range(release + 10, deadline - duration, 10):
            if not any(a <= start % 1440 and (start + duration - 1) % 1440 < z and start // 1440 == (start + duration - 1) // 1440
                       for a, z in policy['machine_windows_min']):
                continue
            load_choices = [s for s in loads if s[0] + 10 <= start and start - s[0] - 10 <= policy['maximum_preload_wait_min']]
            unload_choices = [s for s in unloads if start + duration <= s[0] and s[0] - start - duration <= policy['maximum_retrieval_wait_min']]
            if not load_choices or not unload_choices:
                continue
            # Latest feasible load and first feasible retrieval minimize handling waits.
            lt = max(s[0] for s in load_choices)
            ut = min(s[0] for s in unload_choices)
            load = min((s for s in load_choices if s[0] == lt), key=lambda s: digest([self.rules['seed'], nid, 'load', s[1]]))
            unload = min((s for s in unload_choices if s[0] == ut), key=lambda s: digest([self.rules['seed'], nid, 'unload', s[1]]))
            if not policy['timer_allowed'] and load[0] + 10 != start:
                continue
            if any(max(load[0], a) < min(unload[0] + 10, z) for a, z in self.asset_holds[aid]):
                continue
            preferred = need['preferred_start_min']
            cost = (self.rules['start_deviation_weight'] * abs(start - preferred)
                    + self.rules['preload_wait_weight'] * (start - load[0] - 10)
                    + self.rules['retrieval_wait_weight'] * (unload[0] - start - duration))
            item = (cost, start, load, unload)
            if best is None or item < best:
                best = item
        if best is None:
            return {'need_id': nid, 'status': 'unserved', 'reason': 'NO_JOINT_LOAD_RUN_RETRIEVE'}
        _, start, load, unload = best
        self.reserve(aid, nid, 'load', load)
        self.reserve(aid, nid, 'unload', unload)
        task = {'task_id': nid, 'need_id': nid, 'asset_id': aid, 'kind': need['kind'],
                'start_min': start, 'end_min': start + duration}
        if need.get('depends_on_need_id'):
            task['depends_on_need_id'] = need['depends_on_need_id']
        self.tasks.append(task)
        self.asset_holds[aid].append((load[0], unload[0] + 10))
        return {'need_id': nid, 'status': 'scheduled', 'program_start_min': start,
                'program_end_min': start + duration, 'load_min': load[0],
                'retrieval_end_min': unload[0] + 10, 'preload_wait_min': start - load[0] - 10,
                'retrieval_wait_min': unload[0] - start - duration}


def thermostat_controls(spec, world, days):
    controls, comfort = [], []
    assets = {d['asset_id']: d for d in world['devices']}
    covered = set()
    for policy in spec['thermostat_policies']:
        aid = policy['asset_id']
        require(aid not in covered and assets[aid]['kind'] == 'ac', 'DUPLICATE_OR_NON_AC_POLICY')
        covered.add(aid)
        require(policy['mode'] in ('occupied_with_hold', 'home_continuous', 'continuous'), 'UNKNOWN_THERMOSTAT_HABIT')
        require(type(policy['fan_operating_mode']) is int and policy['fan_operating_mode'] in (0, 1), 'INVALID_FAN_MODE')
        minute(policy['hold_min'], 'hold_min')
        require(5 <= policy['heating_setpoint_C'] < policy['cooling_setpoint_C'] <= 40, 'INVALID_THERMOSTAT_BAND')
        require(5 <= policy['setback_heating_C'] < policy['setback_cooling_C'] <= 40, 'INVALID_SETBACK_BAND')
        room = assets[aid]['room_id']
        occupants = set()
        for day in days.values():
            for cal in day['calendars'].values():
                for e in cal:
                    if e['location'] == 'home' and e['room_id'] == room:
                        occupants.update(range(day['base_min'] + e['start_min'], day['base_min'] + e['end_min'], 10))
        raw = []
        for day in days.values():
            base = day['base_min']
            home = {base + t for mid, cal in day['calendars'].items()
                    if next(m for m in world['members'] if m['member_id'] == mid)['household_id'] in assets[aid]['using_household_ids']
                    for e in cal if e['location'] == 'home' for t in range(e['start_min'], e['end_min'], 10)}
            for t in range(base, base + 1440, 10):
                active = (policy['mode'] == 'continuous' or (policy['mode'] == 'home_continuous' and t in home)
                          or (policy['mode'] == 'occupied_with_hold' and any(t - dtm in occupants for dtm in range(0, policy['hold_min'] + 10, 10))))
                raw.append({'asset_id': aid, 'kind': 'ac_setpoint', 'start_min': t, 'end_min': t + 10,
                            'heating_setpoint_C': policy['heating_setpoint_C'] if active else policy['setback_heating_C'],
                            'cooling_setpoint_C': policy['cooling_setpoint_C'] if active else policy['setback_cooling_C'],
                            'fan_operating_mode': policy['fan_operating_mode']})
        controls.extend(compress_controls(raw))
    require(covered == {d['asset_id'] for d in world['devices'] if d['kind'] == 'ac'}, 'EVERY_AC_REQUIRES_EXPLICIT_HABIT')
    for requirement in spec['comfort_requirements']:
        aid = requirement['asset_id']; require(aid in covered, 'COMFORT_REQUIRES_INSTALLED_AC')
        band = requirement['temperature_band_C']
        require(band is None or (len(band) == 2 and band[0] < band[1]), 'INVALID_INDEPENDENT_COMFORT_BAND')
        room = assets[aid]['room_id']
        for day in days.values():
            spans = merge([[day['base_min'] + e['start_min'], day['base_min'] + e['end_min']]
                           for cal in day['calendars'].values() for e in cal if e['location'] == 'home' and e['room_id'] == room])
            for lo, hi in spans:
                comfort.append({'need_id': str(lo) + ':comfort:' + aid, 'kind': 'comfort', 'asset_id': aid,
                                'room_id': room, 'release_min': lo, 'deadline_min': hi,
                                'temperature_band_C': band, 'origin': requirement['origin'],
                                'derived_from_A_setpoint': False})
    return controls, comfort


def compress_controls(rows):
    out = []
    for row in rows:
        values = {k: v for k, v in row.items() if k not in ('start_min', 'end_min')}
        if out and out[-1]['end_min'] == row['start_min'] and {k: v for k, v in out[-1].items() if k not in ('start_min', 'end_min')} == values:
            out[-1]['end_min'] = row['end_min']
        else:
            out.append(copy.deepcopy(row))
    return out


def mobility(spec, world, scheduler):
    """Original journeys, actual handling, known anchor connection, continuous SOC."""
    evs = [d for d in world['devices'] if d['kind'] == 'ev']
    require(bool(evs) == bool(spec.get('mobility')), 'EV_MOBILITY_CONTRACT_MISMATCH')
    if not evs:
        return {'controls': [], 'connections': [], 'journeys': [], 'states': [], 'charge_events': [], 'failures': [], 'requirements': []}
    require(len(evs) == 1, 'ONE_EV_SUPPORTED')
    device, contract = evs[0], spec['mobility']
    aid, p = device['asset_id'], device['parameters']
    require(contract['anchor_state'] == 'plugged', 'KNOWN_EV_ANCHOR_CONNECTION_REQUIRED')
    mid = contract['operator_id']
    require(mid in scheduler.members and scheduler.allowed(scheduler.members[mid], aid), 'EV_HANDLER_NOT_AUTHORIZED')
    journeys = []
    for date, day in scheduler.days.items():
        for n, route in enumerate(dated(contract['journey_templates'], dt.date.fromisoformat(date))):
            departure, arrival = minute(route['departure_min'], 'departure', 1440), minute(route['arrival_min'], 'arrival', 1440)
            require(departure < arrival, 'JOURNEY_MUST_RETURN_SAME_DAY')
            positive(route['traction_kWh'], 'traction_kWh')
            # The driver calendar must contain the declared away interval.
            cal = day['calendars'][mid]
            require(sum(max(0, min(arrival, e['end_min']) - max(departure, e['start_min'])) for e in cal if e['location'] == 'away') == arrival - departure, 'JOURNEY_CALENDAR_MISMATCH')
            journeys.append({**route, 'absolute_departure_min': day['base_min'] + departure,
                             'absolute_arrival_min': day['base_min'] + arrival, 'journey_id': date + ':trip:' + str(n)})
    journeys.sort(key=lambda x: x['absolute_departure_min'])
    require(all(a['absolute_arrival_min'] <= b['absolute_departure_min'] for a, b in zip(journeys, journeys[1:])), 'OVERLAPPING_JOURNEYS')
    connections, controls, needs, failures = [], [], [], []
    start, origin = 0, 'given_anchor_connection'
    for index in range(len(journeys) + 1):
        trip = journeys[index] if index < len(journeys) else None
        stop = trip['absolute_departure_min'] - 10 if trip else scheduler.limit
        nid = 'EV:connection:' + str(index)
        if trip:
            choices = [s for s in scheduler.slots(aid, stop, stop + 10) if s[1] == mid]
            if not choices:
                failures.append({'need_id': nid, 'status': 'unserved', 'reason': 'NO_REAL_EV_UNPLUG_HANDLER'})
            else:
                scheduler.reserve(aid, nid, 'EV_unplug', choices[0])
        require(start <= stop, 'INVALID_EV_PHYSICAL_CONNECTION')
        connections.append({'need_id': nid, 'asset_id': aid, 'start_min': start, 'end_min': stop, 'origin': origin})
        if start < stop:
            controls.append({'asset_id': aid, 'kind': 'ev_charge_window', 'need_id': nid,
                             'start_min': start, 'end_min': stop, 'stop_at_target_soc': p['target_soc']})
            needs.append({'need_id': nid, 'kind': 'ev', 'asset_id': aid, 'release_min': start,
                          'deadline_min': stop, 'required_departure_soc': p['target_soc'],
                          'origin': 'original_connection_and_next_given_journey'})
        if trip is None:
            break
        arrival = trip['absolute_arrival_min']
        choices = [s for s in scheduler.slots(aid, arrival, arrival + 10) if s[1] == mid]
        if not choices:
            failures.append({'need_id': nid, 'status': 'unserved', 'reason': 'NO_REAL_EV_PLUG_HANDLER'})
        else:
            scheduler.reserve(aid, 'EV:connection:' + str(index + 1), 'EV_plug', choices[0])
        start, origin = arrival + 10, 'declared_arrival_and_actual_plug_operation'
    energy = p['initial_energy_kwh']; states, charge_events = [], []
    trips = {j['absolute_departure_min']: j for j in journeys}
    for t in range(0, scheduler.limit + 1, 10):
        states.append([t, energy])  # Before the departure at this same minute.
        if t in trips:
            need = trips[t]['traction_kWh']
            if energy < p['target_soc'] * p['capacity_kwh'] - 1e-8:
                failures.append({'need_id': trips[t]['journey_id'], 'status': 'unserved', 'reason': 'EV_DEPARTURE_TARGET_SHORTFALL'})
            if energy - need < p['minimum_soc'] * p['capacity_kwh'] - 1e-8:
                failures.append({'need_id': trips[t]['journey_id'], 'status': 'unserved', 'reason': 'EV_DEPARTURE_RESERVE_SHORTFALL'})
            energy = max(0, energy - need)
        if t == scheduler.limit:
            break
        connection = next((c for c in connections if c['start_min'] <= t and t + 10 <= c['end_min']), None)
        if connection:
            inc = min(p['charger_kw'] * p['efficiency'] / 6, max(0, p['target_soc'] * p['capacity_kwh'] - energy))
            if inc:
                charge_events.append({'kind': 'charge', 'need_id': connection['need_id'], 'start_min': t, 'end_min': t + 10, 'battery_kWh': inc})
                energy += inc
    return {'controls': controls, 'connections': connections, 'journeys': journeys, 'states': states,
            'charge_events': charge_events, 'failures': failures, 'requirements': needs}


def generate_household(spec, world, rules=None):
    """Build A for all supplied dates, never conditioning on an intervention."""
    spec, world = copy.deepcopy(spec), copy.deepcopy(world)
    rules = {**LIFE_RULES, **(rules or {})}
    require(set(rules) == set(LIFE_RULES) and rules['step_min'] == rules['operation_duration_min'] == 10, 'UNKNOWN_OR_UNSUPPORTED_LIFE_RULES')
    require(all(type(rules[k]) in (int, float) and math.isfinite(rules[k]) and rules[k] >= 0 for k in ('start_deviation_weight', 'preload_wait_weight', 'retrieval_wait_weight')), 'INVALID_SCHEDULING_WEIGHT')
    require(spec['household_id'] == world['household_id'], 'LIFE_WORLD_ID_MISMATCH')
    require(not set(spec) & {'B', 'events', 'VPP_events', 'tariff', 'human_answers', 'acceptance'}, 'DOWNSTREAM_INFORMATION_IN_A_INPUT')
    require(set(spec) <= {'household_id', 'anchor', 'end_exclusive', 'member_calendars', 'hot_water_minimum_C', 'program_policies', 'thermostat_policies', 'comfort_requirements', 'tank_policy', 'mobility', 'facility_reservations', 'provenance'}, 'UNKNOWN_LIFE_INPUT_FIELD')
    require(10 <= spec['hot_water_minimum_C'] <= 60, 'INVALID_HOT_WATER_SERVICE_TEMPERATURE')
    days = build_days(spec, world)
    scheduler = Scheduler(world, days, rules)
    ev = mobility(spec, world, scheduler)  # Fixed real visits reserve resources first.
    controls, comfort = thermostat_controls(spec, world, days)
    controls += ev['controls']
    tanks = [d for d in world['devices'] if d['kind'] == 'water_heater']
    water = [n for d in days.values() for n in d['water_needs']]
    water_failures = []
    if water and not tanks:
        for n in water:
            n['kind'], n['asset_id'] = 'water_heater', None
            water_failures.append({'need_id': n['need_id'], 'status': 'unserved', 'reason': 'HOT_WATER_REQUIREMENT_WITHOUT_TANK'})
    if tanks:
        require(len(tanks) == 1, 'ONE_TANK_SUPPORTED')
        tank, policy = tanks[0], spec['tank_policy']
        require(policy['asset_id'] == tank['asset_id'] and 10 <= policy['target_C'] <= tank['parameters']['maximum_C'], 'INVALID_TANK_POLICY')
        require(policy['mode'] in ('continuous', 'before_draws'), 'UNKNOWN_TANK_HABIT')
        minute(policy['preheat_lead_min'], 'preheat_lead')
        minute(policy['after_draw_hold_min'], 'tank_hold')
        active = merge([[max(0, n['release_min'] - policy['preheat_lead_min']), min(scheduler.limit, n['deadline_min'] + policy['after_draw_hold_min'])] for n in water])
        raw = [{'asset_id': tank['asset_id'], 'kind': 'tank_setpoint', 'start_min': t, 'end_min': t + 10,
                'value_C': policy['target_C'] if policy['mode'] == 'continuous' or any(a <= t < z for a, z in active) else policy['setback_C']}
               for t in range(0, scheduler.limit, 10)]
        controls += compress_controls(raw)
        for n in water:
            n['kind'], n['asset_id'] = 'water_heater', tank['asset_id']
            member = scheduler.members[n['requester']]
            if member['household_id'] not in tank['using_household_ids']:
                water_failures.append({'need_id': n['need_id'], 'status': 'unserved', 'reason': 'HOT_WATER_ASSET_ACCESS_NOT_DECLARED'})
    policies = spec['program_policies']
    require(len({p['service_id'] for p in policies}) == len(policies), 'DUPLICATE_SERVICE_POLICY')
    for p in policies:
        fields = {'service_id', 'asset_id', 'kind', 'trigger', 'duration_min', 'preferred_start_min', 'maximum_preload_wait_min',
                  'maximum_retrieval_wait_min', 'deadline_after_release_min', 'machine_windows_min', 'timer_allowed', 'priority'}
        fields |= {'daily_quantity_kg', 'capacity_kg', 'initial_inventory_kg', 'daily_service', 'no_arrival_release_min'} if p['trigger'] == 'textile' else {'upstream_service_id'} if p['trigger'] == 'after_service' else set()
        require(set(p) == fields, 'UNKNOWN_OR_INCOMPLETE_SERVICE_POLICY_FIELD')
        require(p['asset_id'] in scheduler.assets and scheduler.assets[p['asset_id']]['kind'] == p['kind'], 'PROGRAM_ASSET_MISMATCH')
        require(p['kind'] in ('washer', 'dryer', 'dishwasher'), 'UNSUPPORTED_PROGRAM_KIND')
        for key in ('duration_min', 'maximum_preload_wait_min', 'maximum_retrieval_wait_min', 'deadline_after_release_min'):
            minute(p[key], key)
        require(p['duration_min'] > 0 and p['deadline_after_release_min'] > 0 and type(p['timer_allowed']) is bool, 'INVALID_PROGRAM_CAPABILITY')
        require(type(p['priority']) is int and p['priority'] >= 0, 'INVALID_SERVICE_PRIORITY')
        for k in ('weekday', 'weekend'):
            minute(p['preferred_start_min'][k], 'preferred_start', 1440)
        for a, z in p['machine_windows_min']:
            require(minute(a, 'machine_window', 1440) < minute(z, 'machine_window', 1440), 'EMPTY_MACHINE_WINDOW')
    roots = sorted([p for p in policies if p['trigger'] != 'after_service'], key=lambda p: (p['priority'], p['service_id']))
    children = [p for p in policies if p['trigger'] == 'after_service']
    require(all((p['trigger'], p['kind']) in {('textile', 'washer'), ('after_dinner', 'dishwasher')} for p in roots), 'SERVICE_TRIGGER_KIND_MISMATCH')
    require(all(p['kind'] == 'dryer' for p in children), 'ONLY_EXPLICIT_SEPARATE_DRYER_DEPENDENCY_SUPPORTED')
    require(all(p['upstream_service_id'] in {r['service_id'] for r in roots} for p in children), 'UNKNOWN_OR_NESTED_SERVICE_DEPENDENCY')
    requirements, ledger, inventory = [], [], {}
    for p in roots:
        if p['trigger'] == 'textile':
            positive(p['daily_quantity_kg'], 'daily_quantity', True)
            positive(p['capacity_kg'], 'capacity')
            positive(p['initial_inventory_kg'], 'initial_inventory', True)
            require(type(p['daily_service']) is bool, 'DAILY_SERVICE_CONDITION_MUST_BE_EXPLICIT')
            minute(p['no_arrival_release_min'], 'no_arrival_release', 1430)
            inventory[p['service_id']] = p['initial_inventory_kg']
    for date, day in days.items():
        daytype = 'weekend' if dt.date.fromisoformat(date).weekday() >= 5 else 'weekday'
        base = day['base_min']
        for p in roots:
            if p['trigger'] == 'textile':
                inventory[p['service_id']] += p['daily_quantity_kg']
                available = inventory[p['service_id']]
                if not p['daily_service'] and available < p['capacity_kg']:
                    continue
                eligible = {m['member_id'] for m in world['members'] if m['household_id'] in scheduler.assets[p['asset_id']]['using_household_ids']}
                arrivals = [e['start_min'] for mid, cal in day['calendars'].items() if mid in eligible for prior, e in zip(cal, cal[1:])
                            if prior['location'] == 'away' and e['location'] == 'home']
                release = base + (max(arrivals) if arrivals else p['no_arrival_release_min'])
                count = math.ceil(available / p['capacity_kg']) if p['daily_service'] else math.floor((available + 1e-9) / p['capacity_kg'])
                quantities = [min(p['capacity_kg'], max(0, available - i * p['capacity_kg'])) for i in range(count)]
            elif p['trigger'] == 'after_dinner':
                eligible = {m['member_id'] for m in world['members'] if m['household_id'] in scheduler.assets[p['asset_id']]['using_household_ids']}
                meals = [t for mid, t in day['meal_end_min_by_member'].items() if mid in eligible]
                if not meals:
                    continue
                release = base + max(meals)
                quantities = [len(meals)]
            else:
                raise ValueError('UNKNOWN_SERVICE_TRIGGER')
            for index, quantity in enumerate(quantities):
                nid = date + ':' + p['service_id'] + ':' + str(index)
                need = {'need_id': nid, 'kind': p['kind'], 'asset_id': p['asset_id'],
                        'release_min': release, 'deadline_min': release + p['deadline_after_release_min'],
                        'preferred_start_min': base + p['preferred_start_min'][daytype],
                        'quantity': quantity, 'unit': 'kg' if p['trigger'] == 'textile' else 'declared_dinner_participants',
                        'maximum_retrieval_wait_min': p['maximum_retrieval_wait_min'],
                        'maximum_preload_wait_min': p['maximum_preload_wait_min'],
                        'timer_allowed': p['timer_allowed'], 'machine_windows_min': p['machine_windows_min'],
                        'constraint_origin': 'declared_life_service_policy',
                        'origin': 'declared_daily_textile_inventory' if p['trigger'] == 'textile' else 'dated_dinner_completion',
                        'service_policy_id': p['service_id']}
                requirements.append(need)
                result = scheduler.program(need, p)
                ledger.append(result)
                if result['status'] == 'scheduled' and p['trigger'] == 'textile':
                    inventory[p['service_id']] -= quantity
                for child in sorted((c for c in children if c['upstream_service_id'] == p['service_id']), key=lambda c: c['service_id']):
                    child_need = {**need, 'need_id': nid + ':' + child['service_id'], 'kind': child['kind'],
                                  'asset_id': child['asset_id'], 'depends_on_need_id': nid,
                                  'deadline_min': release + child['deadline_after_release_min'],
                                  'maximum_retrieval_wait_min': child['maximum_retrieval_wait_min'],
                                  'maximum_preload_wait_min': child['maximum_preload_wait_min'],
                                  'timer_allowed': child['timer_allowed'], 'machine_windows_min': child['machine_windows_min'],
                                  'preferred_start_min': base + child['preferred_start_min'][daytype],
                                  'service_policy_id': child['service_id'], 'origin': 'same_declared_textile_service_dependency'}
                    requirements.append(child_need)
                    ledger.append(scheduler.program(child_need, child, result['retrieval_end_min']) if result['status'] == 'scheduled'
                                  else {'need_id': child_need['need_id'], 'status': 'unserved', 'reason': 'UPSTREAM_SERVICE_UNSERVED'})
    requirements += comfort + water + ev['requirements']
    failures = [r for r in ledger if r['status'] == 'unserved'] + ev['failures'] + water_failures
    return {'schema': LIFE_VERSION, 'household_id': spec['household_id'],
            'anchor': spec['anchor'], 'end_exclusive': spec['end_exclusive'],
            'input_sha256': digest(spec), 'world_sha256': digest(world), 'rules': rules,
            'days': days, 'requirements': requirements,
            'A': {'tasks': sorted(scheduler.tasks, key=lambda x: (x['start_min'], x['task_id'])),
                  'operations': sorted(scheduler.operations, key=lambda x: (x['start_min'], x['operation_id'])),
                  'controls': sorted(controls, key=lambda x: (x['start_min'], x['asset_id']))},
            'service_ledger': ledger, 'unserved': failures, 'remaining_unallocated_textile_kg': inventory,
            'EV': ev, 'status': 'needs_unserved' if failures else 'A_constructed',
            'B_events_prices_or_answers_used': False,
            'field_calibration_claimed': False, 'human_acceptance': None}
