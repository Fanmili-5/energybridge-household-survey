"""EB role + unchanged calendars/services -> explainable energy-use portrait.

This compiler adds information only. It never schedules, edits, samples, reads B,
predicts acceptance, or turns thermostat commands into actual room temperatures.
"""
from collections import Counter
import copy
import datetime as dt
from pathlib import Path

from .core import HERE, digest, read, require, save, seal, sha
from .device_persona import RULES as PERSONA_RULES, generate_personas, render_family

RULES = HERE / 'ENERGY_PORTRAIT_RULES.json'
SOURCE_LOCK = HERE / 'ENERGY_PORTRAIT_SOURCES.json'
LABELS = {'washer': '洗衣机', 'dryer': '烘干机', 'dishwasher': '洗碗机',
          'water_heater': '热水器', 'ac': '空调', 'ev': 'EV充电'}
COMPLETION = {'washer': '洗净并完成原约定的取衣；不等同衣物已经可穿。',
              'dryer': '完成原约定烘干及取出；此处不预测实际干燥效果。',
              'dishwasher': '完成原约定程序及取出，保持既有服务期限。',
              'water_heater': '在既定用水时段提供原声明的水量与出水温度；加热时刻与洗浴时刻分开。',
              'ac': '保护已声明的房间使用需求；设定温度不等于实际室温。',
              'ev': '在声明的期限前达到本户目标电量；不以出行最低电量替换用户目标。'}
PROTECTED = {'dinner', 'bathing', 'sleep', 'sleep_rest', 'work', 'school', 'home_work',
             'given_child_meal', 'given_protected_service_check', 'child_bathing_assistance',
             'childcare_supervision', 'day_nap', 'meal_and_rest'}
DEVICE_RULES = {
    'washer': '可提出完整程序改时；保留原衣物量、程序和取衣要求，不把洗净写成可穿。',
    'dryer': '若原有烘干需求，保持洗完再烘及原取出期限；没有需求不补造烘干。',
    'dishwasher': '可提出完整程序改时；保留用餐后释放、原餐具量及下次用具期限。',
    'water_heater': '加热改时与储水设温分别提出；未声明设温授权范围时先确认，既定洗浴时段、水量与出水要求不变。',
    'ac': '按原房间使用分别提出制冷、制热、提前运行或停机；各自授权范围分开，设定值不等于实际室温。',
    'ev': '只在原连接区间内建议充电改时；保留本户离车期限和目标SOC，不新增出行。'}


def role_attitude(role):
    rules = read(RULES)
    require(role in rules['roles'], 'UNKNOWN_PORTRAIT_ROLE')
    return copy.deepcopy(rules['roles'][role])


def _time(value):
    return dt.datetime.fromisoformat(value)


