"""Same-world data for the existing R72 interface. No frontend rewrite or release."""
from common import *
LABELS={'ac':'空调','washer':'洗衣机','dishwasher':'洗碗机','dryer':'烘干机','water_heater':'电热水器','ev':'家庭EV充电'}
ICONS={**{k:k for k in LABELS},'water_heater':'electric_water_heater','ev':'home_ev'}
REL={1:'家庭参照人',2:'配偶',3:'子女',4:'父母',5:'岳父母或公婆',6:'祖父母',7:'儿媳或女婿',8:'孙辈',9:'兄弟姐妹',10:'其他亲属'}
ACT={'commuter':'外出工作','home_worker':'居家工作','home_activity':'居家活动','school':'在校学习','preschool_with_given_daycare':'日间托育'}
def clock(m):
    d,t=divmod(m,1440);return ('次日' if d==1 else f'第{d+1}日' if d else '')+f'{t//60:02d}:{t%60:02d}'
def lines(plan):
    return [f'{LABELS[t["kind"]]} {clock(t["start_min"])}—{clock(t["end_min"])}' for t in plan['tasks']]+[
        f'{LABELS[{"ac_setpoint":"ac","tank_setpoint":"water_heater","ev_charge_window":"ev"}[c["kind"]]]} {clock(c["start_min"])}—{clock(c["end_min"])}'+(f'，设定{c["value_C"]:g}℃' if 'value_C' in c else '允许充电') for c in plan['controls']]
