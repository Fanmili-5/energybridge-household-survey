"""Opt-in Gaussian-copula portraits. No outcomes, A commands or rejection sampling.

Only the transformation is a published algorithm. Marginals, factor structure
and behavioral mappings are declared experimental design, not fitted psychology.
NumPy PCG64 and SciPy normal CDF implement the standard statistical primitives.
"""
import copy
import datetime as dt
import math

from .core import HERE, digest, read, require, sha

RULES = HERE / 'JOINT_SAMPLING_RULES.json'
VERSION = 'within_class_joint_v1'


def configuration(value):
    require(isinstance(value, dict) and set(value) <= {'mode', 'seed', 'loading'}, 'JOINT_UNKNOWN_CONFIGURATION')
    require(value.get('mode') == VERSION and type(value.get('seed')) is int, 'JOINT_MODE_OR_SEED_REQUIRED')
    loading = value.get('loading', read(RULES)['loading_default'])
    require(type(loading) in (int, float) and math.isfinite(loading) and 0 <= loading <= 1, 'JOINT_INVALID_LOADING')
    return {'mode': VERSION, 'seed': value['seed'], 'loading': loading}


def normal(seed, hid, key):
    """Keyed independent PCG64 stream: list ordering cannot change another draw."""
    import numpy as np
    return float(np.random.Generator(np.random.PCG64(int(digest([VERSION, seed, hid, key]), 16))).standard_normal())


def coordinates(cfg, hid, scope, rules):
    from scipy.special import ndtr
    loading = cfg['loading']; result = {}
    for dim in rules['dimensions']:
        common = normal(cfg['seed'], hid, ['household', dim])
        residual = normal(cfg['seed'], hid, [scope, dim])
        z = loading * common + math.sqrt(1-loading*loading) * residual
        result[dim] = float(ndtr(z))
    return result


def quantile(values, u):
    require(bool(values), 'JOINT_EMPTY_QUANTILE_SUPPORT')
    return values[min(len(values)-1, math.floor(u*len(values)))]