def compile_portrait(context):
    before = digest(context); require(context['schema'] == 'eb.energy_portrait.input.v1', 'UNKNOWN_PORTRAIT_SCHEMA')
    rules = read(RULES); role = context['role']; require(role in rules['roles'], 'UNKNOWN_PORTRAIT_ROLE')
    require(read(SOURCE_LOCK)['EB_commit'] == rules['source_commit'], 'PORTRAIT_SOURCE_LOCK_MISMATCH')
    family_profile = generate_personas(context)
    personas = {(d['asset_id'], d['kind']): d for d in family_profile['devices']}
    require(bool(context['members']), 'PORTRAIT_MEMBERS_REQUIRED')
    members = {m['member_id'] for m in context['members']}
    require(len(members) == len(context['members']), 'PORTRAIT_DUPLICATE_MEMBER')
    assets = {d['asset_id']: d for d in context['devices']}
    require(len(assets) == len(context['devices']), 'PORTRAIT_DUPLICATE_ASSET')
    core = copy.deepcopy(rules['roles'][role]); warnings = []; seen = set()
    for day in context['days']:
        require(set(day['calendars']) == members, 'PORTRAIT_ALL_MEMBER_CALENDARS_REQUIRED')
        for calendar in day['calendars'].values():
            for event in calendar:
                require(0 <= event['start_min'] < event['end_min'] <= 1440, 'PORTRAIT_INVALID_CALENDAR_INTERVAL')
    for s in context['services']:
        require(s['asset_id'] in assets and s['kind'] in assets[s['asset_id']]['types'], 'PORTRAIT_UNOWNED_SERVICE')
        require(s['need_id'] not in seen, 'PORTRAIT_DUPLICATE_SERVICE'); seen.add(s['need_id'])
        if 'source_requirement' in s:
            require(digest(s['source_requirement']) == s['source_requirement_sha256'], 'PORTRAIT_SOURCE_REQUIREMENT_CHANGED')
        require('release_at' in s and 'deadline_at' in s, 'PORTRAIT_MISSING_SERVICE_DEADLINE')
        require(_time(s['release_at']) < _time(s['deadline_at']), 'PORTRAIT_INVALID_SERVICE_INTERVAL')
        require(s.get('required_departure_soc') is None or 0 <= s['required_departure_soc'] <= 1, 'PORTRAIT_INVALID_SOC')
        for task in s['baseline_tasks']:
            require(_time(task['start_at']) < _time(task['end_at']), 'PORTRAIT_INVALID_BASELINE_INTERVAL')
    policy = context['existing_policy']; thermal = policy.get('thermal', {})
    permissions = policy.get('permissions', {})
    expected_auto = role in ('D', 'F')
    if 'automatic_within_declared_bounds' in permissions and permissions['automatic_within_declared_bounds'] != expected_auto:
        warnings.append('EXISTING_AUTOMATION_POLICY_DIFFERS_FROM_EB_ROLE')
    if role == 'A' and thermal.get('usual_setpoint_C', 0) + thermal.get('temporary_increase_C', 0) > 26:
        warnings.append('EXISTING_CONTROL_BOUND_ABOVE_EB_A_PREFERRED26;preference_and_permission_are_distinct')
    protections = [{'date': day['date'], 'member_id': mid, **copy.deepcopy(e)}
                   for day in context['days'] for mid, cal in sorted(day['calendars'].items())
                   for e in cal if e['activity'] in PROTECTED or e.get('available_for_operation') is False]
    devices = []
    for aid, asset in sorted(assets.items()):
        for kind in sorted(asset['types']):
            require(kind in LABELS, 'PORTRAIT_UNSUPPORTED_DEVICE_KIND')
            persona = personas[(aid, kind)]
            services = sorted((copy.deepcopy(s) for s in context['services'] if s['asset_id'] == aid and s['kind'] == kind),
                              key=lambda s: (s['source_date'], s['release_at'], s['need_id']))
            if role == 'F' and any(s.get('required_departure_soc') not in (None, .8) for s in services):
                warnings.append('EXISTING_EV_TARGET_DIFFERS_FROM_EB_F_REFERENCE80;preserved')
            ref = [{k: copy.deepcopy(s[k]) for k in ('need_id', 'source_date', 'preferred_start_at', 'baseline_tasks', 'handling') if k in s}
                   for s in services]
            devices.append({'asset_id': aid, 'kind': kind, 'label': LABELS[kind], 'room_id': asset['room_id'],
                'habit_basis': 'EB_role+declared_per_asset_calendar_service_conditions;not_measured_human_preference',
                'habit_references_meaning': 'daily_A_arrangement_reference_only;not_used_to_infer_habits',
                'habit_references': ref, 'requirements': services, 'completion_standard': COMPLETION[kind],
                'declared_settings': copy.deepcopy(context.get('declared_device_settings', {}).get(aid, {})),
                'habit': persona['habit'],
                'adjustment_preference': persona['adjustment_preference'],
                'authorization': copy.deepcopy(persona['authorization']),
                'inherited_preferences': copy.deepcopy(persona['inherited_preferences']),
                'persona_rule_ids': copy.deepcopy(persona['rule_ids']),
                'persona_sources': copy.deepcopy(persona['sources']),
                'device_adjustment_rule': DEVICE_RULES[kind],
                'adjustment_rule_origin': 'researcher_service_preservation_rule;not_measured_preference',
                'room_use_references': [{'date': day['date'], 'member_id': mid, **copy.deepcopy(event)}
                    for day in context['days'] for mid, calendar in sorted(day['calendars'].items())
                    for event in calendar if kind == 'ac' and event.get('room_id') == asset['room_id']],
                'handling_preference': persona['handling_preference'],
                'confirmation': persona['authorization']['narrative'], 'no_task_in_selected_days': not services,
                'sources': ['existing_family_devices', 'existing_A_requirements_and_handling', 'EB_role_summary']})
    require(digest(context) == before, 'PORTRAIT_INPUT_MUTATED')
    return {'schema': 'eb.energy_portrait.v2', 'household_id': context['household_id'], 'role': role,
        'members': copy.deepcopy(context['members']), 'attitude': core, 'devices': devices,
        'family_device_profile': family_profile,
        'household_preferences': copy.deepcopy(family_profile['household_preferences']),
        'participant_family_text': render_family(family_profile),
        'participant_family_brief': render_family(family_profile, brief=True),
        'existing_days': copy.deepcopy(context['days']),
        'calendar_protections': protections, 'existing_policy': copy.deepcopy(policy),
        'declared_thermostats': copy.deepcopy(context['declared_thermostats']),
        'warnings': sorted(set(warnings)), 'unmeasured_preferences': None, 'human_acceptance': None,
        'bindings': {'context_sha256': before, 'rules_sha256': sha(RULES),
                     'device_persona_rules_sha256': sha(PERSONA_RULES),
                     'source_lock_sha256': sha(SOURCE_LOCK),
                     'compiler_sha256': sha(Path(__file__)), 'EB_commit': rules['source_commit'],
                     'input_adapter_sha256': sha(HERE / 'portrait_inputs.py'),
                     'source_kind': context['source_kind']},
        'source_calendar_or_A_modified': False, 'B_outcomes_or_answers_used': False,
        'simulation_started': False, 'physical_success_claimed': False}


