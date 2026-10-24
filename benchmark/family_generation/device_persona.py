"""Construct experimental appliance habits/preferences/consent WITHOUT plan A.

Only the household's declared calendar, owned devices, explicit policy and EB
role are projected into this module. Time availability never grants authority.
"""
import copy
import datetime as dt
import math
from pathlib import Path

from .core import HERE, digest, read, require, sha
from .decision_conditions import asset_facts, decision_rules, contract_input
from .household_preferences import (SOURCES as HOUSEHOLD_SOURCES, household_preferences,
                                    device_preferences, apply_member_consent)

RULES = HERE / 'DEVICE_PERSONA_RULES.json'
ROLE_RULES = HERE / 'ENERGY_PORTRAIT_RULES.json'
CARE = {'care', 'caregiving', 'childcare_supervision', 'child_bathing_assistance'}
REST = {'sleep', 'sleep_rest', 'nap', 'day_nap'}
BUSY = CARE | REST | {'work', 'school', 'work_or_school', 'home_work', 'bathing', 'bath', 'dinner', 'given_child_meal'}
ACTIONS = {
    'washer': (['shift_complete_wash', 'timer_if_supported'], ['change_program_or_quantity', 'cancel_required_wash']),
    'dryer': (['shift_complete_dry', 'coordinate_with_wash'], ['shorten_required_dry', 'claim_wash_is_ready_to_wear']),
    'dishwasher': (['shift_complete_dish_cycle', 'timer_if_supported'], ['cancel_required_dishes', 'replace_with_unagreed_handwashing']),
    'water_heater': (['shift_heating_preserving_draw_service', 'change_tank_setpoint_preserving_draw_service'], ['move_bath', 'reduce_required_water_or_outlet_temperature', 'tank_setpoint_outside_declared_bounds']),
    'ac': (['small_setpoint_change', 'change_cooling_setpoint', 'change_heating_setpoint', 'precondition_if_supported'], ['stop_occupied_room_without_separate_consent', 'change_occupied_hours', 'temperature_change_without_mode_specific_bounds']),
    'ev': (['shift_charging_in_original_connection'], ['lower_target_SOC', 'change_journey_or_plug_arrangement', 'V2G'])}
LABELS = {'washer': '洗衣', 'dryer': '烘干', 'dishwasher': '洗碗', 'water_heater': '热水', 'ac': '空调', 'ev': '充电'}


def merge(spans):
    out = []
    for lo, hi in sorted(spans):
        require(0 <= lo < hi <= 1440, 'PERSONA_INVALID_CALENDAR_WINDOW')
        if out and lo <= out[-1][1]:
            out[-1][1] = max(out[-1][1], hi)
        else:
            out.append([lo, hi])
    return out


