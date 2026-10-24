"""EB household-first preference inheritance; experimental member allocation.

Never infer a real person's psychology from age, sex, availability, or plan A.
Calendar predicates select declared benchmark scenarios, not empirical traits.
Physical assets and dated service contracts always remain the original inputs.
"""
import copy

from .core import HERE, digest, read, require, sha

SOURCES = HERE / 'EB_HOUSEHOLD_PREFERENCE_SOURCES.json'
VERSION = 'household-preferences-v4'
HOME_WORK = {'home_work'}
STUDY = {'school', 'school_home_study'}
CARE = {'care', 'caregiving', 'childcare_supervision', 'child_bathing_assistance'}
S1 = 'household_s1_dual_commuter_standard'
S2 = 'household_s2_multigeneration_caregiver'
S3 = 'household_s3_hybrid_work_from_home'
S4 = 'household_s4_ev_commuter_flexible'
S5 = 'household_s5_shared_roommates_irregular'


def clock(hour):
    minute = round(hour * 60)
    return f'{minute // 60:02d}:{minute % 60:02d}'


def household_preferences(source, role_rules):
    library = read(SOURCES)
    require(library['EB_commit'] == role_rules['source_commit'], 'HOUSEHOLD_PREFERENCE_SOURCE_MISMATCH')
    before = digest(source)
    members = sorted(source['members'], key=lambda m: m['member_id'])
    mids = {m['member_id'] for m in members}
    activities = {mid: {e['activity'] for day in source['days'] for e in day['calendars'][mid]} for mid in mids}
    matching_events = [{'member_id': mid, 'date': day['date'],
                        **{k: e[k] for k in ('activity', 'start_min', 'end_min') if k in e}}
                       for day in source['days'] for mid in sorted(mids) for e in day['calendars'][mid]
                       if e['activity'] in CARE | HOME_WORK | STUDY]
    holder = source['existing_policy'].get('holder', {}).get('person_id')
    declaration = source.get('energy_preferences', {})
    require(isinstance(declaration, dict), 'INVALID_ENERGY_PREFERENCE_DECLARATION')
    joint = declaration.get('preference_sampling') is not None
    # This rule order is an explicit experimental design. It is not a learned
    # distribution, and does not transfer the original household's demographics.
    if declaration.get('EB_household_id'):
        selected, trigger = declaration['EB_household_id'], 'explicit_household_reference'
    elif any(a & CARE for a in activities.values()):
        selected, trigger = S2, 'declared_care_scenario'
    elif any(a & HOME_WORK for a in activities.values()):
        selected, trigger = S3, 'declared_home_work_scenario'
    elif source['role'] == 'C':
        selected, trigger = S5, 'given_autonomy_role_scenario'
    elif source['role'] == 'F' and any('ev' in d['types'] for d in source['devices']):
        selected, trigger = S4, 'given_EV_role_scenario'
    else:
        selected, trigger = S1, 'shared_routines_reference_fallback'
    require(selected in library['households'], 'UNKNOWN_EB_HOUSEHOLD_REFERENCE')
    shared = copy.deepcopy(library['households'][selected])
    # Real declared overrides are field-checked; no silent replacement of the
    # whole household with a personal role's absent appliance example.
    overrides = declaration.get('shared_appliances', {})
    require(isinstance(overrides, dict), 'INVALID_SHARED_PREFERENCE_OVERRIDES')
    owned = {k for d in source['devices'] for k in d['types']}
    allowed = {'preferred_h', 'earliest_h', 'latest_h', 'duration_h', 'dr_adjustable',
               'shiftable', 'setpoint_preferred_min_c', 'setpoint_preferred_max_c',
               'temp_tolerance_c', 'pre_heat_window_start_h', 'pre_heat_window_end_h'}
    for kind, fields in overrides.items():
        require(kind in owned and isinstance(fields, dict) and set(fields) <= allowed,
                'INVALID_SHARED_PREFERENCE_OVERRIDE_FIELD')
        for key, value in fields.items():
            if key in ('dr_adjustable', 'shiftable'):
                require(type(value) is bool, 'INVALID_SHARED_PREFERENCE_BOOLEAN')
            else:
                require(type(value) in (int, float) and 0 <= value <= (24 if key.endswith('_h') else 100),
                        'INVALID_SHARED_PREFERENCE_NUMBER')
        shared['appliances'].setdefault(kind, {}).update(copy.deepcopy(fields))

    # F variants reuse whole EB member profiles, never independently sampled
    # temperatures, consent flags and task attitudes. Existing declarations win.
    # Other classes retain their six-class core unless explicitly overridden.
    explicit = declaration.get('member_personas', {})
    require(isinstance(explicit, dict) and set(explicit) <= mids, 'UNKNOWN_MEMBER_PREFERENCE_OWNER')
    basics = {r: path['source_path'].rsplit('/', 1)[-1][:-5] for r, path in role_rules['EB_roles'].items()}
    household_operators = {v.get('registered_operator_id') for aid, v in source.get('asset_authority', {}).get('assets', {}).items()
                           if any(d['asset_id'] == aid and set(d['types']) & {'washer', 'dryer', 'dishwasher'} for d in source['devices'])}
    rows = []
    for member in members:
        mid = member['member_id']; persona = basics[source['role']]
        reason = 'household_core_inherited;individual_preference_not_measured'
        origin = 'experimental_household_core_inheritance'
        if mid in explicit:
            persona, reason, origin = explicit[mid], 'explicit_member_preference_declaration', 'explicit_experimental_declaration'
            require(not joint or persona == basics[source['role']], 'JOINT_MEMBER_CANNOT_CHANGE_HOUSEHOLD_CLASS')
        elif mid == holder:
            reason = 'given_household_decision_role'
        elif joint:
            reason = 'fixed_household_core;within_class_joint_residual_pending'
            origin = 'experimental_within_class_only;not_calendar_psychology'
        elif source['role'] == 'F' and selected == S3:
            if activities[mid] & HOME_WORK:
                persona, reason = basics['B'], 'F_HOME_WORK_JOINT_PROFILE:home_worker'
            elif activities[mid] & STUDY:
                persona, reason = 'atom_task_rigid', 'F_HOME_WORK_JOINT_PROFILE:fixed_study_member'
            else:
                persona, reason = 'atom_control_auto', 'F_HOME_WORK_JOINT_PROFILE:other_member'
            origin = 'experimental_joint_role_assignment;not_psychology_inferred_from_calendar'
        elif source['role'] == 'F' and selected == S4:
            persona = basics['D'] if mid in household_operators else 'atom_price_indifferent'
            reason = 'F_FLEXIBLE_JOINT_PROFILE:' + ('shared_task_operator' if mid in household_operators else 'convenience_member')
            origin = 'experimental_joint_role_assignment;not_psychology_inferred_from_calendar'
        elif source['role'] == 'B':
            if activities[mid] & STUDY:
                persona, reason = 'atom_task_rigid', 'B_COMFORT_JOINT_PROFILE:fixed_study_member'
            elif mid in household_operators:
                persona, reason = basics['D'], 'B_COMFORT_JOINT_PROFILE:flexible_shared_task_operator'
            else:
                persona, reason = 'atom_price_indifferent', 'B_COMFORT_JOINT_PROFILE:convenience_member'
            origin = 'experimental_joint_role_assignment;not_psychology_inferred_from_calendar'
        require(persona in library['personas'], 'UNKNOWN_EB_MEMBER_PERSONA')
        ref = library['personas'][persona]
        # Copy the joint ENERGY preference facet, not the original role's
        # commuter/WFH schedule, demographic identity or physical ownership.
        energy_tags = {k: copy.deepcopy(ref['tags'][k]) for k in ('comfort', 'task', 'price', 'control', 'grid_value') if k in ref['tags']}
        rows.append({'member_id': mid, 'persona_id': persona, 'tags': energy_tags,
                     'appliances': copy.deepcopy(ref['appliances']), 'source_path': ref['source_path'],
                     'appliance_fields_are_preference_references_not_personal_ownership': True,
                     'assignment_rule': reason, 'assignment_origin': origin,
                     'assignment_evidence': {'given_household_role': source['role'], 'is_registered_holder': mid == holder,
                         'registered_shared_task_operator': mid in household_operators,
                         'calendar_activity_evidence': [e for e in matching_events if e['member_id'] == mid]},
                     'source_sha256': ref['source_sha256']})
    require(before == digest(source), 'HOUSEHOLD_PREFERENCE_INPUT_MUTATED')
    return {'version': VERSION, 'EB_household_id': selected, 'selection_trigger': trigger,
            'selection_origin': 'declared_experimental_scenario_matching;not_observed_household_identity',
            'shared_appliances': shared['appliances'], 'shared_source_path': shared['source_path'],
            'shared_original_source_sha256': shared['source_sha256'], 'selection_evidence': matching_events,
            'explicit_shared_override_kinds': sorted(overrides), 'member_profiles': rows,
            'source_sha256': sha(SOURCES), 'code_sha256': sha(HERE / 'household_preferences.py'),
            'physical_inventory_replaced': False, 'demographics_or_calendars_replaced': False,
            'individual_human_preferences_observed': False,
            'original_household_members_copied': False,
            'source_numeric_windows_are_soft_references': True}


