"""Snapshot existing family/calendar/service inputs; never inspect B or outcomes."""
import copy
import datetime as dt

from .core import digest, require
from .decision_conditions import contract_input


def at(anchor, minute):
    require(type(minute) in (int, float), 'PORTRAIT_TIME_REQUIRED')
    return (dt.datetime.fromisoformat(anchor) + dt.timedelta(minutes=minute)).isoformat(timespec='minutes')


def _service(need, anchor, tasks, operations):
    ident = need['need_id']
    keep = ('need_id', 'asset_id', 'kind', 'requester', 'quantity', 'unit', 'service_purpose',
            'required_departure_soc', 'target_C', 'temperature_band_C', 'constraint_origin',
            'origin', 'source_or_design_rule', 'wearable_clothes_ready_at_program_end')
    out = {k: copy.deepcopy(need[k]) for k in keep if k in need}
    if out['kind'] == 'comfort':
        out['kind'] = 'ac'
    for field in ('release', 'deadline', 'preferred_start', 'departure', 'delivery_deadline'):
        if field + '_min' in need:
            out[field + '_at'] = at(anchor, need[field + '_min'])
    out['source_date'] = anchor
    out['baseline_tasks'] = [{**{k: t[k] for k in ('kind', 'task_id') if k in t},
                              'start_at': at(anchor, t['start_min']), 'end_at': at(anchor, t['end_min'])}
                             for t in tasks if t.get('need_id') == ident]
    out['handling'] = [{**{k: o[k] for k in ('kind', 'operator_id', 'need_id') if k in o},
                        'start_at': at(anchor, o['start_min']), 'end_at': at(anchor, o['end_min'])}
                       for o in operations if o.get('need_id') == ident]
    out['source_requirement_sha256'] = digest(need)
    out['source_requirement'] = copy.deepcopy(need)
    return out


def from_reference(profile, packets, role, habit_packets=None):
    """Frozen reference50 adapter. Uses context.needs.A and plans.A only.

    Each packet has its own midnight origin; cross-midnight deadlines are not
    reduced modulo 24 hours. Neighbor calendars and devices are not borrowed.
    """
    hid = profile['household_id']; mids = {m['member_id'] for m in profile['members']}
    require(packets and len({p['date'] for p in packets}) == len(packets), 'PORTRAIT_DUPLICATE_OR_EMPTY_DATES')
    days, services = [], []
    for packet in sorted(packets, key=lambda p: p['date']):
        require(packet['household_id'] == hid, 'PORTRAIT_HOUSEHOLD_MISMATCH')
        date = packet['date']; dt.date.fromisoformat(date)
        day = next(d for d in packet['context']['days'] if d['date'] == date)
        calendars = {mid: copy.deepcopy(day['calendars'][mid]) for mid in sorted(mids)}
        days.append({'date': date, 'calendars': calendars,
                     'family': copy.deepcopy(day.get('family', {})),
                     'operator_windows': copy.deepcopy(day.get('operator_windows', {}))})
        plan = packet['plans']['A']
        # Daily requirements carry their original date in the frozen need ID.
        # Nearby context days are not mistaken for today's tasks.
        for need in packet['context']['needs']['A']:
            if need['need_id'].startswith(date + ':'):
                services.append(_service(need, date, plan.get('tasks', []), plan.get('operations', [])))
    habit_days = []
    for packet in sorted(packets if habit_packets is None else habit_packets, key=lambda p: p['date']):
        require(packet['household_id'] == hid, 'PORTRAIT_HABIT_HOUSEHOLD_MISMATCH')
        day = next(d for d in packet['context']['days'] if d['date'] == packet['date'])
        habit_days.append({'date': day['date'], 'calendars': {mid: copy.deepcopy(day['calendars'][mid]) for mid in sorted(mids)},
                           'operator_windows': {mid: copy.deepcopy(day.get('operator_windows', {}).get(mid, [])) for mid in sorted(mids)}})
    require(len({d['date'] for d in habit_days}) == len(habit_days), 'PORTRAIT_DUPLICATE_HABIT_DATE')
    return {'schema': 'eb.energy_portrait.input.v1', 'household_id': hid, 'role': role,
            'members': copy.deepcopy(profile['members']), 'devices': copy.deepcopy(profile['devices']),
            'existing_policy': copy.deepcopy(profile.get('role_policy', {})),
            'declared_thermostats': [], 'declared_device_settings': {}, 'days': days, 'services': services,
            'habit_days': habit_days,
            'source_kind': 'frozen_generated_reference_family_calendar_and_A;not_observed_preferences'}


