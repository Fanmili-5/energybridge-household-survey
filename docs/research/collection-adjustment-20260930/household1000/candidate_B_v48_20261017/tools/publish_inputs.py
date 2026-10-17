"""Publish verified A46/B48 local input pointers; historical results retain bindings."""
import json,hashlib,re
from pathlib import Path
OUT=Path(__file__).resolve().parents[1];BASE=OUT.parent;ROOT=BASE.parents[3];A=BASE/'normal_A_v46_20261017';PUB=ROOT/'docs/household1000'
def read(p):return json.loads(p.read_text())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(p,x):
    tmp=p.with_suffix(p.suffix+'.tmp');tmp.write_text(json.dumps(x,ensure_ascii=False,sort_keys=True,indent=2)+'\n');tmp.replace(p)
def main():
    aa=read(A/'ACCEPTANCE.json');ba=read(OUT/'ACCEPTANCE.json');br=read(OUT/'COMMAND_AND_VPP_REVIEW.json')
    if not all([aa['accepted'],ba['accepted'],br['accepted'],read(OUT/'DESIGN_REVIEW.json')['accepted'],(A/'FINAL_SEAL.json').exists(),(OUT/'FINAL_SEAL.json').exists()]):raise ValueError('MATCHED_STAGES_NOT_ACCEPTED')
    if read(OUT/'A_REAUDIT.json')['A_seal_sha256']!=sha(A/'FINAL_SEAL.json'):raise ValueError('A_SEAL_MISMATCH')
    # Publication is a final step, following full file/hash verification.
    import subprocess,sys
    subprocess.run([sys.executable,'-B',str(OUT/'code/finalize.py'),'--verify-only'],check=True)
    ap=read(BASE/'CURRENT_NORMAL_A_INPUTS.json')
    if ap['stage']!=A.name or ap['bindings_sha256']!=sha(A/'A_BINDINGS10000.json')or ap['seal_sha256']!=sha(A/'FINAL_SEAL.json'):raise ValueError('CURRENT_A_NOT_FROZEN_A46')
    ap.update(B_generation_pending=False,current_AB_inputs='CURRENT_AB_INPUTS.json');subset=read(OUT/'SUBSET50.json')['type_counts']
    bp={'schema':'eb.current_AB_inputs.v48','stage':OUT.name,'households':1000,'pairs':10000,'source_A_stage':A.name,'source_A_bindings_sha256':ap['bindings_sha256'],'source_A_seal_sha256':ap['seal_sha256'],'bindings_sha256':sha(OUT/'PAIR_BINDINGS10000.json'),'rules_sha256':ba['rules_sha256'],'seal_sha256':sha(OUT/'FINAL_SEAL.json'),'given_constraints_feasible_cases':ba['given_constraints_feasible_cases'],'given_constraint_conflict_cases_kept':ba['given_constraint_conflict_cases_kept'],'subset50_same_master':True,'subset50_type_counts':subset,'A_and_B_static_accepted':True,'executable_command_and_multi_VPP_review_accepted':True,'physical_acceptance':False,'human_labels_generated':0,'new_questionnaire_released':False}
    for p,x in[(BASE/'CURRENT_NORMAL_A_INPUTS.json',ap),(PUB/'CURRENT_NORMAL_A.json',ap),(BASE/'CURRENT_AB_INPUTS.json',bp),(PUB/'CURRENT_AB.json',bp)]:save(p,x)
    for p in[PUB/'STATUS.json',PUB/'PIPELINE.json',BASE/'CURRENT_GENERATION_REQUIREMENTS.json']:
        d=read(p);d.update(current_normal_A=ap,current_static_AB_inputs=bp,latest_static_input_stage=OUT.name,current_local_static_scope='A46 unchanged/B48 executable-command equivalence,zero preparation readback and exogenous mixed multi-window VPP;historical physics,questionnaires and answers keep original versions',current_VPP_generation_audit=str((OUT/'COMMAND_AND_VPP_REVIEW.json').relative_to(ROOT)))
        d['current_generation_points_3_4']={'A_schedule_design':'retained_A46_scoped_generation_review','B_VPP_design':'accepted_scoped_command_and_coverage_review','A_indoor_hold_review':str((A/'THERMAL_CONTEXT_REVIEW.json').relative_to(ROOT)),'B_direction_and_preconditioning_review':str((OUT/'THERMAL_FLEX_REVIEW.json').relative_to(ROOT)),'B_executable_and_multi_window_review':str((OUT/'COMMAND_AND_VPP_REVIEW.json').relative_to(ROOT)),'rules_sha256_A':aa['rules_sha256'],'rules_sha256_B':ba['rules_sha256'],'full_physical_acceptance':False,'human_acceptance_known':False};save(p,d)
    m=read(BASE/'CURRENT_MASTER_INPUTS.json');m.update(current_normal_A='CURRENT_NORMAL_A_INPUTS.json',current_AB_inputs='CURRENT_AB_INPUTS.json',current_A_resource_world_version='v46',current_static_AB_version='v48',current_static_AB_accepted=True);save(BASE/'CURRENT_MASTER_INPUTS.json',m)
    c=br['counts'];s=br['multi_window_factor_counts'];intro=f'''<!-- current-life-generation-v46-v48 -->
当前本地输入：**V33家庭 → A46（保留） → B48 VPP候选**。1000户、10000组；50户按5/15/16/5/4/5引用同批文件。

B按实际执行指令合并等价档位、判断差异及发生时间；准备阶段零变化明确保留，不计实际提前温控。双事件含同向/异向与相同/不同目标四类：{s}。保留{ba['given_constraint_conflict_cases_kept']}组约束冲突、{c['no_command_change_cases']}组无指令变化，不强求B优于A。

[本轮修改与复核](../research/collection-adjustment-20260930/household1000/candidate_B_v48_20261017/review/实际指令与多窗口验收.md) · [B48生成方法](../research/collection-adjustment-20260930/household1000/candidate_B_v48_20261017/METHODS.md)

复现：`python scripts/generation_commands.py B <phase>`，顺序见方法文件。A46与旧B47封存及所有旧入口保留。**本轮验收范围为生成规则、实际指令、资源排程、覆盖与版本；全量A/B物理、热水、舒适和人类接受尚未验收，新问卷未发布。**
<!-- /current-life-generation-v46-v48 -->
'''
    (PUB/'CURRENT_VPP_GENERATION.md').write_text('# 当前生活日程与VPP生成版本\n\n'+intro)
    for name in ['README.md','PIPELINE.md','REPRODUCTION.md']:
        p=PUB/name;text=p.read_text();text=re.sub(r'<!-- current-(?:life|vpp)-generation-[^>]+-->.*?<!-- /current-(?:life|vpp)-generation-[^>]+-->\s*','',text,flags=re.S);lines=text.splitlines();p.write_text(lines[0]+'\n\n'+intro+'\n'+'\n'.join(lines[1:])+'\n')
    print({'published_A':A.name,'published_B':OUT.name,'subset50':subset,'physical_acceptance':False,'online_questionnaire_changed':False})
if __name__=='__main__':main()