def _slots(source, aid, date, lo, hi, step):
    """Preserve the registered handler. Multiple qualified people are not substitutes."""
    rights = source['asset_authority'].get('assets', {}).get(aid, {})
    operators = rights.get('authorized_operator_ids', [])
    primary = rights.get('registered_operator_id')
    if primary is None and len(operators) == 1:
        primary = operators[0]  # sole original qualified handler, not a new grant
    if primary is None:
        return [], 'registered_handler_unknown_or_ambiguous'
    days = {d['date']: d for d in source['days']}
    base = dt.date.fromisoformat(date); slots = []
    for offset in range(max(0, lo//1440), hi//1440+1):
        d = days.get(str(base+dt.timedelta(days=offset)))
        if d is None:
            continue
        for a, b in d['operator_windows'].get(primary, []):
            start = max(lo, offset*1440+a)
            for minute in range(math.ceil(start/step)*step, min(hi, offset*1440+b)-step+1, step):
                slots.append(minute)
    return sorted(set(slots)), None


def feasible_starts(source, need, finish_extension=0, earliest=None):
    """Local full-cycle/load/retrieval domain, NOT a whole-home scheduler.

    Minutes remain relative to source_date; never modulo deadlines. Original
    machine windows are daily non-crossing intervals. A midnight deadline can
    still include a full cycle within a subsequent day's machine window.
    """
    rules = read(RULES); step = rules['time_step_min']; handling = rules['handling_duration_min']
    required = {'duration_min', 'machine_windows_min', 'maximum_preload_wait_min', 'maximum_retrieval_wait_min', 'timer_allowed'}
    if not required <= need.keys():
        return [], 'missing_declared_program_or_machine_window'
    release = max(need['release_min'], earliest if earliest is not None else need['release_min'])
    deadline = min(need['deadline_min'], need.get('delivery_deadline_min', need['deadline_min']))
    duration = need['duration_min'] + finish_extension
    require(type(duration) is int and duration > 0 and type(release) is int and type(deadline) is int, 'JOINT_INVALID_PROGRAM_TIME')
    if deadline-release < duration+2*handling:
        return [], 'no_complete_load_run_retrieve_window'
    loads, reason = _slots(source, need['asset_id'], need['source_date'], release, deadline, step)
    if reason: return [], reason
    starts = []
    for start in range(math.ceil((release+handling)/step)*step, deadline-duration-handling+1, step):
        end = start+duration
        if start//1440 != (end-1)//1440 or not any(a <= start%1440 and (end-1)%1440 < b for a,b in need['machine_windows_min']):
            continue
        if not any(t+handling <= start and start-t-handling <= need['maximum_preload_wait_min'] and
                   (need['timer_allowed'] or t+handling == start) for t in loads):
            continue
        if not any(end <= t and t-end <= need['maximum_retrieval_wait_min'] and t+handling <= deadline for t in loads):
            continue
        starts.append(start)
    return starts, None if starts else 'no_complete_load_run_retrieve_window_or_neighbor_calendar_missing'


def _policy_opportunities(source, asset, kind):
    """Before-A potential service bounds from original policies and calendars.

    This does not create dated demand or infer an inventory. The original life
    compiler alone decides if a textile batch actually exists on a given day.
    """
    policies = source['declared_device_settings'].get(asset['asset_id'], {}).get('program_policies', [])
    rows = []
    for p in policies:
        if p['kind'] != kind or p['trigger'] == 'after_service': continue
        for day in source['days']:
            if p['trigger'] == 'after_dinner':
                ends = [e['end_min'] for cal in day['calendars'].values() for e in cal if e['activity'] == 'dinner']
                if not ends: continue
                release = max(ends)
            elif p['trigger'] == 'textile':
                arrivals = [e['start_min'] for cal in day['calendars'].values() for prior,e in zip(cal, cal[1:])
                            if prior['location'] == 'away' and e['location'] == 'home']
                release = max(arrivals) if arrivals else p['no_arrival_release_min']
            else:
                continue
            rows.append({**copy.deepcopy(p), 'need_id': day['date']+':potential:'+p['service_id'],
                         'source_date': day['date'], 'release_min': release,
                         'deadline_min': release+p['deadline_after_release_min'],
                         'potential_service_only': True})
    return rows


def _time_preferences(source, asset, kind, u):
    needs = [n for n in source['declared_service_contracts'] if n['asset_id'] == asset['asset_id'] and n['kind'] == kind]
    if not needs:
        needs = _policy_opportunities(source, asset, kind)
    rows = []; period_domains = {'weekday': set(), 'weekend': set()}
    for n in sorted(needs, key=lambda n:n['need_id']):
        # Explicit automatic combo: full chain must fit, with no fake transfer.
        children = [c for c in source['declared_service_contracts'] if c.get('upstream_need_id') == n['need_id']]
        auto = children and all(c['asset_id'] == n['asset_id'] and 'auto combo' in n.get('wash_only_delivery', '') for c in children)
        if children and any(c['asset_id'] == n['asset_id'] for c in children) and not auto:
            domain, reason = [], 'same_asset_chain_handling_not_declared'
        else:
            bounded = copy.deepcopy(n)
            if auto:
                bounded['deadline_min'] = min([n['deadline_min']]+[c['deadline_min'] for c in children])
            domain, reason = feasible_starts(source, bounded, sum(c['duration_min'] for c in children) if auto else 0)
            if auto:
                offset = n['duration_min']
                for child in sorted(children, key=lambda c:c['need_id']):
                    if 'machine_windows_min' not in child:
                        domain, reason = [], 'missing_original_child_machine_window'
                        break
                    domain = [t for t in domain if (t+offset)//1440 == (t+offset+child['duration_min']-1)//1440 and
                              any(a <= (t+offset)%1440 and (t+offset+child['duration_min']-1)%1440 < b for a,b in child['machine_windows_min'])]
                    offset += child['duration_min']
                if not domain and reason is None: reason = 'no_complete_chain_machine_window'
        category = 'weekend' if dt.date.fromisoformat(n['source_date']).weekday() >= 5 else 'weekday'
        period_domains[category].update(t%1440 for t in domain)
        rows.append({'need_id': n['need_id'], 'source_date': n['source_date'],
                     'preferred_start_min': quantile(domain, u) if domain else None,
                     'feasible_start_count': len(domain), 'domain_sha256': digest(domain),
                     'reason': reason, 'potential_service_only': n.get('potential_service_only', False),
                     'scope': 'local_service_feasibility;whole_home_resources_reserved_by_original_scheduler'})
    policies = source['declared_device_settings'].get(asset['asset_id'], {}).get('program_policies', [])
    targets = {}
    for category in ('weekday', 'weekend'):
        # Marginal support is the union of feasible clock grids for this period.
        # Per-date rows remain available; a union target need not fit every day.
        clocks = sorted(period_domains[category])
        if clocks: targets[category] = quantile(clocks, u)
    return {'per_service': rows, 'preferred_start_min': targets, 'independent_dryer_time_sampled': False,
            'reason': None if rows else 'no_declared_program_opportunity',
            'has_original_policy_entry': any(p['kind'] == kind for p in policies)}


def sample(source, role_rules, cfg):
    import numpy as np
    import scipy
    from scipy.special import ndtr
    cfg = configuration(cfg); rules = read(RULES); before = digest(source)
    role = source['role']; hid = source['household_id']
    shared = {dim: float(ndtr(normal(cfg['seed'], hid, ['household', dim]))) for dim in rules['dimensions']}
    members = {m['member_id']: {'role': role, 'coordinates': coordinates(cfg,hid,['member',m['member_id']],rules)}
               for m in sorted(source['members'],key=lambda m:m['member_id'])}
    for m in members.values():
        c=m['coordinates']
        m['preference_context']={'time_direction':'earlier_when_feasible' if c['time_orientation']<.5 else 'later_when_feasible',
            'tradeoff':'preserve_routine' if c['routine_stability']>=c['manual_burden'] else 'minimize_extra_handling',
            'shift_willingness_fraction':(1-c['routine_stability'])*(1-c['manual_burden']),
            'confirmation_preferred':role not in ('D','F') or c['autonomy']>=rules['authorization_confirmation_threshold'],
            'use':'member_evaluation_and_authorization_context;not_independent_hardware_or_A_schedule'}
    out = []; thermal = role_rules['EB_roles'][role]['appliances']['ac']
    grid = [round(i*rules['temperature_step_C'], 1) for i in range(round(thermal['setpoint_preferred_min_c']/rules['temperature_step_C']),
                                                                 round(thermal['setpoint_preferred_max_c']/rules['temperature_step_C'])+1)]
    for asset in sorted(source['devices'], key=lambda d:d['asset_id']):
        for kind in sorted(asset['types']):
            scope_kind = 'washer' if kind == 'dryer' and 'washer' in asset['types'] else kind
            c = coordinates(cfg,hid,['asset',asset['asset_id'],scope_kind],rules)
            willingness = (1-c['routine_stability'])*(1-c['manual_burden'])
            bound = source['existing_policy'].get('service_policy',{}).get('reschedule_limit_min')
            change = source['existing_policy'].get('thermal',{}).get('temporary_increase_C')
            require(bound is None or type(bound) in (int,float) and math.isfinite(bound) and bound >= 0, 'JOINT_BAD_EXISTING_RESCHEDULE_BOUND')
            require(change is None or type(change) in (int,float) and math.isfinite(change) and change >= 0, 'JOINT_BAD_EXISTING_COOLING_BOUND')
            prefer_confirm = role not in ('D','F') or c['autonomy'] >= rules['authorization_confirmation_threshold']
            row = {'asset_id':asset['asset_id'],'kind':kind,'coordinates':c,
                   'core': rules['class_cores'][role],
                   'tradeoff': 'preserve_routine' if c['routine_stability'] >= c['manual_burden'] else 'minimize_extra_handling',
                   'shift_willingness_fraction': willingness,
                   'preferred_shift_limit_min': math.floor(bound*willingness/rules['time_step_min'])*rules['time_step_min'] if bound is not None else None,
                   'authorization_preference': 'confirm_each_proposal' if prefer_confirm else 'bounded_automation_only_if_previously_permitted',
                   'actual_authority_expanded': False, 'origin': 'experimental_joint_draw_with_fixed_EB_core',
                   'use': 'A_input_and_B_evaluation' if kind in ('washer','dryer','dishwasher','ac') else 'B_evaluation_and_authorization_context_only'}
            if kind in ('washer','dishwasher'):
                row['time_preference'] = _time_preferences(source,asset,kind,c['time_orientation'])
            if kind == 'ac':
                row.update(cooling_preferred_C=quantile(grid,c['thermal_level']),
                           cooling_support_C=[grid[0],grid[-1]],
                           preferred_cooling_change_C=round(change*(1-c['comfort_sensitivity']),2) if change is not None else None,
                           member_cooling_preferences_C={mid:quantile(grid,m['coordinates']['thermal_level']) for mid,m in members.items()},
                           heating_change_preference_C=None, off_authorization=None)
            if kind == 'dryer': row['waiting_sensitivity'] = c['manual_burden']
            if kind == 'water_heater': row['readiness_priority'] = c['comfort_sensitivity']
            if kind == 'ev': row['readiness_priority'] = 1-c['time_orientation']
            out.append(row)
    bykey = {(r['asset_id'],r['kind']):r for r in out}
    for row in out:
        if row['kind'] != 'dryer': continue
        children = [n for n in source['declared_service_contracts'] if n['asset_id'] == row['asset_id'] and n['kind'] == 'dryer']
        linked = []
        for n in children:
            parent = next((p for p in source['declared_service_contracts'] if p['need_id'] == n.get('upstream_need_id')),None)
            p = bykey.get((parent['asset_id'],'washer')) if parent else None
            target = next((x for x in p['time_preference']['per_service'] if x['need_id']==parent['need_id']),None) if p else None
            value = target['preferred_start_min']+parent['duration_min'] if target and target['preferred_start_min'] is not None else None
            automatic = parent and parent['asset_id']==n['asset_id'] and 'auto combo' in parent.get('wash_only_delivery','')
            if not automatic: value = None
            linked.append({'need_id':n['need_id'],'upstream_need_id':n.get('upstream_need_id'),'source_date':n['source_date'],
                           'preferred_start_min':value,'reason':None if value is not None else 'upstream_or_transfer_feasibility_pending',
                           'link':'original_automatic_combo' if automatic else 'original_upstream_requires_original_scheduler'})
        # Separate public dryer: derive a target from root policy, never redraw.
        policy_targets = {}
        for p in source['declared_device_settings'].get(row['asset_id'],{}).get('program_policies',[]):
            if p['kind'] != 'dryer' or p.get('trigger') != 'after_service': continue
            parent = next((q for s in source['declared_device_settings'].values() for q in s.get('program_policies',[])
                           if q['service_id']==p['upstream_service_id']),None)
            root = bykey.get((parent['asset_id'],'washer')) if parent else None
            for period, value in (root or {}).get('time_preference',{}).get('preferred_start_min',{}).items():
                # Requested target only; the scheduler supplies real transfer times.
                t = value+parent['duration_min']+2*rules['handling_duration_min']
                if t < 1440 and any(a <= t and t+p['duration_min'] <= b for a,b in p['machine_windows_min']):
                    policy_targets[period]=t
        row['time_preference']={'per_service':linked,'preferred_start_min':policy_targets,'independent_dryer_time_sampled':False,
                                'reason':None if linked or policy_targets else 'no_explicit_upstream_or_feasible_target'}
    require(digest(source)==before,'JOINT_INPUT_MUTATED')
    result={'version':VERSION,'configuration':cfg,'household_id':hid,'role':role,'class_core':rules['class_cores'][role],
            'shared_coordinates':shared,'member_preferences':members,'devices':out,
            'rules_sha256':sha(RULES),'code_sha256':sha(HERE/'joint_sampling.py'),
            'runtime':{'numpy':np.__version__,'scipy':scipy.__version__,'rng':'NumPy PCG64;SHA256 keyed streams'},
            'parameter_ledger':copy.deepcopy(rules['parameter_ledger']), 'input_sha256':before,
            'draw_count_per_household':1,'retry_count':0,'empirically_fitted':False,
            'A_B_actions_outcomes_or_labels_used':False}
    result['profile_sha256']=digest(result)
    return result


def obtain(source, role_rules):
    cfg=source.get('energy_preferences',{}).get('preference_sampling')
    if cfg is None: return None
    cfg=configuration(cfg)
    frozen=source.get('frozen_joint_sampling')
    if frozen is None: return sample(source,role_rules,cfg)
    require(frozen['profile_sha256']==digest({k:v for k,v in frozen.items() if k!='profile_sha256'}),'JOINT_FROZEN_HASH_MISMATCH')
    require(frozen['household_id']==source['household_id'] and frozen['role']==source['role'] and frozen['configuration']==cfg,
            'JOINT_FROZEN_IDENTITY_MISMATCH')
    require(frozen['rules_sha256']==sha(RULES) and frozen['code_sha256']==sha(HERE/'joint_sampling.py'),'JOINT_FROZEN_METHOD_CHANGED')
    require({(r['asset_id'],r['kind']) for r in frozen['devices']}=={(d['asset_id'],k) for d in source['devices'] for k in d['types']},
            'JOINT_FROZEN_DEVICE_SET_CHANGED')
    return copy.deepcopy(frozen)


def apply_to_life(life, profile):
    """Project only supported soft inputs; never mutate facts or requirements."""
    result=copy.deepcopy(life); joint=profile.get('joint_sampling'); changes=[]
    if joint is None: return result,changes
    require(joint['profile_sha256']==digest({k:v for k,v in joint.items() if k!='profile_sha256'}),'JOINT_FROZEN_HASH_MISMATCH')
    require(joint['code_sha256']==sha(HERE/'joint_sampling.py') and joint['rules_sha256']==sha(RULES),'JOINT_FROZEN_METHOD_CHANGED')
    lookup={(r['asset_id'],r['kind']):r for r in joint['devices']}
    for i,p in enumerate(result.get('program_policies',[])):
        row=lookup[(p['asset_id'],p['kind'])]
        for period,value in row.get('time_preference',{}).get('preferred_start_min',{}).items():
            path=f'program_policies[{i}].preferred_start_min.{period}'
            changes.append({'path':path,'before':p['preferred_start_min'][period],'after':value,'origin':'experimental_joint_soft_preference'})
            p['preferred_start_min'][period]=value
    for i,p in enumerate(result.get('thermostat_policies',[])):
        row=lookup[(p['asset_id'],'ac')]; value=row['cooling_preferred_C']
        # The original heating/setback/state controls remain separate and intact.
        if value <= p['heating_setpoint_C']:
            changes.append({'path':f'thermostat_policies[{i}].cooling_setpoint_C','applied':False,'reason':'original_heating_deadband_conflict'})
        else:
            changes.append({'path':f'thermostat_policies[{i}].cooling_setpoint_C','before':p['cooling_setpoint_C'],'after':value,'origin':'experimental_cooling_soft_preference'})
            p['cooling_setpoint_C']=value
    return result,changes


def clock(value):
    return f'{value//1440:+d}日 ' + f'{value%1440//60:02d}:{value%60:02d}' if value>=1440 else f'{value//60:02d}:{value%60:02d}'


def device_text(row):
    trade='更在意保持固定家务节奏，改动先商量' if row['tradeoff']=='preserve_routine' else '可以商量机器改时，但更在意少装取、少额外干预'
    kind=row['kind']
    if kind in ('washer','dishwasher','dryer'):
        time=row['time_preference']; starts=sorted({v for v in time['preferred_start_min'].values()})
        if not starts: starts=sorted({r['preferred_start_min']%1440 for r in time['per_service'] if r['preferred_start_min'] is not None})
        habit=('条件允许时偏好约'+ '、'.join(clock(v) for v in starts)+'运行；') if starts else '暂无足够依据给出可行的偏好时刻；'
        if kind=='dryer': habit='烘干跟随原洗衣链衔接，不独立指定一套随机启动时刻；'
        habit+=trade+'，保留完整程序和原服务期限。'
    elif kind=='ac': habit=f"制冷偏好约{row['cooling_preferred_C']:g}℃，"+('对短时温度变化较敏感' if row['coordinates']['comfort_sensitivity']>=0.5 else '可商量短时温度变化，但不愿反复干预')+'；制热、提前运行与停机另行确认。'
    elif kind=='water_heater': habit=('更重视提前备好热水，避免临时补救' if row['readiness_priority']>=0.5 else '在保证既定用水的前提下，更愿意减少不必要的加热运行')+'；不移动洗浴，不减少水量或出水要求。'
    else: habit=('更重视尽早备足出行电量' if row['readiness_priority']>=0.5 else '可以商量在原连接期内推迟充电')+'；原出行、连接和目标SOC不变。'
    if row['preferred_shift_limit_min'] is not None and kind in ('washer','dishwasher','dryer','ev'):
        value = row['preferred_shift_limit_min']
        habit+=(f"相对当前安排，偏好先讨论{value}分钟以内的改时；" if value else '倾向保留当前时刻，其他改时仍可逐案商量；')+'这是软偏好，不是新权限或拒绝阈值。'
    return habit


def attach(profile, joint):
    """One structure drives machine data and participant material."""
    if joint is None:return profile
    profile['joint_sampling']=joint; profile['schema']='eb.household_device_persona.v5'
    profile['role_label_scope']='fixed_household_core;members_have_within_class_differences_only'
    profile['bindings']['joint_sampling_profile_sha256']=joint['profile_sha256']
    for m in profile['household_preferences']['member_profiles']:
        m['sampled_preferences']=copy.deepcopy(joint['member_preferences'][m['member_id']])
    for device in profile['devices']:
        row=next(r for r in joint['devices'] if r['asset_id']==device['asset_id'] and r['kind']==device['kind'])
        device['sampled_preferences']=copy.deepcopy(row)
        device['habit']=device_text(row)
        device['adjustment_preference']=row['core']+'；'+device_text(row)
        auth=device['authorization']; auth['experimental_preference']=row['authorization_preference']
        contexts={mid:copy.deepcopy(joint['member_preferences'][mid]['preference_context']) for mid in auth['affected_member_ids'] if mid in joint['member_preferences']}
        device['sampled_preferences']['affected_member_preference_contexts']=contexts
        device['sampled_preferences']['member_tradeoff_tensions']=[mid for mid,c in contexts.items() if c['tradeoff']!=row['tradeoff']]
        confirm_members=[mid for mid,c in contexts.items() if c['confirmation_preferred']]
        auth['experimental_member_confirmation_preferred_ids']=confirm_members
        if (row['authorization_preference']=='confirm_each_proposal' or confirm_members) and auth['standing_consent_actions']:
            auth['standing_consent_actions']=[]; auth['mode']='experimental_preference_requires_confirmation'
            auth['narrative']='本户在原许可范围内仍偏好逐案确认；未声明的范围须另行授权。'
    return profile


def render(profile):
    labels={'washer':'洗衣','dryer':'烘干','dishwasher':'洗碗','ac':'空调','water_heater':'热水','ev':'充电'}
    f=profile['context_evidence']
    adults='、'.join(str(v) for v in f['member_ages_years'] if v>=18)
    children='、'.join(str(v) for v in f['member_ages_years'] if v<18)
    heading=f"家庭资料：{profile['household_id']}，{f['adult_count']}位成人（{adults}岁）"+(f"、{f['minor_count']}位未成年成员（{children}岁）" if children else '')+'。'
    holder=profile['confirmation_holder']
    holder_text=f"原登记确认人：成员{holder['member_index']}。" if holder and holder.get('member_index') else '方案仍由原登记确认人确认，不新增操作人或授权。'
    lines=[heading,profile['joint_sampling']['class_core']+'。',holder_text,
           f"原登记设备资产{len({d['asset_id'] for d in profile['devices']})}项；同一资产的洗衣、烘干服务仍算一台设备。"]
    for i,m in enumerate(profile['joint_sampling']['member_preferences'].values(),1):
        c=m['preference_context']
        lines.append(f'成员{i}：'+('条件允许时偏好较早处理设备家务，' if c['time_direction']=='earlier_when_feasible' else '条件允许时偏好较晚处理设备家务，')+
                     ('更在意维持固定节奏；' if c['tradeoff']=='preserve_routine' else '更在意减少额外操作；')+
                     ('调整先询问。' if c['confirmation_preferred'] else '仅在原许可边界内愿意交给系统择时。'))
    for d in profile['devices']:
        label=labels[d['kind']]+('（'+d['room_label']+'）' if d['kind']=='ac' else '')
        lines.append(label+'：'+d['habit']+' 授权：'+d['authorization']['narrative'])
        if d['kind']=='ac':
            affected=d['authorization']['affected_member_ids']
            values=d['sampled_preferences']['member_cooling_preferences_C']
            if affected:
                lines.append('该房间使用成员的制冷偏好：'+'、'.join(f"{mid.rsplit('-',1)[-1]}约{values[mid]:g}℃" for mid in affected if mid in values)+'；不把多人的意见平均成已获同意。')
    lines.append('来源：六类核心及制冷偏好支持范围参照EB；类内分布、关联强度及具体抽样结果为实验设定，不是实测习惯。家庭、设备、生活日程及原有服务/权限不变；未成年成员由原登记成人协调，不因此取得操作权。以上是候选画像，不改写封存A/B。')
    return '\n\n'.join(lines)+'\n'