def preference_input(context):
    """Explicit whitelist: baseline_tasks, handling, services and B are absent."""
    mids = {m['member_id'] for m in context['members']}
    external = set(context.get('external_operator_ids', []))
    require(not external & mids, 'PERSONA_EXTERNAL_OPERATOR_IS_RESIDENT')
    days = []
    for day in context.get('habit_days', context['days']):
        require(set(day['calendars']) == mids, 'PERSONA_COMPLETE_CALENDARS_REQUIRED')
        calendars = {mid: [{k: copy.deepcopy(e[k]) for k in ('start_min', 'end_min', 'activity', 'location', 'room_id', 'available_for_operation') if k in e}
                           for e in day['calendars'][mid]] for mid in sorted(mids)}
        for cal in calendars.values():
            for event in cal:
                require(0 <= event['start_min'] < event['end_min'] <= 1440, 'PERSONA_INVALID_CALENDAR_INTERVAL')
        # Availability is a resource fact, not consent or a grant of operation rights.
        windows = {}
        for mid, cal in calendars.items():
            spans = day.get('operator_windows', {}).get(mid)
            if spans is None:
                spans = [[e['start_min'], e['end_min']] for e in cal if e.get('available_for_operation') is True]
            for lo, hi in spans:
                require(not any((e['activity'] in BUSY or e.get('available_for_operation') is False or e.get('location') == 'away')
                                and lo < e['end_min'] and e['start_min'] < hi for e in cal),
                        'PERSONA_AVAILABILITY_OVERLAPS_EXISTING_COMMITMENT')
            windows[mid] = merge(spans)
        for mid in sorted(external):
            windows[mid] = merge(day.get('operator_windows', {}).get(mid, []))
        days.append({'date': day['date'], 'calendars': calendars, 'operator_windows': windows})
    require(days and len({d['date'] for d in days}) == len(days), 'PERSONA_EMPTY_OR_DUPLICATE_DATES')
    result = {k: copy.deepcopy(context.get(k, {})) for k in
            ('household_id', 'role', 'members', 'devices', 'existing_policy', 'declared_device_settings',
             'asset_authority', 'energy_preferences')} | {'days': sorted(days, key=lambda d: d['date']), 'external_operator_ids': sorted(external)}
    result['devices'] = [{k: copy.deepcopy(d[k]) for k in ('asset_id', 'types', 'room_id')} for d in result['devices']]
    assets = {d['asset_id']: d for d in result['devices']}
    require(len(assets) == len(result['devices']), 'PERSONA_DUPLICATE_ASSET')
    for aid, rights in result['asset_authority'].get('assets', {}).items():
        require(aid in assets and set(rights['authorized_operator_ids']) <= mids | external, 'PERSONA_UNKNOWN_OPERATOR_OR_ASSET')
        require(rights.get('registered_operator_id') is None or rights['registered_operator_id'] in rights['authorized_operator_ids'], 'PERSONA_REGISTERED_OPERATOR_NOT_QUALIFIED')
    contracts = [contract_input(n, n['source_date']) for n in context.get('declared_service_contracts', [])]
    require(len({n['need_id'] for n in contracts}) == len(contracts), 'PERSONA_DUPLICATE_CONTRACT')
    for n in contracts:
        require(n['asset_id'] in assets and n['kind'] in assets[n['asset_id']]['types'], 'PERSONA_CONTRACT_UNOWNED_DEVICE')
        require(n['source_date'] in {d['date'] for d in days} and n['release_min'] < n['deadline_min'], 'PERSONA_INVALID_CONTRACT_DATE_OR_INTERVAL')
    result['declared_service_contracts'] = sorted(contracts, key=lambda n: n['need_id'])
    if context.get('frozen_joint_sampling') is not None:
        result['frozen_joint_sampling'] = copy.deepcopy(context['frozen_joint_sampling'])
    return result


def _features(source):
    age = {m['member_id']: m['age_years'] for m in sorted(source['members'], key=lambda m: m['member_id'])}
    care, rest_by_room, uses_by_room = [], {}, {}
    for day in source['days']:
        for mid, cal in day['calendars'].items():
            for e in cal:
                ref = {'date': day['date'], 'member_id': mid, **e}
                if e['activity'] in CARE:
                    care.append(ref)
                if e.get('room_id') is not None and e.get('location') == 'home':
                    uses_by_room.setdefault(e['room_id'], []).append(ref)
                    if age[mid] < 18 and e['activity'] in REST:
                        rest_by_room.setdefault(e['room_id'], []).append(ref)
    return {'care_references': care, 'dependent_rest_by_room': rest_by_room, 'room_use': uses_by_room,
            'household_day_count': len(source['days']), 'adult_count': sum(v >= 18 for v in age.values()),
            'member_ages_years': list(age.values()),
            'minor_count': sum(v < 18 for v in age.values())}


def room_label(source, features, room_id):
    members = {m['member_id']: i + 1 for i, m in enumerate(sorted(source['members'], key=lambda m: m['member_id']))}
    uses = features['room_use'].get(room_id, [])
    sleepers = sorted({e['member_id'] for e in uses if e['activity'] in REST})
    if sleepers:
        return '卧室（成员' + '、'.join(str(members[m]) for m in sleepers) + '）'
    if any(e['activity'] in ('dinner', 'given_child_meal') for e in uses):
        return '公共活动房间'
    return '原登记的使用房间'


