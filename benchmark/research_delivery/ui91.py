"""Bind new materials to the approved UI91 assets, offline and answer-free."""
import argparse
import copy
import difflib
import shutil
import subprocess
from pathlib import Path
from benchmark.ab_generation.common import read,save,sha,digest,seal
from benchmark.ab_generation.unified.contract import config
from benchmark.project.questionnaire import display_plans,changes,time
from .presentation import plans as semantic_plans,equivalent_display


def context_lines(questionnaire,profile,calendar,date,names):
    """Render existing context; do not infer a new habit, action or outcome."""
    priority=profile.get('attitude',{}).get('priority')
    if not priority:raise ValueError('PROFILE_ATTITUDE_PRIORITY_MISSING')
    lines=['你代入这户家庭：'+priority]
    day_rows=[]
    for day in calendar.get('days',[]):
        family=day.get('family',{});parts=[]
        if family.get('dinner_min') is not None:parts.append('晚餐'+time(family['dinner_min']))
        for mid,t in sorted(family.get('bath_times_min',{}).items()):
            if t is not None:parts.append(names.get(mid,'原登记成员')+'洗浴'+time(t))
        if parts:
            row='原定生活（'+day['date']+'）：'+'；'.join(parts)+'。这些安排不因B改变。'
            lines.append(row);day_rows.append(row)
    labels={}
    for device in profile['devices']:
        label=device['label']+('（'+device['room_label']+'）' if device.get('room_label') else '')
        labels.setdefault(device['asset_id'],[])
        if label not in labels[device['asset_id']]:labels[device['asset_id']].append(label)
    event=questionnaire['event'];lo,hi=event['start_min'],event['end_min']
    overlap=lambda pair:max(0,min(pair[1],hi)-max(pair[0],lo))
    reason_rows=[]
    for aid,reasons in sorted(questionnaire['reasons'].items()):
        fragments=[]
        for reason in reasons:
            role=reason['role']
            if role=='direct_event_request':
                for evidence in reason['evidence']:
                    kind=evidence['kind']
                    if kind=='event_service_reschedule':
                        fragments.append('该程序在VPP时段内的计划运行从'+str(overlap(evidence['A_interval']))+'分钟变为'+str(overlap(evidence['B_interval']))+'分钟')
                    elif kind=='event_thermal_command':
                        fragments.append(time(evidence['start_min'])+'—'+time(evidence['end_min'])+'改变温控请求；实际运行、温度与用电响应未知')
                    elif kind=='event_charging_permission_pause':
                        fragments.append(time(evidence['start_min'])+'—'+time(evidence['end_min'])+'请求暂停充电；原目标电量和出发期限保留，实际补能结果未知')
                    else:raise ValueError('UI91_REASON_KIND_NOT_RENDERED:'+kind)
            elif role=='support_event_request':
                kinds={e['kind'] for e in reason['evidence']}
                allowed={'operator_conflict_caused_by_event_request','room_conflict_caused_by_event_request','known_schedule_supply_conflict_caused_by_event_request'}
                if not kinds<=allowed:raise ValueError('UI91_SUPPORT_REASON_NOT_RENDERED')
                fragments.append('配合事件相关动作重排；移除这项配套动作后，会重新出现已核对的人员、房间或计划功率冲突（不表示实际跳闸）')
            elif role=='necessary_original_deadband_companion':
                fragments.append('冷热设定配套调整以保留原阈值间隔；不代表已取得另一温控模式的执行同意')
            elif role=='same_material_dependent_service_chain':
                fragments.append('与同一批衣物的洗后烘干衔接；未据此声称这是唯一必要安排')
            else:raise ValueError('UI91_REASON_ROLE_NOT_RENDERED:'+role)
        row='动作与事件的关系——'+'、'.join(labels.get(aid,['原登记设备']))+'：'+'；'.join(dict.fromkeys(fragments))+'。这是计划依据，不是收益保证或接受建议。'
        lines.append(row);reason_rows.append(row)
    return lines,dict(attitude_priority=priority,calendar_lines=day_rows,action_reason_lines=reason_rows,
        date=date,calendar_source='approved_case.context.days',new_calendar_or_preference_generated=False)