def device_preferences(source, family, asset, kind):
    prior = copy.deepcopy(family['shared_appliances'].get(kind, {}))
    rows = {m['member_id']: m for m in family['member_profiles']}
    authority = source.get('asset_authority', {}).get('assets', {}).get(asset['asset_id'], {})
    primary = authority.get('registered_operator_id')
    holder = source['existing_policy'].get('holder', {}).get('person_id')
    if kind == 'ac':
        affected = {mid for day in source['days'] for mid, events in day['calendars'].items()
                    if any(e.get('location') == 'home' and e.get('room_id') == asset['room_id'] for e in events)}
    elif kind in ('water_heater', 'ev'):
        affected = {n['requester'] for n in source['declared_service_contracts']
                    if n['asset_id'] == asset['asset_id'] and n['kind'] == kind and n.get('requester') in rows}
        if not affected and primary in rows:
            affected.add(primary)
    else:
        affected = {primary} if primary in rows else set()
    members = [copy.deepcopy(rows[mid]) for mid in sorted(affected)]
    dependents = {m['member_id'] for m in source['members'] if m['age_years'] < 18}
    missing_operator = kind in ('washer', 'dryer', 'dishwasher') and primary not in rows
    descriptions = []
    for m in members:
        short = '成员' + str(sorted(rows).index(m['member_id']) + 1)
        tags = m['tags']; texts = []
        if tags.get('control') in ('confirm_required', 'suggestion_first', 'low_auto_accept'):
            texts.append('改变其使用或操作安排前先询问')
        if tags.get('task') == 'rigid': texts.append('不愿为小额节省改变固定任务习惯')
        if tags.get('task') == 'flexible': texts.append('只要任务完整且不增加操作，可以协商机器改时')
        if tags.get('price') == 'low_incentive': texts.append('小额节省不足以抵消额外麻烦')
        if tags.get('control') == 'high_trust_auto': texts.append('支持已约定边界内自动优化')
        ac = m['appliances'].get('ac', {})
        if kind == 'ac' and ac.get('present'):
            texts.append(f"制冷偏好{ac['setpoint_preferred_min_c']:g}—{ac['setpoint_preferred_max_c']:g}℃")
        if texts: descriptions.append(short + '：' + '，'.join(texts) + '。')
    # Preferences are not permissions. A service's current date/quantity/target
    # has precedence over the EB scenario's illustrative bath time or EV target.
    preferred_start_text, habit_clock_origin = None, None
    if kind in ('washer', 'dryer', 'dishwasher') and 'preferred_h' in prior:
        preferred_start_text, habit_clock_origin = clock(prior['preferred_h']), 'EB_household_soft_reference'
        declared = source['declared_device_settings'].get(asset['asset_id'], {}).get('program_policies', [])
        starts = {period: minute for p in declared if p.get('kind') == kind
                  for period, minute in p.get('preferred_start_min', {}).items()}
        if starts:
            preferred_start_text = '、'.join(('工作日' if period == 'weekday' else '周末' if period == 'weekend' else period) + clock(minute / 60)
                                           for period, minute in sorted(starts.items()))
            habit_clock_origin = 'original_declared_program_policy'
        window = ''
        if 'earliest_h' in prior and 'latest_h' in prior:
            end = ('次日' if prior['latest_h'] <= prior['earliest_h'] else '') + clock(prior['latest_h'])
            window = f"参考运行窗口{clock(prior['earliest_h'])}至{end}（末端指完成）。"
        habit = f"习惯保留完整{dict(washer='洗衣',dryer='烘干',dishwasher='洗碗')[kind]}程序；本实验的共享时间偏好是条件允许时约{preferred_start_text}安排。" + window + '这是软偏好，不是当天A的实际时间，也不新增完成期限。'
        if kind == 'dryer': habit += '该参考时刻不表示与洗衣必属同批；若原需求已绑定同批，仍须洗完再烘。'
    elif kind == 'ac':
        habit = f"家庭共享制冷偏好为{prior['setpoint_preferred_min_c']:g}—{prior['setpoint_preferred_max_c']:g}℃；同时保留实际使用成员的个人偏好，不平均掉较敏感成员的意见。"
    elif kind == 'water_heater':
        habit = '习惯提前备好热水，不以推迟洗浴换取节省。'
        if 'pre_heat_window_start_h' in prior:
            habit += f"EB参考预热窗口{clock(prior['pre_heat_window_start_h'])}—{clock(prior['pre_heat_window_end_h'])}，本户仍按原有各段用水需求准备，不把它改成新洗浴时间。"
    else:
        targets = sorted({n['required_departure_soc'] for n in source['declared_service_contracts']
                          if n['asset_id'] == asset['asset_id'] and n.get('required_departure_soc') is not None})
        habit = '习惯按下一次出行备足电；是否交给系统择时另按本户授权，原连接期和出行安排不变。'
        if targets: habit += '本户原目标电量' + '、'.join(f'{100*v:g}%' for v in targets) + '保持不变，不替换成EB示例值。'
    return {'shared_reference': prior, 'habit': habit, 'member_preference_text': ''.join(descriptions),
            'affected_member_profiles': members, 'registered_operator_unknown': missing_operator,
            'dependent_preference_member_ids': sorted(affected & dependents),
            'preferred_start_text': preferred_start_text, 'habit_clock_origin': habit_clock_origin,
            'origin': 'EB_shared_values+experimental_scenario_and_member_assignment',
            'hard_service_contracts_changed': False}


def apply_member_consent(consent, preferences):
    result = copy.deepcopy(consent)
    blockers = [m['member_id'] for m in preferences['affected_member_profiles']
                if m['tags'].get('control') != 'high_trust_auto' or m['tags'].get('task') == 'rigid']
    result['affected_member_ids'] = [m['member_id'] for m in preferences['affected_member_profiles']]
    result['member_confirmation_required_ids'] = blockers
    result['dependent_preference_member_ids'] = preferences['dependent_preference_member_ids']
    result['dependent_views_do_not_grant_device_control'] = True
    result['member_gate_origin'] = 'experimental_consensus_rule;not_new_real_user_consent'
    result['shared_machine_eligibility_is_not_member_acceptance'] = True
    if result['standing_consent_actions'] and (blockers or preferences['registered_operator_unknown']):
        result['mode'] = 'affected_member_confirmation'
        result['standing_consent_actions'] = []
        scope = result['narrative'].split('没有明确边界则先确认。', 1)[-1]
        result['narrative'] = ('家庭总体预授权仍保留，但涉及这台设备的成员偏好或操作人尚未确认；本研究方案先向相关成员说明并确认。' + scope)
    return result
