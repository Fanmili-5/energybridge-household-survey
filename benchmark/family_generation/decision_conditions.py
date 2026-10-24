"""Observable conditions and declared service contracts, never A/B actions.

These are inputs to project-authored conditional role-play preferences, NOT a
psychological estimator. Missing rights, schedules or bounds remain unknown.
"""
import copy

CARE = {'care', 'caregiving', 'childcare_supervision', 'child_bathing_assistance'}
REST = {'sleep', 'sleep_rest', 'nap', 'day_nap'}
WORK = {'work', 'school', 'work_or_school', 'home_work'}
CONTRACT_FIELDS = ('need_id', 'asset_id', 'kind', 'requester', 'quantity', 'unit',
    'release_min', 'deadline_min', 'delivery_deadline_min', 'duration_min',
    'maximum_retrieval_wait_min', 'maximum_preload_wait_min', 'timer_allowed', 'machine_windows_min', 'loading_required',
    'upstream_need_id', 'batch_id', 'wash_only_delivery', 'connection_start_min',
    'departure_min', 'required_departure_soc', 'target_C', 'temperature_band_C',
    'reference_cooling_setpoint_C', 'reference_heating_setpoint_C',
    'constraint_origin', 'source_or_design_rule', 'service_purpose')
JOURNEY_FIELDS = ('departure_min', 'arrival_min', 'driver_id', 'handling_operator_id',
                  'purpose', 'traction_kWh', 'source')


def contract_input(need, date):
    """Exclude scheduler decisions (load/unload/wait/start), A and all results."""
    result = {k: copy.deepcopy(need[k]) for k in CONTRACT_FIELDS if k in need}
    result['source_date'] = date
    if need.get('journey'):
        result['journey'] = {k: copy.deepcopy(need['journey'][k]) for k in JOURNEY_FIELDS if k in need['journey']}
    return result


