"""Synchronize actor facts and original renderer inputs; no synthetic actor answers."""
import collections,copy,csv,datetime as dt,html,re,shutil,subprocess
from common import *
from worlds import merge_ranges
from activity_model import dated
LABELS={'commuter_reference':'有工作来源提示；给定外出工作情景','home_work_reference':'有工作来源提示；给定居家工作情景',
 'flexible_work_reference':'有工作来源提示；给定混合地点工作情景','given_short_work_reference':'有工作来源提示；给定短时工作情景',
 'unknown_outside_commitments':'就业未知；给定外出事务，不指定职业','unknown_home_commitments':'就业未知；给定在家事务，不指定职业',
 'unknown_mixed_activity':'就业未知；给定居家与外出事务，不指定职业','home_commitments_reference':'无当前工作来源提示；给定居家事务',
 'community_activity_reference':'无当前工作来源提示；给定社区活动','mixed_activity_reference':'无当前工作来源提示；给定居家与社区事务',
 'given_home_care_reference':'给定家庭照护责任；来源就业状态另列','infant_home_care':'给定婴儿居家照护及小睡',
 'toddler_home_care':'给定幼儿居家照护及小睡','toddler_given_daycare':'给定幼儿日托及小睡，非实测入托',
 'preschool_home_care':'给定学前儿童居家照护','preschool_given_daycare':'给定学前日托，非实测入托','school_reference':'给定就学情景，非实测学籍'}
FAILURE_LABELS={'outside_given_operator_window':'该时段没有已给定可用操作人','operator_resource_conflict':'同一操作人同时有另一操作','vehicle_away':'车辆不在家','already_connected':'车辆已经接上充电线','not_connected':'车辆没有接上充电线','asset_not_empty':'设备中上一批物品尚未取走','program_interlock_active':'程序仍在运行，不能按此时直接取出','batch_not_available':'此时没有可取出的已完成批次','unclean_batch_removed_before_program':'启动前取走未洗物品，此批程序未启动','batch_program_missing':'没有对应的批次程序'}
OP_LABELS={'load':'装载','unload':'取出','EV_plug':'插枪','EV_unplug':'拔枪'}
NAMES={'ac':'空调','washer':'洗衣','dryer':'烘干','dishwasher':'洗碗','water_heater':'电热水器','ev':'电动车充电'}
ICONS={'water_heater':'electric_water_heater','ev':'home_ev'}
DAYLABELS={'national_holiday':'法定节假日','makeup_workday':'调休工作日','weekday':'普通工作日','weekend':'周末'}
TRANSPORTLABELS={'given_family_shared_vehicle':'家庭共用参考车辆','given_resident_driver':'居民驾驶的参考车辆','given_external_driving_service':'给定外部驾驶服务'}
def simple_clock(t):return f'{t//60:02d}:{t%60:02d}'
def person_label(w,member_id):
    member=next((m for m in w['members'] if m['member_id']==member_id),None)
    if member:return '成员'+member['local_id']
    names={'given_baseline_handling_service':'给定基线操作服务者','given_A_departure_care_provider':'给定离家操作照护者','given_home_caregiver':'给定共同居家照护者','given_external_driver':'给定外部驾驶服务者'}
    return names.get(str(member_id).split(':')[-1],'给定非同住协助者')
def actor(w):
    a=copy.deepcopy(read(SOURCE/'actors'/f'{w["household_id"]}.json'));p=a['profile'];old={m['member_id']:m for m in p['members']};members=[]
    for m in w['members']:
        s=m['daily_reference_specs'][0];rest=m['daily_reference_specs'][5]
        new={**copy.deepcopy(m),'relationship':old[m['member_id']]['relationship'],'sleep_room':m['reference_home_room_id'],
             'life_roles':LABELS[m['reference_activity_role']],
             'routine':f"工作日参考：{simple_clock(s['wake_min'])}起床、{simple_clock(s['sleep_min'])}休息；休息日参考：{simple_clock(rest['wake_min'])}起床、{simple_clock(rest['sleep_min'])}休息。钟点为本情景给定安排。",
             'weekday_home':'、'.join(f"{simple_clock(start)}—{simple_clock(end)}" for start,end in merge_ranges([[i['start_min'],i['end_min']] for i in m['weekly_calendar'][0]['intervals'] if i['location']=='home']))}
        members.append(new)
    p['joint_age_evidence']=w['joint_age_evidence'];p['reference_change_ledger']=w['reference_change_ledger'];p['baseline_assistance_contract']=w['baseline_assistance_contract'];p['activity_contract']=w['activity_contract'];p['care_contract']=w['care_contract'];p['members']=members;p['routine']=w['routine'];p['operating_context']=w['operating_context'];p['service_semantics']=w['service_semantics']
    p['device_instances']=[{k:copy.deepcopy(v) for k,v in d.items() if k not in ('previous_OEM_anchor','source_EB_usage_defaults_evidence')} for d in w['parameter_pack']['devices']];p['devices']=[]
    p['external_services']=copy.deepcopy(w['given_external_services']);p['external_services']['heating']='本参考模型给定最低18℃的外部供热边界；不属于六设备电力调度，实际费用和真实供暖条件未知'
    if any('daycare' in m['reference_activity_role'] for m in w['members']):p['external_services']['daycare_transport']='给定日托开放日有接送服务；非实测服务或额外居民'
    else:p['external_services']['daycare_transport']='幼儿居家照护情景；没有给定日托出行'
    for d in w['parameter_pack']['devices']:
        k=d['types'][0];p['devices'].append({'asset_id':d['asset_id'],'device_class':ICONS.get(k,k),'device':'洗烘一体机' if set(d['types'])=={'washer','dryer'} else NAMES[k],
           'functional_classes':d['types'],'zone':d['room_id'],'owned':None,'installed':True,'accessible':True,'controllable':True,'modelled':True,
           'parameters':copy.deepcopy(d['parameters']),'conditions_status':'给定参考设备，不代表实测持有'})
    p['household']['comfort_importance_1_5']=None;p['household']['saving_importance_1_5']=None
    p['household']['building_type']={'1_to3':'1—3层城市住宅参考','4_to7':'4—7层城市住宅参考','8_to33':'8—33层城市住宅参考'}.get(w['layout']['stock_reference_features']['building_storeys'],'城市住宅参考')
    p['household']['household_net_share_m2']=round(p['household']['household_net_share_m2'],2)
    p['household']['control_condition']='按给定设备、操作窗口和服务需求判断；额外协助、习惯变化和主观取舍由你表达，不预设采纳。'
    a['geometry']['reference_sleep_frames']=copy.deepcopy(w['layout']['sleep_reference']['frames'])
    a['geometry']['reference_berths']=copy.deepcopy(w['layout']['sleep_reference']['berths'])
    a['geometry']['reference_device_footprints']=[copy.deepcopy(x) for x in w['joint_matching']['spatial_witnesses'] if x['kind'] in ('laundry','dishwasher','tank')]
    a['geometry']['portals_are_non_swing_reference']=True
    a['geometry'].setdefault('zone_labels',{})['external_dedicated_EV_bay']='独立专用车位（住宅外）'
    a.update(source_world_content_sha256=w['world_content_sha256'],world_content_sha256=w['world_content_sha256'],parameter_pack_sha256=w['parameter_pack_sha256'],formal_human_answers=0,collection_release=False)
    return a
