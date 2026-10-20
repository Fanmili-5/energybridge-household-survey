"""Seal reference-50 v4 proposals into the v69 collector, without deployment/EP.

Old release contributes profiles only. All schedules and cases come from the
new v4 selection. Pending outcomes are null, never copied from old B results.
"""
import argparse
import copy
import json
import shutil
import subprocess
from collections import Counter
from pathlib import Path
from benchmark.ab_generation.common import read,save,verify,bound,sha,digest
from .questionnaire import HERE,COLLECTOR,UI,preview_assets,display_plans,changes,time


def proposal_question_copy(html):
    """Pending-outcome scores concern plan requests, never unobserved results."""
    substitutions={
        '室温与生活变化是否适合这户家庭':'温控请求与生活安排是否适合这户家庭',
        '用电量变化是否适合这户家庭':'用电时段与设备安排是否适合这户家庭',
        '四项均评价B相对A的调整是否适合这户家庭：1分很不合适，5分很合适，可填一位小数。VPP是否达标单独记录。':
        '四项均评价B相对A的提议安排：1分很不合适，5分很合适，可填一位小数。请按给定家庭的时段、温控请求和生活约束判断，不推测尚未计算的用电量、室温或VPP达标情况。',
    }
    for old,new in substitutions.items():
        if html.count(old)!=1:raise ValueError('V69_PROPOSAL_QUESTION_ANCHOR_CHANGED')
        html=html.replace(old,new)
    return html


def typed_control_copy(code):
    """Type the cooling sentinel per axis without hiding heating or fan axes."""
    old="key==='cooling_setpoint_C' ? `制冷${num(x[key]??x.value_C,1)}℃`"
    new="key==='cooling_setpoint_C' ? (x._eb_cooling_stop_fallback ? '暂停制冷请求（实际运行未计算）' : `制冷${num(x[key]??x.value_C,1)}℃`)"
    if code.count(old)!=1:raise ValueError('V69_CONTROL_FIELD_ANCHOR_CHANGED')
    return code.replace(old,new)