def _bounds(source, asset, kind, prior):
    policy = source['existing_policy']; settings = source['declared_device_settings'].get(asset['asset_id'], {})
    out = {'preserve_original_services_and_operator_rights': True, 'device_capability_verified': False}
    if kind in ('washer', 'dryer', 'dishwasher', 'water_heater', 'ev'):
        limit = policy.get('service_policy', {}).get('reschedule_limit_min')
        if limit is not None:
            out['existing_reschedule_limit_min'] = limit
    if kind == 'ac':
        out['existing_thermal_policy'] = copy.deepcopy(policy.get('thermal', {}))
        out['EB_reference_temperature_preference'] = {k: v for k, v in prior.items() if k.startswith('setpoint_preferred') or k == 'temp_tolerance_c'}
        out['EB_reference_temperature_preference_mode'] = 'cooling_only;not_heating_or_actual_room_temperature'
        out['heating_change_numeric_bound'] = policy.get('thermal', {}).get('heating_change_limit_C')
    if kind == 'water_heater':
        out['tank_setpoint_bounds_C'] = settings.get('tank_setpoint_bounds_C')
    if settings:
        out['declared_device_settings'] = copy.deepcopy(settings)
    numbers = [out[k] for k in ('existing_reschedule_limit_min', 'heating_change_numeric_bound') if out.get(k) is not None]
    numbers += [v for k, v in out.get('existing_thermal_policy', {}).items() if k in ('temporary_increase_C', 'maximum_change_duration_min')]
    require(all(type(v) in (int, float) and math.isfinite(v) and v >= 0 for v in numbers), 'PERSONA_INVALID_EXPLICIT_ACTION_BOUND')
    tank = out.get('tank_setpoint_bounds_C')
    require(tank is None or (isinstance(tank, list) and len(tank) == 2 and all(type(v) in (int, float) and math.isfinite(v) for v in tank) and tank[0] <= tank[1]), 'PERSONA_INVALID_TANK_BOUND')
    return out