def rows(w,p,side):
    out=[];lo,hi=p['primary_evaluation_min']
    for d in w['parameter_pack']['devices']:
        events=[]
        for x in p[side]['tasks']+p[side]['controls']:
            if x['asset_id']!=d['asset_id'] or not overlap((x['start_min'],x['end_min']),(lo,hi)):continue
            typ=x['kind'];event={'start_abs_min':x['start_min'],'end_abs_min':x['end_min'],
                   'source_start_abs_min':x['start_min'],'source_end_abs_min':x['end_min'],
                   'operation_kind':'program_power' if typ in ('washer','dryer','dishwasher') else 'temperature_setpoint' if typ=='ac_setpoint' else 'heater_availability' if typ=='tank_setpoint' else 'charge_availability',
                   'operation_label':NAMES[typ]+'程序请求' if typ in NAMES else '空调设定' if typ=='ac_setpoint' else '允许加热' if typ=='tank_setpoint' else '允许充电'}
            if typ in NAMES:event['functional_class']=typ
            if 'value_C' in x:
                event['setpoint_C']=x['value_C'];event['operation_label']=('设定温度 ' if typ=='ac_setpoint' else '允许加热，目标 ')+f"{x['value_C']:g} ℃"
            if x['start_min']<lo or x['end_min']>hi:
                event['operation_label']+=f"（完整安排 {clock(x['start_min'])}—{clock(x['end_min'])}；图中仅显示相交部分）"
                event['end_status']='observation_cutoff' if x['end_min']>hi else 'complete'
            events.append(event)
        out.append({'asset_id':d['asset_id'],'device_class':ICONS.get(d['types'][0],d['types'][0]),'events':sorted(events,key=lambda x:x['start_abs_min']),'schedule_complete':True,'semantics':'requested instructions; executed program and service delivery are separately reported'})
    return {'window_start_abs_min':lo,'window_end_abs_min':hi,'rows':out,'semantics':'requested instructions; executed program and service delivery are separately reported'}
def commands(w,p):
    out=[];A={t['task_id']:t for t in p['A']['tasks']}
    for t in p['B']['tasks']:
        a=A[t['task_id']]
        if t==a:continue
        out.append({'asset_id':t['asset_id'],'device_class':ICONS.get(t['kind'],t['kind']),'kind':'event_interval',
            'start_abs_min':t['start_min'],'end_abs_min':t['end_min'],'A_start_abs_min':a['start_min'],'A_end_abs_min':a['end_min'],
            'display_change_text':f"{NAMES[t['kind']]}：{clock(a['start_min'])}—{clock(a['end_min'])} → {clock(t['start_min'])}—{clock(t['end_min'])}"})
    for c in p['B']['changed_controls']:
        k={'ac_setpoint':'ac','tank_setpoint':'water_heater','ev_charge_window':'ev'}[c['kind']]
        matches=[a for a in p['A']['controls'] if a['asset_id']==c['asset_id'] and a['kind']==c['kind']]
        a=min(matches,key=lambda a:abs(a['start_min']-c['start_min'])) if matches else None
        if c['kind']=='ac_setpoint' and a and c['value_C']==a.get('value_C'):continue
        text=('原未安排 → 请求 '+NAMES[k]+' '+clock(c['start_min'])+'—'+clock(c['end_min'])) if not a else (f"{NAMES[k]}：{clock(a['start_min'])}—{clock(a['end_min'])} → {clock(c['start_min'])}—{clock(c['end_min'])}")
        if 'value_C' in c:text+=f"；目标 {c['value_C']:g} ℃"+(f"（A：{a['value_C']:g} ℃）" if a and 'value_C' in a else '')
        out.append({'asset_id':c['asset_id'],'device_class':ICONS.get(k,k),'kind':'ac_setpoint' if k=='ac' else 'control_interval',
             'start_abs_min':c['start_min'],'end_abs_min':c['end_min'],'A_start_abs_min':a['start_min'] if a else c['start_min'],
             'A_end_abs_min':a['end_min'] if a else c['start_min'],'from_setpoint_C':a.get('value_C') if a else None,
             'to_setpoint_C':c.get('value_C'),'display_change_text':text})
    oa={o['operation_id']:o for o in p['A']['operations']}
    for o in p['B']['operations']:
        a=oa.get(o['operation_id'])
        if o==a:continue
        label={'unload':'取出物品','EV_plug':'插枪','EV_unplug':'拔枪','load':'装载'}.get(o['kind'],o['kind'])
        out.append({'asset_id':next((t['asset_id'] for t in p['B']['tasks'] if t['need_id']==o['need_id']),next((d['asset_id'] for d in w['parameter_pack']['devices'] if 'ev' in d['types']),w['parameter_pack']['devices'][0]['asset_id'])),
             'device_class':'home_ev' if o['kind'].startswith('EV') else next((t['kind'] for t in p['B']['tasks'] if t['need_id']==o['need_id']),'washer'),'kind':'handling_change',
             'start_abs_min':o['start_min'],'end_abs_min':o['end_min'],'A_start_abs_min':a['start_min'] if a else o['start_min'],'A_end_abs_min':a['end_min'] if a else o['start_min'],
             'display_change_text':f"请求{person_label(w,o['operator_id'])}在{clock(o['start_min'])}—{clock(o['end_min'])}{label}"+(f"（惯常：{clock(a['start_min'])}）" if a else '（额外操作，需要你判断是否愿意）')})
    assert out
    for i,c in enumerate(out):c['command_id']=p['case_id']+':requested-command:'+str(i+1).zfill(3)
    return out