def clock(value, date):
    t = dt.datetime.fromisoformat(value); delta = (t.date() - dt.date.fromisoformat(date)).days
    prefix = '' if delta == 0 else '次日' if delta == 1 else '前日' if delta == -1 else f'{delta:+d}日'
    return prefix + t.strftime('%H:%M')


def device_line(device, date):
    rows = [s for s in device['requirements'] if s['source_date'] == date]
    if not rows:
        return device['label'] + '：所选日期没有对应服务记录，不补造任务或需求。'
    kind = device['kind']; detail = []
    if kind in ('washer', 'dryer', 'dishwasher'):
        explicit = sorted({clock(s['preferred_start_at'], date) for s in rows if 'preferred_start_at' in s})
        starts = sorted({clock(t['start_at'], date) for s in rows for t in s['baseline_tasks']})
        if explicit: detail.append('原声明偏好启动' + '、'.join(explicit))
        elif starts: detail.append('既有A启动' + '、'.join(starts) + '（安排参考）')
        detail.append('服务期限' + '、'.join(sorted({clock(s['deadline_at'], date) for s in rows})))
        if kind == 'washer': detail.append('洗净不等于可穿')
    elif kind == 'water_heater':
        detail.append('既定用水开始于' + '、'.join(sorted({clock(s['release_at'], date) for s in rows})))
        detail.append('加热可否改时须保护这些用水时段')
    elif kind == 'ev':
        detail += ['原约定' + clock(s['deadline_at'], date) + '前达到' +
                   (f"{100*s['required_departure_soc']:g}%" if 'required_departure_soc' in s else '声明电量（数值未给定）') for s in rows]
        for s in rows:
            plugs = [clock(o['end_at'], date) for o in s['handling'] if o['kind'] == 'EV_plug']
            unplugs = [clock(o['start_at'], date) for o in s['handling'] if o['kind'] == 'EV_unplug']
            if plugs and unplugs:
                detail.append('原插接安排' + '、'.join(plugs) + '接好，' + '、'.join(unplugs) + '开始拔离；出行期限不等于全程连接')
    else:
        detail.append('保护原声明房间需求' + '、'.join(sorted({clock(s['release_at'], date) + '—' + clock(s['deadline_at'], date) for s in rows})))
        detail.append('按原日历保护使用者；设定值不等于实际室温')
    name = device['label'] + (f"（{device['room_id']}）" if kind == 'ac' else '')
    return name + '：' + '；'.join(detail) + '。'