def _consent(source, asset, kind, prior, protected_rest):
    role = source['role']; policy = source['existing_policy']; permissions = policy.get('permissions', {})
    routine, separate = copy.deepcopy(ACTIONS[kind]); bounds = _bounds(source, asset, kind, prior)
    baseline_dr_disabled = prior.get('present') is True and prior.get('dr_adjustable') is False
    role_auto = role in ('D', 'F')
    auto = role_auto and permissions.get('automatic_within_declared_bounds') is True
    confirm = permissions.get('confirmation_before_action', False) or not role_auto
    if role == 'E':
        mode = 'advice_first_separate_confirmation'
    elif role == 'C' or permissions.get('same_day_reconfirmation'):
        mode = 'same_day_confirmation_revocable'
    elif baseline_dr_disabled:
        mode = 'outside_routine_DR_separate_confirmation'
    elif protected_rest or confirm:
        mode = 'confirm_each_proposal'
    elif auto:
        mode = 'standing_consent_only_with_explicit_bounds'
    else:
        mode = 'confirm_each_proposal'
    # No device capability or numeric scheduling freedom is invented from ownership.
    # A declared target, device capability or role alone is not an action bound.
    schedule_bounded = bounds.get('existing_reschedule_limit_min') is not None
    thermal = bounds.get('existing_thermal_policy', {})
    eligible = []
    if schedule_bounded:
        eligible += [a for a in routine if a.startswith('shift_') or a == 'coordinate_with_wash']
    if kind == 'ac' and all(k in thermal for k in ('usual_setpoint_C', 'temporary_increase_C', 'maximum_change_duration_min')):
        eligible += ['change_cooling_setpoint']
    if kind == 'ac' and bounds['heating_change_numeric_bound'] is not None and thermal.get('maximum_change_duration_min') is not None:
        eligible += ['change_heating_setpoint']
    if kind == 'water_heater' and bounds.get('tank_setpoint_bounds_C') is not None:
        eligible += ['change_tank_setpoint_preserving_draw_service']
    standing = [a for a in routine if a in eligible] if mode == 'standing_consent_only_with_explicit_bounds' else []
    texts = {
        'advice_first_separate_confirmation': '默认只给建议；要改变这台设备的安排，需另行确认。',
        'outside_routine_DR_separate_confirmation': '该设备不在本户已声明的常规响应范围内，改时必须单独询问。',
        'same_day_confirmation_revocable': '按当天安排确认后才调整，并保留撤回选择。',
        'confirm_each_proposal': '每个调整方案先说明并确认，不默认自动执行。',
        'standing_consent_only_with_explicit_bounds': '仅在明确的设备、服务和时间边界内预先同意优化；没有明确边界则先确认。'}
    scope = {'washer': '只涉及完整洗衣改时；换程序、减衣量或取消洗衣不在这项授权内。',
             'dryer': '只涉及完整烘干与洗衣衔接；不能擅自缩短程序。',
             'dishwasher': '只涉及完整洗碗程序改时；不能改成家人临时手洗。',
             'water_heater': '加热改时和储水设温可分别提出；未声明储水设温调整范围时须逐次确认，不能改洗浴时间、水量或出水要求。',
             'ac': '制冷、制热和提前运行分别提出；制冷边界不授权制热变化，未声明的模式或幅度须确认；有人使用时停机另询。',
             'ev': '只涉及原连接期内的充电改时；不能擅自降低目标电量、改出行或反向放电。'}[kind]
    return {'mode': mode, 'holder_member_id': policy.get('holder', {}).get('person_id'),
            'standing_consent_actions': standing, 'proposal_actions': routine,
            'requires_new_explicit_consent': separate + ['change_handler', 'add_manual_operations', 'book_extra_helper'],
            'same_day_reconfirmation': mode == 'same_day_confirmation_revocable', 'notification_required': True,
            'bounds': bounds, 'automatic_execution_claimed': False, 'narrative': texts[mode] + scope,
            'origin': 'EB_role_and_device_flags+existing_consent+experimental_action_scope',
            'proposal_is_not_obtained_consent': True,
            'routine_DR_eligible': not baseline_dr_disabled and role != 'E',
            'EB_device_DR_disabled': baseline_dr_disabled}