def profile_for_day(w,a,p):
    prof=copy.deepcopy(a['profile']);day=p['dated_activity_days'][0]
    prof['current_reference_date']=day['date'];prof['current_day_type']=day['day_type']
    for m in prof['members']:
        spec=day['member_specs'][m['member_id']];ints=day['member_calendars'][m['member_id']]
        m['routine']=f"本情景{day['date']}（{DAYLABELS[day['day_type']]}）：{simple_clock(spec['wake_min'])}起床、{simple_clock(spec['sleep_min'])}休息。"+(f"白天小睡合计{spec['nap_min']}分钟；照护阶段为给定。" if spec['nap_min'] else '')
        m['weekday_home']='、'.join(simple_clock(a)+'—'+simple_clock(b) for a,b in merge_ranges([[i['start_min'],i['end_min']] for i in ints if i['location']=='home']))
        m['current_reference_calendar']=ints
        nxt=p['dated_activity_days'][1]['member_specs'][m['member_id']]
        m['routine']+=f"次日{p['dated_activity_days'][1]['date']}参考{simple_clock(nxt['wake_min'])}起床，{simple_clock(nxt['sleep_min'])}休息。"
        m['dated_context_calendars']=[{'date':d['date'],'intervals':d['member_calendars'][m['member_id']]} for d in p['dated_activity_days']]
    for o in prof['operating_context']['operators']:o['current_windows_min']=day['operator_windows_min'][o['operator_id']]
    return prof

