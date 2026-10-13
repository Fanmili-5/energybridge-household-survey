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
NAMES={'ac':'空调','washer':'洗衣','dryer':'烘干','dishwasher':'洗碗','water_heater':'电热水器','ev':'电动车充电'}
ICONS={'water_heater':'electric_water_heater','ev':'home_ev'}
DAYLABELS={'national_holiday':'法定节假日','makeup_workday':'调休工作日','weekday':'普通工作日','weekend':'周末'}
TRANSPORTLABELS={'given_family_shared_vehicle':'家庭共用参考车辆','given_resident_driver':'居民驾驶的参考车辆','given_external_driving_service':'给定外部驾驶服务'}
def simple_clock(t):return f'{t//60:02d}:{t%60:02d}'
def person_label(w,member_id):
    member=next((m for m in w['members'] if m['member_id']==member_id),None)
    return '成员'+member['local_id'] if member else '给定非同住协助者'
def actor(w):
    a=copy.deepcopy(read(SOURCE/'actors'/f'{w["household_id"]}.json'));p=a['profile'];old={m['member_id']:m for m in p['members']};members=[]
    for m in w['members']:
        s=m['daily_reference_specs'][0];rest=m['daily_reference_specs'][5]
        new={**copy.deepcopy(m),'relationship':old[m['member_id']]['relationship'],'sleep_room':m['reference_home_room_id'],
             'life_roles':LABELS[m['reference_activity_role']],
             'routine':f"工作日参考：{simple_clock(s['wake_min'])}起床、{simple_clock(s['sleep_min'])}休息；休息日参考：{simple_clock(rest['wake_min'])}起床、{simple_clock(rest['sleep_min'])}休息。钟点为本情景给定安排。",
             'weekday_home':'、'.join(f"{simple_clock(start)}—{simple_clock(end)}" for start,end in merge_ranges([[i['start_min'],i['end_min']] for i in m['weekly_calendar'][0]['intervals'] if i['location']=='home']))}
        members.append(new)
    p['activity_contract']=w['activity_contract'];p['care_contract']=w['care_contract'];p['members']=members;p['routine']=w['routine'];p['operating_context']=w['operating_context'];p['service_semantics']=w['service_semantics']
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
                   'operation_label':NAMES[typ]+'程序' if typ in NAMES else '空调设定' if typ=='ac_setpoint' else '允许加热' if typ=='tank_setpoint' else '允许充电'}
            if typ in NAMES:event['functional_class']=typ
            if 'value_C' in x:
                event['setpoint_C']=x['value_C'];event['operation_label']=('设定温度 ' if typ=='ac_setpoint' else '允许加热，目标 ')+f"{x['value_C']:g} ℃"
            if x['start_min']<lo or x['end_min']>hi:
                event['operation_label']+=f"（完整安排 {clock(x['start_min'])}—{clock(x['end_min'])}；图中仅显示相交部分）"
                event['end_status']='observation_cutoff' if x['end_min']>hi else 'complete'
            events.append(event)
        out.append({'asset_id':d['asset_id'],'device_class':ICONS.get(d['types'][0],d['types'][0]),'events':sorted(events,key=lambda x:x['start_abs_min']),'schedule_complete':True})
    return {'window_start_abs_min':lo,'window_end_abs_min':hi,'rows':out}
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
    for o in prof['operating_context']['operators']:o['current_windows_min']=day['operator_windows_min'][o['operator_id']]
    return prof

