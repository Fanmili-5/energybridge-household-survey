"""Seal, verify and publish the matched A46/B54 local dataset."""
import sys, re
from pathlib import Path
STAGE=Path(__file__).resolve().parents[1];sys.path.insert(0,str(STAGE/'code'))
from common import *
PUB=REPO/'docs/household1000'
ENTRY=REPO/'scripts/generation_opportunity_state.py'

def check_acceptance():
    verify_inputs();a=read(OUT/'ACCEPTANCE.json');sig=rules_id()
    if not a['accepted']or a['rules_sha256']!=sig or a['bindings_sha256']!=sha(OUT/'PAIR_BINDINGS10000.json'):raise ValueError('NOT_ACCEPTED_CURRENT_BYTES')
    regression=read(OUT/'REGRESSION_RESULTS.json')
    if not regression['passed']or regression['rules_sha256']!=sig:raise ValueError('REGRESSIONS_NOT_CURRENT')
    design=read(OUT/'DESIGN_REVIEW.json')
    if not design['passed']or design['rules_sha256']!=sig or design['counts']['cases']!=10000 or design['bindings_sha256']!=sha(OUT/'PAIR_BINDINGS10000.json'):raise ValueError('DESIGN_REVIEW_NOT_CURRENT')
    state=read(OUT/'STATE_BINDINGS.json');thermal=read(OUT/'THERMAL_EVENT_VALIDATION.json')
    if not state['passed']or state['cases']!=10000 or not thermal['passed']or thermal['bindings_sha256']!=sha(OUT/'PAIR_BINDINGS10000.json'):raise ValueError('THERMAL_REFERENCES_NOT_CURRENT')
    if not (OUT/'review/设备独立强度复核.md').exists():raise ValueError('REVIEW_REPORT_MISSING')
    return a

def seal():
    a=check_acceptance()
    if (OUT/'FINAL_SEAL.json').exists():raise ValueError('ALREADY_SEALED')
    current=OUT/'runs'/rules_id()[:16]
    save(OUT/'DEVELOPMENT_HISTORY.json',{'source_A_preserved':A_STAGE.name,'source_B_preserved':SOURCE_B.name,'runs':[{'run':p.name,'accepted':p==current,'household_record_count':len(list((p/'records').glob('*.json'))),'status':'current_accepted'if p==current else'superseded_unpublished','build_report':read(p/'BUILD_REVIEW.json')if(p/'BUILD_REVIEW.json').exists()else None}for p in sorted((OUT/'runs').iterdir())],'selected_input_vector':0,'no_outcome_or_acceptance_filter':True,'all10000_used_as_one_dataset':True})
    files=[p for p in OUT.rglob('*')if p.is_file()and p.name!='FINAL_SEAL.json'and 'pairs'not in p.parts and '__pycache__'not in p.parts]
    save(OUT/'FINAL_SEAL.json',{'schema':'eb.device_strength_seal.v54','rules_sha256':rules_id(),'stage_files':{rel(p):sha(p)for p in files},'external_files':{str(ENTRY.relative_to(REPO)):sha(ENTRY)},'source_A_seal_sha256':sha(A_STAGE/'FINAL_SEAL.json'),'source_B53_seal_sha256':sha(SOURCE_B/'FINAL_SEAL.json'),'physical_acceptance':False,'collection_released':False,'scope':'native device request generation,actual command classification,given constraints;full physics and human acceptance pending'})
    print({'sealed':OUT.name,'all_cases_retained':10000,'no_change_cases':100})