def adapt_offline_assets(public):
    """Keep UI91 layout; disclose missing targets and in-memory preview transport."""
    view=public/'view.js';before=view.read_text()
    original="`${span(r)}，希望${r.direction==='down'?'降低':'增加'}${num(r.target_kw)}kW；${time(r.notification_min)}通知。`"
    replacement="`${span(r)}，${Number.isFinite(r.target_kw)?`希望${r.direction==='down'?'降低':'增加'}${num(r.target_kw)}kW`:`请求${r.direction==='down'?'降低':'增加'}用电；本题未设定数值目标`}；${time(r.notification_min)}通知。`"
    if before.count(original)!=1:raise ValueError('APPROVED_UI91_REQUEST_ANCHOR_CHANGED')
    after=before.replace(original,replacement);view.write_text(after)
    html=public/'index.html';old_html=html.read_text()
    save_note='草稿自动保存，提交后生成回执。凭恢复码可换设备续填。'
    if old_html.count(save_note)!=1:raise ValueError('APPROVED_UI91_PREVIEW_NOTICE_ANCHOR_CHANGED')
    new_html=old_html.replace(save_note,'离线资料预览：填写内容仅在当前页面暂存，不保存正式答卷，也不生成回执。')
    if new_html.count('src="view.js"')!=1:raise ValueError('APPROVED_UI91_RENDERER_ANCHOR_CHANGED')
    new_html=new_html.replace('src="view.js"','src="view.js?offline_sha='+sha(view)+'"')
    html.write_text(new_html)
    return dict(version='ui91_offline_copy_v1',
        reasons=['null_event_target_is_unspecified_not_zero','preview_has_no_formal_save_or_receipt','offline_renderer_hash_invalidates_stale_cache'],
        patch=''.join(difflib.unified_diff(before.splitlines(True),after.splitlines(True),fromfile='approved/view.js',tofile='offline/view.js'))+
            ''.join(difflib.unified_diff(old_html.splitlines(True),new_html.splitlines(True),fromfile='transport-adapted/index.html',tofile='offline/index.html')),
        changes_to_layout=False,changes_to_3d=False,changes_to_answers_or_outcomes=False)