def need_text(w,p):
    out=['本次完整一天：'+p['date']+' 08:00 至次日08:00；下面按实际日期列出跨夜与后续依赖。',
        '十个日期是同一角色快照的独立参考任务，年龄与照护阶段保持给定，非一户真实家庭的全年追踪。成员编号与家庭卡片对应。年龄为来源联合区间内的合成参考值；父母、子女等保留来源关系类别，生物、继亲或收养关系细分未知，不按年龄差编造身世。']
    for day_index,day in enumerate(p['dated_activity_days']):
        origin=1440*day_index
        out.append(day['date']+'（'+DAYLABELS[day['day_type']]+'）参考晚餐：'+clock(origin+day['family_context']['dinner_min'])+'。')
        for m in w['members']:
            spec=day['member_specs'][m['member_id']]
            out.append(day['date']+' '+person_label(w,m['member_id'])+'：'+simple_clock(spec['wake_min'])+'起床，'+simple_clock(spec['sleep_min'])+'休息；'+LABELS[m['reference_activity_role']]+'。')
        for oid,ws in day['operator_windows_min'].items():
            text='、'.join(clock(origin+a)+'—'+clock(origin+b) for a,b in ws) or '无已给定空闲窗'
            out.append(day['date']+' '+person_label(w,oid)+'可安排人工操作：'+text+'；可用性不表示愿意改变安排。')
        j=day['transport']
        if j:out.append(day['date']+' 给定车辆行程：'+person_label(w,j['travelling_member_id'])+'于'+clock(origin+j['departure_min'])+'出发，'+clock(origin+j['arrival_min'])+'返回；本次牵引服务需求'+str(j['traction_kWh'])+' kWh。85%电量目标与实际行程剂量分开。车辆插枪或电量不足时该参考行程不能交付，替代交通方式未知。')
        for child,assistant in day['family_context']['child_bathing_assistants'].items():
            if assistant:out.append(day['date']+' '+person_label(w,child)+'的洗浴由'+person_label(w,assistant)+'在'+clock(origin+day['family_context']['bath_times_min'][child])+'协助；能力和共同基线安排为给定，额外改变意愿未知。')
        visits=merge_ranges([[origin+v['start_min'],origin+v['end_min']] for v in day['external_visits'] if 'care coverage' in v['reason']])
        if visits:out.append(day['date']+' 共同照护预约：'+'、'.join(clock(a)+'—'+clock(b) for a,b in visits)+'；外部服务者不计常住成员，费用未知。')
    for booking in p['common_A_departure_care_bookings']:
        out.append('A必要离家操作已预订共同照护：'+clock(booking['start_min'])+'—'+clock(booking['end_min'])+'。B仅共享这段已授权服务，额外接替意愿未知。')
    hi=p['service_tail_min'][1]
    for n in p['needs_A']:
        if n['release_min']>=hi:continue
        if n['kind'] in ('washer','dishwasher') and not any(o['need_id']==n['need_id'] and o['end_min']>p['primary_evaluation_min'][0] for side in ('A','B') for o in p[side]['operations']):continue
        if n['kind']=='water_heater' and n['release_min']<p['primary_evaluation_min'][0]:continue
        if n['kind']=='ev' and n['deadline_min']<p['primary_evaluation_min'][0]:continue
        if n['kind'] in ('washer','dishwasher'):
            out.append(n['need_id'].split(':')[0]+'安排的'+NAMES[n['kind']]+'批次：'+n['service_purpose'].replace('次日',(dt.date.fromisoformat(n['need_id'].split(':')[0])+dt.timedelta(days=1)).isoformat())+'；程序完成期限'+clock(n['deadline_min'])+'，人工交付期限'+clock(n['delivery_deadline_min'])+'。此交付约定为给定任务条件，非实测个人偏好。')
            if n['kind']=='washer':out.append('本批质量'+str(n['quantity'])+' kg；频率来自历史匹配辅助资料，批量是参考剂量。'+('同一自动洗烘链完成后取出。' if n['wearable_clothes_ready_after_required_chain'] else '未配置烘干时，洗后可穿时间未知。'))
            programs=[t for t in p['A']['tasks'] if t['need_id'] in (n['need_id'],n['need_id']+':dry')]
            out.append('固定A程序：'+'；'.join(NAMES[t['kind']]+'于'+clock(t['start_min'])+'—'+clock(t['end_min']) for t in programs)+'；B改变的程序另列。')
            actions=[o for o in p['A']['operations'] if o['need_id']==n['need_id']]
            out.append('固定A操作：'+'；'.join(person_label(w,o['operator_id'])+'在'+clock(o['start_min'])+'—'+clock(o['end_min'])+({'load':'装载','unload':'取出'}.get(o['kind'],o['kind']))+('（已给定基线服务预约）' if o.get('given_baseline_booking') else '') for o in actions)+'。B中的改变另列；未改变的操作沿用A。')
        elif n['kind']=='water_heater':out.append(person_label(w,n['requester'])+'于'+clock(n['release_min'])+'洗浴10分钟，30 L混水，给定目标'+f"{n['target_C']:.1f}"+'℃；剂量来自原EB参考任务，非年龄实测用水。')
        elif n['kind']=='ev':
            cfg=next(d['parameters'] for d in w['parameter_pack']['devices'] if 'ev' in d['types'])
            out.append(f"参考车辆电池{cfg['capacity_kwh']:g} kWh，充电器{cfg['charger_kw']:g} kW，参考效率{cfg['efficiency']*100:g}%；{cfg['min_soc']*100:g}%保留目标与85%可用目标分别判断，非实测偏好。")
            out.append('车辆可用期限'+clock(n['deadline_min'])+'，给定85%目标；'+('该时点有下一次给定行程。' if n['next_access_is_actual_trip'] else '该时点仅为车辆可用目标，没有额外给定行程。'))
            out.append('固定A车辆操作：'+'；'.join(person_label(w,o['operator_id'])+'在'+clock(o['start_min'])+'—'+clock(o['end_min'])+('插枪' if o['kind']=='EV_plug' else '拔枪')+('（基线服务预约）' if o.get('given_baseline_booking') else '') for o in p['A']['operations'] if o['need_id']==n['need_id'] and o['kind'].startswith('EV_'))+'。驾驶授权为给定条件，来源驾照未知。')
    original=w['evidence_layer']['original_housing_facets'];configured=w['layout']['stock_reference_features']
    for field in ('piped_water','bathing_hot_water'):
        if original[field]!=configured[field]:
            label={'piped_water':'管道供水','bathing_hot_water':'洗浴热水'}[field]
            words={'absent':'未给定管道供水','present':'给定管道供水','none':'无热水设施参考','self_installed_heater':'给定本户电热水器','central_supply':'集中热水参考'}
            out.append('原住房参考与当前配置分开：'+label+'，原参考为'+words.get(original[field],str(original[field]))+'；当前任务为'+words.get(configured[field],str(configured[field]))+'。此配置为任务设计，不是来源家庭的改造记录或全国持有率。')
    limits=w['parameter_pack']
    out.append(f"本任务给定住宅功率边界{limits['home_service_limit_kw']:g} kW（独立EV回路另计）；各给定回路上限为"+'、'.join(({'AC':'空调回路','EV_bay':'独立充电回路','hot_water':'热水回路','wet_appliances':'洗烘与洗碗回路'}.get(k,k)+f" {v:g} kW") for k,v in limits['circuit_limit_kw'].items())+'。这些是规划边界，仿真不模拟断路保护动作，不代表该住房实测供电容量。')
    out+=['程序、人工装取与实际交付分开：运行中提前取出在本参考设备中失败；延时启动前取走未洗物品会取消该批程序；不会自动补做。车辆只有在场、已连接且允许充电时才有充电电量。',
        '未满6岁儿童在家需满足给定监督或成人在场条件，睡眠也保留成人在场。家庭卡片里的青少年不自动承担额外照护。',
        '26℃设定、27℃控制边界、85%SOC和服务期限均为给定条件；主观舒适、重要性、改变习惯和额外协助意愿由你表达。',
        '睡眠可有给定制冷；房间、照明和空调从同一日程及实际操作派生。校历为注明地区的迁移参考，非实测学籍。',
        '仿真按共同给定作息保持其余活动；交通或服务失败后是否改变外出、改用其他方式等未知，不把固定作息的条件计算说成你的实际行为。',
        '参考电量包含六设备和明示的背景电力；18℃外部供热不计入该电量。尾段是有限观察，A/B末态可能不同，不把耗尽电池或未交付服务当作等服务净节能。']
    return out

