"""Seal, verify and publish the matched A46/B51 local dataset."""
import sys, re
from pathlib import Path
STAGE=Path(__file__).resolve().parents[1];sys.path.insert(0,str(STAGE/'code'))
from common import *
PUB=REPO/'docs/household1000'
ENTRY=REPO/'scripts/generation_noop_refinement.py'

def check_acceptance():
    verify_inputs();a=read(OUT/'ACCEPTANCE.json');sig=rules_id()
    if not a['accepted']or a['rules_sha256']!=sig or a['bindings_sha256']!=sha(OUT/'PAIR_BINDINGS10000.json'):raise ValueError('NOT_ACCEPTED_CURRENT_BYTES')
    regression=read(OUT/'REGRESSION_RESULTS.json')
    if not regression['passed']or regression['rules_sha256']!=sig:raise ValueError('REGRESSIONS_NOT_CURRENT')
    return a

def seal():
    a=check_acceptance()
    if (OUT/'FINAL_SEAL.json').exists():raise ValueError('ALREADY_SEALED')
    run=OUT/'runs'/rules_id()[:16]
    save(OUT/'DEVELOPMENT_HISTORY.json',{'source_B_preserved':SOURCE_B.name,
        'unpublished_split_only_draft_withdrawn_after_user_clarification':True,
        'all_generated_runs':[{'run':p.name,'accepted':p==run,
            'status':'current_accepted'if p==run else'superseded_before_publication',
            'superseded_reason':None if p==run else'unpublished revision plan superseded after the user clarified the unified10000-case dataset',
            'build_report':read(p/'BUILD_REVIEW.json')if(p/'BUILD_REVIEW.json').exists()else None}for p in sorted((OUT/'runs').iterdir())],
        'no_physical_success_or_human_acceptance_filter':True,
        'maximum_identical_case_count':100,
        'all10000_used_as_one_dataset':True,
        'old_identical_commands_are_the_explicit_revision_scope':True})
    files=list((OUT/'code').glob('*.py'))+list((OUT/'tools').glob('*.py'))+list((OUT/'review').iterdir())
    files+=list((run/'records').glob('*.json'))+list((run/'revision_log').glob('*.json'))+list((run/'source_snapshot').iterdir())
    for prior in (OUT/'runs').iterdir():
        if prior!=run:
            files+=list((prior/'records').glob('*.json'))+list((prior/'revision_log').glob('*.json'))+list((prior/'source_snapshot').iterdir())
            files+=[prior/'BUILD_REVIEW.json',prior/'RUN.json']
    files+=list(OUT.glob('*.json'))+list(OUT.glob('*.md'))
    save(OUT/'FINAL_SEAL.json',{'schema':'eb.material_revision_seal.v51','rules_sha256':rules_id(),
         'stage_files':{rel(p):sha(p)for p in files if p.is_file()},
         'external_files':{str(ENTRY.relative_to(REPO)):sha(ENTRY)},
         'source_A_seal_sha256':sha(A_STAGE/'FINAL_SEAL.json'),
         'source_B50_seal_sha256':sha(SOURCE_B/'FINAL_SEAL.json'),
         'scope':'input request revision,preserved source references,classification;not physics or human acceptance',
         'physical_acceptance':False,'collection_released':False})
    print({'sealed':OUT.name,'all_cases_retained':10000,'no_change_cases':a['counts'].get('identical_commands',0)})

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
           'original9810_changed_B_preserved':True,'all10000_in_total_dataset':True,
           'no_change_cases':a['counts'].get('identical_commands',0),'physical_acceptance':False})

def pointer():
    a=read(OUT/'ACCEPTANCE.json');counts=a['counts']
    return {'schema':'eb.current_AB_inputs.v51','stage':OUT.name,'households':1000,'pairs':10000,
        'source_A_stage':A_STAGE.name,'source_A_bindings_sha256':sha(A_STAGE/'A_BINDINGS10000.json'),
        'source_A_seal_sha256':sha(A_STAGE/'FINAL_SEAL.json'),'source_B_parent_stage':SOURCE_B.name,
        'source_B_parent_seal_sha256':sha(SOURCE_B/'FINAL_SEAL.json'),
        'source_B_schedule_stage':OUT.name,'source_generation_rules_sha256':a['rules_sha256'],
        'source_B_schedule_seal_sha256':sha(OUT/'FINAL_SEAL.json'),
        'inherited9810_B50_requests_and90_revisions_have_explicit_per_case_lineage':True,
        'classification_only_update':False,'bindings_sha256':sha(OUT/'PAIR_BINDINGS10000.json'),
        'rules_sha256':a['rules_sha256'],'seal_sha256':sha(OUT/'FINAL_SEAL.json'),
        'changed_command_cases':counts.get('changed_commands',0),'no_command_change_cases':counts.get('identical_commands',0),
        'given_constraint_conflict_cases_kept':counts['constraint_conflict_cases'],
        'given_constraints_feasible_cases':10000-counts['constraint_conflict_cases'],
        'original1172_constraint_conflict_cases_preserved':counts['old_constraint_conflicts_preserved'],
        'revised_old_identical_cases':counts['revised_old_identical_cases'],
        'all10000_retained_in_total_dataset':True,'all10000_used_as_one_dataset':True,'evaluation_inclusion_changed':False,
        'no_change_group_separately_indexed':True,
        'A_and_B_static_accepted':True,'input_revision_and_classification_accepted':True,
        'subset50_same_master':True,'subset50_type_counts':a['subset50_type_counts'],
        'physical_acceptance':False,'human_labels_generated':0,'new_questionnaire_released':False}