def need_text(w,p):
    day=p['dated_activity_days'][0];family=day['family_context']
    out=['本次完整一天：'+p['date']+' 08:00 至次日08:00；跨夜服务和后续期限分别显示。',
        '十个日期使用同一给定年龄、成员关系和照护阶段；日期决定当天日型与参考天气。请按本题条件扮演和判断。',
        f"本日为{DAYLABELS[day['day_type']]}情景；家庭晚餐参考时点{clock(family['dinner_min'])}，婴幼儿进餐按自身作息单列。"]
    for m in w['members']:
        spec=day['member_specs'][m['member_id']]
        out.append(f"成员{m['local_id']}（{m['age_years']}岁）：{LABELS[m['reference_activity_role']]}；{simple_clock(spec['wake_min'])}起床、{simple_clock(spec['sleep_min'])}休息。"+(f"白天小睡合计{spec['nap_min']}分钟。" if spec['nap_min'] else ''))
        labels={'home_work':'居家工作','work':'外出工作','home_commitment':'给定在家事务','unclassified_outside_commitment':'给定外出事务','childcare_supervision':'照护监督','child_bathing_assistance':'儿童洗浴协助','school_home_study':'在家学习'}
        for activity,label in labels.items():
            spans=merge_ranges([[i['start_min'],i['end_min']] for i in day['member_calendars'][m['member_id']] if i['activity']==activity])
            if spans:out.append(person_label(w,m['member_id'])+'的'+label+'：'+'、'.join(simple_clock(a)+'—'+simple_clock(b) for a,b in spans)+'。')
    for o in w['operating_context']['operators']:
        text='、'.join(simple_clock(a)+'—'+simple_clock(b) for a,b in day['operator_windows_min'][o['operator_id']])
        out.append(person_label(w,o['operator_id'])+'的当天已明确空闲的人工操作窗：'+text+'；表示能安排操作，额外协助意愿未知。')
    care=day['care_context']
    if care['under6_supervision_child_ids']:
        out.append('未满6岁儿童在家时使用本日给定照护分工，日托儿童闭园或接送前后也按居家时段安排。基础作息中睡眠时有成人或给定照护服务在场；额外离家操作是否需要照护接替，请结合本题时间提出条件，不预设愿意。')
        people=sorted({e['responsible_person_id'] for e in day['supervision_ledger']})
        for who in people:
            spans=merge_ranges([[e['start_min'],e['end_min']] for e in day['supervision_ledger'] if e['responsible_person_id']==who])
            out.append(person_label(w,who)+'负责本日给定监督：'+'、'.join(simple_clock(a)+'—'+simple_clock(b) for a,b in spans)+'。')
        visits=merge_ranges([[v['start_min'],v['end_min']] for v in day['external_visits'] if 'care coverage' in v['reason']])
        out.append('给定外部照护预约：'+('、'.join(simple_clock(a)+'—'+simple_clock(b) for a,b in visits) if visits else '本日没有')+'；不计入常住人数，服务和费用均非实测。')
    for n in p['needs_A']:
        if n['kind'] in ('washer','dishwasher') and n['release_min']<1440:
            out.append(f"参考服务：{NAMES[n['kind']]}完成期限{clock(n['deadline_min'])}；取用期限{clock(n['delivery_deadline_min'])}。"+('洗涤后仍需自动烘干，再按期限取出。' if n['kind']=='washer' and n['wearable_clothes_ready_after_required_chain'] else '没有烘干时衣物可穿时间未知。' if n['kind']=='washer' else '程序结束与人工取出分开。'))
            actual=[o for o in p['A']['operations'] if o['need_id']==n['need_id']]
            out.append(NAMES[n['kind']]+'固定A的人工操作：'+'；'.join(person_label(w,o['operator_id'])+'在'+clock(o['start_min'])+'—'+clock(o['end_min'])+({'load':'装载','unload':'取出'}.get(o['kind'],o['kind'])) for o in actual)+'。B中的变化另列；未改变的操作继续沿用A。')
        if n['kind']=='water_heater' and n['release_min']<1440:out.append(f"{person_label(w,n['requester'])}：{clock(n['release_min'])}起参考洗浴10分钟，30 L混水，给定目标{n['target_C']:.1f}℃；这是EB服务剂量，非该年龄实测用水。")
        if n['kind']=='ev' and n['release_min']<1440:
            tc=w['given_transport_contract'];j=n['journey'];driver=person_label(w,tc['driver_id'])
            out.append(f"交通资源：{TRANSPORTLABELS[tc['mode']]}；{driver}执行给定行程。驾驶授权为本情景给定，来源驾照信息未知。")
            actual=[o for o in p['A']['operations'] if o['need_id']==n['need_id'] and o['kind'] in ('EV_plug','EV_unplug')]
            out.append('本题固定A的人工操作：'+'；'.join(person_label(w,o['operator_id'])+'在'+clock(o['start_min'])+'—'+clock(o['end_min'])+('插枪' if o['kind']=='EV_plug' else '拔枪') for o in actual)+'。设备参考联系人与实际操作人可不同；B提出的变化另列，额外协助意愿未知。')
            out.append(f"给定行程：{clock(n['trip_departure_min'])}出发，耗电{n['quantity']:g} kWh；{clock(n['deadline_min'])}前参考SOC目标85%。"+('该次可用时间有给定行程。' if n['next_access_is_actual_trip'] else '该次为车辆可用目标，没有额外给定行程。')+'实际行程、20%参考保留与85%目标分别核查。')
    out+=['睡眠与小睡可有给定制冷服务；活动房间、照明和空调均从同一当天日程派生。26℃通常设定和27℃给定边界不表示你的个人舒适阈值。',
        '列出的空闲窗是保守参考。照护监督期间能否兼顾短时就近操作、是否需要他人协助尚未确定；可在原因中提出条件或修改。改变惯常时点、家庭共用车辆和额外协助是否愿意由你评价，不预设采用。',
        '学校假期采用已注明地区的参考校历；其他地区为给定迁移情景，非该家庭实测学籍或真实日记。',
        '本参考模型给定最低18℃外部供热边界，其热量不计入本轮六设备参考电量；供暖费用及真实家庭供暖情况未知。固定15℃与季节入水等边界可能改变数值。空气温度不等于个人舒适，参考电量不等于实测全屋账单。']
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
        for k,label in [('event','目标时段参考电力'),('living_day','完整24小时参考电力'),('living_day_and_service_tail','含后续服务与恢复的参考电力')]:
            quantities.append({'label':label,**{s:{'value':r['energy'][k][s],'unit':'kWh','status':'computed'} for s in ('A','B')},'scope':k,'evidence_sha256':digest(r)})
        for s in ('A','B'):
            need_index={n['need_id']:n for n in p['needs_A']}
            for n in r['services'][s].get('hot_water',[]):
                need=need_index[n['need_id']];scope='后续服务' if need['release_min']>=p['primary_evaluation_min'][1] else '本次完整一天'
                impacts.append({'status':'computed','service_need_id':n['need_id'],'description':f"{s}（{scope}）：{clock(need['release_min'])}{person_label(w,need['requester'])}模型混水温度{n['minimum_mixed_C']:.1f}℃，给定目标{n['target_C']:.1f}℃。"})
            for n in r['services'][s].get('EV',{}).get('goals',[]):
                scope='后续服务' if n['deadline_min']>p['primary_evaluation_min'][1] else '本次完整一天'
                impacts.append({'status':'computed','description':f"{s}（{scope}）：{clock(n['deadline_min'])}前模型SOC {n['actual_SOC_before_any_trip_debit']*100:.1f}%，参考目标85%；是否有出行另按给定日程。"})
    if r:
        variants=[r]
        for variant in ('prior14','seasonal7','seasonal14'):
            variant_path=OUT/'readback'/variant/w['household_id']/f'{p["round_index"]:02d}.json'
            if variant_path.exists():variants.append(read(variant_path))
        if len(variants)>1:
            deltas=[x['energy']['living_day']['A_minus_B_kWh'] for x in variants]
            impacts.append({'status':'computed','description':f"同一案例在7/14日前史、固定15℃/季节入水参考边界下，完整一天A减B的电量差为{min(deltas):.3f}—{max(deltas):.3f} kWh。这是已检查情景范围，不是实测置信区间。"})
    vpp={'start_abs_min':p['event_window_min'][0],'end_abs_min':p['event_window_min'][1],'notice_abs_min':p['decision_abs_min'],
         'household_request':{'text':'参考任务：目标时段平均负荷比A降低0.5 kW；按给定需求判断B及协商条件'},'incentive':None}
    physical={'status':'complete' if r else 'pending','channels':[]}
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
def main():
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
        (site/'index.html').write_text(page)
        for name in assets:shutil.copyfile(PILOT/'frontend_snapshot'/name,site/name)
        js=site/'joint-view.js';s=js.read_text().replace("if(command.kind==='ac_setpoint')difference=","if(command.display_change_text)difference=command.display_change_text;\n   else if(command.kind==='ac_setpoint')difference=",1)
        s=s.replace('function focusWindow(c){','function focusWindow(c){\n  const explicitStart=c.plans.A.window_start_abs_min, explicitEnd=c.plans.A.window_end_abs_min;\n  if(Number.isFinite(explicitStart)&&Number.isFinite(explicitEnd)&&explicitEnd-explicitStart===1440)return [explicitStart,explicitEnd];',1)
        s=s.replace("const label=e=>e.operation_kind","const label=e=>e.operation_label|| (e.operation_kind",1).replace("'安排时段';","'安排时段');",1)
        s=s.replace('renderHome(c.identity.role_id);','PROFILES[c.identity.role_id]=c.profile;renderHome(c.identity.role_id);',1)
        js.write_text(s)
        hv=site/'household-view.js';hv.write_text(hv.read_text().replace('工作日通常在家：','本情景当天在家：'))
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