def scene(w,h,p,a):
    path=OUT/'readback/base7'/w['household_id']/f'{p["round_index"]:02d}.json';r=read(path) if path.exists() else None
    prof={'role_id':w['household_id'],'sha256':digest(profile_for_day(w,a,p)),'profile':profile_for_day(w,a,p),'geometry':a['geometry'],'source_actor_profile_sha256':digest(a['profile']),'source_world_sha256':w['world_content_sha256']}
    cmd=commands(w,p);plans={s:rows(w,p,s) for s in ('A','B')};quantities=[];impacts=[]
    state='物理前态尚未回读，本页用于角色材料检查。'
    if r:
        temps=[v for k,v in r['pre_event_state']['A'].items() if k.startswith('Zone Mean Air Temperature|')]
        if temps:state=f'通知前模型房间空气温度 {min(temps):.1f}—{max(temps):.1f}℃。空气温度不等于个人舒适。'
        tank=[v for k,v in r['pre_event_state']['A'].items() if k.startswith('Water Heater Tank Temperature|')]
        if tank:state+=f'水箱模型平均温度{tank[0]:.1f}℃。'
        if 'pre_event_EV_SOC' in r:state+=f"参考车辆通知前电量{r['pre_event_EV_SOC']['A']*100:.1f}%。"
        for k,label in [('event','目标时段参考电力'),('living_day','完整24小时参考电力'),('living_day_and_service_tail','完整一天及有限后续服务尾段电力')]:
            quantities.append({'label':label,**{s:{'value':r['energy'][k][s],'unit':'kWh','status':'computed'} for s in ('A','B')},'scope':k,'evidence_sha256':digest(r)})
        for s in ('A','B'):
            need_index={n['need_id']:n for n in p['needs_A']}
            for n in r['services'][s].get('hot_water',[]):
                need=need_index[n['need_id']];scope='后续服务' if need['release_min']>=p['primary_evaluation_min'][1] else '本次完整一天'
                impacts.append({'status':'computed','service_need_id':n['need_id'],'description':f"{s}（{scope}）：{clock(need['release_min'])}{person_label(w,need['requester'])}模型混水温度{n['minimum_mixed_C']:.1f}℃，给定目标{n['target_C']:.1f}℃。"})
            for trip in r['services'][s].get('EV',{}).get('trips',[]):
                delivered=trip['traction_delivered_kWh']
                text=(f"按给定行程交付参考牵引能量{delivered:g} kWh" if trip['trip_departed'] else '未交付此给定行程'+('，车辆仍接着充电线' if trip['departure_connection_conflict'] else f"，电量缺口{trip['shortfall_kWh']:.2f} kWh"))
                impacts.append({'status':'computed','description':s+' '+clock(trip['minute_relative_to_target'])+'：'+text+'；替代交通与因此改变外出安排均未知。'})
            for n in r['services'][s].get('EV',{}).get('goals',[]):
                scope='后续服务' if n['deadline_min']>p['primary_evaluation_min'][1] else '本次完整一天'
                impacts.append({'status':'computed','description':f"{s}（{scope}）：{clock(n['deadline_min'])}前模型SOC {n['actual_SOC_before_any_trip_debit']*100:.1f}%，参考目标85%；是否有出行另按给定日程。"})
    for side in ('A','B'):
        ex=p['service_execution_reference'][side]
        for item in ex['program_services']:
            need=next(n for n in p['needs_A'] if n['need_id']==item['need_id'])
            if not any(o['need_id']==need['need_id'] and o['end_min']>p['primary_evaluation_min'][0] for arm in ('A','B') for o in p[arm]['operations']):continue
            need_label=need['need_id'].split(':')[0]+'的'+NAMES[need['kind']]+'批次'
            impacts.append({'status':'computed_design_execution','description':side+' '+need_label+'：'+('按给定期限完成并取出交付。' if item['delivered_before_given_bound'] else '未按给定期限交付；程序运行与取出是否成功分别记录。')})
        for item in ex['operations']:
            if not item['succeeded']:impacts.append({'status':'computed_design_execution','description':side+' 在'+clock(item['start_min'])+'的'+OP_LABELS.get(item['kind'],item['kind'])+'执行条件未满足：'+FAILURE_LABELS.get(item['failure_reason'],'未满足已给定操作条件')+'；这是条件执行结果，不预设你拒绝B。'})
        if p['post_operation_care'][side]:impacts.append({'status':'computed_design_execution','description':side+'有离家操作未满足已给定成人在场条件；额外照护需要你协商，青少年不自动接替。'})
    if r:
        for side in ('A','B'):
            limit=r['services'][side]['power_limits']
            impacts.append({'status':'computed','description':side+'住宅参考电力峰值'+f"{limit['residential_peak_excluding_dedicated_EV_kW']:.2f}"+' kW（EV独立计）；'+('超出给定规划边界，服务结果只是假设指令供电时的模型后果，不能保证可实行。' if limit['home_exceeded'] or limit['circuit_exceeded'] else '在所列给定功率边界内；不构成实测供电或配电认证。')})
            for item in r['services'][side]['room_air']:
                room_label=a['geometry'].get('zone_labels',{}).get(item['room_id'],item['room_id'])
                impacts.append({'status':'computed','description':side+' '+room_label+'完整一天模型空气温度'+f"{item['min_C']:.1f}—{item['max_C']:.1f}"+'℃，不等于个人舒适评价。'})
        related_rooms={d['room_id'] for d in w['parameter_pack']['devices'] if d['asset_id'] in {x['asset_id'] for x in cmd}}
        for side in ('A','B'):
            for item in r['services'][side].get('room_air_by_scope',{}).get('event',[]):
                if item['room_id'] not in related_rooms:continue
                label=a['geometry'].get('zone_labels',{}).get(item['room_id'],item['room_id'])
                impacts.append({'status':'computed','description':side+' '+label+'目标时段模型空气温度'+f"{item['min_C']:.1f}—{item['max_C']:.1f}"+'℃；是给定模型条件结果，个人舒适由你评价。'})
            if r['services'][side].get('AC_curve_boundary',{}).get('status')=='original_boundary_used':
                impacts.append({'status':'computed_model_boundary','description':side+'在本案例使用了原空调温度修正范围外的模型边界截断；相关后果保留，不能视为范围外真实设备性能已验证。'})
            delta=r.get('terminal_EV_storage')
        if delta:impacts.append({'status':'computed','description':'尾段结束B相对A电池储能差'+f"{delta['B_minus_A_kWh']:.3f}"+' kWh；若补至A储能，按参考效率额外需电'+f"{delta['B_additional_grid_replenishment_to_A_if_negative_kWh']:.3f}"+' kWh（解析估算，尚未仿真恢复）。'})
        impacts.append({'status':'computed','description':'有限尾段末态与A/B服务未强制一致；此处电量比较不构成等服务净节能结论。'})
    if r:
        variants=[r]
        for variant in ('prior14','seasonal7','seasonal14','temperature_flat7'):
            variant_path=OUT/'readback'/variant/w['household_id']/f'{p["round_index"]:02d}.json'
            if variant_path.exists():variants.append(read(variant_path))
        if len(variants)>1:
            deltas=[x['energy']['living_day']['A_minus_B_kWh'] for x in variants]
            impacts.append({'status':'computed','description':f"同一案例在已检查的前史、入水及空调模型假设下，完整一天A减B的电量差为{min(deltas):.3f}—{max(deltas):.3f} kWh。这是已检查情景范围，不是实测置信区间。"})
    if r is None:impacts.append({'status':'physical_pending','description':'用电量、房间温度和水温等物理结果尚未回读；下面的程序与操作后果仅依据已给定执行条件。'})
    if any('ac' in d['types'] for d in w['parameter_pack']['devices']):
        impacts.append({'status':'given_reference_model_boundary','description':'空调采用原EB定速DX参考模型；室内湿球12.78—23.89℃、室外干球21.11—46.11℃范围外，性能修正按模型边界截断。相关电量和温度为该模型条件结果，未验证为范围外真实设备性能；不是品牌实测或个人舒适结论。'})
    vpp={'start_abs_min':p['event_window_min'][0],'end_abs_min':p['event_window_min'][1],'notice_abs_min':p['decision_abs_min'],
         'household_request':{'text':'参考任务：目标时段平均负荷比A降低0.5 kW；按给定需求判断B及协商条件'},'incentive':None}
    physical={'status':'computed_reference' if r else 'pending','channels':[]}
    if r:physical['channels']=[{'label':'参考电力','unit':'kWh',**{s:{'status':'computed','value':r['energy']['event'][s]} for s in ('A','B')},'evidence_sha256':digest(r),'start_abs_min':p['event_window_min'][0],'end_abs_min':p['event_window_min'][1]}]
    c={'schema':'eb.joint_b.consumer.v2','identity':{'role_id':w['household_id'],'case_id':p['case_id'],'date':p['date'],'round_index':p['round_index'],'day_index':0,'split':None},
       'profile':prof,'plans':plans,'commands':cmd,'vpp':vpp,'context':{'daily_need_texts':need_text(w,p),'weather_days':weather(h['weather']['path'],p['date']),
       'pre_event_state':{'display_text':state}},'quantities':quantities,'impacts':impacts,'physical':physical,
       'after_horizon':{'status':'reported_model_tail' if r else 'pending','service_tail_min':p['service_tail_min'],'terminal_states':r['terminal_states'] if r else None},
       'display_assignment':{'left':'A','right':'B'},'audit':{'source_pair_sha256':h['pair_sha256'],'physical_calibration_complete':False},
       'human_label_count':0,'collection_release':False,'training_release':False}
    c['bindings']={k:digest(v) for k,v in [('profile_sha256',prof),('commands_sha256',cmd),('A_plan_sha256',plans['A']),('B_plan_sha256',plans['B']),('vpp_sha256',vpp),('physical_sha256',physical)]}
    c['bindings']['source_pair_sha256']=h['pair_sha256'];return c
