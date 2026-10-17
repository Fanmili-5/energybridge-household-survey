"""Verify then publish matched local A46/B49 classification-only pointers."""
import sys,subprocess,re
from pathlib import Path
STAGE=Path(__file__).resolve().parents[1];sys.path.insert(0,str(STAGE/'code'))
from common import *
PUB=REPO/'docs/household1000'
def main():
    subprocess.run([sys.executable,'-B',str(OUT/'tools/verify.py')],check=True)
    a=read(OUT/'ACCEPTANCE.json');ap=read(BASE/'CURRENT_NORMAL_A_INPUTS.json');current=read(BASE/'CURRENT_AB_INPUTS.json')
    if current['stage']not in [SOURCE_B.name,OUT.name]or ap['stage']!=A_STAGE.name or ap['seal_sha256']!=sha(A_STAGE/'FINAL_SEAL.json'):raise ValueError('CURRENT_INPUTS_NOT_SOURCE_VERSION')
    bp={'schema':'eb.current_AB_inputs.v49','stage':OUT.name,'households':1000,'pairs':10000,'source_A_stage':A_STAGE.name,'source_A_bindings_sha256':sha(A_STAGE/'A_BINDINGS10000.json'),'source_A_seal_sha256':sha(A_STAGE/'FINAL_SEAL.json'),'source_B_schedule_stage':SOURCE_B.name,'source_B_schedule_seal_sha256':sha(SOURCE_B/'FINAL_SEAL.json'),'source_generation_rules_sha256':read(SOURCE_B/'ACCEPTANCE.json')['rules_sha256'],'classification_only_update':True,'bindings_sha256':sha(OUT/'PAIR_BINDINGS10000.json'),'rules_sha256':a['rules_sha256'],'seal_sha256':sha(OUT/'FINAL_SEAL.json'),'given_constraints_feasible_cases':10000-a['counts']['constraint_conflict_cases'],'given_constraint_conflict_cases_kept':a['counts']['constraint_conflict_cases'],'no_command_change_cases':a['counts']['identical_commands_cases'],'changed_command_cases':a['counts']['changed_commands_cases'],'no_change_group_separately_indexed':True,'evaluation_inclusion_changed':False,'A_and_B_static_accepted':True,'classification_and_preservation_accepted':True,'subset50_same_master':True,'subset50_type_counts':a['subset50_type_counts'],'physical_acceptance':False,'human_labels_generated':0,'new_questionnaire_released':False}
    for path in [BASE/'CURRENT_AB_INPUTS.json',PUB/'CURRENT_AB.json']:save(path,bp)
    for path in [PUB/'STATUS.json',PUB/'PIPELINE.json',BASE/'CURRENT_GENERATION_REQUIREMENTS.json']:
        obj=read(path);obj.update(current_normal_A=ap,current_static_AB_inputs=bp,latest_static_input_stage=OUT.name,current_local_static_scope='A46/B48 schedules unchanged;B49 classification-only update;intent,requested action direction and given-constraint conflict independent;historical physics,questionnaires and answers retain original bindings',current_VPP_generation_audit=str((SOURCE_B/'COMMAND_AND_VPP_REVIEW.json').relative_to(REPO)),current_B_classification_audit=str((OUT/'ACCEPTANCE.json').relative_to(REPO)))
        obj['current_generation_points_3_4']={'A_schedule_design':'retained_A46_scoped_review','B_schedule_design':'retained_B48_scoped_command_and_VPP_review','B_classification':'accepted_independent_three_axis_and_schedule_preservation_review','A_review':str((A_STAGE/'DESIGN_REVIEW.json').relative_to(REPO)),'B_schedule_source_review':str((SOURCE_B/'COMMAND_AND_VPP_REVIEW.json').relative_to(REPO)),'B_classification_review':str((OUT/'ACCEPTANCE.json').relative_to(REPO)),'source_schedule_rules_sha256':bp['source_generation_rules_sha256'],'classification_rules_sha256':a['rules_sha256'],'full_physical_acceptance':False,'human_acceptance_known':False};save(path,obj)
    master=read(BASE/'CURRENT_MASTER_INPUTS.json');master.update(current_AB_inputs='CURRENT_AB_INPUTS.json',current_static_AB_version='v49',current_static_AB_accepted=True);save(BASE/'CURRENT_MASTER_INPUTS.json',master)
    intro='''<!-- current-life-generation-v46-v49 -->
当前本地输入：**A46/B49（排程完整保留自B48，只更新分类）**。1000户、10000组；50户按5/15/16/5/4/5直接引用同批主数据。

设计意图、实际动作方向和给定约束冲突分开记录，不用实验分支名称预判真实坏方案或人类拒绝。9500组指令改变、500组同指令分别列清单；1111组约束冲突保留。本轮不删无变化样本，也不决定后续评分的纳入或权重。

[分类更新验收](../research/collection-adjustment-20260930/household1000/candidate_B_v49_20261017/review/B分类更新验收.md) · [分类方法与复现](../research/collection-adjustment-20260930/household1000/candidate_B_v49_20261017/METHODS.md)

复现：`python scripts/generation_classification.py B <phase>`。A46/B48与旧入口保持封存。**本轮通过分类、全量排程保留和版本一致性复核；完整物理、舒适、热水、连续B状态及人类接受仍待验收，新问卷未发布。**
<!-- /current-life-generation-v46-v49 -->
'''
    (PUB/'CURRENT_VPP_GENERATION.md').write_text('# 当前生活日程与VPP生成版本\n\n'+intro)
    for name in ['README.md','PIPELINE.md','REPRODUCTION.md']:
        path=PUB/name;body=path.read_text();body=re.sub(r'<!-- current-(?:life|vpp)-generation-[^>]+-->.*?<!-- /current-(?:life|vpp)-generation-[^>]+-->\s*','',body,flags=re.S);lines=body.splitlines();path.write_text(lines[0]+'\n\n'+intro+'\n'+'\n'.join(lines[1:])+'\n')
    print({'published':OUT.name,'source_A':A_STAGE.name,'source_B_schedule':SOURCE_B.name,'schedule_changes':0,'no_change_cases':500,'physical_acceptance':False,'online_questionnaire_changed':False})
if __name__=='__main__':main()
