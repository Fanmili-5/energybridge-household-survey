"""Household-only semantic mapping; no A/B generation or simulation imports."""
import copy
import datetime as dt
import math

from .core import HERE, digest, read, require, sha
from . import joint_sampling_v1 as latent

VERSION = 'within_class_joint_v2'
RULES = HERE / 'JOINT_SAMPLING_RULES_V2.json'
PROGRAMS = ('washer', 'dryer', 'dishwasher')
LABELS = {'washer':'洗衣', 'dryer':'烘干', 'dishwasher':'洗碗', 'ac':'空调', 'water_heater':'热水', 'ev':'充电'}


def time_fields(date, minute):
    """Canonical relative minutes plus redundant, verifiable dated display."""
    if minute is None:
        return {'preferred_start_min':None, 'preferred_start_at':None,
                'preferred_day_offset':None, 'preferred_clock_min':None}
    instant = dt.datetime.fromisoformat(date) + dt.timedelta(minutes=minute)
    return {'preferred_start_min':minute, 'preferred_start_at':instant.isoformat(timespec='minutes'),
            'preferred_day_offset':minute//1440, 'preferred_clock_min':minute%1440}


def show_time(row):
    minute = row['preferred_start_min']
    if minute is None:
        reason=row['reason']
        if 'primary_handler' in reason:text='原登记操作人的已知窗口放不下完整链；是否由其他合格成员接手需协商'
        elif reason.startswith('upstream'):text='原洗衣目标或衔接条件待确认，不另造烘干时刻'
        elif 'preference' in reason:text='声明的偏好与原局部窗口暂不能同时满足'
        else:text='原声明条件下尚无可确定的局部候选，原因见核查记录'
        return '未给出（'+text+'）'
    day = minute//1440
    prefix = '' if day == 0 else '次日' if day == 1 else f'{day}日后'
    return prefix+f'{minute%1440//60:02d}:{minute%60:02d}'


def service_text(contract):
    """Display only declared service facts, with their original date offset."""
    def at(value):
        return show_time({'preferred_start_min':value})
    fields=[]
    if contract.get('release_min') is not None:fields.append('原释放'+at(contract['release_min']))
    if contract.get('deadline_min') is not None:fields.append('原期限'+at(contract['deadline_min']))
    if contract.get('duration_min') is not None:fields.append('完整程序'+str(contract['duration_min'])+'分钟')
    if contract.get('quantity') is not None:fields.append('需求'+str(contract['quantity'])+' '+str(contract.get('unit','单位未声明')))
    if contract.get('target_C') is not None:fields.append('原出水要求'+f"{contract['target_C']:g}℃")
    if contract.get('required_departure_soc') is not None:fields.append('原出发目标SOC '+f"{contract['required_departure_soc']*100:g}%")
    if contract.get('connection_start_min') is not None:fields.append('原连接开始'+at(contract['connection_start_min']))
    return '；'.join(fields)


def machine_willingness(c, declared):
    # Preference about machine time is not a preference about extra operations.
    return 0.0 if declared.get('shiftable') is False else 1-c['routine_stability']


def declared_fields(source, kind):
    return copy.deepcopy(source.get('energy_preferences', {}).get('shared_appliances', {}).get(kind, {}))


def local_domain(source, need):
    """Original local hard constraints, including the complete explicit combo."""
    children = [c for c in source['declared_service_contracts'] if c.get('upstream_need_id') == need['need_id']]
    same = [c for c in children if c['asset_id'] == need['asset_id']]
    auto = bool(same) and len(same) == len(children) and 'auto combo' in need.get('wash_only_delivery', '')
    if same and not auto:
        return [], 'same_asset_chain_handling_not_declared'
    bounded = copy.deepcopy(need)
    extension = sum(c['duration_min'] for c in same) if auto else 0
    if auto:
        bounded['deadline_min'] = min([need['deadline_min']]+[c['deadline_min'] for c in same])
    domain, reason = latent.feasible_starts(source, bounded, extension)
    offset = need.get('duration_min', 0)
    for child in sorted(same, key=lambda n:n['need_id']):
        if 'machine_windows_min' not in child:
            return [], 'missing_original_child_machine_window'
        domain = [t for t in domain if (t+offset)//1440 == (t+offset+child['duration_min']-1)//1440 and
                  any(a <= (t+offset)%1440 and (t+offset+child['duration_min']-1)%1440 < b for a,b in child['machine_windows_min'])]
        offset += child['duration_min']
    if not domain and reason is None:
        reason = 'no_complete_chain_machine_window'
    if reason == 'no_complete_load_run_retrieve_window_or_neighbor_calendar_missing':
        reason = 'no_complete_primary_handler_local_window_in_supplied_calendar'
    return domain, reason


def preference_domain(source, need, declared):
    domain, reason = local_domain(source, need)
    if not domain:
        return domain, reason
    if 'earliest_h' in declared or 'latest_h' in declared:
        if not {'earliest_h','latest_h'} <= declared.keys():
            return [], 'incomplete_explicit_shared_preference_window'
        a, z = declared['earliest_h']*60, declared['latest_h']*60
        duration = need['duration_min']+sum(c['duration_min'] for c in source['declared_service_contracts']
                    if c.get('upstream_need_id') == need['need_id'] and c['asset_id'] == need['asset_id'])
        def inside(t):
            return any(k*1440+a <= t and t+duration <= k*1440+z+(1440 if z <= a else 0)
                       for k in range(t//1440-1, t//1440+1))
        domain = [t for t in domain if inside(t)]
        if not domain:
            return [], 'declared_shared_preference_has_no_local_opportunity'
    return domain, None


def projection(rows):
    """Only lossless values may reach the old weekday/weekend input."""
    values, states = {}, {}
    for category in ('weekday', 'weekend'):
        selected = [r for r in rows if ('weekend' if dt.date.fromisoformat(r['source_date']).weekday() >= 5 else 'weekday') == category]
        starts = [r['preferred_start_min'] for r in selected]
        if not selected:
            reason = 'no_declared_dates_in_period'
        elif None in starts:
            reason = 'dated_target_missing'
        elif any(v >= 1440 for v in starts):
            reason = 'dated_offset_not_supported_by_original_A_input'
        elif len(set(starts)) != 1:
            reason = 'dated_targets_differ_not_supported_by_original_A_input'
        else:
            values[category] = starts[0]
            states[category] = {'status':'representable_without_information_loss', 'reason':None}
            continue
        states[category] = {'status':'pending_A_interface', 'reason':reason}
    return values, states


def targets(source, asset, kind, u, declared):
    needs = [n for n in source['declared_service_contracts'] if n['asset_id'] == asset['asset_id'] and n['kind'] == kind]
    if not needs:
        needs = latent._policy_opportunities(source, asset, kind)
    rows = []
    for n in sorted(needs, key=lambda n:n['need_id']):
        domain, reason = preference_domain(source, n, declared)
        if domain and 'preferred_h' in declared:
            clock = declared['preferred_h']*60
            # Distance to the nearest daily occurrence, preserving the chosen day.
            value = min(domain, key=lambda t:(abs(t%1440-clock), t))
        else:
            value = latent.quantile(domain, u) if domain else None
        rows.append({'need_id':n['need_id'], 'source_date':n['source_date'], 'service_id':n.get('service_id'),
                     **time_fields(n['source_date'], value), 'reason':reason,
                     'release_min':n['release_min'], 'deadline_min':n['deadline_min'],
                     'duration_min':n.get('duration_min'), 'preference_candidate_count':len(domain),
                     'domain_sha256':digest(domain), 'potential_service_only':n.get('potential_service_only',False),
                     'origin':'explicit_shared_clock_conditioned_on_original_windows' if 'preferred_h' in declared else 'frozen_quantile_in_dated_local_domain',
                     'scope':'local_candidate_only;not_actual_A_or_whole_home_schedule'})
    values, states = projection(rows)
    policies = {}
    for sid in sorted({r['service_id'] for r in rows if r['service_id'] is not None}):
        v, s = projection([r for r in rows if r['service_id'] == sid])
        policies[sid] = {'preferred_start_min':v, 'states':s}
    return {'per_service':rows, 'preferred_start_min':values, 'A_projection':states, 'by_policy':policies,
            'stable_direction':'earlier_when_feasible' if u < .5 else 'later_when_feasible',
            'declared_stable_clock_min':declared.get('preferred_h',None)*60 if 'preferred_h' in declared else None,
            'independent_dryer_time_sampled':False,
            'reason':None if rows else 'no_declared_program_opportunity'}


def cooling_support(role_rules, role, declared):
    prior = role_rules['EB_roles'][role]['appliances']['ac']
    lo = declared.get('setpoint_preferred_min_c', prior['setpoint_preferred_min_c'])
    hi = declared.get('setpoint_preferred_max_c', prior['setpoint_preferred_max_c'])
    if 'setpoint_preferred_min_c' in declared and 'setpoint_preferred_max_c' not in declared:
        hi = max(lo,hi)
    if 'setpoint_preferred_max_c' in declared and 'setpoint_preferred_min_c' not in declared:
        lo = min(lo,hi)
    require(type(lo) in (int,float) and type(hi) in (int,float) and math.isfinite(lo) and math.isfinite(hi) and 0 < lo <= hi < 40,
            'PORTRAIT_INVALID_SHARED_COOLING_PREFERENCE;40C_is_not_a_comfort_default')
    return lo, hi, ('explicit_shared_declaration' if any(k.startswith('setpoint_preferred_') for k in declared) else 'EB_class_soft_reference')


def sample(source, role_rules, cfg):
    from .joint_sampling import method_hash
    before = digest(source); rule_hash = sha(RULES); code_hash = method_hash(VERSION)
    rules = read(RULES)
    # Exactly the old random coordinates, even though mapping and mode differ.
    legacy_source = copy.deepcopy(source)
    old_cfg = {**cfg, 'mode':latent.VERSION}
    legacy_source['energy_preferences']['preference_sampling'] = old_cfg
    result = latent.sample(legacy_source, role_rules, old_cfg)
    for m in result['member_preferences'].values():
        c = m['coordinates']; p = m['preference_context']
        p.update(shift_willingness_fraction=1-c['routine_stability'],
                 routine_sensitive=c['routine_stability']>=.5, handling_change_sensitive=c['manual_burden']>=.5,
                 extra_handling_preference='avoid_extra_handling' if c['manual_burden']>=.5 else 'discuss_handling_changes_separately',
                 legacy_tradeoff_reference_only=True)
    for row in result['devices']:
        c = row['coordinates']; declared = declared_fields(source,row['kind'])
        willingness = machine_willingness(c,declared)
        bound = source['existing_policy'].get('service_policy',{}).get('reschedule_limit_min')
        row.update(shift_willingness_fraction=willingness,
                   preferred_shift_limit_min_raw=bound*willingness if bound is not None else None,
                   preferred_shift_limit_min=math.floor(bound*willingness/rules['time_step_min'])*rules['time_step_min'] if bound is not None else None,
                   routine_sensitive=c['routine_stability']>=.5, handling_change_sensitive=c['manual_burden']>=.5,
                   extra_handling_preference='avoid_extra_handling' if c['manual_burden']>=.5 else 'discuss_handling_changes_separately',
                   explicit_shared_declaration=declared,
                   legacy_tradeoff_reference_only=True,
                   use='household_portrait_context_only;downstream_A_B_acceptance_deferred',
                   shift_range_meaning='soft_negotiation_preference;not_permission_or_rejection_threshold',
                   mapping_version=VERSION)
        asset = next(d for d in source['devices'] if d['asset_id']==row['asset_id'])
        if row['kind'] in ('washer','dishwasher'):
            row['time_preference'] = targets(source,asset,row['kind'],c['time_orientation'],declared)
        elif row['kind']=='ac':
            lo,hi,origin = cooling_support(role_rules,source['role'],declared)
            step=rules['temperature_step_C']
            grid = [round(i*step,8) for i in range(math.ceil(lo/step-1e-9),math.floor(hi/step+1e-9)+1)]
            # A narrow explicit interval may have no 0.1C grid point. Preserve
            # the declaration as missing; never clip it or change the seed.
            require(bool(grid),'PORTRAIT_SHARED_COOLING_RANGE_HAS_NO_DECLARED_GRID_POINT')
            row.update(cooling_preferred_C=latent.quantile(grid,c['thermal_level']), cooling_support_C=[lo,hi], cooling_support_origin=origin,
                       member_cooling_preferences_C={mid:latent.quantile(grid,m['coordinates']['thermal_level']) for mid,m in result['member_preferences'].items()})
    lookup = {(d['asset_id'],d['kind']):d for d in result['devices']}
    for row in result['devices']:
        if row['kind']!='dryer':continue
        rows = []
        children = [n for n in source['declared_service_contracts'] if n['asset_id']==row['asset_id'] and n['kind']=='dryer']
        for n in children:
            parent = next((p for p in source['declared_service_contracts'] if p['need_id']==n.get('upstream_need_id')),None)
            root = lookup.get((parent['asset_id'],'washer')) if parent else None
            upstream = next((r for r in root['time_preference']['per_service'] if r['need_id']==parent['need_id']),None) if root else None
            auto = parent and parent['asset_id']==n['asset_id'] and 'auto combo' in parent.get('wash_only_delivery','')
            value = upstream['preferred_start_min']+parent['duration_min'] if auto and upstream and upstream['preferred_start_min'] is not None else None
            root_reason = upstream['reason'] if upstream and upstream['preferred_start_min'] is None else None
            rows.append({'need_id':n['need_id'],'source_date':n['source_date'],'service_id':None,
                         'upstream_need_id':n.get('upstream_need_id'),**time_fields(n['source_date'],value),
                         'reason':None if value is not None else ('upstream_target_missing:'+root_reason if root_reason else 'upstream_or_original_transfer_feasibility_pending'),
                         'scope':'derived_original_combo;not_an_independent_schedule'})
        # Public separate-dryer policies: derive after the same dated washer
        # target, then honor the original handler and complete-cycle domain.
        for p in source['declared_device_settings'].get(row['asset_id'],{}).get('program_policies',[]):
            if p['kind']!='dryer' or p.get('trigger')!='after_service':continue
            parent = next((q for s in source['declared_device_settings'].values() for q in s.get('program_policies',[]) if q['service_id']==p['upstream_service_id']),None)
            root = lookup.get((parent['asset_id'],'washer')) if parent else None
            for upstream in (root or {}).get('time_preference',{}).get('per_service',[]):
                if upstream['service_id']!=p['upstream_service_id']:continue
                release = upstream['preferred_start_min']
                if release is None:
                    value, reason = None, 'upstream_target_missing'
                else:
                    n = {**p,'need_id':upstream['need_id']+':'+p['service_id'],'source_date':upstream['source_date'],
                         'release_min':release+parent['duration_min']+rules['handling_duration_min'],
                         'deadline_min':upstream['release_min']+p['deadline_after_release_min']}
                    domain, reason = preference_domain(source,n,row['explicit_shared_declaration'])
                    value = min(domain) if domain else None
                rows.append({'need_id':upstream['need_id']+':'+p['service_id'],'source_date':upstream['source_date'],'service_id':p['service_id'],
                             'upstream_need_id':upstream['need_id'],**time_fields(upstream['source_date'],value),'reason':reason,
                             'scope':'derived_after_upstream_with_original_handling;actual_transfer_pending_original_scheduler'})
        v,s = projection(rows)
        by_policy = {}
        for sid in sorted({r['service_id'] for r in rows if r['service_id'] is not None}):
            vv,ss = projection([r for r in rows if r['service_id']==sid]);by_policy[sid]={'preferred_start_min':vv,'states':ss}
        row['time_preference']={'per_service':rows,'preferred_start_min':v,'A_projection':s,'by_policy':by_policy,
                                'stable_direction':'follow_original_upstream','declared_stable_clock_min':None,
                                'independent_dryer_time_sampled':False,'reason':None if rows else 'no_explicit_original_upstream'}
    result.update(version=VERSION, configuration=cfg, input_sha256=before, rules_sha256=rule_hash,
                  code_sha256=code_hash, latent_stream_version=latent.VERSION,
                  parameter_ledger=copy.deepcopy(rules['parameter_ledger']),
                  scope='household_portrait_only;A_B_UI91_acceptance_deferred')
    result['profile_sha256']=digest({k:v for k,v in result.items() if k!='profile_sha256'})
    require(digest(source)==before and sha(RULES)==rule_hash and method_hash(VERSION)==code_hash,'PORTRAIT_INPUT_OR_METHOD_CHANGED')
    return result


def habit(row):
    kind = row['kind']
    if kind in PROGRAMS:
        t = row['time_preference']; declared = t.get('declared_stable_clock_min')
        if kind=='dryer': text='烘干随原洗衣批次衔接，不独立抽启动时刻；'
        elif declared is not None: text=f'家庭明确声明的时间习惯约{int(declared)//60:02d}:{int(declared)%60:02d}；'
        else:text=('原条件允许的窗口内偏早处理；' if t['stable_direction']=='earlier_when_feasible' else '原条件允许的窗口内偏晚处理；')
        text+=('较重视固定家务节奏。' if row['routine_sensitive'] else '机器改时有商量余地。')
        text+=('不愿增加装取或额外干预；机器改时与人工负担分开商量。' if row['handling_change_sensitive'] else '装取变化可另行讨论，增加操作仍须确认。')
        text+='保留原完整程序、需求量与交付期限。'
    elif kind=='ac':
        text=f"制冷偏好约{row['cooling_preferred_C']:g}℃；"+('较在意短时温度变化。' if row['coordinates']['comfort_sensitivity']>=.5 else '短时温度变化可商量。')
        text+='制热、提前运行与停机分别确认，设定值不是实际室温。'
    elif kind=='water_heater':
        text=('更重视提前备水、少临时补救；' if row['readiness_priority']>=.5 else '更愿在保证用水的前提下减少不必要加热；')+'原洗浴时段、水量与出水要求不变。'
    else:
        text=('更重视尽早备足出行电量；' if row['readiness_priority']>=.5 else '可商量在原连接期内择时充电；')+'原行程、连接及目标SOC不变，不能因偏好扩大许可。'
    if kind in ('washer','dishwasher','ev') and row['preferred_shift_limit_min'] is not None:
        value=row['preferred_shift_limit_min']
        text+=(f'机器改时偏好先协商约{value}分钟以内。' if value else '机器时间更倾向维持原安排，其他改动逐案商量。')+'这是软偏好，不是硬限制或拒绝标签。'
    return text


def attach(profile, joint):
    profile = latent.attach(profile,joint)
    profile['schema']='eb.household_device_persona.v6'
    for d in profile['devices']:
        row=d['sampled_preferences'];d['habit']=habit(row);d['adjustment_preference']=row['core']+'；'+habit(row)
        d['inherited_preferences']['reference_only_in_v2']=True
        d['sources']['habit_and_action_scope']='EB_core+explicit_shared_declaration+experimental_v2_joint_mapping'
        d['active_preference_fields']=['sampled_preferences','habit','adjustment_preference','authorization','member_negotiation']
        # Preserve each affected person's opinion. No invented opinion from an
        # absent operator, no averaging, no generated household decision.
        discussions=[]
        for mid,c in row['affected_member_preference_contexts'].items():
            applicable=('routine_sensitive','handling_change_sensitive') if d['kind'] in PROGRAMS else ('routine_sensitive',) if d['kind']=='ev' else ()
            fields=[k for k in applicable if c[k]!=row[k]]
            member=joint['member_preferences'][mid]['coordinates']
            if d['kind']=='ac' and row['member_cooling_preferences_C'][mid]!=row['cooling_preferred_C']:
                fields.append('cooling_preferred_C')
            if d['kind']=='ac' and (member['comfort_sensitivity']>=.5)!=(row['coordinates']['comfort_sensitivity']>=.5):
                fields.append('comfort_sensitivity')
            if d['kind'] in ('water_heater','ev'):
                readiness=member['comfort_sensitivity'] if d['kind']=='water_heater' else 1-member['time_orientation']
                if (readiness>=.5)!=(row['readiness_priority']>=.5):fields.append('readiness_priority')
            if fields:discussions.append({'member_id':mid,'fields':fields,'status':'needs_negotiation;not_engineering_error_or_rejection'})
        d['member_negotiation']=discussions
    return profile


def apply_to_life(life, profile):
    """Only lossless original inputs; otherwise preserve them and report pending."""
    result=copy.deepcopy(life);changes=[]
    lookup={(d['asset_id'],d['kind']):d for d in profile['joint_sampling']['devices']}
    for i,p in enumerate(result.get('program_policies',[])):
        row=lookup[(p['asset_id'],p['kind'])]
        entry=row['time_preference']['by_policy'].get(p['service_id'])
        if entry is None:
            changes.append({'path':f'program_policies[{i}].preferred_start_min','applied':False,'reason':'no_matching_dated_policy_target'})
            continue
        for category,state in entry['states'].items():
            path=f'program_policies[{i}].preferred_start_min.{category}'
            if category in entry['preferred_start_min']:
                value=entry['preferred_start_min'][category]
                changes.append({'path':path,'before':p['preferred_start_min'][category],'after':value,'applied':True,'reason':'dated_targets_representable_without_information_loss'})
                p['preferred_start_min'][category]=value
            else:changes.append({'path':path,'applied':False,'reason':state['reason'],'status':'pending_A_interface'})
    for i,p in enumerate(result.get('thermostat_policies',[])):
        value=lookup[(p['asset_id'],'ac')]['cooling_preferred_C']
        if value<=p['heating_setpoint_C']:
            changes.append({'path':f'thermostat_policies[{i}].cooling_setpoint_C','applied':False,'reason':'original_heating_deadband_conflict'})
        else:
            changes.append({'path':f'thermostat_policies[{i}].cooling_setpoint_C','before':p['cooling_setpoint_C'],'after':value,'applied':True})
            p['cooling_setpoint_C']=value
    return result,changes


def render(profile):
    f=profile['context_evidence'];ages='、'.join(map(str,f['member_ages_years']))
    holder=profile['confirmation_holder'];owner='成员'+str(holder['member_index']) if holder and holder.get('member_index') else '原登记确认人'
    numbers={mid:i+1 for i,mid in enumerate(profile['joint_sampling']['member_preferences'])}
    lines=[f"家庭资料（实验画像）：{profile['household_id']}，{f['adult_count']}位成人、{f['minor_count']}位未成年成员，年龄依次为{ages}岁。",
           profile['joint_sampling']['class_core']+'。','由'+owner+'负责家庭方案确认；原登记资产'+str(len({d['asset_id'] for d in profile['devices']}))+'项，同资产洗烘仍算一台。']
    for i,m in enumerate(profile['joint_sampling']['member_preferences'].values(),1):
        p=m['preference_context']
        lines.append(f'成员{i}：'+('可行窗口内偏早处理；' if p['time_direction']=='earlier_when_feasible' else '可行窗口内偏晚处理；')+
                     ('较重固定节奏；' if p['routine_sensitive'] else '机器时间可商量；')+
                     ('较在意少装取、少干预。' if p['handling_change_sensitive'] else '操作变化另行讨论和确认。'))
    for d in profile['devices']:
        name=LABELS[d['kind']]+('（'+d['room_label']+'）' if d['kind']=='ac' else '')
        lines.append(name+'：'+d['habit']+' 授权：'+d['authorization']['narrative'])
        facts=d['decision_conditions'];primary=facts.get('registered_operator_id')
        if primary:
            lines.append('原登记常用操作人：'+('成员'+str(numbers[primary]) if primary in numbers else '原声明的外部操作人')+'；其他有资格成员是否接手需另行商量。')
        durations=sorted({c['duration_min'] for c in facts['service_contracts'] if c.get('duration_min') is not None})
        if durations and d['kind'] in PROGRAMS:lines.append('原完整程序：'+' / '.join(str(v) for v in durations)+'分钟，按原批次保留。')
        targets=sorted({c['required_departure_soc'] for c in facts['service_contracts'] if c.get('required_departure_soc') is not None})
        if targets:lines.append('原出发目标SOC：'+' / '.join(f'{v*100:g}%' for v in targets)+'；具体连接和出发期限按日期查看。')
        bounds=d['authorization']['bounds']
        if d['kind'] in ('washer','dishwasher','ev') and bounds.get('existing_reschedule_limit_min') is not None:
            lines.append('原登记改时范围为前后'+str(bounds['existing_reschedule_limit_min'])+'分钟；与上述软偏好分开，也不是本次已经同意。')
        if d['kind']=='ac':
            vals=d['sampled_preferences']['member_cooling_preferences_C'];affected=d['authorization']['affected_member_ids']
            if affected:lines.append('该房间使用成员的制冷偏好：'+'、'.join(f"成员{numbers[mid]}约{vals[mid]:g}℃" for mid in affected if mid in vals)+'。')
        if d['member_negotiation']:
            names={'routine_sensitive':'固定节奏','handling_change_sensitive':'装取负担','cooling_preferred_C':'制冷偏好','comfort_sensitivity':'温度变化敏感程度','readiness_priority':'提前备妥与减少不必要运行的取舍'}
            lines.append('需协商：'+'；'.join('成员'+str(numbers[v['member_id']])+'在'+'、'.join(names[k] for k in v['fields'])+'上与共享默认不同' for v in d['member_negotiation'])+'，不自动平均成已经同意。')
    lines.append('每日候选时刻另按日期列示，不把它们写成长期固定习惯，也不是已经安排的A。家庭事实、硬件、必要服务及原权限不变；未成年成员仍由原成人协调，不因此取得操作权。')
    lines.append('来源：六类核心与参考配置来自EB；类内分布、载荷、取舍映射与协商偏好为实验设定，未实测标定。')
    return '\n\n'.join(lines)+'\n'


def render_dated(profile, date=None):
    lines=['按日期的单项候选目标（尚未排全屋A；偏离或无机会不等于拒绝）']
    for d in profile['devices']:
        contracts={c['need_id']:c for c in d['decision_conditions']['service_contracts']}
        for row in d['sampled_preferences'].get('time_preference',{}).get('per_service',[]):
            if date is None or row['source_date']==date:
                facts=contracts.get(row['need_id'],row)
                lines.append(row['source_date']+' '+LABELS[d['kind']]+'候选：'+show_time(row)+'。'+service_text(facts))
        if d['kind'] in ('water_heater','ev'):
            for contract in contracts.values():
                if date is None or contract['source_date']==date:
                    lines.append(contract['source_date']+' '+LABELS[d['kind']]+'原需求（未生成新运行时刻）：'+service_text(contract))
    return '\n'.join(lines)+'\n'


def audit(profile, source):
    """Independent semantic invariants, not acceptance or physical evaluation."""
    issues=[];missing=[];discussions=[];pending=[]
    j=profile['joint_sampling'];rules=read(RULES)
    if j['class_core']!=rules['class_cores'][source['role']] or any(m['role']!=source['role'] for m in j['member_preferences'].values()):
        issues.append('class_core_changed')
    if {(d['asset_id'],d['kind']) for d in profile['devices']}!={(a['asset_id'],k) for a in source['devices'] for k in a['types']}:
        issues.append('physical_device_set_changed')
    for d in profile['devices']:
        r=d['sampled_preferences']
        if r['shift_willingness_fraction']!=machine_willingness(r['coordinates'],r['explicit_shared_declaration']):issues.append('handling_mixed_into_machine_willingness')
        if d['habit']!=habit(r) or r['core'] not in d['adjustment_preference']:issues.append('text_structure_disagreement')
        if source['role'] not in ('D','F') and d['authorization']['standing_consent_actions']:issues.append('class_confirmation_expanded')
        if r.get('heating_change_preference_C') is not None or r.get('off_authorization') is not None:issues.append('unknown_thermal_permission_invented')
        if d['kind']=='ac':
            lo,hi=r['cooling_support_C']
            if not lo<=r['cooling_preferred_C']<=hi or not all(lo<=v<=hi for v in r['member_cooling_preferences_C'].values()):issues.append('cooling_preference_outside_declared_support')
        asset=next(a for a in source['devices'] if a['asset_id']==d['asset_id'])
        original=[n for n in source['declared_service_contracts'] if n['asset_id']==d['asset_id'] and n['kind']==d['kind']]
        if not original and d['kind'] in ('washer','dishwasher'):original=latent._policy_opportunities(source,asset,d['kind'])
        originals={n['need_id']:n for n in original}
        supplied=[n for n in source['declared_service_contracts'] if n['asset_id']==d['asset_id'] and n['kind']==d['kind']]
        if d['decision_conditions']['service_contracts']!=supplied:issues.append('original_service_contract_changed')
        if any(v['member_id'] not in d['authorization']['affected_member_ids'] for v in d['member_negotiation']):issues.append('unaffected_member_opinion_imposed')
        for row in r.get('time_preference',{}).get('per_service',[]):
            if row['preferred_start_min'] is None:
                if not row['reason']:issues.append('missing_without_reason')
                missing.append({'asset_id':d['asset_id'],'kind':d['kind'],**row})
            else:
                if any(row[k]!=v for k,v in time_fields(row['source_date'],row['preferred_start_min']).items()):issues.append('date_or_day_offset_lost')
                if d['kind'] in ('washer','dishwasher'):
                    n=originals.get(row['need_id'])
                    if n is None or row['preferred_start_min'] not in preference_domain(source,n,r['explicit_shared_declaration'])[0]:issues.append('dated_target_outside_original_local_domain')
        for category,state in r.get('time_preference',{}).get('A_projection',{}).items():
            if state['status']=='pending_A_interface':pending.append({'asset_id':d['asset_id'],'kind':d['kind'],'period':category,**state})
        discussions.extend({'asset_id':d['asset_id'],'kind':d['kind'],**v} for v in d['member_negotiation'])
    roots={r['need_id']:r for d in profile['devices'] if d['kind']=='washer' for r in d['sampled_preferences']['time_preference']['per_service']}
    durations={n['need_id']:n['duration_min'] for n in source['declared_service_contracts'] if n['kind']=='washer'}
    for d in profile['devices']:
        if d['kind']!='dryer':continue
        for row in d['sampled_preferences']['time_preference']['per_service']:
            if row['preferred_start_min'] is None:continue
            root=roots.get(row.get('upstream_need_id'))
            if root is None or root['preferred_start_min'] is None:issues.append('dry_target_without_upstream')
            elif row['scope'].startswith('derived_original_combo') and row['preferred_start_min']!=root['preferred_start_min']+durations[row['upstream_need_id']]:issues.append('automatic_combo_link_changed')
    return {'household_id':source['household_id'],'engineering_errors':issues,'missing_targets':missing,
            'member_negotiations':discussions,'pending_A_projection':pending,
            'acceptance_or_score_generated':False,'all_original_services_and_authority_unchanged':True}