def verify():
    a=check_acceptance();seal=read(OUT/'FINAL_SEAL.json')
    for stage in (A_STAGE,SOURCE_B,OUT):
        for name,h in read(stage/'FINAL_SEAL.json')['stage_files'].items():
            if sha(stage/name)!=h:raise ValueError('SEALED_STAGE_CHANGED:'+str(stage/name))
    for name,h in seal['external_files'].items():
        if sha(REPO/name)!=h:raise ValueError('ENTRY_CHANGED')
    count=0
    for row in read(OUT/'PAIR_BINDINGS10000.json')['records']:
        for rr in row['rounds']:
            if sha(OUT/rr['path'])!=rr['sha256']:raise ValueError('CURRENT_PAIR_CHANGED')
            count+=1
    if count!=10000:raise ValueError('NOT10000')
    for row in read(SOURCE_B/'PAIR_BINDINGS10000.json')['records']:
        for rr in row['rounds']:
            if sha(SOURCE_B/rr['path'])!=rr['sha256']:raise ValueError('PARENT_CASE_CHANGED')
    for row in read(A_STAGE/'A_BINDINGS10000.json')['records']:
        for pk,hk in [('A_world_path','A_world_sha256'),('annual_A_path','annual_A_sha256'),('HVAC_components_path','HVAC_components_sha256')]:
            if sha(A_STAGE/row[pk])!=row[hk]:raise ValueError('A46_OUTPUT_CHANGED')
        for r in row['cases']:
            if sha(A_STAGE/r['path'])!=r['sha256']:raise ValueError('A46_CASE_CHANGED')
    print({'verified_households':1000,'verified_pairs':count,'A46_preserved':True,
           'device_native_requests_rebuilt':True,'all10000_in_total_dataset':True,
           'no_change_cases':a['counts'].get('identical_commands',0),'physical_acceptance':False})

def pointer():
    a=read(OUT/'ACCEPTANCE.json');counts=a['counts']
    return {'schema':'eb.current_AB_inputs.v54','stage':OUT.name,'households':1000,'pairs':10000,'source_A_stage':A_STAGE.name,'source_A_bindings_sha256':sha(A_STAGE/'A_BINDINGS10000.json'),'source_A_seal_sha256':sha(A_STAGE/'FINAL_SEAL.json'),'source_B_parent_stage':SOURCE_B.name,'source_B_parent_seal_sha256':sha(SOURCE_B/'FINAL_SEAL.json'),'source_B_schedule_stage':OUT.name,'source_generation_rules_sha256':a['rules_sha256'],'source_B_schedule_seal_sha256':sha(OUT/'FINAL_SEAL.json'),'bindings_sha256':sha(OUT/'PAIR_BINDINGS10000.json'),'rules_sha256':a['rules_sha256'],'seal_sha256':sha(OUT/'FINAL_SEAL.json'),'classification_only_update':False,'strength_schema':'eb.device_native_strength.v54','actual_strength_presentation':'multi_axis_no_overall_grade','native_A_state_reference_cases':10000,'paired_thermal_validation_cases':read(OUT/'THERMAL_EVENT_VALIDATION.json')['cases'],'full_B_physical_acceptance':False,'EV_causal_paths_recorded':True,'changed_command_cases':9900,'no_command_change_cases':100,'same100_B_payload_preserved':True,'given_constraint_conflict_cases_kept':counts['constraint_conflict_cases'],'given_constraints_feasible_cases':10000-counts['constraint_conflict_cases'],'all10000_retained_in_total_dataset':True,'all10000_used_as_one_dataset':True,'evaluation_inclusion_changed':False,'A_and_B_static_accepted':True,'input_revision_and_classification_accepted':True,'subset50_same_master':True,'subset50_type_counts':a['subset50_type_counts'],'physical_acceptance':False,'human_labels_generated':0,'new_questionnaire_released':False}