def build(collection,profiles_release,original_a,out):
    collection=Path(collection).resolve();profiles_release=Path(profiles_release).resolve();original_a=Path(original_a).resolve();out=Path(out).resolve()
    verify(collection);assignment=read(collection/'ASSIGNMENT.json');selected=assignment['selected_ids']
    if assignment['schema']!='eb.collection.assignment.v4' or len(selected)!=500:raise ValueError('EXACT_NEW_METHOD_500_REQUIRED')
    old=read(profiles_release/'FORMAL_RELEASE.json');old_index=read(profiles_release/'INDEX50.json')
    if digest({k:v for k,v in old.items() if k!='release_sha256'})!=old['release_sha256']:raise ValueError('PROFILE_RELEASE_SIGNATURE_CHANGED')
    original_records={x['household_id']:x for x in read(original_a/'SUBSET50.json')['records']}
    out.mkdir(parents=True,exist_ok=False);preview_assets(out)
    # Preserve the approved form and collection client. Only the renderer gets
    # pending-outcome and typed-control presentation branches.
    for name in ('index.html','entry.html','entry.js','collection-client.js'):
        shutil.copyfile(COLLECTOR/name,out/'public'/name)
    entry=out/'public/entry.html';entry_text=entry.read_text()
    entry_text=entry_text.replace('方案为参考仿真，不会改变现实电器的设置。','本版只评价调整提案，实际后果尚未计算，不会改变现实电器的设置。')
    entry_anchor='<p id="notice-text" class="section-note"></p>'
    if entry_text.count(entry_anchor)!=1:raise ValueError('V69_PROPOSAL_ENTRY_ANCHOR_CHANGED')
    entry_text=entry_text.replace(entry_anchor,entry_anchor+'<p class="section-note">本版本尚未计算实际用电、室温和VPP响应。请根据家庭需要与A/B计划评价提案；以后补做仿真不会改写本次作答条件。</p>')
    entry.write_text(entry_text)
    html=out/'public/index.html';s=html.read_text();old_notice='结果为仿真估算。用电减少可能伴随任务未完成；费用与补偿未计算。'
    if s.count(old_notice)!=1:raise ValueError('V69_OUTCOME_NOTICE_ANCHOR_CHANGED')
    s=s.replace(old_notice,'本题先评价调整提案是否适合本户。实际用电、室温、任务完成和VPP响应尚未计算，后续另行仿真；未计算不代表没有变化。')
    html.write_text(proposal_question_copy(s))
    js=out/'public/view.js';s=typed_control_copy(js.read_text())
    start=s.index('  function familyLines(c,p) {');end=s.index('\n  function ',start+5);section=s[start:end]
    if section.count('return lines;')!=1:raise ValueError('V69_FAMILY_CONTEXT_ANCHOR_CHANGED')
    section=section.replace('return lines;','return [...lines,...(c.collection_life_lines||[])];');s=s[:start]+section+s[end:];js.write_text(s)
    index={'schema':'eb.reference_benchmark.index.v1','ui_revision':UI,'mode':'reference_collection',
           'households':[],'cases':[],'profiles_sha256':{}}
    cases=[];audit=[];source_proofs=[]
    for ident in selected:
        pair=read(collection/'pairs'/(ident+'.json'));row=pair['row'];hid=row['household_id'];date=row['date']
        c=read(collection/'contexts'/(row['case_id']+'.json.gz'))
        if hid not in index['households']:
            profile_path=profiles_release/'public/households'/(hid+'.json')
            if sha(profile_path)!=old_index['profiles_sha256'][hid]:raise ValueError('ORIGINAL_HOUSEHOLD_PROFILE_CHANGED')
            target=out/'public/households'/(hid+'.json');target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(profile_path,target)
            index['households'].append(hid);index['profiles_sha256'][hid]=sha(target)
        profile=read(out/'public/households'/(hid+'.json'));names={m['member_id']:'成员'+str(i+1) for i,m in enumerate(profile['members'])}
        entry=next(x for x in original_records[hid]['cases'] if x['date']==date);raw_path=bound(original_a,entry['path'])
        if sha(raw_path)!=entry['sha256'] or entry['sha256']!=c['source']['A_case_sha256']:raise ValueError('ORIGINAL_A_CASE_CHANGED')
        raw=read(raw_path);plans=display_plans(pair)
        for side in ('A','B'):
            for control in plans[side]['controls']:
                if control['kind']=='ac_setpoint' and control.get('cooling_setpoint_C')==40:
                    control['_eb_cooling_stop_fallback']=True
        life_lines=[]
        for mid,name in names.items():
            spans=[[max(480,a),min(1920,z)] for a,z in c['operator_windows'].get(mid,[]) if a<1920 and z>480]
            life_lines.append(name+'在本题可操作设备的给定时段：'+('、'.join(time(a)+'—'+time(z) for a,z in spans) or '没有已声明的可操作窗口')+'。')
        life_lines.append('上述窗口与角色偏好是给定情境；B可能与其冲突，请判断是否接受，不预设答案。')
        cid=row['case_id']+'__v4__'+ident[:16]
        case={'schema':'eb.reference_benchmark.case.v1','case_id':cid,'household_id':hid,'date':date,'window_min':[480,1920],
              'plans':plans,'changes':changes(plans),'collection_life_lines':life_lines,
              'context':{'days':[{'date':d['date'],'family':d['activity']['family_context']} for d in raw['days']],
                         'needs':{'A':c['needs'],'B':c['needs']}},
              'outcome_status':'not_computed','impact':None,'VPP_results':None,'response':None,
              'VPP_requests':[dict(e,notification_min=480) for e in c['events']],
              'bindings':{'source_pair_sha256':sha(collection/'pairs'/(ident+'.json')),'source_A_case_sha256':entry['sha256'],
                          'source_profile_sha256':index['profiles_sha256'][hid],'selection_sha256':sha(collection/'ASSIGNMENT.json'),
                          'A_commands_sha256':pair['review']['A_commands_sha256'],'B_commands_sha256':pair['review']['B_commands_sha256'],
                          'outcome_status':'not_computed','label_condition':'proposal_judgment_before_physical_results',
                          'information_set':c['reference']['information_set']}}
        relative='cases/'+hid+'/'+ident+'.json';save(out/'public'/relative,case)
        index['cases'].append({'case_id':cid,'household_id':hid,'date':date,'path':relative,'sha256':sha(out/'public'/relative)})
        audit.append({'case_id':cid,'sample_id':ident,'issues':row['issues'],'full_plan_review_passed':pair['review']['passed'],
                      'outcome_status':'not_computed','old_B_results_copied':False})
        source_proofs.append({'household_id':hid,'date':date,'source_A_case_sha256':entry['sha256'],'source_profile_sha256':index['profiles_sha256'][hid]})
    if set(index['households'])!=set(old_index['households']) or set(Counter(x['household_id'] for x in index['cases']).values())!={10}:raise ValueError('ORIGINAL_REFERENCE50_FRAME_CHANGED')
    save(out/'public/index.json',index)
    result=subprocess.run(['node',str(HERE/'verify_display.js'),str(out)],capture_output=True,text=True)
    if result.returncode:raise ValueError('REFERENCE50_V69_DISPLAY_REJECTED:'+result.stderr[-3000:])
    models=read(out/'DISPLAY_MODELS.json')
    if any('制冷40' in m['changes']+m['schedule'] for m in models.values()):raise ValueError('COOLING_FALLBACK_MISREPRESENTED')
    save(out/'DISPLAY_MODELS50.json',models)
    from sys import path as sys_path
    sys_path.insert(0,str(COLLECTOR))
    from answer_contract import ANSWER_INSTRUCTIONS
    instructions=copy.deepcopy(ANSWER_INSTRUCTIONS)
    instructions['collection_condition']='本版本评价提案的操作时段、温控请求与生活安排；不要求推测未计算的用电量、室温或达标。后续仿真不会改写受访者当时看到的资料和答案。'
    instructions['scores']['comfort_score']['meaning']='温控请求与生活安排是否适合这户家庭'
    instructions['scores']['energy_score']['meaning']='用电时段与设备安排是否适合这户家庭'
    instructions['objective_outcomes']='实际用电、室温、任务完成和VPP达标未计算，不要求参与者推测；后续结果另行关联冻结A/B。'
    save(out/'ANSWER_INSTRUCTIONS.json',instructions)
    index['ui_assets_sha256']={p.name:sha(p) for p in (out/'public').iterdir() if p.is_file()};save(out/'INDEX50.json',index)
    save(out/'SOURCE_IDENTITY.json',{'records':source_proofs,'same_50_households_and_10_original_dates':True,
                                   'old_profile_release_sha256':old['release_sha256'],'original_A_command_values_and_times_changed':False})
    save(out/'PLAN_REVIEW.json',{'passed':all(x['full_plan_review_passed'] for x in audit),'records':audit,'new_engine_runs':0})
    manifest={'schema':'eb.reference_benchmark.release.v1','households':50,'cases':500,'questions_per_household':10,
              'cohort_id':'reference50-v4-proposal-20261020','assignment_lease_seconds':7200,
              'ui_revision':UI,'response_contract':'eb.required_role_response.v69',
              'source_pins':{'original_profile_release_sha256':old['release_sha256'],'collection_manifest_sha256':sha(collection/'MANIFEST.json'),
                             'builder_sha256':sha(Path(__file__))},'type_counts':old['type_counts'],
              'A_stage':'normal_A_v46_20261017_command_equivalent_import','B_stage':'collection_selection_v4_20261020',
              'physical_stage':'not_run_for_new_B','impact_stage':'not_computed',
              'human_collection_release':True,'training_release':False,'fixture_only':False,'source_case_bytes_modified':False,
              'source_case_definition':'new_v4_cases_sealed_before_collection;old500_cases_not_reused_or_modified',
              'new_EP_runs':0,'full1000_deferred_by_user':True,'entry_mode':'open_no_invitation','timeline':False,
              'quality_policy':'manual_versioned_review_no_auto_labels','outcome_status':'not_computed',
              'collection_condition':'proposal_judgment_before_physical_results','score_interpretation':'plan_timing_and_control_requests_not_realized_outcomes','production_deployed':False}
    manifest['files']={str(p.relative_to(out)):sha(p) for p in sorted(out.rglob('*')) if p.is_file()}
    manifest['implementation_files']={p.name:sha(p) for p in sorted(COLLECTOR.iterdir()) if p.is_file()}
    manifest['release_sha256']=digest(manifest);save(out/'FORMAL_RELEASE.json',manifest)
    from release import Release
    checked=Release(out)
    return {'households':len(checked.households),'cases':len(checked.records),'release_sha256':checked.signature,
            'outcome_status':'not_computed','new_engine_runs':0,'production_deployed':False,'online_questionnaire_changed':False}


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--collection',required=True);p.add_argument('--profiles-release',required=True);p.add_argument('--original-a',required=True);p.add_argument('--out',required=True);a=p.parse_args();print(json.dumps(build(a.collection,a.profiles_release,a.original_a,a.out),ensure_ascii=False))
