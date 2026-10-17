"""Publish only the matched, accepted A46/B47 local input versions."""
import json,hashlib,re
from pathlib import Path
OUT=Path(__file__).resolve().parents[1];BASE=OUT.parent;ROOT=BASE.parents[3];A=BASE/'normal_A_v46_20261017';PUB=ROOT/'docs/household1000'
def read(p):return json.loads(p.read_text())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(p,x):
 tmp=p.with_suffix(p.suffix+'.tmp');tmp.write_text(json.dumps(x,ensure_ascii=False,sort_keys=True,indent=2)+'\n');tmp.replace(p)
def main():
 aa=read(A/'ACCEPTANCE.json');ba=read(OUT/'ACCEPTANCE.json');ad=read(A/'DESIGN_REVIEW.json');bd=read(OUT/'DESIGN_REVIEW.json')
 if not all([aa['accepted'],ba['accepted'],ad['accepted'],bd['accepted'],(A/'FINAL_SEAL.json').exists(),(OUT/'FINAL_SEAL.json').exists()]):raise ValueError('MATCHED_STAGES_NOT_ACCEPTED')
 if read(OUT/'A_REAUDIT.json')['A_seal_sha256']!=sha(A/'FINAL_SEAL.json'):raise ValueError('A_SEAL_MISMATCH')
 subset=read(A/'SUBSET50.json')['type_counts']
 ap={'schema':'eb.current_normal_A.v46','stage':A.name,'households':1000,'cases':10000,'source_household_master':'household_master_v33_20261016','source_household_master_unchanged':True,'A_resource_worlds':'A_BINDINGS10000.json:records[].A_world_path','A_static_accepted':True,'upstream_calendar_regenerated':True,'design_causal_checks_accepted':True,'rules_sha256':aa['rules_sha256'],'bindings_sha256':sha(A/'A_BINDINGS10000.json'),'seal_sha256':sha(A/'FINAL_SEAL.json'),'subset50_same_master':True,'subset50_type_counts':subset,'physical_acceptance':False,'B_generation_pending':False,'current_AB_inputs':'CURRENT_AB_INPUTS.json','new_questionnaire_released':False}
 bp={'schema':'eb.current_AB_inputs.v47','stage':OUT.name,'households':1000,'pairs':10000,'source_A_stage':A.name,'source_A_bindings_sha256':ap['bindings_sha256'],'source_A_seal_sha256':ap['seal_sha256'],'bindings_sha256':sha(OUT/'PAIR_BINDINGS10000.json'),'rules_sha256':ba['rules_sha256'],'seal_sha256':sha(OUT/'FINAL_SEAL.json'),'given_constraints_feasible_cases':ba['given_constraints_feasible_cases'],'given_constraint_conflict_cases_kept':ba['given_constraint_conflict_cases_kept'],'subset50_same_master':True,'subset50_type_counts':subset,'A_and_B_static_accepted':True,'input_design_and_temporal_review_accepted':True,'physical_acceptance':False,'human_labels_generated':0,'new_questionnaire_released':False}
 for p,x in[(BASE/'CURRENT_NORMAL_A_INPUTS.json',ap),(PUB/'CURRENT_NORMAL_A.json',ap),(BASE/'CURRENT_AB_INPUTS.json',bp),(PUB/'CURRENT_AB.json',bp)]:save(p,x)
 for p in[PUB/'STATUS.json',PUB/'PIPELINE.json',BASE/'CURRENT_GENERATION_REQUIREMENTS.json']:
  d=read(p);d.update(current_normal_A=ap,current_static_AB_inputs=bp,latest_static_input_stage=OUT.name,current_local_static_scope='A46/B47 short indoor holds, explicit adverse pause direction and prospective thermal storage requests;legacy physics,online and answers retain historical bindings',current_VPP_generation_audit=str((OUT/'DESIGN_REVIEW.json').relative_to(ROOT)));d['current_generation_points_3_4']={'A_schedule_design':'accepted_scoped_generation_review','B_VPP_design':'accepted_scoped_generation_review','A_circulation_review':str((A/'CIRCULATION_REVIEW.json').relative_to(ROOT)),'B_continuity_and_joint_review':str((OUT/'FOUR_POINT_REVIEW.json').relative_to(ROOT)),'A_indoor_hold_review':str((A/'THERMAL_CONTEXT_REVIEW.json').relative_to(ROOT)),'B_direction_and_preconditioning_review':str((OUT/'THERMAL_FLEX_REVIEW.json').relative_to(ROOT)),'rules_sha256_A':aa['rules_sha256'],'rules_sha256_B':ba['rules_sha256'],'full_physical_acceptance':False,'human_acceptance_known':False};save(p,d)
 m=read(BASE/'CURRENT_MASTER_INPUTS.json');m.update(current_normal_A='CURRENT_NORMAL_A_INPUTS.json',current_AB_inputs='CURRENT_AB_INPUTS.json',current_A_resource_world_version='v46',current_static_AB_accepted=True);save(BASE/'CURRENT_MASTER_INPUTS.json',m)
 intro=f'''<!-- current-life-generation-v46-v47 -->
当前本地输入：**V33家庭 → A46全年生活日程与A → B47 VPP候选**。1000户、10000组；50户按5/15/16/5/4/5引用同批文件。

A将实际占用、日常温控与硬件可调范围分开；短室内离房可保持温控，每台每日60分钟循环风仍要求实际占用。B增加提前预冷/预热候选，增负荷时暂停温控如实标为预设反向请求。约束冲突{ba['given_constraint_conflict_cases_kept']}组保留；不强求B优于A。

[本轮修改与复核](../research/collection-adjustment-20260930/household1000/candidate_B_v47_20261017/review/四项修改验收简表.md) · [A方法](../research/collection-adjustment-20260930/household1000/normal_A_v46_20261017/METHODS.md) · [B方法](../research/collection-adjustment-20260930/household1000/candidate_B_v47_20261017/METHODS.md)

复现：`python scripts/generation_thermal.py A build` → A review/design-review/family-review/regressions/thermal-probes/export/seal → B build/audit-A/regressions/review/design-review/export/seal/publish → A verify、B verify。B seal前另运行本阶段tools/run_B_thermal_probes.py，执行两个实际提前温控功能探针。封存后代码不改；变更须新版本。旧入口generation_rhythm.py、generation_joint.py、generation_life.py及generation_vpp.py保留。

**验收范围是生成规则、资源排程、因果设计及版本一致。4个新A HVAC功能探针不代表全量物理验收；围护层次/额定曲线/低温制冷警告仍待跟进。全量A/B热电、热水、舒适及新问卷尚未验收；旧线上问卷、物理与答案保持历史绑定。**
<!-- /current-life-generation-v46-v47 -->
'''
 (PUB/'CURRENT_VPP_GENERATION.md').write_text('# 当前生活日程与VPP生成版本\n\n'+intro)
 for name in('README.md','PIPELINE.md','REPRODUCTION.md'):
  p=PUB/name;s=p.read_text()
  s=re.sub(r'<!-- current-(?:life|vpp)-generation-[^>]+-->.*?<!-- /current-(?:life|vpp)-generation-[^>]+-->\s*','',s,flags=re.S)
  lines=s.splitlines();s=lines[0]+'\n\n'+intro+'\n'+'\n'.join(lines[1:])+'\n';p.write_text(s)
 print({'published_A':A.name,'published_B':OUT.name,'same_batch_subset50':subset,'physical_acceptance':False,'online_questionnaire_changed':False})
if __name__=='__main__':main()