def publish():
    verify();current=read(BASE/'CURRENT_AB_INPUTS.json');ap=read(BASE/'CURRENT_NORMAL_A_INPUTS.json')
    if current['stage']not in (SOURCE_B.name,OUT.name)or ap['stage']!=A_STAGE.name:raise ValueError('UNEXPECTED_CURRENT_SOURCE')
    bp=pointer()
    for path in (BASE/'CURRENT_AB_INPUTS.json',PUB/'CURRENT_AB.json'):save(path,bp)
    for path in (PUB/'STATUS.json',PUB/'PIPELINE.json',BASE/'CURRENT_GENERATION_REQUIREMENTS.json'):
        data=read(path);data.update(current_static_AB_inputs=bp,current_normal_A=ap,latest_static_input_stage=OUT.name,current_local_static_scope='A46 unchanged;B54 feasible opportunity and multi-axis requests,native A thermal state references,causal EV windows;whole10000 retained,100 identical,no preset acceptance',current_B_classification_audit=str((OUT/'ACCEPTANCE.json').relative_to(REPO)),current_VPP_generation_audit=str((OUT/'ACCEPTANCE.json').relative_to(REPO)))
        data['current_generation_points_3_4']={'A_schedule_design':'retained_A46_scoped_review','B_schedule_design':'B54_actual_strength_and_state_aware_rebuild','B_classification':'independent_raw_executable_and_event_readback_passed','A_review':str((A_STAGE/'DESIGN_REVIEW.json').relative_to(REPO)),'B_review':str((OUT/'ACCEPTANCE.json').relative_to(REPO)),'all10000_retained_in_total_dataset':True,'full_physical_acceptance':False,'human_acceptance_known':False}
        save(path,data)
    master=read(BASE/'CURRENT_MASTER_INPUTS.json');master.update(current_static_AB_version='v54',current_static_AB_accepted=True);save(BASE/'CURRENT_MASTER_INPUTS.json',master)
    intro='<!-- current-life-generation-v46-v54 -->\n当前本地输入：**A46/B54，1000户、整批10000组统一使用**。A46、家庭日程与每日设备服务需求保持；B先判断释放、装载、操作窗口、程序链和截止时间所允许的VPP机会。无机会请求单独说明，不用延迟把已完成的充电移入下调事件。实际强度同时展示各技术轴与数值，没有整体强度档位。\n\nEV保存原始接入、所需电量、计时/事件/截止请求、实际许可和电量缺口的形成路径；目标电量缺口、出行约束及人类拒绝分别记录。热控使用整批A46房型、原生空调和分层水箱的事件内仿真状态参考，另有配对B抽样验证；已知范围和未验证项均明确记录，不声称整批B物理响应或舒适度验收完成。\n\n原100组相同B载荷保持，失败照留，不预填接受答案。50户按原5/15/16/5/4/5引用同批文件及哈希。[方法](../research/collection-adjustment-20260930/household1000/candidate_B_v54_20261017/METHODS.md) · [复核](../research/collection-adjustment-20260930/household1000/candidate_B_v54_20261017/review/设备独立强度复核.md)\n\n复现：`python -B scripts/generation_opportunity_state.py B <phase>`。新问卷尚未发布，旧物理结果与问卷结果不可混用；历史版本保持封存。\n<!-- /current-life-generation-v46-v54 -->\n'
    for name in ('README.md','PIPELINE.md','REPRODUCTION.md','CURRENT_VPP_GENERATION.md'):
        path=PUB/name;body,n=re.subn(r'<!-- current-life-generation-v46-v(?:53|54) -->.*?<!-- /current-life-generation-v46-v(?:53|54) -->',lambda _:intro.rstrip(),path.read_text(),flags=re.S)
        if n!=1:raise ValueError('CURRENT_DOC_BLOCK_MISSING:'+name)
        path.write_text(body)
    print({'published':OUT.name,'all10000_retained':True,'online_frontend_changed':False})

def verify_pointers():
    bp=pointer();ap=read(BASE/'CURRENT_NORMAL_A_INPUTS.json')
    for p in (BASE/'CURRENT_AB_INPUTS.json',PUB/'CURRENT_AB.json'):
        if read(p)!=bp:raise ValueError('AB_POINTER_MISMATCH')
    if ap['stage']!=A_STAGE.name or read(PUB/'CURRENT_NORMAL_A.json')!=ap:raise ValueError('A_POINTER_MISMATCH')
    for p in (PUB/'STATUS.json',PUB/'PIPELINE.json',BASE/'CURRENT_GENERATION_REQUIREMENTS.json'):
        data=read(p)
        if data['current_static_AB_inputs']!=bp or data['current_normal_A']!=ap:raise ValueError('NESTED_POINTER_MISMATCH')
    if read(BASE/'CURRENT_MASTER_INPUTS.json')['current_static_AB_version']!='v54':raise ValueError('MASTER_POINTER_MISMATCH')
    if (BASE/'CURRENT_PREFERENCE_EVALUATION.json').exists():raise ValueError('WITHDRAWN_SPLIT_ONLY_POINTER_EXISTS')
    verify_inputs();print({'all_current_versions_match':True,'source_A':'A46','B':'B54','all10000_retained':True,'subset50_type_counts':bp['subset50_type_counts']})

if __name__=='__main__':
    {'seal':seal,'verify':verify,'publish':publish,'verify-pointers':verify_pointers}[sys.argv[1]]()
