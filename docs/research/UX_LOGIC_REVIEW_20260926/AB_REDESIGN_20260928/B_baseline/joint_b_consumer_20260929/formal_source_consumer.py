"""Snapshot and consume the new formal A/B source without physics or human answers."""
from __future__ import annotations
from pathlib import Path
from datetime import datetime
import argparse
import hashlib
import json

from joint_contract import bind, canonical, digest, apply_commands, require

HERE = Path(__file__).resolve().parent
AB = HERE.parents[1]
SOURCE = AB / 'A_proposals/joint_method_freeze_candidate_20260929'
LOCK = SOURCE / 'FORMAL_SOURCE_LOCK_CANDIDATE.json'
READBACK = SOURCE / 'BUILD_READBACK.json'
REVISION2 = AB / 'A_proposals/joint_method_revision2_20260930'
REVISION2_LOCK = REVISION2 / 'FORMAL_SOURCE_LOCK_REVISION2.json'
REVISION2_READBACK = REVISION2 / 'SOURCE_REVISION2_READBACK.json'
DEVICE = {'ac':'空调','dishwasher':'洗碗机','dryer':'烘干机','electric_water_heater':'电热水器',
          'home_ev':'家用电动车充电','washer':'洗衣机'}
ROLE = {'reference_adult':'参考成人','spouse':'配偶','child':'子女','parent_of_reference_adult':'长辈',
        'sibling':'兄弟姐妹','other_adult':'家庭成员'}
ROUTINE = {'home_most':'主要在家','out_regular':'通常外出','mixed':'在家与外出交替',
           'shift':'轮班','school':'上学','home_regular':'通常在家','irregular':'作息不固定'}
LIFE_ROLE = {'caregiver':'照护家人','home_work':'在家工作','not_working':'暂未工作',
             'outside_work':'外出工作','preschool':'学龄前','shift':'轮班工作','student':'学生'}
CONTROL = {'confirm_required':'每次调整需确认','high_trust_auto':'可自动执行设定内的调整',
           'low_auto_accept':'仅少量自动调整可接受'}
ROOMS = {'one_room':'一间','two_rooms':'两间','three_rooms':'三间','four_rooms':'四间','five_or_more':'五间或更多'}
NEEDS = {'household_dinner':'晚餐','dishes_after_meal':'餐具整理','ev_charge':'电动车充电目标',
         'ev_trip':'电动车出行','hot_water_draw':'热水','laundry_clean':'洗衣','laundry_dry':'烘干'}
UNITS = {'servings':'份','batch':'批','battery_kWh':'kWh','target_SOC':'目标电量比例','L':'升'}


def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for part in iter(lambda:stream.read(1024*1024),b''):h.update(part)
    return h.hexdigest()