def asset_facts(source, asset, kind):
    aid = asset['asset_id']; mids = {m['member_id'] for m in source['members']} | set(source.get('external_operator_ids', []))
    rights = source.get('asset_authority', {}).get('assets', {}).get(aid, {})
    operators = sorted(set(rights.get('authorized_operator_ids', [])) & mids)
    primary = rights.get('registered_operator_id')
    if primary not in operators:
        primary = None
    refs = {mid: [] for mid in operators}; care = {}; work = {}; sleep = {}
    for mid in operators:
        # Visit windows do not reveal an external helper's outside commitments.
        care[mid] = work[mid] = sleep[mid] = None if mid in source.get('external_operator_ids', []) else 0
        for day in source['days']:
            refs[mid].append({'date': day['date'], 'windows': day['operator_windows'][mid]})
            for e in day['calendars'].get(mid, []):
                length = e['end_min'] - e['start_min']
                care[mid] += length if e['activity'] in CARE else 0
                work[mid] += length if e['activity'] in WORK else 0
                sleep[mid] += length if e['activity'] in REST else 0
    room_uses = [dict(date=day['date'], member_id=mid, **e)
                 for day in source['days'] for mid, cal in day['calendars'].items()
                 for e in cal if e.get('room_id') == asset.get('room_id') and e.get('location') == 'home'] if asset.get('room_id') is not None else []
    children = {m['member_id'] for m in source['members'] if m['age_years'] < 18}
    contracts = [copy.deepcopy(n) for n in source.get('declared_service_contracts', [])
                 if n['asset_id'] == aid and n['kind'] == kind]
    all_asset_contracts = [n for n in source.get('declared_service_contracts', []) if n['asset_id'] == aid]
    settings = source['declared_device_settings'].get(aid, {})
    policies = [p for p in settings.get('program_policies', []) if p['kind'] == kind]
    waits = sorted({n['maximum_retrieval_wait_min'] for n in contracts if 'maximum_retrieval_wait_min' in n} |
                   {p['maximum_retrieval_wait_min'] for p in policies if 'maximum_retrieval_wait_min' in p})
    timer = sorted({n['timer_allowed'] for n in contracts if 'timer_allowed' in n} |
                   {p['timer_allowed'] for p in policies if 'timer_allowed' in p})
    # Contiguous/overlapping demand intervals are determined by declared needs,
    # not by an arbitrary "close enough" time threshold.
    water_groups = []
    for date in sorted({n['source_date'] for n in contracts}):
        groups = []
        for n in sorted((n for n in contracts if n['source_date'] == date), key=lambda n: n['release_min']):
            lo, hi = n['release_min'], n['deadline_min']
            if groups and lo <= groups[-1][1]: groups[-1][1] = max(groups[-1][1], hi)
            else: groups.append([lo, hi])
        water_groups.append({'date': date, 'groups': groups})
    reasons = []
    if not operators: reasons.append('operator_rights_unknown')
    else:
        reasons.append('single_qualified_handler' if len(operators) == 1 else 'multiple_qualified_handlers_not_assigned_substitutes')
        if primary: reasons.append('registered_operator_known')
        if primary and care[primary]: reasons.append('registered_operator_has_care_commitments')
        if any(care[m] for m in operators if m != primary): reasons.append('other_qualified_handler_has_care_commitments')
        if any(work.values()): reasons.append('qualified_handlers_have_work_commitments')
        shapes = [tuple(tuple(w) for w in r['windows']) for mid in operators for r in refs[mid]]
        if not any(shapes): reasons.append('no_declared_handling_windows')
        elif any(len(s) > 1 for s in shapes): reasons.append('handling_windows_separated_by_commitments')
        if primary and care[primary] is not None and any(care[m] is not None and care[m] > care[primary] for m in operators if m != primary):
            reasons.append('substitute_has_more_recorded_care_than_registered_operator')
        if set(operators) & set(source.get('external_operator_ids', [])): reasons.append('declared_external_operator_visits')
    room_modes = sorted({('child_rest' if e['member_id'] in children else 'adult_rest') if e['activity'] in REST
                         else 'work' if e['activity'] in WORK else 'care' if e['activity'] in CARE else 'ordinary_use' for e in room_uses})
    trip_kinds = sorted({'work_aligned' if 'work-aligned' in n.get('journey', {}).get('purpose', '') else 'declared_other_trip'
                        for n in contracts if n.get('journey')})
    assisted = [dict(date=day['date'], member_id=mid, **e) for day in source['days']
                for mid, cal in day['calendars'].items() for e in cal if e['activity'] == 'child_bathing_assistance'
                and any(n['source_date'] == day['date'] and n.get('requester') in children
                        and max(e['start_min'], n['release_min']) < min(e['end_min'], n['deadline_min']) for n in contracts)] if kind == 'water_heater' else []
    return {'authorized_operator_ids': operators, 'registered_operator_id': primary,
            'registered_operator_is_not_case_assignment_or_exclusive_right': True,
            'handling_windows_by_operator': refs, 'care_minutes_by_operator': care,
            'work_minutes_by_operator': work, 'sleep_minutes_by_operator': sleep,
            'handling_conditions': reasons, 'room_use_modes': room_modes, 'room_use_references': room_uses,
            'service_contracts': contracts, 'service_contracts_status': 'declared' if contracts else 'not_yet_bound',
            'retrieval_wait_limits_min': waits, 'timer_allowed_values': timer,
            'same_asset_wash_dry_chain': kind in ('washer', 'dryer') and ('washer' in asset['types'] and 'dryer' in asset['types']),
            'automatic_combo_explicitly_declared': any(n.get('wash_only_delivery') == 'auto combo wash then dry' for n in all_asset_contracts),
            'declared_upstream_links': sorted({n['upstream_need_id'] for n in all_asset_contracts if n.get('upstream_need_id')}),
            'water_demand_groups': water_groups if kind == 'water_heater' else [],
            'assisted_bath_references': assisted,
            'journey_purposes': trip_kinds, 'source': 'unchanged_declarations;not_inferred_from_A_or_B'}