def generate_personas(context):
    source = preference_input(context); frozen = digest(source); rules = read(RULES)
    require(rules['source_commit'] == read(HERE / 'ENERGY_PORTRAIT_SOURCES.json')['EB_commit'], 'PERSONA_SOURCE_COMMIT_MISMATCH')
    role = source['role']; require(role in rules['EB_roles'], 'PERSONA_UNKNOWN_ROLE')
    features = _features(source); care = bool(features['care_references'])
    records = []
    core = read(ROLE_RULES)['roles'][role]
    household = household_preferences(source, rules)
    for asset in sorted(source['devices'], key=lambda d: d['asset_id']):
        for kind in sorted(asset['types']):
            require(kind in ACTIONS, 'PERSONA_UNSUPPORTED_DEVICE')
            personal_prior = rules['EB_roles'][role]['appliances'].get(kind, {'present': False})
            inherited = device_preferences(source, household, asset, kind)
            prior = inherited['shared_reference']
            triggers = []
            protected_rest = bool(features['dependent_rest_by_room'].get(asset['room_id']))
            consent = _consent(source, asset, kind, prior, protected_rest)
            consent = apply_member_consent(consent, inherited)
            triggers += ['AUTH_SCOPE', 'AUTH_NEW_HELP']
            facts = asset_facts(source, asset, kind)
            conditions = decision_rules(kind, facts)
            require(all(r['rule_id'] in rules['rule_catalog'] for r in conditions), 'PERSONA_UNDOCUMENTED_CONDITION_RULE')
            # Conditions drive the actual participant text AND machine-readable
            # tradeoffs. The former generic habit is not used to fake diversity.
            habit_rules = {
                'AUTOMATIC_COMBO_CHAIN', 'SAME_ASSET_CHAIN_UNSPECIFIED_HANDLING', 'DRYER_ORIGINAL_UPSTREAM', 'WASHED_NOT_WEARABLE', 'PRESERVE_DISH_RELEASE_AND_DUE', 'DISH_STOCK_UNKNOWN',
                'SEPARATED_WATER_SERVICES', 'CONTIGUOUS_WATER_SERVICES', 'WATER_REQUIREMENTS_PENDING',
                'PROTECT_CHILD_ROOM_REST', 'PROTECT_ROOM_SLEEP', 'PROTECT_ROOM_WORK', 'OCCUPIED_COMMON_ROOM',
                'EV_WORK_AND_OTHER_TRIPS', 'EV_WORK_TRIPS', 'EV_NONCOMMUTE_DECLARED_TRIPS', 'EV_TRAVEL_NOT_BOUND'}
            habit = inherited['habit'] + ''.join(r['preference'] for r in conditions if r['rule_id'] in habit_rules)
            handling = ''.join(r['preference'] for r in conditions if r['rule_id'] not in habit_rules)
            preference = (core['thermal'] if kind == 'ac' else core['device_adjustment']) + inherited['member_preference_text'] + handling
            triggers += [r['rule_id'] for r in conditions]
            records.append({'asset_id': asset['asset_id'], 'kind': kind, 'label': LABELS[kind], 'room_id': asset['room_id'],
                            'room_label': room_label(source, features, asset['room_id']) if kind == 'ac' else None,
                            'habit': habit, 'adjustment_preference': preference, 'handling_preference': handling,
                            'authorization': consent, 'rule_ids': triggers,
                            'inherited_preferences': inherited,
                            'decision_conditions': facts, 'conditional_preferences': conditions,
                            'context_features': {'explicit_care': care, 'child_rest_in_this_room': protected_rest,
                                'qualified_operator_ids_with_declared_windows': [mid for mid, refs in facts['handling_windows_by_operator'].items() if any(r['windows'] for r in refs)]},
                            'sources': {'EB_role': role, 'EB_device_present_in_basic_role': personal_prior.get('present') is True,
                                        'EB_appliance_reference': copy.deepcopy(personal_prior),
                                        'EB_household_reference': household['EB_household_id'],
                                        'EB_shared_appliance_reference': copy.deepcopy(prior),
                                        'habit_and_action_scope': 'EB_shared_reference+explicit_experimental_member_assignment;not_measured_or_inferred_from_A',
                                        'existing_inputs': 'owned device+unchanged calendar+explicit policy',
                                        'device_absent_from_basic_EB_persona_requires_extension': personal_prior.get('present') is not True,
                                        'device_present_in_EB_household_reference': prior.get('present') is True}})
    require(frozen == digest(source), 'PERSONA_INPUT_MUTATED')
    holder_id = source['existing_policy'].get('holder', {}).get('person_id')
    holder = next(({'member_id': m['member_id'], 'member_index': i + 1, 'age_years': m['age_years']}
                   for i, m in enumerate(sorted(source['members'], key=lambda m: m['member_id'])) if m['member_id'] == holder_id), None)
    if holder_id in source['external_operator_ids']:
        holder = {'member_id': holder_id, 'member_index': None, 'age_years': None, 'resident': False}
    profile = {'schema': 'eb.household_device_persona.v4', 'household_id': source['household_id'], 'role': role,
            'role_label_scope': 'given_household_decision_orientation;not_every_member_has_the_same_personality',
            'confirmation_holder': holder,
            'household_preferences': household,
            'attitude': copy.deepcopy(core), 'devices': records, 'context_evidence': features,
            'bindings': {'preference_input_sha256': frozen, 'rules_sha256': sha(RULES), 'code_sha256': sha(Path(__file__)),
                         'conditions_code_sha256': sha(HERE / 'decision_conditions.py'),
                         'household_preferences_code_sha256': household['code_sha256'],
                         'household_preferences_sources_sha256': sha(HOUSEHOLD_SOURCES),
                         'EB_commit': rules['source_commit'], 'calendar_dates': [d['date'] for d in source['days']]},
            'origin': 'declared_experimental_role_play_profile', 'A_or_B_actions_read': False,
            'schedule_or_plan_modified': False, 'acceptance_or_score_generated': False}
    from .joint_sampling import obtain, attach
    return attach(profile, obtain(source, rules))


