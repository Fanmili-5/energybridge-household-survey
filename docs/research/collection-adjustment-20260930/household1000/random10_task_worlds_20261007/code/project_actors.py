"""Project one verified world into the existing R72 actor/collection contracts."""
import collections,csv,datetime as dt,gzip,random
from common import *
PAGE=REPO/'docs/research/UX_LOGIC_REVIEW_20260926/AB_REDESIGN_20260928/B_baseline/r72_questionnaire_candidate_20260929'
LABELS={'ac':'空调','washer':'洗衣机','dishwasher':'洗碗机','dryer':'烘干机','water_heater':'电热水器','ev':'电动车充电'}
ICONS={**{k:k for k in LABELS},'water_heater':'electric_water_heater','ev':'home_ev'}
RELATIONS={1:'家庭参照人',2:'配偶',3:'子女',4:'父母',5:'岳父母/公婆',6:'祖父母',7:'儿媳/女婿',8:'孙辈',9:'兄弟姐妹',10:'其他亲属'}
ACTIVITIES={'commuter':'外出工作','home_worker':'居家工作','school':'在校学习','preschool_with_given_daycare':'日间托育','home_activity':'居家活动'}

def clock(h):
    m=round(h*60);return '%02d:%02d'%(m//60,m%60)
def load_program(p):return json.loads(gzip.decompress(Path(p).read_bytes()))
def room_label(r):
    base={'bedroom':'卧室','living':'起居室','kitchen':'厨房','corridor':'过道','non_H7_service':'服务空间'}.get(r['census_room_class'],'自然间')
    if 'wash' in r['room_id']:base='洗浴空间'
    return base+' '+r['room_id'].split('_')[-1] if r['room_id'].startswith(('private_','aux_')) else base

def profile(w,binding):
    hid=w['household_id'];labels={r['room_id']:room_label(r) for r in w['layout']['rooms']};members=[]
    for m in w['members']:
        day=m['weekly_calendar'][0]['intervals'];home=[clock(x['start_h'])+'—'+clock(x['end_h']) for x in day if x['location']=='home']
        members.append({'local_id':m['local_id'],'relationship':RELATIONS.get(m['ego_relation_code'],'亲属关系代码'+str(m['ego_relation_code'])),
            'relationship_code':m['ego_relation_code'],'age_years':m['age_years'],'sex':m['sex'],'generation_level':m['generation_level'],
            'life_roles':ACTIVITIES[m['reference_activity_role']],'routine':'22:30休息，06:30起床；'+ACTIVITIES[m['reference_activity_role']],
            'weekday_home':'、'.join(home),'sleep_room':labels[m['reference_home_room_id']],
            'weekly_calendar':m['weekly_calendar'],'exact_clock_is_reference_design':True})
    net=sum(r['usable_area_m2']*r['area_allocation_fractions'].get(hid,0) for r in w['layout']['rooms'])
    shared=any(len(r['using_household_ids'])>1 and hid in r['using_household_ids'] for r in w['layout']['rooms'])
    devices=[]
    for kind,a in w['assets'].items():
        devices.append({'device':LABELS[kind],'device_class':ICONS[kind],'asset_id':a['id'],'owned':a['present'],'installed':a['present'],
            'accessible':a['present'],'controllable':a['present'],'modeled':a['present'],'zone':a['room_id'] if kind!='ev' else 'outdoor',
            'configuration':a['config'],'operator_local_id':next((m['local_id'] for m in w['members'] if m['member_id']==a['operator_member_id']),None),
            'control_condition':'可以提出调整，是否接受由扮演者判断；预先执行仅用于展示后果' if a['present'] else '本参考家庭未配置',
            'installation_status_is_reference_not_observed_ownership':True})
    card=(f'你扮演{w["province"]}的一户城市住宅家庭，共{w["N"]}名常住成员、{w["G"]}代，'
          f'本户H6建筑面积设定{w["H6"]}平方米，H7独立自然间{w["H7"]}间。'
          '按给定成员、空间、设备、作息与任务期限判断每个方案。采用统一实验电价0.6元/kWh，补偿以每轮情境为准。'
          '共用空间的照明与背景用电按登记使用家庭数均分，六类控制设备归本户计量；外部供暖只作为热边界，不折算购电费。'
          '未配置的家用服务由角色资料列明的外部或手动服务提供。不得自行添加同住者或设备。'
          '节费、舒适、接受与拒绝没有预设标准答案；不能从资料作出判断时可以选择不能判断。')
    home={'province':w['province'],'city':w['province']+'城市住宅参考家庭','family_size':w['N'],'generation_count':w['G'],
        'building_type':'单层住宅参考模型','housing_form_design':'shared_or_partial_dwelling' if shared else 'independent_dwelling',
        'natural_rooms_H7':w['H7'],'h6_design_building_area_m2':w['H6'],'h6_area_basis':'本户普查口径建筑面积参考；不是热区净面积',
        'whole_gross_m2':w['layout']['whole_unit_building_area_m2'],'household_net_share_m2':net,
        'floor_position':'本实验采用固定围护与相邻空间边界，未指定真实楼层',
        'control_condition':'只调整本户已配置的EB六类设备；需要共用空间和任务依赖的方案遵守本户记录',
        'actor_card_full':card,'role_card_short':card,'economic_reference':w['economic_reference'],
        'saving_importance_1_5':None,'comfort_importance_1_5':None,'conditional_grid_shift_importance_1_5':None,
        'notice_preference_hours':None,'budget_margin_1_tight_5_roomy':None,'monthly_bill_scenario_CNY':None,
        'undefined_personal_attitudes_are_questions_not_missing_physical_configuration':True}
    floors=[];walls=[]
    for r in w['layout']['rooms']:
        x0,y0,x1,y1=r['thermal_centerline_rect_m'];pts=[[x0,y0],[x1,y0],[x1,y1],[x0,y1]];floors.append({'zone':r['room_id'],'points':pts})
        walls.extend({'zone':r['room_id'],'points':[pts[i],pts[(i+1)%4]]} for i in range(4))
    openings=[]
    for a in w['layout']['access']:
        edge=a['common_edge'];center=[sum(x[i] for x in edge)/2 for i in range(2)];axis=0 if abs(edge[0][0]-edge[1][0])>abs(edge[0][1]-edge[1][1]) else 1
        p=list(center);q=list(center);p[axis]-=a['width_design_m']/2;q[axis]+=a['width_design_m']/2
        openings.append({'type':'door','points':[p,q]})
    return {'role_id':hid,'world_content_sha256':w['world_content_sha256'],'profile':{'household':home,'members':members,'devices':devices,
        'weekly_tasks':w['weekly_tasks'],'external_services':w['external_services'],'service_constraints_given_not_human_answers':True},
        'geometry':{'floors':floors,'walls':walls,'openings':openings,'zone_labels':labels,
            'owned_zones':[r['room_id'] for r in w['layout']['rooms'] if r['using_household_ids']==[hid]],
            'reference_layout_only_not_asbuilt_survey':True},'formal_human_answers':0}

def spans(program,kind,date):
    rows=program['rows'][144:];values=[]
    for i,r in enumerate(rows):
        d=date+dt.timedelta(days=i//144)
        if kind=='ac':v=r['ac_setpoint_C'] if 5<=d.month<=9 else 0
        elif kind=='water_heater':v=r['tank_setpoint_C'] if r['tank_setpoint_C']>10 else 0
        else:v=r[kind]
        values.append(v)
    first=0;output=[]
    for end in range(1,289):
        if end==288 or values[end]!=values[first]:
            v=values[first]
            if v>0:output.append({'start_h':first/6,'end_h':end/6,'label':f'{v:g} ℃' if kind in ['ac','water_heater'] else '运行',
                'operation_kind':'heater_setpoint_window' if kind=='water_heater' else 'temperature_setpoint' if kind=='ac' else 'program_power'})
            first=end
    return output

def weather_days(path):
    by_day=collections.defaultdict(list)
    with Path(path).open() as f:
        rows=csv.reader(f)
        for _ in range(8):next(rows)
        for row in rows:by_day[int(row[1]),int(row[2])].append(float(row[6]))
    return by_day

def scene(w,case,result,a,b,weather,action_hash,command_hash,command):
    date=dt.date.fromisoformat(case['context']['date']);layout_labels={r['room_id']:room_label(r) for r in w['layout']['rooms']};control=[];timeline=[]
    for kind,asset in w['assets'].items():
        if not asset['present']:continue
        original=spans(a,kind,date);proposal=spans(b,kind,date)
        label=LABELS[kind]+' · '+('室外专用充电位' if kind=='ev' else layout_labels[asset['room_id']])
        control.append({'device_id':asset['id'],'icon_device_id':ICONS[kind],'device':label,'original':original,'proposal':proposal,'schedule_complete':True})
        timeline.extend({'kind':'A_event','device_class':ICONS[kind],'device_id':asset['id'],'start_abs_min':1440+round(s['start_h']*60),'end_abs_min':1440+round(s['end_h']*60),'label':s['label']} for s in original)
    A=result['A_48h_kWh'];B=result['B_48h_kWh'];tariff=w['tariff_reference']['flat_CNY_per_kWh'];compensation=case['context']['event_compensation_CNY_per_kWh']
    linesA=[];linesB=[]
    for action in case['actions']:
        k=action['kind'];job=next((j for j in case['context']['service_constraints'] if j['kind']==k),None)
        if action['command']=='shift':
            linesA.append(LABELS[k]+'：'+clock(job['baseline_start_h'])+'开始，运行'+str(job['duration_h'])+'小时')
            linesB.append(LABELS[k]+'：'+clock(action['new_start_h'])+'开始，任务期限'+clock(job['deadline_h']))
        elif k=='water_heater':linesA.append('电热水器：17:00—21:00允许加热，设定55 ℃');linesB.append('电热水器：16:00—18:00允许加热，设定65 ℃；20:30开始用水')
        elif k=='ev':linesA.append('电动车：返回后按原策略充电，次日出发前SOC要求85%');linesB.append('电动车：22:00后允许充电，次日出发前SOC要求85%')
        else:linesA.append('空调：18:00—19:00设定26 ℃');linesB.append('空调：18:00—19:00设定27 ℃，随后恢复26 ℃')
    if not linesA:linesA=['按原安排执行'];linesB=['保持同一安排；此轮为预先指定的对照或当天无可调任务']
    effects=[]
    for kind in ['water_heater','ac']:
        aa=result['A_reference_physical_services'].get(kind);bb=result['B_reference_physical_services'].get(kind)
        if not aa:continue
        if kind=='water_heater':description=f'两日每个10分钟用水步长的最低平均出口温度：A {aa["minimum_10minute_average_outlet_C"]:.1f} ℃，B {bb["minimum_10minute_average_outlet_C"]:.1f} ℃；约定要求40 ℃。'
        else:description=f'服务房间两日晚间最高平均空气温度：A {aa["maximum_reference_evening_air_C"]:.1f} ℃，B {bb["maximum_reference_evening_air_C"]:.1f} ℃；参考上限{bb["reference_upper_air_C"]:g} ℃。'
        effects.append({'label':LABELS[kind],'status':'simulated_reference','description':description})
    serviceA=result['A_program_services'];serviceB=result['B_program_services']
    for kind in ['washer','dishwasher','dryer','ev']:
        aa=[j for j in serviceA if j['kind']==kind];bb=[j for j in serviceB if j['kind']==kind]
        if aa:effects.append({'label':LABELS[kind],'status':'reference_program','description':'两日约定服务：原安排'+('满足' if all(j['served'] for j in aa) else '存在未满足')+'，调整后'+('满足' if all(j['served'] for j in bb) else '存在未满足')})
    servedB=all(j['served'] for j in serviceB) and all(j['served'] for j in result['B_reference_physical_services'].values())
    return {'artifact':{'role_id':w['household_id'],'date':date.isoformat(),'day_index':1,'source_action_sha256':action_hash,'source_command_sha256':command_hash},
        'context':{'city':w['province']+'城市住宅参考家庭','day_type':'weekday' if date.weekday()<5 else 'weekend',
            'weather_days':[{'date':(date+dt.timedelta(days=i)).isoformat(),'min_drybulb_C_derived':min(weather[((date+dt.timedelta(days=i)).month,(date+dt.timedelta(days=i)).day)]),
                'max_drybulb_C_derived':max(weather[((date+dt.timedelta(days=i)).month,(date+dt.timedelta(days=i)).day)]),'kind':'typical_weather_reference'} for i in range(2)],
            'notification_h':case['context']['notification_h'],'notice_minutes':case['context']['notice_minutes'],
            'given_service_constraints':case['context']['service_constraints'],'reference_tariff_CNY_per_kWh':tariff,
            'compensation_CNY_per_kWh_event_reduction':compensation},
        'source_A':{'target_event':{'device_class':command['device_class'],'start_abs_min':command['start_abs_min'],'end_abs_min':command['end_abs_min']},'timeline_48h':timeline},
        'source_B':{'command':command,'all_actions':case['actions']},'model_schedule_48h':control,
        'display_plan_lines':{'A':linesA,'B':linesB},
        'two_day_result':{'technical_valid':True,'service_met_in_two_day_window':servedB,'delivered_service_quantity':None},
        'physical_target_48h':{'scope':'uncalibrated coherent reference world,defined facility electricity','kind':'six_device_reference_electricity',
            'A_48h_kWh':A,'B_48h_kWh':B,'A_SQL_sha256':result['A_SQL_sha256'],'B_SQL_sha256':result['B_SQL_sha256']},
        'quantities':[{'label':'两日模型购电量','A':{'value':round(A,3),'unit':'kWh'},'B':{'value':round(B,3),'unit':'kWh'},'scope':'按本参考住房总表；共用空间的家庭分摊规则另列'},
            {'label':'18:00—19:00模型购电量','A':{'value':round(result['A_event_kWh'],3),'unit':'kWh'},'B':{'value':round(result['B_event_kWh'],3),'unit':'kWh'},'scope':'允许零减负荷或负减负荷'},
            {'label':'两日总表参考电费','A':{'value':round(A*tariff,2),'unit':'元'},'B':{'value':round(B*tariff,2),'unit':'元'},'scope':'统一实验电价；外部供暖热量不计入；不是实际地方账单'}],
        'downstream_impacts':effects,'predecision_state_reference':result['predecision_state'],
        'impact_limit_note':'给定参考家庭的模拟后果。典型气象不是该日实测天气；温度指标不等于个体舒适偏好。真人回答留空。'}

def main():
    guard();prod=read(OUT/'PRODUCTION1000.json');assert prod['households_complete']==1000 and not prod['failures'] and prod['paired_rounds']==10000
    bindings={b['household_id']:b for b in read(OUT/'WORLD_BINDINGS1000.json')['records']}
    sys.path.insert(0,str(REPO/'realtime_pilot'));from role_r72_adapter import load_manifest,load_display_package,balanced_assignment
    asset_names=['candidate.js','candidate.css','r72-view-adapter.js','source-draft.js','r72-collection.js','template.html'];assets={n:sha(OUT/'frontend'/n) for n in asset_names};assets['plan-view.js']=sha(OUT/'frontend/plan-view.js');render_hash=digest(assets)
    batch='random10_coherent_reference_20261007';registry=[];all_profiles={};weather_cache={}
    for household in sorted(prod['records'],key=lambda h:h['household_id']):
        hid=household['household_id'];binding=bindings[hid];w=read(OUT/binding['world_path']);public=profile(w,binding);pp=OUT/'actor_profiles'/f'{hid}.json';save(pp,public);all_profiles[hid]=public
        if binding['weather']['sha256'] not in weather_cache:weather_cache[binding['weather']['sha256']]=weather_days(binding['weather']['path'])
        weather=weather_cache[binding['weather']['sha256']];manifest_cases=[];display_rows=[]
        for row in household['rounds']:
            case=read(OUT/row['case_path']);pair_result=read(OUT/row['paired_result_path']);root=(OUT/row['case_path']).parent
            a=load_program(root/'A_PROGRAM.json.gz');b=load_program(root/'B_PROGRAM.json.gz');index=row['round_index'];command={'role_id':hid,'date':row['date'],
                'family':'six_device_reference','device_class':ICONS[case['actions'][0]['kind']] if case['actions'] else 'none',
                'start_abs_min':1440+18*60,'end_abs_min':1440+19*60,'offset_min':0,'actions':case['actions'],'predecision_state_sha256':digest(pair_result['predecision_state'])}
            cmd_hash=digest(command);action_hash=row['case_sha256'];left,right=balanced_assignment(hid,batch,index)
            manifest_cases.append({'day_index':index,'date':row['date'],'role_id':hid,'source_action_sha256':action_hash,'source_command_sha256':cmd_hash,
                'service_full_result_sha256':row['paired_result_sha256'],'physical_target_48h_sha256':row['paired_result_sha256'],'response_eligible':True,'display_left':left,'display_right':right})
            context=scene(w,case,pair_result,a,b,weather,action_hash,cmd_hash,command)
            display_rows.append({'status':'ready','day_index':index,'date':row['date'],'role_id':hid,'source_action_sha256':action_hash,'source_command_sha256':cmd_hash,'case':context})
        manifest={'schema':'eb.ab.r72.answer_manifest.v1','status':'engineering_fixture','study_batch_id':batch,'role_id':hid,
            'selection_sha256':digest(w['random10_date_selection']),'profile_sha256':sha(pp),'render_asset_sha256':render_hash,
            'presentation_version':'r72_random10_six_device_reference_v1','cases':manifest_cases}
        mp=OUT/'collection_packages'/hid/'answer_manifest.json';save(mp,manifest);loaded,mhash=load_manifest(mp,allow_engineering_fixture=True)
        dp=mp.parent/'display_package.json';save(dp,{'schema':'eb.ab.r72.display_package.v1','manifest_sha256':mhash,'role_id':hid,'cases':display_rows})
        package,dhash=load_display_package(dp,loaded,mhash)
        save(mp.parent/'BLANK_ANSWERS.json',{'role_id':hid,'answers':[{'date':r['date'],'schema':'eb.ab.r72.answer.v1','adoption':None,'relative_preference':None,'modification_condition':None,'rejection_reason':None,'note':None} for r in household['rounds']],
            'formal_human_answers':0,'training_release':False})
        registry.append({'role_id':hid,'profile_path':str(pp.relative_to(OUT)),'profile_sha256':sha(pp),'manifest_path':str(mp.relative_to(OUT)),'manifest_sha256':mhash,
            'display_path':str(dp.relative_to(OUT)),'display_sha256':dhash,'ready_days':10,'status':'engineering_fixture'})
    save(OUT/'ACTOR_PROFILES1000.json',all_profiles);save(OUT/'COLLECTION_REGISTRY1000.json',{'schema':'eb.r72.reference_package_registry.v1','records':registry,'unchanged_existing_collection_contract':True,
        'formal_human_answers':0,'training_release':False,'live_invitation_service_changed':False})
    save(OUT/'FRONTEND_PROJECTION_CHECKS.json',{'households':len(registry),'ready_cases':len(registry)*10,'actual_original_R72_loaders_passed':True,'render_asset_hashes':assets,
        'render_asset_set_sha256':render_hash,'new_frontend_layout_designed':False,'narrow_renderer_extensions':['multi-device A/B plan lines','full actor context'],
        'browser_visual_QA_complete':False,'formal_human_admission':False})
    print({'existing_R72_packages':len(registry),'ready_cases':len(registry)*10,'formal_human_answers':0},flush=True)
if __name__=='__main__':main()