def decision_rules(kind, facts):
    """Executable, inspectable preference guards; same conditions may repeat.

    No scalar willingness, acceptance threshold or numerical preference is
    invented. Exact service bounds remain declared inputs, separate from EB.
    """
    rows = []
    def add(code, trigger, text, evidence):
        rows.append({'rule_id': code, 'trigger': trigger, 'preference': text,
                     'evidence_fields': evidence, 'origin': 'conditional_experimental_setting',
                     'strength': 'stated_tradeoff;not_acceptance_label_or_new_hard_A_constraint'})
    cond = facts['handling_conditions']
    if kind in ('washer', 'dryer', 'dishwasher'):
        if 'declared_external_operator_visits' in cond:
            add('EXISTING_VISIT_WINDOWS_ONLY', 'declared_external_operator_visits', '原有非同住支持者只按已声明的到访窗口操作，不把其当作随时在家的家人，也不临时增加到访。', ['authorized_operator_ids', 'handling_windows_by_operator'])
        if not facts['authorized_operator_ids']:
            add('HANDLER_UNKNOWN', 'operator_rights_unknown', '未声明逐设备操作人，不能把任一成人空闲当成有人会来装取。', ['authorized_operator_ids'])
        elif 'substitute_has_more_recorded_care_than_registered_operator' in cond:
            add('KEEP_HANDLER_AVOID_CARE_TRANSFER', 'substitute_has_more_recorded_care_than_registered_operator',
                '改时仍衔接每项任务原已约定的装取人员；家中照护较重的成员即使有操作资格，也不默认被换来代接。', ['registered_operator_id', 'care_minutes_by_operator'])
        elif 'registered_operator_has_care_commitments' in cond:
            add('PROTECT_HANDLER_CARE', 'registered_operator_has_care_commitments', '改时先避开原操作人的照护安排，不以临时中断照护换节省。', ['care_minutes_by_operator'])
        elif 'single_qualified_handler' in cond:
            add('SINGLE_HANDLER_COORDINATION', 'single_qualified_handler', '装入和取出都要衔接这位操作人的原可用时段，不能假定另一人会接手。', ['authorized_operator_ids'])
        else:
            add('NO_UNAGREED_HANDOFF', 'multiple_or_unknown_registered_assignment', '可以商量改时，但有操作资格不等于已答应代劳；原装取人员不默认更换。', ['authorized_operator_ids'])
        if 'handling_windows_separated_by_commitments' in cond:
            add('FIT_BOTH_HANDLING_WINDOWS', 'handling_windows_separated_by_commitments', '即使允许机器预约运行，装取仍要分别落在原人员清醒且有空的窗口；不愿半夜被叫醒。', ['handling_windows_by_operator'])
        if facts['retrieval_wait_limits_min']:
            limits = '、'.join(str(v) for v in facts['retrieval_wait_limits_min'])
            add('KEEP_RETRIEVAL_CONTRACT', 'declared_retrieval_wait_limit', '相比只移动开机，更在意保留原取出等待上限（本批声明为' + limits + '分钟）；不能把取出无限后延。', ['retrieval_wait_limits_min'])
        if 'no_declared_handling_windows' in cond:
            add('NO_DECLARED_HANDLING_WINDOW', 'no_declared_handling_windows', '没有声明可用装取窗口，不能说可以随时移时；先明确谁能操作。', ['handling_windows_by_operator'])
        if facts['timer_allowed_values'] == [False]:
            add('NO_ASSUMED_TIMER', 'timer_not_declared_allowed', '没有允许预约启动的声明，改开机时间要说明谁在场，不能默认远程启动。', ['timer_allowed_values'])
    if kind in ('washer', 'dryer'):
        if facts['same_asset_wash_dry_chain'] and facts['automatic_combo_explicitly_declared']:
            add('AUTOMATIC_COMBO_CHAIN', 'same_asset_wash_dry_chain', '同一洗烘一体机按原程序连续完成，不需要虚构一次人工转移；更在意最终取衣是否方便。', ['same_asset_wash_dry_chain'])
        elif facts['same_asset_wash_dry_chain']:
            add('SAME_ASSET_CHAIN_UNSPECIFIED_HANDLING', 'same_asset_chain_without_declared_auto_transfer', '原洗烘需求须衔接完成；同一资产编号本身不证明自动转程序，按原设备声明安排操作。', ['same_asset_wash_dry_chain', 'automatic_combo_explicitly_declared'])
        elif kind == 'washer':
            add('WASHED_NOT_WEARABLE', 'no_same_asset_drying_chain', '洗净后仍需按原安排取出处理，不能把洗衣结束说成衣物已可穿。', ['same_asset_wash_dry_chain'])
        else:
            add('DRYER_ORIGINAL_UPSTREAM', 'separate_dryer', '只处理原已声明的烘干需求，保留原洗衣上游与取衣期限，不为错峰临时补造烘干。', ['declared_upstream_links', 'service_contracts'])
    elif kind == 'dishwasher':
        if facts['service_contracts']:
            add('PRESERVE_DISH_RELEASE_AND_DUE', 'declared_meal_related_service', '只在原餐具释放与交付期限之间商量预约，宁可说明取舍，也不临时改成手洗或补造餐具库存。', ['service_contracts.release_min', 'service_contracts.deadline_min'])
        else:
            add('DISH_STOCK_UNKNOWN', 'service_not_bound', '未声明餐具库存和完成期限前，只能讨论完整程序改时，不能假定可拖到任意下一餐。', ['service_contracts_status'])
    elif kind == 'water_heater':
        if facts['assisted_bath_references']:
            add('PROTECT_ASSISTED_BATH', 'declared_child_bath_and_actual_assistance_overlap', '原洗浴包含明确的儿童协助环节，偏好事先备足，避免照护者临时补救；不新增照护任务或医学温度。', ['assisted_bath_references'])
        groups = facts['water_demand_groups']
        if any(len(g['groups']) > 1 for g in groups):
            add('SEPARATED_WATER_SERVICES', 'multiple_disjoint_draw_groups', '家人用水分成不止一段；更在意每一段都能按需用水，不把第一段有热水当成全天都够。', ['water_demand_groups'])
        elif groups:
            add('CONTIGUOUS_WATER_SERVICES', 'one_draw_group_per_day', '相邻用水要作为一整段准备；不能只顾第一人，后面的人却要等水。', ['water_demand_groups'])
        else:
            add('WATER_REQUIREMENTS_PENDING', 'service_not_bound', '按既定洗浴准备热水；没有绑定用水声明时，不声称已知可降温的储水余量。', ['service_contracts_status'])
        add('TANK_TARGET_DISTINCT_FROM_OUTLET', 'owned_water_heater', '提前加热或改变储水设温可分别提出，不能把水箱设温当作洗浴出水温度；洗浴时间、水量和出水要求不随之降低。', ['service_contracts.target_C'])
    elif kind == 'ac':
        for mode in facts['room_use_modes']:
            if mode in ('child_rest', 'adult_rest', 'work'):
                code, text = {'child_rest': ('PROTECT_CHILD_ROOM_REST', '该房间有孩子休息，偏好少反复停开；先讨论其他不影响休息的调整。'),
                              'adult_rest': ('PROTECT_ROOM_SLEEP', '该房间承担睡眠，偏好睡眠过程稳定，不能把卧室无人活动理解成无人使用。'),
                              'work': ('PROTECT_ROOM_WORK', '该房间有工作或学习，偏好少临时打断，不把人在家理解成随时可改温控。')}[mode]
                add(code, mode, text, ['room_use_modes', 'room_use_references'])
        if not set(facts['room_use_modes']) & {'child_rest', 'adult_rest', 'work'}:
            add('OCCUPIED_COMMON_ROOM', 'no_declared_sleep_or_work_in_room', '活动房间的小幅调温可以商量；无人时提前运行仍须有用途和授权，不默认已有实际节能。', ['room_use_modes'])
        add('SEPARATE_HEATING_COOLING', 'owned_reversible_AC_or_unspecified_mode', '制冷升温、制热降温、提前运行和停机分别确认；制冷的温度偏好不能直接套给冬季制热。', ['service_contracts.reference_heating_setpoint_C', 'service_contracts.reference_cooling_setpoint_C'])
    elif kind == 'ev':
        modes = facts['journey_purposes']
        if 'work_aligned' in modes:
            add('EV_WORK_AND_OTHER_TRIPS' if len(modes) > 1 else 'EV_WORK_TRIPS', 'declared_work_aligned_journey',
                '工作相关出行的离车时间优先保留，其他日子按各自原行程安排，不能统一拖到同一个早晨才充完。', ['journey_purposes', 'service_contracts.departure_min'])
        elif modes:
            add('EV_NONCOMMUTE_DECLARED_TRIPS', 'declared_noncommute_journey', '按原有实际任务备电，不把每天都当作固定早班通勤；可错时但不改行程。', ['journey_purposes', 'service_contracts.departure_min'])
        else:
            add('EV_TRAVEL_NOT_BOUND', 'service_not_bound', '未声明具体离车和目标电量时，不能声称可延后到次日任意时刻。', ['service_contracts_status'])
        targets = sorted({round(100*n['required_departure_soc'], 6) for n in facts['service_contracts'] if n.get('required_departure_soc') is not None})
        target_text = '（本批原目标为' + '、'.join(f'{v:g}%' for v in targets) + '）' if targets else ''
        add('EV_TARGET_NOT_MINIMUM', 'owned_EV', '按原连接期和每次目标电量' + target_text + '讨论错时，出行最低电量不替代本户声明目标，也不增加插拔。', ['service_contracts.required_departure_soc', 'service_contracts.connection_start_min'])
    return rows