def source_digest(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def checked(path, expected):
    path=Path(path)
    require(path.is_file() and sha(path)==expected,'Snapshot source mismatch: '+str(path))
    return path


def snapshot(out_dir):
    before=sha(LOCK);lock=json.loads(LOCK.read_text());readback_sha=sha(READBACK);readback=json.loads(READBACK.read_text())
    require(lock['selected_count']==len(lock['proposals']) and len(readback['roles'])==300,'Incomplete formal source index')
    eligible={h['role_id']:h for h in lock['households']}
    rows=[]
    for r in sorted(readback['roles'],key=lambda x:x['role_id']):
        role=r['role_id'];annual=SOURCE/'candidate_annual'/f'{role}.json';profile=SOURCE/'candidate_profiles'/f'{role}.json'
        a_sha=sha(annual);p_sha=sha(profile)
        require(a_sha==r['sha256'],'Annual disagrees with build readback: '+role)
        if role in eligible:
            require(a_sha==eligible[role]['annual']['sha256'] and p_sha==eligible[role]['canonical']['sha256'],
                    'Eligible household source drift: '+role)
        rows.append({'role_id':role,'annual':{'path':str(annual),'sha256':a_sha},
                     'profile':{'path':str(profile),'sha256':p_sha},
                     'ordinary_A_eligible':bool(r['ordinary_A_eligible'] and role in eligible),
                     'selected_B_count':sum(p['role_id']==role for p in lock['proposals'])})
    require(sha(LOCK)==before and sha(READBACK)==readback_sha,'Source changed during snapshot')
    for r in rows:
        checked(r['annual']['path'],r['annual']['sha256']);checked(r['profile']['path'],r['profile']['sha256'])
    data={'schema':'eb.formal_source_snapshot.v1','source_lock':{'path':str(LOCK),'sha256':before},
          'build_readback':{'path':str(READBACK),'sha256':readback_sha},
          'roles':rows,'household_count':300,'eligible_A_count':sum(r['ordinary_A_eligible']for r in rows),
          'selected_B_count':sum(r['selected_B_count']for r in rows),'formal_split':None}
    out_dir.mkdir(parents=True,exist_ok=True)
    out=out_dir/(before[:16]+'.json')
    content=json.dumps(data,ensure_ascii=False,indent=2)+'\n'
    require(not out.exists() or out.read_text()==content,'Snapshot name collision')
    out.write_text(content)
    return out


def snapshot_revision2(out_dir):
    lock_sha=sha(REVISION2_LOCK);lock=json.loads(REVISION2_LOCK.read_text())
    readback_sha=sha(READBACK);readback=json.loads(READBACK.read_text())
    repair_sha=sha(REVISION2_READBACK)
    require(lock['schema']=='joint-b-formal-preoutcome-revision2-v1' and
            lock['selected_count']==len(lock['proposals'])==2970 and
            len(lock['households'])==298 and len(readback['roles'])==300,
            'Incomplete revision2 source')
    require(lock['parent_v1_full_source_lock']['sha256']==sha(LOCK),
            'Revision2 parent source changed')
    eligible={h['role_id']:h for h in lock['households']}
    require(len(eligible)==298,'Duplicate revision2 household')
    rows=[]
    for r in sorted(readback['roles'],key=lambda x:x['role_id']):
        role=r['role_id']
        if role in eligible:
            annual=eligible[role]['annual'];profile=eligible[role]['canonical']
        else:
            annual={'path':str(SOURCE/'candidate_annual'/f'{role}.json'),'sha256':r['sha256']}
            profile_path=SOURCE/'candidate_profiles'/f'{role}.json'
            profile={'path':str(profile_path),'sha256':sha(profile_path)}
        checked(annual['path'],annual['sha256']);checked(profile['path'],profile['sha256'])
        rows.append({'role_id':role,'annual':annual,'profile':profile,
                     'ordinary_A_eligible':role in eligible,
                     'selected_B_count':sum(p['role_id']==role for p in lock['proposals'])})
    require(sha(REVISION2_LOCK)==lock_sha and sha(READBACK)==readback_sha and
            sha(REVISION2_READBACK)==repair_sha,'Revision2 source changed during snapshot')
    data={'schema':'eb.formal_source_snapshot.v2','source_lock':{'path':str(REVISION2_LOCK),'sha256':lock_sha},
          'build_readback':{'path':str(READBACK),'sha256':readback_sha},
          'source_revision2_readback':{'path':str(REVISION2_READBACK),'sha256':repair_sha},
          'roles':rows,'household_count':300,'eligible_A_count':298,'selected_B_count':2970,
          'formal_split':None}
    out_dir.mkdir(parents=True,exist_ok=True)
    out=out_dir/(lock_sha[:16]+'.json');content=json.dumps(data,ensure_ascii=False,indent=2)+'\n'
    require(not out.exists() or out.read_text()==content,'Revision2 snapshot name collision')
    out.write_text(content)
    return out


def load_snapshot(path,expected_sha):
    checked(path,expected_sha)
    s=json.loads(path.read_text())
    require(s['schema'] in ('eb.formal_source_snapshot.v1','eb.formal_source_snapshot.v2') and s['household_count']==300 and
            s['formal_split'] is None and len(s['roles'])==300,'Wrong formal snapshot')
    lock=json.loads(checked(s['source_lock']['path'],s['source_lock']['sha256']).read_text())
    checked(s['build_readback']['path'],s['build_readback']['sha256'])
    if 'source_revision2_readback' in s:
        checked(s['source_revision2_readback']['path'],s['source_revision2_readback']['sha256'])
    require(len(lock['proposals'])==s['selected_B_count'] and
            len({r['role_id']for r in s['roles']})==300,'Formal snapshot count drift')
    return s,lock


def profile_projection(source, annual, source_sha):
    e=source['effective_profile'];dw=e['dwelling_interface'];income=e['economic_context'];att=e['attitude_design']
    answers=e.get('questionnaire_answers') or {}
    operating_reference={}
    for device_class in source['inventory']:
        start_key='H_ac_start' if device_class=='ac' else 'H_'+device_class
        finish_key='H_ac_end' if device_class=='ac' else 'D_'+device_class
        start=answers.get(start_key) or {};finish=answers.get(finish_key) or {}
        def stated_hour(item):
            if item.get('response_status') not in {'answered','design_imputed'}:return None
            try:value=float(item['value'])
            except (TypeError,ValueError,KeyError):return None
            return value if 0<=value<=24 else None
        operating_reference[device_class]={
            'usual_start_hour':stated_hour(start),
            'usual_finish_hour':stated_hour(finish),
            'start_status':start.get('response_status'),
            'finish_status':finish.get('response_status'),
            'finish_meaning':'usual_end' if device_class=='ac' else 'stated_latest_completion',
            'source':'synthetic_questionnaire_profile'}
    household={'city':e['city'],'family_size':e['family_size'],'building_type':dw.get('building_type'),
       'natural_rooms_H7':ROOMS.get(dw.get('room_count_census_h7_category'),dw.get('room_count_census_h7_category')),
       'whole_gross_m2':dw.get('whole_dwelling_building_area_design_m2'),
       'household_net_share_m2':dw.get('household_modeled_net_area_design_m2'),
       'floor_position':dw.get('floor_position'),'housing_form_design':dw.get('housing_form_design'),
       'saving_importance_1_5':att.get('expanded_cost_level'),
       'comfort_importance_1_5':att.get('expanded_comfort_level'),
       'conditional_grid_shift_importance_1_5':None,'notice_preference_hours':None,
       'control_condition':CONTROL.get(att.get('control_condition'),'未提供'),
       'budget_margin_1_tight_5_roomy':None,
       'budget_explanation':income.get('budget_explanation'),
       'monthly_bill_scenario_CNY':income.get('monthly_electricity_bill_scenario_yuan')}
    annual_assets=annual['A']['assets']
    ac_assets={a['asset_id'] for d in annual['AC']['days'] for a in d['assets']}
    devices=[]
    for a in source['asset_designs']:
        asset=a['asset_id'];source_control=(asset in ac_assets if a['device_class']=='ac'
                                           else annual_assets.get(asset,{}).get('controllable_design'))
        control=bool(a.get('installed') and a.get('accessible') and a.get('offline_controllable') and source_control)
        devices.append({'asset_id':asset,'device_class':a['device_class'],'device':DEVICE.get(a['device_class'],a['device_class']),
                        'zone':a.get('zone'),'owned':None,'installed':a.get('installed'),'accessible':a.get('accessible'),
                        'controllable':control,'human_permission':a.get('human_permission'),'modeled':True})
    members=[]
    for m in e['members']:
        windows=m.get('typical_weekday_home_windows') or []
        members.append({'member_id':m['member_id'],'relationship':ROLE.get(m.get('role'),m.get('role','家庭成员')),
           'age_years':m.get('age_years_design') or '未知',
           'life_roles':'、'.join(LIFE_ROLE.get(x,'角色未说明') for x in (m.get('life_roles') or [])) or '生活安排未提供',
           'routine':ROUTINE.get(m.get('routine'),m.get('routine') or '作息未提供'),
           'weekday_home':'、'.join('—'.join(w) for w in windows) or None})
    return {'role_id':source['role_id'],'source_household_sha256':source_sha,
            'profile':{'household':household,'devices':devices,'members':members,
                       'operating_reference':operating_reference},
            'geometry':{'zone_labels':{}}}


def plan_from_annual(annual,proposal,profile):
    day=proposal['day_index'];start=(day-1)*1440;end=(day+2)*1440
    rows={a['asset_id']:{'asset_id':a['asset_id'],'device_class':a['device_class'],
                         'schedule_complete':True,'events':[]}
          for a in profile['profile']['devices'] if a['controllable'] is True}
    for d in annual['A']['days']:
        for event in d['events']:
            if event['asset_id'] not in rows or event['end_abs_min']<=start or event['start_abs_min']>=end:continue
            rows[event['asset_id']]['events'].append({k:event.get(k) for k in
                ('event_id','operation_kind','start_abs_min','end_abs_min')})
    for d in annual['AC']['days']:
        for a in d['assets']:
            if a['asset_id'] not in rows:continue
            for lo,hi in a['available_intervals_abs_min']:
                if hi<=start or lo>=end:continue
                rows[a['asset_id']]['events'].append({'start_abs_min':lo,'end_abs_min':hi,
                                                       'setpoint_C':a['usual_setpoint_C']})
    for row in rows.values():row['events'].sort(key=lambda e:(e['start_abs_min'],e['end_abs_min']))
    return {'role_id':proposal['role_id'],'date':proposal['date'],
            'window_start_abs_min':start,'window_end_abs_min':end,'rows':list(rows.values())}


def need_text(need,day):
    name=NEEDS.get(need['service_kind'],need['service_kind']);minute=need['at_abs_min']-day*1440
    when=f'{minute//60:02d}:{minute%60:02d}' if 0<=minute<1440 else '跨日时段'
    amount=need.get('quantity');unit=UNITS.get(need.get('unit'),need.get('unit') or '')
    if need.get('unit')=='target_SOC':amount=f'{amount*100:g}';unit='%'
    return f'{name}：约 {when}，{amount} {unit}（合成情境需求）。'


def case_from_source(proposal,annual,source,source_sha,annual_sha,lock_sha,allowed_schemas=None):
    if allowed_schemas is None:
        allowed_schemas=('joint-b-formal-preoutcome-candidate-v1','joint-b-formal-preoutcome-revision2-v1')
    require(proposal['schema'] in allowed_schemas and proposal['split'] is None and
            proposal['human_response'] is None and proposal['role_id']==annual['role_id']==source['role_id'],
            'Unsupported formal proposal/source')
    profile=profile_projection(source,annual,source_sha)
    A=plan_from_annual(annual,proposal,profile)
    all_events=[e for d in annual['A']['days'] for e in d['events']]
    commands=[]
    for i,c in enumerate(proposal['commands']):
        common={'command_id':proposal['proposal_id']+f'/command/{i}','asset_id':c['asset_id'],
                'device_class':c['device_class'],'source_A_sha256':digest(A),
                'reason_text':c['reason'].split('；')[0]+'。'}
        if c['kind']=='event_interval':
            source_events=[e for e in all_events if e['event_id']==c['event_id'] and e['asset_id']==c['asset_id']]
            require(len(source_events)==1 and source_digest(source_events[0])==c['source_event_sha256'] and
                    source_events[0]['need_ids']==c['fixed_need_ids'],'Formal command event/need mismatch')
            commands.append({**common,'kind':'event_interval','event_id':c['event_id'],
                 'A_start_abs_min':c['from_interval_abs_min'][0],'A_end_abs_min':c['from_interval_abs_min'][1],
                 'start_abs_min':c['to_interval_abs_min'][0],'end_abs_min':c['to_interval_abs_min'][1]})
        elif c['kind']=='ac_setpoint':
            require(c['intervals_abs_min'],'Empty AC command')
            ac_sources=[a for d in annual['AC']['days'] if d['day_index']==c['day_index']
                        for a in d['assets'] if a['asset_id']==c['asset_id']]
            require(len(ac_sources)==1 and source_digest(ac_sources[0])==c['source_AC_asset_sha256'] and
                    ac_sources[0]['usual_setpoint_C']==c['from_setpoint_C'],
                    'Formal AC command source mismatch')
            for j,(lo,hi) in enumerate(c['intervals_abs_min']):
                commands.append({**common,'command_id':common['command_id']+f'/interval/{j}',
                    'kind':'ac_setpoint','start_abs_min':lo,'end_abs_min':hi,
                    'from_setpoint_C':c['from_setpoint_C'],'to_setpoint_C':c['to_setpoint_C']})
        else:raise ValueError('Unknown formal command kind')
    B=apply_commands(A,commands,profile)
    events=[]
    for e in proposal['VPP_events']:
        r=e['household_request']
        require(r['metric']=='net_import_energy_reduction_vs_same_household_A' and
                r['meter_boundary']=='whole_household_grid_connection' and e['incentive'] is None,
                'Unsupported VPP semantics')
        events.append({'event_id':e['event_id'],'start_abs_min':e['start_abs_min'],
             'end_abs_min':e['end_abs_min'],'household_request':{'scope':'household',
             'text':f"本事件内，希望家庭从电网购入的电量比原安排少 {r['value']} {r['unit']}。",
             'quantity':r['value'],'unit':r['unit'],'metric':r['metric']},'incentive':None})
    day=proposal['day_index'];days=[d for d in annual['A']['days'] if d['day_index'] in (day,day+1)]
    weather=next(d['weather'] for d in days if d['day_index']==day)
    needs=[('当天：' if d['day_index']==day else '次日：')+need_text(n,d['day_index'])
           for d in days for n in d['needs']]
    result={'schema':'eb.joint_b.consumer.v1','identity':{'case_id':proposal['proposal_id'],
         'role_id':proposal['role_id'],'round_index':proposal['round_index'],'split':None,
         'date':proposal['date'],'day_index':day},'status':'source_bound_candidate','prototype_only':False,
         'human_label_count':0,'training_release':False,'profile':profile,
         'context':{'weather_days':[{'min_drybulb_C_derived':min(weather['drybulb_hourly_C']),
                                    'max_drybulb_C_derived':max(weather['drybulb_hourly_C'])}],
                    'pre_event_state':{'display_text':'当日设备初态尚未单独核算。'},
                    'daily_need_texts':needs},
         'vpp':{'events':events,'notice_abs_min':proposal['notification_abs_min'],
                'evidence_status':'declared_synthetic_event'},
         'commands':commands,'plans':{'A':A,'B':B},
         'quantities':[{'label':'整屋购电','A':{'value':None,'unit':'kWh','status':'not_computed'},
                        'B':{'value':None,'unit':'kWh','status':'not_computed'}}],
         'impacts':[],'after_horizon':{'status':'not_provided','EV_new_target_shortfall_days':[],
                                    'task_material_after_horizon':'unknown'},
         'result_note':'整屋购电、费用、VPP是否达标、空调用电、室温及后续生活服务影响尚未计算。',
         'display_assignment':{'left':proposal['presentation_order'][0],
                               'right':proposal['presentation_order'][1]},
         'scenario_family_id':proposal['scenario_family_id'],
         'collection_linkage':{'household_id':proposal['household_id'],'round_id':proposal['round_id'],
                               'source_scenario_id':proposal['source_scenario_id'],
                               'near_duplicate_family_id':proposal['near_duplicate_family_id'],
                               'derived_from':proposal['derived_from'],'source_version':proposal['source_version'],
                               'presentation_order':proposal['presentation_order'],
                               'participant_id':None,'formal_split':None},
         'bindings':{'formal_source_lock_sha256':lock_sha,'annual_sha256':annual_sha,
                     'active_profile_file_sha256':source_sha,
                     'proposal_sha256':source_digest(proposal)}}
    return bind(result)


def import_roles(snapshot_path,snapshot_sha,roles,out_dir):
    snapshot_data,lock=load_snapshot(snapshot_path,snapshot_sha)
    source_rows={r['role_id']:r for r in snapshot_data['roles']}
    proposals={r:[] for r in roles}
    for p in lock['proposals']:
        if p['role_id'] in proposals:proposals[p['role_id']].append(p)
    out_dir.mkdir(parents=True,exist_ok=True)
    reports=[]
    for role in roles:
        require(role in source_rows,'Role outside 300-source snapshot')
        ref=source_rows[role]
        if not ref['ordinary_A_eligible'] or not proposals[role]:
            reports.append({'role_id':role,'status':'unavailable',
                            'reason':'A_source_blocked' if not ref['ordinary_A_eligible'] else 'B_source_shortage',
                            'case_count':0});continue
        annual=json.loads(checked(ref['annual']['path'],ref['annual']['sha256']).read_text())
        profile=json.loads(checked(ref['profile']['path'],ref['profile']['sha256']).read_text())
        cases=[]
        for p in sorted(proposals[role],key=lambda x:x['round_index']):
            cases.append(case_from_source(p,annual,profile,ref['profile']['sha256'],
                                          ref['annual']['sha256'],snapshot_data['source_lock']['sha256']))
        target=out_dir/f'{role}.json';target.write_text(canonical(cases)+'\n')
        reports.append({'role_id':role,'status':'source_plans_only','case_count':len(cases),
                        'missing_rounds':[n for n in range(1,11) if n not in {c['identity']['round_index']for c in cases}],
                        'case_file':str(target),'case_file_sha256':sha(target),
                        'physical_pairs':0,'human_answers':0,'formal_split':None})
    return reports


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    sub=parser.add_subparsers(dest='mode',required=True)
    capture=sub.add_parser('snapshot');capture.add_argument('--out-dir',type=Path,default=HERE/'formal_source_snapshots')
    capture2=sub.add_parser('snapshot-revision2');capture2.add_argument('--out-dir',type=Path,default=HERE/'formal_source_snapshots')
    consume=sub.add_parser('import');consume.add_argument('--snapshot',type=Path,required=True)
    consume.add_argument('--snapshot-sha256',required=True);consume.add_argument('--roles',nargs='+',required=True)
    consume.add_argument('--out-dir',type=Path,default=HERE/'formal_case_files')
    args=parser.parse_args()
    if args.mode in ('snapshot','snapshot-revision2'):
        out=snapshot(args.out_dir) if args.mode=='snapshot' else snapshot_revision2(args.out_dir)
        print(json.dumps({'snapshot':str(out),'sha256':sha(out)},ensure_ascii=False))
    else:print(json.dumps(import_roles(args.snapshot,args.snapshot_sha256,args.roles,args.out_dir),ensure_ascii=False))