def from_formal(profile, raw_days, role, contexts):
    """Current release adapter: declared calendars/rights/needs, not A commands.

    Context bindings must be verified by the caller against the signed release.
    Actual A/B plans and physics are reserved for the independent audit stage.
    """
    hid = profile['household_id']; dates = {d['date'] for d in raw_days}
    require(dates == {c['date'] for c in contexts}, 'FORMAL_CALENDAR_CONTEXT_DATE_MISMATCH')
    rights = None; contracts = []; external = set()
    for c in contexts:
        require(c['household_id'] == hid, 'FORMAL_CONTEXT_HOUSEHOLD_MISMATCH')
        devices = {d['asset_id']: d for d in c['devices']}
        require(set(devices) == {d['asset_id'] for d in profile['devices']} and
                all(devices[d['asset_id']].get('room_id') == d.get('room_id') for d in profile['devices']), 'FORMAL_PROFILE_ASSET_ROOM_MISMATCH')
        current = {'assets': {aid: {'authorized_operator_ids': sorted(v['authorized_operator_ids']),
                                   'registered_operator_id': devices[aid].get('operator_id')}
                              for aid, v in c['authority']['assets'].items()}}
        require(rights is None or rights == current, 'FORMAL_ASSET_RIGHTS_CHANGE_ACROSS_DAYS')
        rights = current
        residents = {m['member_id'] for m in profile['members']}
        declared = {mid for v in current['assets'].values() for mid in v['authorized_operator_ids']} - residents
        require(all(mid in c['operator_windows'] for mid in declared), 'FORMAL_EXTERNAL_OPERATOR_HAS_NO_DECLARED_WINDOWS')
        external |= declared
        contracts += [contract_input(n, c['date']) for n in c['needs'] if n['need_id'].startswith(c['date'] + ':')]
    return {'schema': 'eb.energy_portrait.input.v1', 'household_id': hid, 'role': role,
            'members': copy.deepcopy(profile['members']), 'devices': copy.deepcopy(profile['devices']),
            'existing_policy': copy.deepcopy(profile['role_policy']), 'declared_thermostats': [],
            'energy_preferences': copy.deepcopy(profile.get('energy_preferences', {})),
            'declared_device_settings': {}, 'days': copy.deepcopy(raw_days), 'habit_days': copy.deepcopy(raw_days),
            'asset_authority': rights, 'external_operator_ids': sorted(external), 'declared_service_contracts': contracts, 'services': [],
            'source_kind': 'current_sealed_release_declarations;no_plan_commands_or_outcomes'}


def from_life(family, result, resource_world):
    """Public family-connection adapter over the already generated life/A result."""
    require(result['household_id'] == family['household_id'], 'PORTRAIT_HOUSEHOLD_MISMATCH')
    hid = family['household_id']; facts = family['facts']
    members = [copy.deepcopy(m) for m in facts['members'] if m['household_id'] == hid]
    mids = {m['member_id'] for m in members}
    require(resource_world['household_id'] == hid, 'PORTRAIT_WORLD_MISMATCH')
    devices = [{'asset_id': d['asset_id'], 'room_id': d.get('room_id'), 'types': [d['kind']]}
               for d in resource_world['devices'] if hid in d['using_household_ids']]
    allowed = {d['asset_id'] for d in devices}
    settings = {aid: {} for aid in allowed}
    for field in ('program_policies', 'thermostat_policies'):
        for policy in family['life'].get(field, []):
            if policy['asset_id'] in allowed:
                settings[policy['asset_id']].setdefault(field, []).append(copy.deepcopy(policy))
    tank = family['life'].get('tank_policy', {})
    if tank.get('asset_id') in allowed:
        settings[tank['asset_id']]['tank_policy'] = copy.deepcopy(tank)
    days = [{'date': date, 'calendars': {mid: copy.deepcopy(day['calendars'][mid]) for mid in sorted(mids)},
             'family': {}, 'operator_windows': {mid: [[lo-day['base_min'], hi-day['base_min']] for lo,hi in day['operator_windows'].get(mid, [])] for mid in sorted(mids)}}
            for date, day in sorted(result['days'].items())]
    plan = result['A']
    services = [_service(n, result['anchor'], plan['tasks'], plan['operations'])
                for n in result['requirements'] if n['asset_id'] in allowed]
    # Here requirement minutes use the whole-run anchor. Their source date is
    # the actual release date, not the anchor repeated for every generated day.
    for service in services:
        service['source_date'] = service['release_at'][:10]
        policies = settings[service['asset_id']].get('program_policies', [])
        matching = [p for p in policies if p['kind'] == service['kind']]
        if matching and 'preferred_start_at' not in service:
            require(len(matching) == 1, 'PORTRAIT_AMBIGUOUS_PROGRAM_POLICY')
            date = service['source_date']; category = 'weekend' if dt.date.fromisoformat(date).weekday() >= 5 else 'weekday'
            preferred = matching[0].get('preferred_start_min', {}).get(category)
            if preferred is not None:
                service['preferred_start_at'] = at(date, preferred)
                service['preferred_start_origin'] = 'declared_life.program_policies.preferred_start_min'
    contracts = []
    for s in services:
        n = copy.deepcopy(s['source_requirement']); n['kind'] = s['kind']
        date = s['source_date']; offset = (dt.date.fromisoformat(date) - dt.date.fromisoformat(result['anchor'])).days * 1440
        for field in ('release_min', 'deadline_min', 'delivery_deadline_min', 'connection_start_min', 'departure_min'):
            if field in n: n[field] -= offset
        for field in ('departure_min', 'arrival_min'):
            if field in n.get('journey', {}): n['journey'][field] -= offset
        contracts.append(contract_input(n, date))
    out = {'schema': 'eb.energy_portrait.input.v1', 'household_id': hid, 'role': family['archetype'],
            'members': members, 'devices': devices, 'existing_policy': {'holder': {'person_id': facts['decision_maker_id'], 'resident': True}},
            'energy_preferences': copy.deepcopy(family.get('energy_preferences', {})),
            'declared_thermostats': copy.deepcopy(family['life']['thermostat_policies']),
            'declared_device_settings': settings,
            'declared_service_contracts': contracts,
            'asset_authority': {'assets': {d['asset_id']: {'authorized_operator_ids': sorted(m['member_id'] for m in resource_world['members']
                if m['member_id'] in mids and d['asset_id'] in m['can_operate_asset_ids'])} for d in devices}},
            'days': days, 'habit_days': copy.deepcopy(days), 'services': services,
            'source_kind': 'declared_public_family_and_life_requirements;not_observed_preferences'}
    if family.get('energy_use_profile', {}).get('joint_sampling'):
        out['frozen_joint_sampling'] = copy.deepcopy(family['energy_use_profile']['joint_sampling'])
    return out