def publish():
    verify();current=read(BASE/'CURRENT_AB_INPUTS.json');ap=read(BASE/'CURRENT_NORMAL_A_INPUTS.json')
    if current['stage']not in (SOURCE_B.name,OUT.name)or ap['stage']!=A_STAGE.name:raise ValueError('UNEXPECTED_CURRENT_SOURCE')
    bp=pointer()
    for path in (BASE/'CURRENT_AB_INPUTS.json',PUB/'CURRENT_AB.json'):save(path,bp)
    for path in (PUB/'STATUS.json',PUB/'PIPELINE.json',BASE/'CURRENT_GENERATION_REQUIREMENTS.json'):
        data=read(path);data.update(current_static_AB_inputs=bp,current_normal_A=ap,
            latest_static_input_stage=OUT.name,current_local_static_scope='A46 unchanged;B51 refines90 old identical requests from A/VPP opportunities within one10000-case dataset;all10000 retained,no preset preference labels',
            current_B_classification_audit=str((OUT/'ACCEPTANCE.json').relative_to(REPO)),
            current_VPP_generation_audit=str((OUT/'ACCEPTANCE.json').relative_to(REPO)))
        data['current_generation_points_3_4']={'A_schedule_design':'retained_A46_scoped_review',
            'B_schedule_design':'B51_refine90_B_requests_in_the_single10000_case_dataset',
            'B_classification':'accepted_independent_requested_action_and_event_readback',
            'A_review':str((A_STAGE/'DESIGN_REVIEW.json').relative_to(REPO)),
            'B_review':str((OUT/'ACCEPTANCE.json').relative_to(REPO)),
            'all10000_retained_in_total_dataset':True,'full_physical_acceptance':False,'human_acceptance_known':False}
        save(path,data)
    master=read(BASE/'CURRENT_MASTER_INPUTS.json');master.update(current_static_AB_version='v51',current_static_AB_accepted=True);save(BASE/'CURRENT_MASTER_INPUTS.json',master)
    count=read(OUT/'ACCEPTANCE.json')['counts'];unchanged=count.get('identical_commands',0)
    intro=f'''<!-- current-life-generation-v46-v51 -->
当前本地输入：**A46/B51，1000户、全部10000组保留在总数据中**。A46及原9810组有变化的B50保持；按A/VPP输入机会修订原190组相同案例中的90组，当前整批有9900组指令不同、100组相同。全部案例统一使用和评测，未预填接受或评分。

修订{count['revised_old_identical_cases']}组；当前有指令变化{count.get('changed_commands',0)}组、无变化{unchanged}组。原1172组约束冲突完整保留，新增请求的冲突也如实记录。100是本批数据修订后的相同指令数量；不预设接受答案，不强求B更优，实际功率与接受度仍未知。

50户按原5/15/16/5/4/5直接引用同批主数据、原十个日期，不另生成。[修订方法](../research/collection-adjustment-20260930/household1000/candidate_B_v51_20261017/METHODS.md) · [修订复核](../research/collection-adjustment-20260930/household1000/candidate_B_v51_20261017/review/B无变化修订复核.md)

复现：`python -B scripts/generation_noop_refinement.py B <phase>`。旧A46/B50及此前封存与入口保持。**本轮验收请求设计、分类及同源保留；全量物理、舒适、热水、连续B状态、人类问卷和模型成绩尚未验收，新问卷未发布。**
<!-- /current-life-generation-v46-v51 -->
'''
    for name in ('README.md','PIPELINE.md','REPRODUCTION.md','CURRENT_VPP_GENERATION.md'):
        p=PUB/name;body=p.read_text();body,n=re.subn(r'<!-- current-life-generation-v46-v(?:50|51) -->.*?<!-- /current-life-generation-v46-v(?:50|51) -->',lambda _:intro.rstrip(),body,flags=re.S)
        if n!=1:raise ValueError('CURRENT_DOC_BLOCK_MISSING:'+name)
        p.write_text(body)
    print({'published':OUT.name,'all10000_retained':True,'online_frontend_changed':False})

def verify_pointers():
    bp=pointer();ap=read(BASE/'CURRENT_NORMAL_A_INPUTS.json')
    for p in (BASE/'CURRENT_AB_INPUTS.json',PUB/'CURRENT_AB.json'):
        if read(p)!=bp:raise ValueError('AB_POINTER_MISMATCH')
    if ap['stage']!=A_STAGE.name or read(PUB/'CURRENT_NORMAL_A.json')!=ap:raise ValueError('A_POINTER_MISMATCH')
    for p in (PUB/'STATUS.json',PUB/'PIPELINE.json',BASE/'CURRENT_GENERATION_REQUIREMENTS.json'):
        data=read(p)
        if data['current_static_AB_inputs']!=bp or data['current_normal_A']!=ap:raise ValueError('NESTED_POINTER_MISMATCH')
    if read(BASE/'CURRENT_MASTER_INPUTS.json')['current_static_AB_version']!='v51':raise ValueError('MASTER_POINTER_MISMATCH')
    if (BASE/'CURRENT_PREFERENCE_EVALUATION.json').exists():raise ValueError('WITHDRAWN_SPLIT_ONLY_POINTER_EXISTS')
    verify_inputs();print({'all_current_versions_match':True,'source_A':'A46','B':'B51','all10000_retained':True,'subset50_type_counts':bp['subset50_type_counts']})

if __name__=='__main__':
    {'seal':seal,'verify':verify,'publish':publish,'verify-pointers':verify_pointers}[sys.argv[1]]()