def main():
    school_guard();records=[]
    for b in read(OUT/'WORLD_BINDINGS1000.json')['records']:
        w=read(OUT/b['world_path']);hid=w['household_id'];layout=w['layout'];devices=w['parameter_pack']['devices']
        card=f'你扮演{w["province"]}的一户城市住宅参考家庭，固定{w["N"]}名常住成员、{w["G"]}代，H6建筑面积{w["H6"]}平方米，H7自然间{w["H7"]}间。按给定成员、房间、设备、操作人和需求判断方案。个人偏好由你表达，没有预设采纳答案。'
        op=w['operating_context']['operators'][0]
        if not op['resident']:card+='本户由给定的非同住监护人协助操作；扮演者以监护人的身份判断，监护人不计入常住人数。'
        public_members=[{**m,'relationship':REL.get(m['ego_relation_code'],'给定关系'),'life_roles':ACT[m['reference_activity_role']],
            'routine':'06:30起床、22:30休息；其余按给定作息表','weekday_home':'、'.join(clock(round(x['start_h']*60))+'—'+clock(round(x['end_h']*60)) for x in m['weekly_calendar'][0]['intervals'] if x['location']=='home'),
            'sleep_room':m['reference_home_room_id']} for m in w['members']]
        zone_labels={r['room_id']:({'bedroom':'卧室','hall':'起居厅','corridor':'过道','kitchen':'厨房','non_H7_service':'服务空间'}.get(r['census_room_class'],'房间')+' '+str(i+1)) for i,r in enumerate(layout['rooms'])}
        profile={'role_id':hid,'world_content_sha256':w['world_content_sha256'],'parameter_pack_sha256':w['parameter_pack_sha256'],
            'profile':{'household':{'province':w['province'],'family_size':w['N'],'generation_count':w['G'],'h6_design_building_area_m2':w['H6'],
                'natural_rooms_H7':w['H7'],'role_card_short':card,'actor_card_full':card,'economic_reference':w['economic_reference'],
                'city':w['province']+'城市住宅参考家庭','whole_gross_m2':layout['whole_unit_building_area_m2'],
                'household_net_share_m2':sum(r['usable_area_m2']*r['area_allocation_fractions'].get(hid,0) for r in layout['rooms']),
                'h6_area_basis':'普查建筑面积参考，净使用面积另列','building_type':layout['stock_reference_features']['building_storeys'],
                'control_condition':'按已给设备、共用空间预约和操作人窗口提出调整；是否接受由扮演者判断',
                'saving_importance_1_5':None,'comfort_importance_1_5':None},'members':public_members,
                'devices':[{'device_class':ICONS[k],'device':LABELS[k],'installed':w['assets'][k]['present'],
                    'controllable':w['assets'][k]['present'],'asset_ids':w['assets'][k]['asset_ids'],'configuration':w['assets'][k]['config'],
                    'zone':next((d['room_id'] for d in devices if k in d['types']),None),
                    'installation_status_is_reference_not_observed_ownership':True} for k in KINDS],
                'device_instances':devices,'routine':w['routine'],'operating_context':w['operating_context'],'external_services':w['given_external_services']},
            'geometry':{'floors':[{'zone':r['room_id'],'points':[[r['thermal_centerline_rect_m'][0],r['thermal_centerline_rect_m'][1]],
                [r['thermal_centerline_rect_m'][2],r['thermal_centerline_rect_m'][1]],[r['thermal_centerline_rect_m'][2],r['thermal_centerline_rect_m'][3]],
                [r['thermal_centerline_rect_m'][0],r['thermal_centerline_rect_m'][3]]]} for r in layout['rooms']],
                'zone_labels':zone_labels,'walls':[],'openings':[],
                'reference_layout_only_not_asbuilt_survey':True},'formal_human_answers':0,'collection_release':False}
        path=OUT/'actors'/f'{hid}.json';save(path,profile);scenes=[]
        for index in range(1,11):
            pairpath=OUT/'pairs'/hid/f'{index:02d}.json';p=read(pairpath)
            timeline=[];chart=[]
            for d in devices:
                byside={}
                for side in ['A','B']:
                    spans=[{'start_h':t['start_min']/60,'end_h':t['end_min']/60,'label':LABELS[t['kind']]+'运行','operation_kind':'program_power'} for t in p[side]['tasks'] if t['asset_id']==d['asset_id']]
                    spans += [{'start_h':c['start_min']/60,'end_h':min(c['end_min'],2880)/60,'label':f'{c["value_C"]:g} ℃' if 'value_C' in c else '允许充电',
                        'operation_kind':'heater_availability' if c['kind']=='tank_setpoint' else 'temperature_setpoint' if c['kind']=='ac_setpoint' else 'program_power'} for c in p[side]['controls'] if c['asset_id']==d['asset_id']]
                    byside[side]=spans
                chart.append({'device_id':d['asset_id'],'icon_device_id':ICONS[d['types'][0]],'device':'/'.join(LABELS[k] for k in d['types'])+' · '+d['room_id'],
                    'original':byside['A'],'proposal':byside['B'],'schedule_complete':True})
            changed_tasks=[t for t in p['B']['tasks'] if t not in p['A']['tasks']]
            main_kind={'ac_setpoint':'ac','hotwater_preheat_shift':'water_heater','ev_charge_delay':'ev'}.get(p['proposal']['family'],changed_tasks[0]['kind'] if changed_tasks else None)
            all_actions=changed_tasks+p['B']['changed_controls']
            command={'role_id':hid,'date':p['date'],'family':'six_device_reference','device_class':ICONS[main_kind] if main_kind else 'none',
                'start_abs_min':1080,'end_abs_min':1140,'offset_min':p['proposal'].get('amount',0),'proposal':p['proposal']}
            scene={'artifact':{'role_id':hid,'date':p['date'],'world_content_sha256':w['world_content_sha256'],
                'parameter_pack_sha256':w['parameter_pack_sha256'],'pair_sha256':sha(pairpath),'day_index':0,
                'source_action_sha256':sha(pairpath),'source_command_sha256':digest(command)},
                'context':{'notification_min':p['decision_abs_min'],'event_window_min':p['event_window_min'],
                    'given_service_constraints':p['needs_A'],'operating_context':w['operating_context'],
                    'city':w['province']+'城市住宅参考家庭','day_type':'weekday' if __import__('datetime').date.fromisoformat(p['date']).weekday()<5 else 'weekend',
                    'notification_h':p['decision_abs_min']/60},
                'source_A':{'description':lines(p['A']),'full_plan':p['A'],'target_event':{k:command[k] for k in ['device_class','start_abs_min','end_abs_min']},'timeline_48h':timeline},
                'source_B':{'command':command,'all_actions':all_actions},'model_schedule_48h':chart,
                'display_plan_lines':{'A':lines(p['A']),'B':lines(p['B'])},'quantities':[],'downstream_impacts':[],
                'two_day_result':{'technical_valid':None,'service_met_in_two_day_window':None},
                'proposal_B':{'description':lines(p['B']),'full_plan':p['B'],'origin':p['proposal']},
                'questions':[{'id':'adoption','choices':['accept','modify','reject','cannot_judge']},
                    {'id':'relative_preference','choices':['A','B','tie','reject_both','cannot_judge']}],
                'answers':{'adoption':None,'relative_preference':None,'reasons':None},
                'simulated_effects':None,'collection_release':False,'release_reason':'paired EP effects have not been run or reviewed'}
            sp=OUT/'collection_inputs'/hid/f'{index:02d}.json';save(sp,scene)
            scenes.append({'round_index':index,'path':str(sp.relative_to(OUT)),'sha256':sha(sp)})
        records.append({'household_id':hid,'profile_path':str(path.relative_to(OUT)),'profile_sha256':sha(path),'scenes':scenes})
    save(OUT/'COLLECTION_INPUT_BINDINGS1000.json',{'records':records,'profiles':len(records),'scenes':sum(len(r['scenes']) for r in records),
        'frontend':'existing R72 data contract,prepared input projection;no deployment/UI replacement performed',
        'formal_human_answers':0,'collection_release':False,'training_release':False})
    print({'profiles':len(records),'collection_scene_inputs':10000,'human_answers':0},flush=True)
if __name__=='__main__':main()