WEATHER_CACHE={}
def weather(path,date):
    if path not in WEATHER_CACHE:
        with Path(path).open() as f:
            for _ in range(8):next(f)
            WEATHER_CACHE[path]={(int(r[1]),int(r[2]),int(r[3])):float(r[6]) for r in csv.reader(f)}
    start=dt.date.fromisoformat(date);nxt=start+dt.timedelta(days=1);cache=WEATHER_CACHE[path]
    values=[cache[start.month,start.day,h] for h in range(9,25)]+[cache[nxt.month,nxt.day,h] for h in range(1,9)]
    return [{'date':date,'window_start_abs_min':480,'window_end_abs_min':1920,'min_drybulb_C_derived':min(values),
             'max_drybulb_C_derived':max(values),'scope':'reference EPW input in08:00-to08:00 window; not actual2025 weather or a calibrated forecast'}]
def data_materials():
    school_guard();sel=read(OUT/'SELECTION1000.json');actor_bindings=[];consumer_bindings=[]
    for h in sel['records']:
        w=read(OUT/h['world_path']);a=actor(w);path=OUT/'actors'/f'{w["household_id"]}.json';save(path,a)
        actor_bindings.append({'household_id':w['household_id'],'actor_path':str(path.relative_to(OUT)),'actor_sha256':sha(path),'world_sha256':h['world_sha256']})
        cases=[]
        for row in h['rounds']:
            p=read(OUT/row['pair_path']);c=scene(w,{**row,'weather':h['weather']},p,a);cases.append(c)
            path=OUT/'consumers'/w['household_id']/f'{row["round_index"]:02d}.json';save(path,c)
            consumer_bindings.append({'case_id':p['case_id'],'consumer_path':str(path.relative_to(OUT)),'consumer_sha256':sha(path),'pair_sha256':row['pair_sha256']})
        save(OUT/'collection_materials'/w['household_id']/'TASKS10.json',cases)
    save(OUT/'ACTOR_BINDINGS.json',{'records':actor_bindings,'human_answers':0});save(OUT/'CONSUMER_BINDINGS.json',{'records':consumer_bindings,'human_answers':0})