def render_portrait(portrait, date):
    p = portrait
    lines = [p['participant_family_text'], f'本日既定服务与原安排参考（{date}，不作为上述习惯的推断依据）：']
    lines += [device_line(d, date) for d in p['devices']]
    lines += ['调整偏好：' + p['attitude']['device_adjustment'], '温控偏好：' + p['attitude']['thermal']]
    thermal = p['existing_policy'].get('thermal', {})
    if thermal:
        lines.append('保留现有温控配置：' + '，'.join(f'{k}={v}' for k, v in thermal.items()) + '；不将其改写为实际室温或原EB实测偏好。')
    permission = p['existing_policy'].get('service_policy', {}).get('reschedule_limit_min')
    if permission is not None:
        lines.append(f'原已登记家务改时边界{permission}分钟；仍须保护具体服务期限和人员日程。')
    if p['warnings']:
        lines.append('需核对的来源差异：现有参数与原EB参照存在已登记差别；本次不改动原值，不据此判定实际执行或接受。')
    return '\n'.join(lines) + '\n'


def build_portraits(input_path, output):
    input_path, output = Path(input_path).resolve(), Path(output).resolve()
    batch = read(input_path); source_hash = sha(input_path)
    rules_hash, lock_hash, device_hash = sha(RULES), sha(SOURCE_LOCK), sha(PERSONA_RULES)
    require(batch['schema'] == 'eb.energy_portrait.batch.v1', 'UNKNOWN_PORTRAIT_BATCH')
    contexts = batch['households']; ids = [c['household_id'] for c in contexts]
    require(ids and len(ids) == len(set(ids)), 'PORTRAIT_DUPLICATE_OR_EMPTY_HOUSEHOLDS')
    output.mkdir(parents=True, exist_ok=False); records = []
    for context in contexts:
        try:
            p = compile_portrait(context)
        except (ValueError, KeyError, TypeError) as error:
            records.append({'household_id': context['household_id'], 'role': context['role'],
                            'status': 'portrait_rejected', 'reason': str(error)})
            continue
        ident = digest(p['household_id'])[:24]
        path = 'portraits/' + ident + '.json'; save(output / path, p)
        dates = [d['date'] for d in context['days']]
        (output / 'portraits' / (ident + '.md')).write_text('\n'.join(render_portrait(p, d) for d in dates), encoding='utf-8')
        (output / 'portraits' / (ident + '.family.md')).write_text(p['participant_family_text'], encoding='utf-8')
        (output / 'portraits' / (ident + '.brief.md')).write_text(p['participant_family_brief'], encoding='utf-8')
        records.append({'household_id': p['household_id'], 'role': p['role'], 'dates': dates, 'path': path,
                        'status': 'portrait_compiled', 'context_sha256': digest(context), 'warnings': p['warnings']})
    require(sha(input_path) == source_hash and sha(RULES) == rules_hash and sha(SOURCE_LOCK) == lock_hash and sha(PERSONA_RULES) == device_hash,
            'PORTRAIT_INPUT_CHANGED_DURING_BUILD')
    summary = {'schema': 'eb.energy_portrait.batch_result.v1', 'requested': len(records), 'records': records,
               'compiled': sum(r['status'] == 'portrait_compiled' for r in records),
               'constructed': sum(r['status'] == 'portrait_compiled' for r in records),
               'role_counts': dict(Counter(r['role'] for r in records)), 'source_inputs_changed': False,
               'EP_runs': 0, 'deployment': False, 'human_labels_generated': 0}
    save(output / 'SUMMARY.json', summary)
    seal(output, {'input_sha256': source_hash, 'rules_sha256': rules_hash, 'source_lock_sha256': lock_hash,
                  'device_persona_rules_sha256': device_hash,
                  'compiler_sha256': sha(Path(__file__)), 'EP_runs': 0})
    return summary