def from_declared_family(family):
    """Generate at the family stage, before housing/life scheduling or any A."""
    hid = family['household_id']; life = family['life']; facts = family['facts']
    members = [copy.deepcopy(m) for m in facts['members'] if m['household_id'] == hid]
    mids = {m['member_id'] for m in members}
    def room(key, mid):
        return '$sleep:' + mid if key == '$sleep' else key
    devices = [{'asset_id': d['asset_id'], 'types': [d['kind']], 'room_id': d.get('room')}
               for d in family['world']['devices'] if hid in d['using_household_ids']]
    days = []; date = dt.date.fromisoformat(life['anchor']); end = dt.date.fromisoformat(life['end_exclusive'])
    while date < end:
        calendars = {}
        for mid in sorted(mids):
            template = life['member_calendars'][mid]
            cal = template.get('date_overrides', {}).get(str(date), template['weekend' if date.weekday() >= 5 else 'weekday'])
            calendars[mid] = [{**copy.deepcopy(e), 'room_id': room(e.get('room'), mid)} for e in cal]
        days.append({'date': str(date), 'calendars': calendars}); date += dt.timedelta(days=1)
    settings = {}
    for field in ('program_policies', 'thermostat_policies'):
        for p in life.get(field, []):
            settings.setdefault(p['asset_id'], {}).setdefault(field, []).append(copy.deepcopy(p))
    tank = life.get('tank_policy', {})
    if tank:
        settings.setdefault(tank['asset_id'], {})['tank_policy'] = copy.deepcopy(tank)
    return generate_personas({'household_id': hid, 'role': family['archetype'], 'members': members,
                              'devices': devices, 'existing_policy': {'holder': {'person_id': facts['decision_maker_id']}},
                              'energy_preferences': copy.deepcopy(family.get('energy_preferences', {})),
                              'asset_authority': {'assets': {d['asset_id']: {'authorized_operator_ids': sorted(m['member_id'] for m in family['world']['members']
                                  if m['member_id'] in mids and d['asset_id'] in m.get('can_operate_asset_ids', []))} for d in devices}},
                              'declared_device_settings': settings, 'days': days})