def main():
    school_guard()
    if '--frontend-only' not in __import__('sys').argv:data_materials()
    actor_bindings=read(OUT/'ACTOR_BINDINGS.json')['records'];consumer_bindings=read(OUT/'CONSUMER_BINDINGS.json')['records']
    template=(PILOT/'frontend_snapshot/index.html').read_text();release=OUT/'frontend_release';index=[]
    assets=['style.css','candidate.css','joint-view.css','plan-view.js','source-draft.js','household-view.js','joint-view.js']
    for h in read(OUT/'SELECTION50.json')['records']:
        hid=h['household_id'];w=read(OUT/h['world_path']);cases=read(OUT/'collection_materials'/hid/'TASKS10.json');prof=cases[0]['profile'];site=release/'households'/hid;site.mkdir(parents=True,exist_ok=True)
        page=template;values={'profile-data':{hid:prof},'source-cases-data':{hid:[]},'source-selection-data':{hid:{}},'joint-cases-data':cases,
             'visible-inputs-data':[{'schema':'eb.joint_b.semantic_input.v1','date':c['identity']['date'],'profile':c['profile']['profile'],'plans':c['plans'],'given_context':c['context']} for c in cases],
             'source-hashes-data':[digest(c) for c in cases]}
        for key,value in values.items():
            page,n=re.subn(r'(<script[^>]+id="'+key+r'"[^>]*>).*?(</script>)',lambda m:m[1]+canonical(value).replace('<','\\u003c')+m[2],page,flags=re.S);assert n==1,key
        route='/household50-'+hid
        for name in assets:page=page.replace('href="'+name+'"','href="'+route+'/'+name+'"').replace('src="'+name+'"','src="'+route+'/'+name+'"')
        page=page.replace('每台设备上方是原安排 A，下方是调整后 B；','每台设备上方是原安排 A，下方是B请求；实际运行和服务交付另列。')
        (site/'index.html').write_text(page)
        for name in assets:shutil.copyfile(PILOT/'frontend_snapshot'/name,site/name)
        pv=site/'plan-view.js';pv.write_text(pv.read_text().replace("const label=thermal?s.label:device==='home_ev'?'充电':'运行'","const label=s.label||(thermal?s.label:device==='home_ev'?'充电':'运行')",1))
        pv.write_text(pv.read_text().replace('仍有运行记录','安排延续').replace('此时安排延续','此时安排仍延续'))
        js=site/'joint-view.js';s=js.read_text().replace("if(command.kind==='ac_setpoint')difference=","if(command.display_change_text)difference=command.display_change_text;\n   else if(command.kind==='ac_setpoint')difference=",1)
        s=s.replace('function focusWindow(c){','function focusWindow(c){\n  const explicitStart=c.plans.A.window_start_abs_min, explicitEnd=c.plans.A.window_end_abs_min;\n  if(Number.isFinite(explicitStart)&&Number.isFinite(explicitEnd)&&explicitEnd-explicitStart===1440)return [explicitStart,explicitEnd];',1)
        s=s.replace("const label=e=>e.operation_kind","const label=e=>e.operation_label|| (e.operation_kind",1).replace("'安排时段';","'安排时段');",1)
        s=s.replace('renderHome(c.identity.role_id);','PROFILES[c.identity.role_id]=c.profile;renderHome(c.identity.role_id);',1)
        s=s.replace("const modelFieldIds=snapshotIds.filter","const fixedScoreQuestion=typeof document==='undefined'?null:q('score-question').cloneNode(true);fixedScoreQuestion?.querySelectorAll('input,textarea,select,output,.score-meaning').forEach(e=>e.remove());const fixedScoreQuestionText=fixedScoreQuestion?.textContent||'';\n const modelFieldIds=snapshotIds.filter",1)
        s=s.replace("const e=q(id);if(id==='joint-needs-list'","const e=q(id);if(id==='score-question')return [id,fixedScoreQuestionText];if(id==='joint-needs-list'",1)
        s=s.replace('modelInputFromSnapshot(rendered,auditInput.display_assignment)', 'modelInputFromSnapshot(rendered,auditInput.display_assignment,auditInput.history||[])',1)
        s=s.replace("async function show(i){","for(const id of ['joint-needs','joint-plan-details'])q(id).addEventListener('toggle',()=>{if(currentInput&&presentedAt)currentInput.history.push({kind:'visible_context_observation',recorded_at:new Date().toISOString(),fields:snapshot()});});\n async function show(i){",1)
        visual_code="""function visibleVisuals(id){const box=q(id);if(box.closest?.('[hidden]'))return [];const allowed=new Set(['viewBox','points','x','y','width','height','x1','y1','x2','y2','cx','cy','r','rx','ry','d','transform','fill','stroke','stroke-width']);return [...box.querySelectorAll('svg')].map(svg=>({viewBox:svg.getAttribute('viewBox'),marks:[...svg.querySelectorAll('path,polygon,rect,line,circle,ellipse,text')].filter(m=>!m.closest('defs,symbol,[hidden]')&&getComputedStyle(m).display!=='none'&&getComputedStyle(m).visibility!=='hidden').map(m=>({tag:m.tagName.toLowerCase(),attributes:Object.fromEntries([...m.attributes].filter(a=>allowed.has(a.name)).map(a=>[a.name,a.value])),transform_matrix:m.getCTM?(()=>{const t=m.getCTM();return t?[t.a,t.b,t.c,t.d,t.e,t.f]:null;})():null,text:m.tagName.toLowerCase()==='text'?m.textContent:null,fill:getComputedStyle(m).fill,stroke:getComputedStyle(m).stroke}))}));}
 """
        s=s.replace('function snapshot(){return Object.fromEntries',visual_code+'function snapshot(){const fields=Object.fromEntries',1)
        s=s.replace("e.innerText:e.textContent];}));}","e.innerText:e.textContent];}));fields['visible-visuals']=canonical({home:visibleVisuals('home-visual'),timeline:visibleVisuals('joint-timeline')});return fields;}",1)
        s=s.replace("id!=='joint-date'&&id!=='joint-history');","id!=='joint-date'&&id!=='joint-history').concat(['visible-visuals']);",1)
        s=s.replace("history_status:'not_loaded_local_preview'","history_status:'current_context_observations_saved;previous_actor_answers_not_loaded'")
        s=s.replace("proposal:'调整后 B'","proposal:'请求安排 B'").replace('上行为原安排，下行为调整后。','上行为原安排，下行为B请求；是否运行和交付另见后果。')
        js.write_text(s)
        hv=site/'household-view.js';view=hv.read_text().replace('工作日通常在家：','基础日程在家（人工操作另列）：').replace('${member.relationship} ·', "成员${member.local_id} · ${member.relationship} · ${member.sex==='female'?'女':member.sex==='male'?'男':'性别未知'} ·")
        view=view.replace('for(const item of profile.devices||[])if(item.device_class===', 'for(const item of geometry.reference_device_footprints?[]:(profile.devices||[]))if(item.device_class===',1)
        view=view.replace('for(const item of geometry.decorative_furniture||[])furniture(item.zone,item.kind);', """if(geometry.reference_sleep_frames){for(const f of geometry.reference_sleep_frames){const r=f.outer_rect_m,a=xy([r[0],r[1]]),b=xy([r[2],r[3]]);picture.append(svg('rect',{x:Math.min(a[0],b[0]),y:Math.min(a[1],b[1]),width:Math.abs(b[0]-a[0]),height:Math.abs(b[1]-a[1]),fill:'#edf4eb',stroke:'#8dac97','stroke-width':1.5}));if(f.kind==='bunk')picture.append(svg('text',{x:(a[0]+b[0])/2,y:(a[1]+b[1])/2,'text-anchor':'middle','font-size':10},'双层'));}}else{for(const item of geometry.decorative_furniture||[])furniture(item.zone,item.kind);}
  for(const f of geometry.reference_device_footprints||[]){const r=f.body_rect_m,a=xy([r[0],r[1]]),b=xy([r[2],r[3]]);picture.append(svg('rect',{x:Math.min(a[0],b[0]),y:Math.min(a[1],b[1]),width:Math.abs(b[0]-a[0]),height:Math.abs(b[1]-a[1]),fill:'#d4e8e8',stroke:'#7aaba7','stroke-width':1}));}""",1)
        view=view.replace('else{const length=Math.hypot(', 'else if(!geometry.portals_are_non_swing_reference){const length=Math.hypot(',1)
        view=view.replace('$("home-caption").textContent="住宅布局";', '$("home-caption").textContent="参考住宅布局；床位及目标设备位置按本任务设计，门位为给定通道。";',1)
        hv.write_text(view)
        assert 'constraint_assessment' not in page and 'design_condition' not in page
        index.append({'household_id':hid,'route':route,'N':w['N'],'G':w['G'],'province':w['province'],'K':h['K'],'cases':10,'case_hashes':values['source-hashes-data']})
    shutil.copyfile(PILOT/'code/serve50.py',release/'serve50.py')
    shutil.copyfile(PILOT/'frontend_snapshot/unified_live_server.py',release/'unified_live_server.py')
    save(release/'INDEX50.json',{'households':index,'pairs':500,'engineering_only':True,'human_collection_release':False,'training_release':False})
    save(OUT/'MATERIALS_REVIEW.json',{'actor_cards':len(actor_bindings),'consumer_tasks':len(consumer_bindings),'original_frontend_households':len(index),
      'original_layout_questions_submit_contract_preserved':True,'source_design_labels_hidden':True,
      'physical_missing_explicit_pending':True,'human_answers':0,'live_deployment_changed':False})
    print(read(OUT/'MATERIALS_REVIEW.json'),flush=True)
if __name__=='__main__':main()