def build(collection,approved,out):
    collection,approved,out=map(lambda x:Path(x).resolve(),(collection,approved,out))
    materials=read(collection/'MATERIALS.json.gz');source_index=read(approved/'INDEX50.json')
    original_cases={(r['household_id'],r['date']):r for r in source_index['cases']}
    out.mkdir(exist_ok=False,parents=True);public=out/'public';public.mkdir()
    pins={}
    for p in (approved/'public').iterdir():
        if p.is_file() and p.suffix in ('.html','.js','.css'):
            pins[str(p)]=sha(p);shutil.copy2(p,public/p.name)
    # Use UI91 assets with a recorded, minimal offline-copy adaptation.
    # The signed collection bank and approved source assets are never written.
    html=(public/'index.html').read_text()
    if 'src="collection-client.js"' not in html:raise ValueError('APPROVED_UI91_TRANSPORT_ANCHOR_MISSING')
    html=html.replace('src="collection-client.js"','src="preview-client.js"')
    html=html.replace('50户正式问卷','UI91 · 生成方法离线核对').replace('<div class="collection-toolbar">','<div class="collection-toolbar" hidden>')
    (public/'index.html').write_text(html)
    adaptation=adapt_offline_assets(public)
    adaptation['approved_renderer_sha256']=sha(approved/'public/view.js')
    adaptation['offline_renderer_sha256']=sha(public/'view.js')
    save(out/'OFFLINE_ASSET_ADAPTATION.json',adaptation)
    index=dict(schema='eb.reference_benchmark.index.v1',ui_revision=source_index['ui_revision'],
        presentation_revision=source_index.get('presentation_revision'),mode='read_only_material_preview',
        households=[],cases=[],profiles_sha256={},physical_review_index=None)
    # A null key is not a valid review locator for the existing client.
    index.pop('physical_review_index')
    checks=[];profiles={};source_contexts={};outside_checks=[]
    for p,h in read(collection/'PRE_GENERATION.json')['source_sha256'].items():
        if not p.endswith('.json'):continue
        data=read(p)
        if data.get('schema')=='eb.unified.inputs.v1':
            for r in data['records']:
                cp=Path(r['context_path']);cp=cp if cp.is_absolute() else Path(p).parent/cp
                source_contexts[(r['household_id'],r['date'])]=cp
            break
    cfg=read(collection/'PRE_GENERATION.json')['configuration']
    for m in materials:
        hid,date=m['household_id'],m['date'];q=copy.deepcopy(m['questionnaire_context'])
        source_c=read(source_contexts[(hid,date)])
        if digest(source_c)!=m['binding']['context_sha256']:raise ValueError('PROJECTION_CONTEXT_MISMATCH')
        q['electrical_constraints']=source_c.get('electrical')
        old=original_cases[(hid,date)]
        old_path=approved/'public'/old['path']
        if sha(old_path)!=old['sha256']:raise ValueError('SOURCE_UI91_CASE_CHANGED')
        original_context=read(old_path)['context']
        if hid not in index['households']:
            p=approved/'public/households'/(hid+'.json')
            if sha(p)!=source_index['profiles_sha256'][hid]:raise ValueError('SOURCE_UI91_PROFILE_CHANGED')
            profile=read(p);profile['candidate_energy_use_profile']=m['household_profile']
            profiles[hid]=profile
            target=public/'households'/(hid+'.json');save(target,profile)
            pins[str(p)]=sha(p);index['households'].append(hid);index['profiles_sha256'][hid]=sha(target)
        profile=profiles[hid];plans=semantic_plans(m)
        if not equivalent_display(m,plans):raise ValueError('DISPLAY_PROJECTION_CHANGED_CONTROL_MEANING')
        for side in ('A','B'):
            for c in plans[side]['controls']:
                if c['kind']=='ac_setpoint' and c.get('cooling_setpoint_C')==40:c['_eb_cooling_stop_fallback']=True
        lines=(q['household_text'] or '').splitlines()
        names={v['member_id']:'成员'+str(i+1) for i,v in enumerate(profile['members'])}
        kinds={'washer':'洗衣','dryer':'烘干','dishwasher':'洗碗','ac':'空调','water_heater':'热水','ev':'车辆充电','bath':'洗浴','comfort':'舒适要求'}
        devices={d['asset_id']:kinds.get(d.get('kind',next(iter(d.get('types',[])),'')),'设备') for d in q['equipment']}
        extra,context_audit=context_lines(q,m['household_profile'],original_context,date,names)
        lines+=extra
        lines += [q['participant_notice']]
        outside=[]
        for component in m['proposal']['components']:
            for patch in component['patches']:
                if patch['type']=='rows':
                    original={r[patch['identity']]:r for r in m['A'][patch['collection']]}
                    for after in patch['rows']:
                        before=original[after[patch['identity']]]
                        if before==after:continue
                        if min(before['start_min'],after['start_min'])<480 or max(before['end_min'],after['end_min'])>1920:
                            outside.append(dict(asset_id=after['asset_id'],kind=after.get('kind','程序'),before=before,after=after))
                elif patch['start_min']<480 or patch['end_min']>1920:
                    outside.append(dict(asset_id=component['asset_id'],kind='control_request',patch=patch))
        if outside:
            lines.append('图表展示08:00至次日08:00；本题以下完整改动超出图表范围，也需要一并判断：')
            labels={'load':'装入','unload':'取出','washer':'洗衣程序','dryer':'烘干程序','dishwasher':'洗碗程序','ev_charge_window':'允许充电窗口'}
            for change in outside:
                label=devices.get(change['asset_id'],'设备')+'的'+labels.get(change['kind'],'控制请求')
                if 'before' in change:
                    a,b=change['before'],change['after']
                    lines.append(label+'：A为'+time(a['start_min'])+'—'+time(a['end_min'])+'，B改为'+time(b['start_min'])+'—'+time(b['end_min'])+'。')
                else:
                    p=change['patch'];lines.append(label+'：B请求'+time(p['start_min'])+'—'+time(p['end_min'])+'；这是控制提案，实际运行和后果未知。')
        outside_checks.append(dict(id=m['id'],outside_changes=outside,all_outside_changes_explicitly_listed=True))
        actors={mid for j in q['member_and_permission_context'] for mid in j['actual_proposed_operator_ids']}
        availability_end=max([1920]+[x['after']['end_min'] for x in outside if x.get('kind') in ('load','unload')])
        for mid in sorted(actors):
            spans=[(max(480,a),min(availability_end,z)) for a,z in q['operator_availability'].get(mid,[]) if a<availability_end and z>480]
            lines.append(names.get(mid,'原定协助者')+'的给定可操作时段：'+('、'.join(time(a)+'—'+time(z) for a,z in spans) or '本题窗口内没有已声明时段')+'；有空不代表已经同意执行B。')
        capacity=q.get('electrical_constraints') or {}
        if capacity.get('supply_W') is not None:lines.append('本题给定的住宅总回路容量为'+str(capacity['supply_W']/1000)+'千瓦。')
        for n in q['original_requirements']:
            if n.get('deadline_min') is not None and n.get('release_min') is not None:
                quantity=('，衣物'+str(n['quantity'])+'公斤') if n.get('unit')=='kg' else ''
                lines.append('给定需求：'+kinds.get(n['kind'],'生活服务')+quantity+'，可开始于'+time(n['release_min'])+'，要求在'+time(n['deadline_min'])+'前交付；原要求不因B改变。')
        for j in q['member_and_permission_context']:
            lines.append(devices.get(j['asset_id'],'设备')+'：提议操作人'+('、'.join(names.get(mid,'原定协助者') for mid in j['actual_proposed_operator_ids']) or '不涉及装取操作')+'；执行同意尚未取得。')
        cid=m['id'];case=dict(schema='eb.reference_benchmark.case.v1',case_id=cid,household_id=hid,date=date,
            window_min=[480,1920],plans=plans,changes=changes(plans),project_presentation={'family_lines':lines},
            collection_life_lines=[],context={'days':original_context.get('days',[]),
                'needs':{'A':q['original_requirements'],'B':q['original_requirements']}},
            questionnaire_context=q,outcome_status='not_computed',impact=None,VPP_results=None,response=None,
            offline_presentation_context=context_audit,
            VPP_requests=[dict(cfg['event'],notification_min=480)],
            bindings={**m['binding'],'source_pair_sha256':digest({'A':m['A'],'B':m['B']}),
                'selection_sha256':sha(collection/'SELECTION.json'),'information_set':'offline_unexecuted_A_plan',
                'label_condition':'proposal_before_outcomes;no_execution_consent'},
            old_physical_fields_copied=False)
        case['portrait_A_lineage']='shadow_audit;new_portrait_not_claimed_to_have_generated_old_A'
        relative='cases/'+hid+'/'+cid+'.json';save(public/relative,case)
        index['cases'].append(dict(household_id=hid,date=date,case_id=cid,path=relative,sha256=sha(public/relative)))
        checks.append(dict(id=cid,full_A_B_binding=m['binding'],original_profile_sha256=source_index['profiles_sha256'][hid],
            unknown_outcomes=True,answer=None,original_calendar_only=True))
    save(public/'index.json',index);save(out/'INDEX50.json',index)
    save(out/'SOURCE_PINS.json',pins);save(out/'MATERIAL_BINDINGS.json',checks)
    save(out/'DISPLAY_COMPLETENESS.json',dict(cases=len(outside_checks),cases_with_outside_changes=sum(bool(x['outside_changes']) for x in outside_checks),
        records=outside_checks,full_A_B_binding_unchanged=True,renderer_window_unchanged=True))
    test=Path(__file__).parents[1]/'project/verify_refined_display.js'
    run=subprocess.run(['node',str(test),str(out)],capture_output=True,text=True)
    offline_run=subprocess.run(['node',str(Path(__file__).with_name('verify_offline_ui91.js')),str(out)],capture_output=True,text=True)
    source_unchanged=all(sha(Path(p))==h for p,h in pins.items())
    save(out/'DISPLAY_CHECK.json',dict(returncode=run.returncode,stdout=run.stdout,stderr=run.stderr,
        exact_UI91_renderer_bytes_unchanged=sha(public/'view.js')==sha(approved/'public/view.js'),
        offline_copy_adaptation=adaptation['version'],approved_sources_unchanged=source_unchanged,
        offline_checks=dict(returncode=offline_run.returncode,stdout=offline_run.stdout,stderr=offline_run.stderr),
        frontend_comprehension_claimed=False,answers_written=0,online_changed=False))
    if run.returncode:raise ValueError('UI91_OFFLINE_DISPLAY_FAILED:'+run.stderr[-1500:])
    if offline_run.returncode:raise ValueError('UI91_OFFLINE_COPY_FAILED:'+offline_run.stderr[-1500:])
    if not source_unchanged:raise ValueError('APPROVED_UI91_SOURCE_CHANGED')
    seal(out,dict(schema='eb.unified.ui91_offline.v2',cases=len(checks),physical_runs=0,answers_written=0,online_changed=False))
    return dict(cases=len(checks),display_check=True,frontend='approved_UI91',online_changed=False)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--collection',required=True);p.add_argument('--approved',required=True);p.add_argument('--out',required=True)
    a=p.parse_args();print(build(a.collection,a.approved,a.out))