def render_family(profile, brief=False):
    if 'joint_sampling' in profile:
        from .joint_sampling import render
        return render(profile)
    f = profile['context_evidence']; role = profile['role']; devices = profile['devices']
    adult_ages = '、'.join(str(a) for a in f['member_ages_years'] if a >= 18)
    child_ages = '、'.join(str(a) for a in f['member_ages_years'] if a < 18)
    heading = f"家庭资料（本研究角色设定）：{f['adult_count']}位成人（{adult_ages}岁）" + (f"、{f['minor_count']}位未成年成员（{child_ages}岁）" if f['minor_count'] else '') + '。'
    core = profile['attitude']['priority']
    if brief:
        if 'household_preferences' in profile:
            return render_household_brief(profile, heading)
        core = {'A': '关注电费，但要说明节省、保证生活可靠。',
                'B': '舒适和原有生活节奏优先，不愿为小额节省明显受扰。',
                'C': '重视自主决定，作息变化后要当天确认、可撤回。',
                'D': '积极配合节能和电网响应，必要服务仍须完成。',
                'E': '照护、热水和生活稳定优先，默认只听建议。',
                'F': '愿意优化电价和充电，先保证原出行目标电量。'}[role]
        texts = []
        for kind in ('washer', 'dryer', 'dishwasher', 'water_heater', 'ac', 'ev'):
            rows = [d for d in devices if d['kind'] == kind]
            if not rows: continue
            if kind == 'dryer' and all(d['decision_conditions']['automatic_combo_explicitly_declared'] for d in rows): continue
            # Deduplicate identical statements, never replace a condition with a
            # generic inventory-based summary in the participant-facing brief.
            sentences = list(dict.fromkeys((d['room_label'] + '：' if kind == 'ac' else '') + d['habit'] for d in rows))
            if kind in ('washer', 'dryer', 'dishwasher'):
                sentences += list(dict.fromkeys(r['preference'] for d in rows for r in d['conditional_preferences']
                    if r['rule_id'] in ('KEEP_HANDLER_AVOID_CARE_TRANSFER', 'PROTECT_HANDLER_CARE',
                                        'SINGLE_HANDLER_COORDINATION', 'NO_UNAGREED_HANDOFF', 'HANDLER_UNKNOWN')))
            if kind == 'water_heater':
                sentences += list(dict.fromkeys(r['preference'] for d in rows for r in d['conditional_preferences'] if r['rule_id'] == 'PROTECT_ASSISTED_BATH'))
            if kind == 'ev':
                sentences += list(dict.fromkeys(r['preference'] for d in rows for r in d['conditional_preferences'] if r['rule_id'] == 'EV_TARGET_NOT_MINIMUM'))
            label = '洗烘' if kind == 'washer' and all(d['decision_conditions']['automatic_combo_explicitly_declared'] for d in rows) else LABELS[kind]
            texts.append(label + '：' + ''.join(dict.fromkeys(sentences)))
        modes = {d['authorization']['mode'] for d in devices}
        if 'same_day_confirmation_revocable' in modes:
            texts.append('调整前按当天安排再次确认，可以撤回。')
        elif 'standing_consent_only_with_explicit_bounds' in modes:
            texts.append('仅对登记了明确边界的设备预先同意优化，其他改动仍须确认；设备支持不等于已经授权。')
        elif role == 'E':
            texts.append('默认只听建议，改变设备安排须另行确认。')
        else:
            holder = profile['confirmation_holder']
            whom = '成员' + str(holder['member_index']) if holder and holder['member_index'] is not None else '登记决策人'
            texts.append('每个方案由' + whom + '先确认，不默认自动执行。')
        modes_without_bounds = []
        if any(d['kind'] == 'water_heater' and d['authorization']['bounds'].get('tank_setpoint_bounds_C') is None for d in devices): modes_without_bounds.append('储水设温')
        if any(d['kind'] == 'ac' and d['authorization']['bounds'].get('heating_change_numeric_bound') is None for d in devices): modes_without_bounds.append('冬季制热')
        if modes_without_bounds: texts.append('和'.join(modes_without_bounds) + '没有明确预授权幅度，须单独说明并确认。')
        texts.append('换人或加人工操作另行商量。')
        return heading + core + '\n\n' + '\n'.join(texts) + '\n'
    holder = profile['confirmation_holder']
    holder_text = ('登记决策人：原已声明的非同住确认人；不作为新增同住成员。' if holder and holder.get('resident') is False else
                   f"登记决策人：成员{holder['member_index']}（{holder['age_years']}岁）。" if holder else '未登记具体确认人，不能据此声称已有人授权。')
    lines = [heading, holder_text, core, profile['attitude']['grid_attitude'], '']
    for d in devices:
        name = d['label'] + ('：' + d['room_label'] if d['kind'] == 'ac' else '')
        lines += [name + '：', '使用习惯：' + d['habit'], '调整偏好：' + d['adjustment_preference'],
                  '授权：' + d['authorization']['narrative'], '']
        bounds = d['authorization']['bounds']
        if bounds.get('existing_reschedule_limit_min') is not None:
            lines.insert(-1, '原已声明的移时范围：前后' + str(bounds['existing_reschedule_limit_min']) + '分钟；超过须另行说明并确认，不等于范围内已经接受。')
        if d['kind'] == 'ac':
            t = bounds['existing_thermal_policy']
            if all(k in t for k in ('usual_setpoint_C', 'temporary_increase_C', 'maximum_change_duration_min')):
                lines.insert(-1, f"原项目制冷控制声明：常用{t['usual_setpoint_C']:g}℃，临时提高至多{t['temporary_increase_C']:g}℃、持续至多{t['maximum_change_duration_min']:g}分钟；这是控制范围，与上面的舒适偏好分开。")
    lines.append('上述设备调整不包含临时换人、增加人工操作或预约额外帮手；这些需要另行协商。')
    return '\n'.join(lines) + '\n'


