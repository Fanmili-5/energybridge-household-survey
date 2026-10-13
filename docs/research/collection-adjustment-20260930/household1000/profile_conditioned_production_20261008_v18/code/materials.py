"""Synchronize actor facts and original renderer inputs; no synthetic actor answers."""
import collections,copy,csv,datetime as dt,html,re,shutil,subprocess
from common import *
from worlds import merge_ranges
LABELS={'commuter':'有工作来源提示；本情景给定外出工作安排','home_worker':'有工作来源提示；本情景给定居家工作安排',
        'short_work_reference':'有工作来源提示；本情景给定短时工作安排','home_activity':'无当前工作来源提示；本情景给定居家活动',
        'unspecified_activity_reference':'就业未知，不指定职业；本情景给定居家或出行活动','school':'本情景给定上学安排，非实测学籍',
        'preschool_with_given_daycare':'本情景给定日托安排，非实测入托记录'}
NAMES={'ac':'空调','washer':'洗衣','dryer':'烘干','dishwasher':'洗碗','water_heater':'电热水器','ev':'电动车充电'}
ICONS={'water_heater':'electric_water_heater','ev':'home_ev'}
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
    p['members']=members;p['routine']=w['routine'];p['operating_context']=w['operating_context'];p['service_semantics']=w['service_semantics']
    p['device_instances']=[{k:copy.deepcopy(v) for k,v in d.items() if k not in ('previous_OEM_anchor','source_EB_usage_defaults_evidence')} for d in w['parameter_pack']['devices']];p['devices']=[]
    p['external_services']=copy.deepcopy(w['given_external_services'])
    if any(m['age_years']<6 for m in w['members']):p['external_services']['daycare_transport']='本情景日托及接送为给定外部服务；不是额外同住成员或被观察的现实服务'
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
             'device_class':'home_ev' if o['kind'].startswith('EV') else 'washer','kind':'handling_change',
             'start_abs_min':o['start_min'],'end_abs_min':o['end_min'],'A_start_abs_min':a['start_min'] if a else o['start_min'],'A_end_abs_min':a['end_min'] if a else o['start_min'],
             'display_change_text':f"请求{person_label(w,o['operator_id'])}在{clock(o['start_min'])}—{clock(o['end_min'])}{label}"+(f"（惯常：{clock(a['start_min'])}）" if a else '（额外操作，需要你判断是否愿意）')})
    assert out
    for i,c in enumerate(out):c['command_id']=p['case_id']+':requested-command:'+str(i+1).zfill(3)
    return out
def need_text(w,p):
    out=['本次完整一天：'+p['date']+' 08:00 至次日08:00；允许跨夜。后续服务期限另列，不能把午夜当状态重置。']
    weekday=dt.date.fromisoformat(p['date']).weekday();family=w['routine']['weekly_family_context'][weekday]
    out.append('惯常安排：本日为'+('工作日参考情景' if weekday<5 else '休息日参考情景')+f"，晚餐{clock(family['dinner_min'])}—{clock(family['dinner_min']+30)}。")
    for m in w['members']:
        s=m['daily_reference_specs'][weekday]
        out.append(f"成员{m['local_id']}（{m['age_years']}岁）：{LABELS[m['reference_activity_role']]}；本日{simple_clock(s['wake_min'])}起床、{simple_clock(s['sleep_min'])}休息。"+
                   (f"给定外出{simple_clock(s['departure_min'])}—{simple_clock(s['arrival_min'])}。" if s['departure_min'] is not None else '本日主要活动在家；操作可用时间另列。'))
        work=[i for i in m['weekly_calendar'][weekday]['intervals'] if i['activity'] in ('home_work','given_short_work_activity')]
        if work:out.append(person_label(w,m['member_id'])+'的给定在家工作时段：'+'、'.join(simple_clock(i['start_min'])+'—'+simple_clock(i['end_min']) for i in work)+'；工作期间不安排人工操作。')
    for o in w['operating_context']['operators']:
        slots='、'.join(simple_clock(a)+'—'+simple_clock(b) for a,b in o['weekly_windows_min'][str(weekday)])
        out.append(f"人工操作可用窗：{person_label(w,o['operator_id'])}（"+('同住成员' if o['resident'] else '非同住协助者，不增加常住人数')+'）'+slots+'；此处表示能安排操作，不表示已同意额外协助。')
    if family['child_bathing_assistant']:out.append('照护安排：幼儿洗浴由'+person_label(w,family['child_bathing_assistant'])+'在给定时段协助；日托及接送为给定外部服务。')
    for n in p['needs_A']:
        if n['kind'] in ('washer','dishwasher') and n['release_min']<1440:
            text=f"必须完成的参考服务：{NAMES[n['kind']]}须完成给定程序；程序期限{clock(n['deadline_min'])}，取用期限{clock(n['delivery_deadline_min'])}。程序完成与人工取出分开。"
            if n['kind']=='washer' and n['wearable_clothes_ready_at_program_end'] is None:text+='未配置烘干，衣物可穿时间未知。'
            elif n['kind']=='washer':text+='洗涤程序结束后仍须完成烘干程序，再按给定取用期限取出；洗涤结束不能单独算衣物已可穿。'
            out.append(text)
        if n['kind']=='water_heater' and n['release_min']<1440:out.append(f"{person_label(w,n['requester'])}：{clock(n['release_min'])}起洗浴10分钟，需要30 L混水，给定目标{n['target_C']:.1f}℃。")
        if n['kind']=='ev' and n['release_min']<1440:
            cfg=next(d['parameters'] for d in w['parameter_pack']['devices'] if d['asset_id']==n['asset_id'])
            contract=w['given_transport_contract']
            out.append(f"出行角色：驾驶由给定非同住参考驾驶服务承担，不增加常住人数；{person_label(w,contract['handling_operator_id'])}负责插拔，并按给定日程作为出行乘员。没有据年龄或就业推断同住成员持驾驶资格。")
            out.append(f"参考电池{cfg['capacity_kwh']:g} kWh；给定出行耗电25 kWh（约{25/cfg['capacity_kwh']*100:.1f}%电量）；{clock(n['deadline_min'])}前参考电量目标85%。"+('该次可用时间对应实际给定出行。' if n['next_access_is_actual_trip'] else '该次为次晨可用目标，次晨没有给定出行。')+f"完成行程、行程后参考保留{100*cfg['min_soc']:g}%、达到85%为三项不同检查；电量模型不会通过截到保留线来凭空增加电量。")
    out += ['可协商条件：自动程序能在装载后预约启动；洗烘一体程序自动衔接。改变人工取出时点、要求其他成员协助，需要你判断，不能预设同意。',
            '未知主观取舍：26℃通常设定、27℃给定控制边界不等于你的个人舒适阈值。习惯变化、噪声、额外协助与省电取舍由你判断，可在原因中写条件或修改建议。',
            '设备程序和固定服务量来自参考任务；成员活动地点与钟点为本情景给定安排，就业未知不会被补成真实职业。']
    out.append('提供的物理数值是在固定15℃入水等给定条件下的模型参考，不是实测账单或个人舒适评价；条件变化可能改变数值。')
    return out
def scene(w,h,p,a):
    path=OUT/'readback/base7'/w['household_id']/f'{p["round_index"]:02d}.json';r=read(path) if path.exists() else None
    prof={'role_id':w['household_id'],'sha256':digest(a['profile']),'profile':a['profile'],'geometry':a['geometry'],'source_world_sha256':w['world_content_sha256']}
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
        js.write_text(s)
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
