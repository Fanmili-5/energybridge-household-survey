"""Project outputs -> v69 questionnaire materials. No simulation or collection.

The signed production collector stays byte-identical. Preview rendering adds
only explicit pending-data branches and case-ID routing for same-day variants.
"""
import copy
import subprocess
from pathlib import Path
from benchmark.ab_generation.common import bound, digest, read, save, seal, sha, verify
from .pipeline import HERE, check

COLLECTOR = HERE.parent / 'collector'
UI = 'eb.questionnaire50.collection.v69'
ADAPTER = 'eb.project.v69_preview_adapter.v1'
GROUPS = ('tasks', 'operations', 'controls')
KINDS = {'washer': '洗衣', 'dryer': '烘干', 'dishwasher': '洗碗', 'ev': '车辆充电', 'water_heater': '热水', 'ac': '空调'}
ACTIVITIES = {'sleep': '睡眠', 'work_or_school': '外出工作或学习', 'home_idle': '在家可安排家务', 'dinner': '晚餐', 'bath': '洗澡', 'care': '照护'}
RELATIONS = {'partner': '伴侣', 'parent': '家长', 'sibling': '兄弟姐妹'}


def time(t):
    day, minute = divmod(t, 1440)
    prefix = '' if day == 0 else '次日' if day == 1 else '前日' if day == -1 else '第%d天' % (day + 1)
    return '%s%02d:%02d' % (prefix, minute // 60, minute % 60)


def display_plans(pair):
    """Keep whole service chains intersecting the 24h window, clamp controls.

    The full, unmodified commands remain in the upstream content-bound pair.
    No thousands of historical commands are rendered as today's schedule.
    """
    lo, hi = 480, 1920
    needs = {r['need_id'] for side in ('A', 'B') for group in ('tasks', 'operations')
             for r in pair[side][group] if r['start_min'] < hi and r['end_min'] > lo}
    plans = {}
    for side in ('A', 'B'):
        plans[side] = {}
        for group in GROUPS:
            rows = []
            for source in pair[side][group]:
                if group == 'controls':
                    if not source['start_min'] < hi or not source['end_min'] > lo:
                        continue
                    row = dict(source, start_min=max(lo, source['start_min']), end_min=min(hi, source['end_min']))
                elif source['need_id'] in needs:
                    row = dict(source)
                else:
                    continue
                row.pop('_ab_control_id', None)
                rows.append(row)
            plans[side][group] = rows
    return plans


def changes(plans):
    rows = []
    for group, identity in (('tasks', 'task_id'), ('operations', 'operation_id')):
        sides = [{r[identity]: r for r in plans[s][group]} for s in ('A', 'B')]
        for key in sorted(set(sides[0]) | set(sides[1])):
            a, b = (s.get(key) for s in sides)
            if a != b:
                r = a or b
                rows.append({'group': group, 'asset_id': r['asset_id'], 'kind': r['kind'], 'A': a, 'B': b})
    controls = [plans[s]['controls'] for s in ('A', 'B')]
    for aid, kind in sorted({(r['asset_id'], r['kind']) for side in controls for r in side}):
        subsets = [[r for r in side if (r['asset_id'], r['kind']) == (aid, kind)] for side in controls]
        points = sorted({t for side in subsets for r in side for t in (r['start_min'], r['end_min'])})
        for lo, hi in zip(points, points[1:]):
            states = [[{k: v for k, v in r.items() if k not in ('start_min', 'end_min')}
                       for r in side if r['start_min'] <= lo and r['end_min'] >= hi] for side in subsets]
            if states[0] != states[1]:
                rows.append({'group': 'controls', 'asset_id': aid, 'kind': kind, 'start_min': lo, 'end_min': hi,
                             'A': states[0], 'B': states[1]})
    return rows


def profile_and_lines(family, household, context):
    facts = family['facts']; hid = family['household_id']
    fm = {m['member_id']: m for m in facts['members']}
    members = [{**m, 'local_id': 'm%02d' % (i + 1), 'sex': fm.get(m['member_id'], {}).get('sex', 'unknown')}
               for i, m in enumerate(household['members'])]
    names = {m['member_id']: '成员%d' % (i + 1) for i, m in enumerate(members)}
    own = [m for m in members if m['household_id'] == hid]
    lines = ['；'.join('%s %d岁%s' % (names[m['member_id']], m['age_years'], {'male': '男', 'female': '女'}.get(m['sex'], '')) for m in own)]
    if facts['relationships']:
        relations = []
        for r in facts['relationships']:
            if r['type'] == 'source_relation_unspecified':
                relations.append('%s与%s的来源关系描述：%s' % (names[r['subject']], names[r['object']], r['source_label']))
            else:
                relations.append('%s是%s的%s' % (names[r['subject']], names[r['object']], RELATIONS[r['type']]))
        lines.append('；'.join(relations))
    lines.append('你代入%s，给定实验角色为“%s”。请结合本户日程与需求判断，不把角色名称当成预设答案。' %
                 (names[facts['decision_maker_id']], family['archetype_definition']['title']))
    lines.append('本户和角色是公开合成情境；收入与真实心理偏好未设为已知事实。')
    shared = [m for m in members if m['household_id'] != hid]
    if shared:
        lines.append('同一住宅还住有：' + '；'.join('%s %d岁（其他住户）' % (names[m['member_id']], m['age_years']) for m in shared) + '。不能默认由你调整其他住户的安排。')
    for care in facts['care']:
        lines.append('给定照护关系：%s照护%s。' %
                     (names[care['caregiver_id']], '、'.join(names[mid] for mid in care['dependent_ids'])))
    for mid, calendar in household['calendars'].items():
        lines.append(names[mid] + '今天：' + '；'.join('%s—%s %s' %
            (time(r['start_min']), time(r['end_min']), ACTIVITIES.get(r['activity'], '已声明活动')) for r in calendar) + '。')
    active = {r['need_id'] for g in ('tasks', 'operations') for r in household['A'][g]}
    for n in context['needs']:
        if n['kind'] == 'water_heater' and n['release_min'] < 1920 and n['deadline_min'] > 480:
            lines.append('热水需求：%s—%s，%s需%g升热水，情境给定最低%g℃；实际交付未计算。' %
                         (time(n['release_min']), time(n['deadline_min']), names[n['requester']], n['quantity'], n['minimum_C']))
        if n['need_id'] in active and n['release_min'] < 1920 and n['deadline_min'] > 480:
            text = '%s需求：%s后可安排，须在%s前交付' % (KINDS.get(n['kind'], n['kind']), time(n['release_min']), time(n['deadline_min']))
            if n.get('unit') == 'kg':
                text += '，衣物量%g kg' % n['quantity']
            if 'required_departure_soc' in n:
                text += '，出发目标电量%g%%' % (100 * n['required_departure_soc'])
            lines.append(text + '。')
    for requirement in family['life']['comfort_requirements']:
        band = requirement['temperature_band_C']
        lines.append('情境给定的舒适范围：%g—%g℃，不是测得的个人容忍度；实际室温未计算。' % tuple(band)
                     if band is not None else '本情境未给定个人舒适温度范围，不能从角色名称补造；实际室温未计算。')
    by_asset = {d['asset_id']: d for d in household['devices']}
    for m in members:
        allowed = sorted({KINDS.get(by_asset[a]['kind'], by_asset[a]['kind']) for a in m['can_operate_asset_ids'] if a in by_asset})
        lines.append('%s有权操作：%s。' % (names[m['member_id']], '、'.join(allowed) or '本次没有已声明授权的设备'))
    lines.append('整套参考住房：建筑面积%.1f㎡、可用面积%.1f㎡、住宅共%d户；由参考房型匹配，不是实测户型。' %
                 (household['housing']['gross_area_m2'], household['housing']['usable_area_m2'], household['housing']['shared_households']))
    devices = copy.deepcopy(household['devices'])
    for device in devices:
        if device['room_id'] is None and device.get('placement') == 'exterior' and device['kind'] == 'ev':
            device.update(source_room_id=None, room_id='external_dedicated_ev_bay',
                          room_projection='v69_display_name_for_declared_exterior_EV_location;not_new_geometry')
    profile = {'schema': 'eb.project.v69_profile.v1', 'household_id': hid, 'province': '公开合成情境 · 地区未指定',
        'members_count': facts['N'], 'generations': facts['G'], 'household_area_m2': household['housing']['gross_area_m2'],
        'area_scope': 'whole_reference_dwelling;not_household_allocated_area',
        'members': members, 'relationships': copy.deepcopy(facts['relationships']), 'devices': devices,
        'role': copy.deepcopy(family['archetype_definition']), 'housing': copy.deepcopy(household['housing']),
        'care': copy.deepcopy(facts['care']), 'comfort_requirements': copy.deepcopy(family['life']['comfort_requirements']),
        'authority': copy.deepcopy(context['authority']), 'field_origins': family['field_origins']}
    return profile, lines


def preview_assets(out):
    """Derive the same v69 form, changing neither questions nor scales.

    Edits are fail-closed at known source anchors; assets and anchors are pinned
    by the source/package manifests. The production files are never written.
    """
    public = out / 'public'; public.mkdir(parents=True, exist_ok=True)
    html = (COLLECTOR / 'index.html').read_text()
    replacements = {
        '家庭用电安排 · 正式问卷': '家庭用电安排 · v69资料预览',
        '50户正式问卷': 'v69 · 资料预览',
        'src="collection-client.js"': 'src="preview-client.js"',
        '<div class="collection-toolbar">': '<div class="collection-toolbar" hidden>',
        '结果为仿真估算。用电减少可能伴随任务未完成；费用与补偿未计算。': '实际用电、室温、任务完成与VPP响应均未计算。时间和设定值属于计划，不能当作实际后果。',
        '草稿自动保存。提交后生成回执；凭恢复码可换设备续填。': '此处只预览既定问卷，填写内容仅作本机交互检查，不保存为正式答卷。',
    }
    for old, new in replacements.items():
        if html.count(old) != 1:
            raise ValueError('V69_HTML_ADAPTER_ANCHOR_CHANGED:' + old)
        html = html.replace(old, new)
    (public / 'index.html').write_text(html)
    js = (COLLECTOR / 'view.js').read_text()
    guards = {
        'function familyLines(c,p) {': 'if(c.project_presentation) return c.project_presentation.family_lines;',
        'function temperatureEffect(c,p) {': "if(c.outcome_status==='not_computed') return {label:'室温',lead:'未计算',lines:[],selectedRooms:[]};",
        'function serviceEffect(c) {': "if(c.outcome_status==='not_computed') return {label:'任务完成',lead:'未计算',lines:[]};",
        'function vppEffect(c) {': "if(c.outcome_status==='not_computed') return {label:'VPP响应',lead:'未计算',lines:[]};",
        'function effects(c,p) {': "if(c.outcome_status==='not_computed') return ['用电','室温','任务完成','VPP响应'].map(label=>({label,lead:'未计算',lines:[]}));",
        'function impactModel(c,p){': "if(c.outcome_status==='not_computed') return ['用电量','有人时的室温','生活任务是否完成','VPP响应'].map(label=>m('div',null,'impact-card',[m('div',null,'impact-title',[m('h3',label)]),m('div',null,'metric-pair',[metricCell('A','未计算'),metricCell('B','未计算')]),m('p','尚未运行仿真；这里不能判断实际后果。','effect-detail')]));",
    }
    for anchor, code in guards.items():
        if js.count(anchor) != 1:
            raise ValueError('V69_JS_ADAPTER_ANCHOR_CHANGED:' + anchor)
        js = js.replace(anchor, anchor + '\n    ' + code)
    # v69's production bank has one B/day. The project can have several B/day.
    # Use immutable case IDs for selection; do not relabel variants as new dates.
    pairs = {
        "x.date===q('case-date').value": "x.case_id===q('case-date').value",
        "date:target.date": "case_id:target.case_id",
        "const o=el('option',x.date);o.value=x.date;": "const o=el('option',x.date+' · 方案'+(index.cases.filter(r=>r.household_id===x.household_id).indexOf(x)+1));o.value=x.case_id;",
        "dates(params.get('date')||data.resume_date)": "dates(params.get('case_id')||data.resume_case_id)",
        "${index.cases.length}题": "${index.cases.filter(r=>r.household_id===current.household_id).length}题",
    }
    for old, new in pairs.items():
        if js.count(old) != 1:
            raise ValueError('V69_CASE_ADAPTER_ANCHOR_CHANGED:' + old)
        js = js.replace(old, new)
    (public / 'view.js').write_text(js)
    for name in ('view.css', 'base.css', 'required-response.js'):
        (public / name).write_bytes((COLLECTOR / name).read_bytes())
    (public / 'preview-client.js').write_bytes((HERE / 'preview-client.js').read_bytes())


def build_questionnaire(project, out):
    project, out = Path(project).resolve(), Path(out).resolve()
    check(project); out.mkdir(parents=True, exist_ok=False)
    preview_assets(out)
    view = read(project / 'VIEW.json'); families = read(project / 'families/SUMMARY.json')
    family_rows = {r['household_id']: r for r in families['records']}
    index = {'schema': 'eb.project.v69_index.v1', 'ui_revision': UI, 'adapter_revision': ADAPTER,
        'households': [], 'cases': [], 'profiles_sha256': {}, 'mode': 'read_only_material_preview',
        'new_EP_runs': 0, 'human_collection_release': False, 'training_release': False}
    audit = []
    for h in view['households']:
        hid = h['id']; c = read(project / 'contexts' / (hid + '.json.gz'))
        family = read(bound(project / 'families', family_rows[hid]['path']))
        p, lines = profile_and_lines(family, h, c)
        profile = out / 'public/households' / (hid + '.json'); save(profile, p)
        index['households'].append(hid); index['profiles_sha256'][hid] = sha(profile)
        for sample in h['previews']:
            pair_path = bound(project, sample['artifact']); pair = read(pair_path)
            plans = display_plans(pair); sid = sample['id']; cid = c['case_id'] + '__' + sid
            case = {'schema': 'eb.project.v69_case.v1', 'case_id': cid, 'household_id': hid, 'date': c['date'],
                'window_min': [480, 1920], 'plans': plans, 'changes': changes(plans),
                'project_presentation': {'family_lines': lines}, 'outcome_status': 'not_computed',
                'impact': None, 'VPP_results': None, 'response': None,
                'VPP_requests': [dict(e, notification_min=c['decision_min']) for e in c['events']],
                'bindings': {'sample_id': sid, 'source_pair_sha256': sha(pair_path),
                    'family_sha256': family_rows[hid]['sha256'], 'A_commands_sha256': pair['A_commands_sha256'],
                    'B_commands_sha256': pair['B_commands_sha256'], 'housing_layout_sha256': sha(project / 'connected/shells' / hid / 'layout.json'),
                    'information_set': pair['information_set']}}
            relative = 'cases/' + hid + '/' + sid + '.json'; target = out / 'public' / relative; save(target, case)
            index['cases'].append({'household_id': hid, 'case_id': cid, 'date': c['date'], 'path': relative, 'sha256': sha(target)})
            audit.append({'sample_id': sid, 'case_id': cid, 'static_valid': sample['static_valid'],
                'static_issues': sample['static_issues'], 'stratum': sample['category'],
                'unchanged_control': pair['A_commands_sha256'] == pair['B_commands_sha256'],
                'physical_results': 'not_computed', 'retained': True})
    save(out / 'public/index.json', index)
    run = subprocess.run(['node', str(HERE / 'verify_display.js'), str(out)], capture_output=True, text=True)
    if run.returncode:
        raise ValueError('V69_DISPLAY_CONTRACT_REJECTED:' + run.stderr[-2000:])
    save(out / 'AUDIT.json', {'records': audit, 'all_selected_retained': len(audit) == view['coverage']['selected'],
        'failed_project_slots': [r for r in view['records'] if r['status'] != 'plans_constructed'],
        'physical_outcomes_fabricated': False, 'reroll_or_replacement': False})
    sources = {str(p.relative_to(HERE.parent.parent)): sha(p) for p in sorted(COLLECTOR.iterdir()) if p.is_file()}
    summary = {'schema': 'eb.project.v69_preview.v1', 'ui_revision': UI, 'adapter_revision': ADAPTER,
        'households': len(index['households']), 'cases': len(audit), 'outcomes_not_computed': len(audit),
        'invalid_retained': sum(not r['static_valid'] for r in audit), 'unchanged_controls_retained': sum(r['unchanged_control'] for r in audit),
        'source_project_manifest_sha256': sha(project / 'MANIFEST.json'), 'source_v69_assets': sources,
        'adapter_sources': {str(p.relative_to(HERE.parent.parent)): sha(p) for p in
                            [HERE / 'questionnaire.py', HERE / 'preview-client.js', HERE / 'verify_display.js']},
        'question_text_and_scales_changed': False, 'new_EP_runs': 0, 'production_deployed': False,
        'human_collection_release': False, 'training_release': False, 'online_questionnaire_changed': False}
    save(out / 'SUMMARY.json', summary)
    seal(out, {'schema': summary['schema'], 'ui_revision': UI, 'new_EP_runs': 0})
    return summary


def verify_questionnaire(folder):
    folder = Path(folder); manifest = verify(folder); summary = read(folder / 'SUMMARY.json')
    if manifest['schema'] != 'eb.project.v69_preview.v1' or summary['ui_revision'] != UI:
        raise ValueError('PROJECT_V69_PREVIEW_REQUIRED')
    for key in ('new_EP_runs', 'question_text_and_scales_changed', 'production_deployed', 'human_collection_release', 'training_release'):
        if summary[key]:
            raise ValueError('PREVIEW_SCOPE_VIOLATED:' + key)
    index = read(folder / 'public/index.json'); seen = set()
    for row in index['cases']:
        if row['case_id'] in seen:
            raise ValueError('DUPLICATE_PREVIEW_CASE')
        seen.add(row['case_id']); path = bound(folder / 'public', row['path']); case = read(path)
        if sha(path) != row['sha256'] or case['case_id'] != row['case_id'] or case['household_id'] != row['household_id']:
            raise ValueError('PREVIEW_CASE_BINDING_FAILED')
        if case['impact'] is not None or case['VPP_results'] is not None or case['response'] is not None or case['outcome_status'] != 'not_computed':
            raise ValueError('UNCOMPUTED_OUTCOMES_OR_ANSWERS_FABRICATED')
        if case['changes'] != changes(case['plans']):
            raise ValueError('PREVIEW_PLAN_CHANGE_MISMATCH')
    for hid in index['households']:
        if sha(folder / 'public/households' / (hid + '.json')) != index['profiles_sha256'][hid]:
            raise ValueError('PREVIEW_PROFILE_BINDING_FAILED')
    if len(seen) != summary['cases'] or not read(folder / 'AUDIT.json')['all_selected_retained']:
        raise ValueError('PREVIEW_SELECTION_LOST')
    for name, expected in {**summary['source_v69_assets'], **summary['adapter_sources']}.items():
        # Frozen examples keep their original provenance when the active
        # collector evolves. A snapshot must match the original source hash.
        snapshot=summary.get('archived_source_paths',{}).get(name)
        path=bound(folder,snapshot) if snapshot else bound(HERE.parent.parent,name)
        if sha(path) != expected:
            raise ValueError('SOURCE_V69_CHANGED:' + name)
    return {'passed': True, 'households': len(index['households']), 'cases': len(seen), 'new_EP_runs': 0, 'formal_collection': False}