def render_household_brief(profile, heading):
    """Compact participant material retains device-level preference AND consent."""
    member_numbers = {m['member_id']: i + 1 for i, m in enumerate(profile['household_preferences']['member_profiles'])}
    holder = profile['confirmation_holder']
    owner = '成员' + str(holder['member_index']) if holder and holder.get('member_index') else '登记决策人'
    counts = {kind: sum(d['kind'] == kind for d in profile['devices']) for kind in LABELS}
    inventory = '、'.join(f"{count}项{LABELS[kind]}" for kind, count in counts.items() if count)
    lines = [heading, '设备服务：' + inventory + '；同一洗烘资产保留为一台设备。',
             profile['attitude']['priority'], '由' + owner + '负责家庭方案确认；机器可调不等于全家已经接受。']
    thermal = next((d['authorization']['bounds'].get('existing_thermal_policy', {}) for d in profile['devices'] if d['kind'] == 'ac'), {})
    if all(k in thermal for k in ('usual_setpoint_C', 'temporary_increase_C', 'maximum_change_duration_min')):
        lines.append(f"原制冷控制声明：常用{thermal['usual_setpoint_C']:g}℃，临时提高至多{thermal['temporary_increase_C']:g}℃、持续至多{thermal['maximum_change_duration_min']:g}分钟；控制边界与舒适偏好及本次是否同意分开。")
    for kind in ('washer', 'dryer', 'dishwasher', 'water_heater', 'ac', 'ev'):
        devices = [d for d in profile['devices'] if d['kind'] == kind]
        if not devices: continue
        # Room-specific AC preferences are retained, not counted as new people
        # or collapsed into a single least/most permissive household average.
        for d in devices:
            ref = d['inherited_preferences']['shared_reference']
            label = d['label'] + ('（' + d['room_label'] + '）' if kind == 'ac' else '')
            if kind in ('washer', 'dryer', 'dishwasher'):
                habit = '习惯保留完整程序；时间偏好是在条件允许时约' + d['inherited_preferences']['preferred_start_text'] + '安排，并非以往固定在此时运行。'
                if kind == 'dryer' and d['decision_conditions']['automatic_combo_explicitly_declared']:
                    habit = '原洗烘一体机洗完后按原程序连续烘干，不另加人工转移；EB参考时刻不是独立启动要求。'
            elif kind == 'ac':
                habit = f"家庭制冷偏好{ref['setpoint_preferred_min_c']:g}—{ref['setpoint_preferred_max_c']:g}℃。"
            elif kind == 'water_heater': habit = '习惯提前备水，保护原来每一段洗浴，不移动洗澡时间。'
            else: habit = d['inherited_preferences']['habit']
            affected = d['inherited_preferences']['member_preference_text']
            auth = d['authorization']; blockers = auth['member_confirmation_required_ids']
            if auth['standing_consent_actions']:
                consent = '授权：仅登记边界内的' + ('充电改时' if kind == 'ev' else '相应设备调整') + '可自动安排，越界及增加人工操作另询。'
            elif blockers:
                consent = '授权：涉及成员' + '、'.join(str(member_numbers[m]) for m in blockers) + '的使用或操作改变先确认，不默认自动执行。'
            else: consent = '授权：由' + owner + '先确认；未声明的动作范围不算已授权。'
            lines.append(label + '：' + habit + affected + consent)
    lines.append('以上习惯时刻是偏好，不是新期限；储水设温、冬季制热、换人和新增操作没有因此获得额外授权。未成年成员的需要由原登记成人协调，不因此取得设备操作权。')
    lines.append('来源：家庭成员、设备和日程沿用原资料；共享习惯与成员角色参照EB；成员角色分配及共同确认规则属于本研究实验设定，并非对真人的测量。')
    return '\n\n'.join(lines) + '\n'
