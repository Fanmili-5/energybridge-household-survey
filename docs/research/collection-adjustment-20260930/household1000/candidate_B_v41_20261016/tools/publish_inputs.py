"""Publish the matched A40/B41 local inputs only after both immutable stages are accepted."""
import json,hashlib,re
from pathlib import Path
OUT=Path(__file__).resolve().parents[1];BASE=OUT.parent;ROOT=BASE.parents[3];A=BASE/'normal_A_v40_20261016';PUB=ROOT/'docs/household1000'
def read(p):return json.loads(p.read_text())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(p,x):
 tmp=p.with_suffix(p.suffix+'.tmp');tmp.write_text(json.dumps(x,ensure_ascii=False,sort_keys=True,indent=2)+'\n');tmp.replace(p)
def main():
 aa=read(A/'ACCEPTANCE.json');ba=read(OUT/'ACCEPTANCE.json');ad=read(A/'DESIGN_REVIEW.json');bd=read(OUT/'DESIGN_REVIEW.json')
 if not all([aa['accepted'],ba['accepted'],ad['accepted'],bd['accepted'],(A/'FINAL_SEAL.json').exists(),(OUT/'FINAL_SEAL.json').exists()]):raise ValueError('MATCHED_STAGES_NOT_ACCEPTED')
 if read(OUT/'A_REAUDIT.json')['A_seal_sha256']!=sha(A/'FINAL_SEAL.json'):raise ValueError('A_SEAL_MISMATCH')
 subset=read(A/'SUBSET50.json')['type_counts']
 ap={'schema':'eb.current_normal_A.v40','stage':A.name,'households':1000,'cases':10000,'source_household_master':'household_master_v33_20261016','source_household_master_unchanged':True,'A_resource_worlds':'A_BINDINGS10000.json:records[].A_world_path','A_static_accepted':True,'upstream_calendar_regenerated':True,'design_causal_checks_accepted':True,'rules_sha256':aa['rules_sha256'],'bindings_sha256':sha(A/'A_BINDINGS10000.json'),'seal_sha256':sha(A/'FINAL_SEAL.json'),'subset50_same_master':True,'subset50_type_counts':subset,'physical_acceptance':False,'B_generation_pending':False,'current_AB_inputs':'CURRENT_AB_INPUTS.json','new_questionnaire_released':False}
 bp={'schema':'eb.current_AB_inputs.v41','stage':OUT.name,'households':1000,'pairs':10000,'source_A_stage':A.name,'source_A_bindings_sha256':ap['bindings_sha256'],'source_A_seal_sha256':ap['seal_sha256'],'bindings_sha256':sha(OUT/'PAIR_BINDINGS10000.json'),'rules_sha256':ba['rules_sha256'],'seal_sha256':sha(OUT/'FINAL_SEAL.json'),'given_constraints_feasible_cases':ba['given_constraints_feasible_cases'],'given_constraint_conflict_cases_kept':ba['given_constraint_conflict_cases_kept'],'subset50_same_master':True,'subset50_type_counts':subset,'A_and_B_static_accepted':True,'input_design_and_temporal_review_accepted':True,'physical_acceptance':False,'human_labels_generated':0,'new_questionnaire_released':False}
 for p,x in [(BASE/'CURRENT_NORMAL_A_INPUTS.json',ap),(PUB/'CURRENT_NORMAL_A.json',ap),(BASE/'CURRENT_AB_INPUTS.json',bp),(PUB/'CURRENT_AB.json',bp)]:save(p,x)
 for p in [PUB/'STATUS.json',PUB/'PIPELINE.json',BASE/'CURRENT_GENERATION_REQUIREMENTS.json']:
  d=read(p);d.update(current_normal_A=ap,current_static_AB_inputs=bp,latest_static_input_stage=OUT.name,current_local_static_scope='A40/B41 regenerated life calendars and matched static inputs only;legacy physics/online fields remain historical',current_VPP_generation_audit=str((OUT/'DESIGN_REVIEW.json').relative_to(ROOT)));save(p,d)
 m=read(BASE/'CURRENT_MASTER_INPUTS.json');m.update(current_normal_A='CURRENT_NORMAL_A_INPUTS.json',current_AB_inputs='CURRENT_AB_INPUTS.json',current_A_resource_world_version='v40',current_static_AB_accepted=True);save(BASE/'CURRENT_MASTER_INPUTS.json',m)
 old_dinner=ad['previous_A38_dinner_minutes_counts'].get('1080',0);new_dinner=ad['dinner_minutes_counts'].get('1080',0);mix=ba['coordinated_portfolio_counts'];multi=sum(n for k,n in mix.items()if k.count('+')>=1);triples=sum(n for k,n in mix.items()if k.count('+')==2)
 intro=f'''<!-- current-life-generation-v40-v41 -->
当前本地输入：**V33家庭 → V40上游生活日程与全年A → V41 VPP条件B**。1000户、10000组，50户按5/15/16/5/4/5引用同批文件。

从家庭稳定习惯重新生成全年日程与需求；未复用旧全年A。18:00家庭晚餐参考时点从{old_dinner}组降至{new_dinner}组，比例为合成场景设计结果，非实测人口分布。保留所有已配设备每日使用、合理稳定习惯及旧家庭/住房/设备条件。

B在构造前按输入机会分配机制、日期、事件和组合；每户两次组合候选，不按B结果或演员答案筛选。实际跨设备调整{multi}组、三设备{triples}组；约束冲突{ba['given_constraint_conflict_cases_kept']}组保留。指令时序与物理响应分开，热水说明对应最终许可片段和真实后续时点。

[本轮修改与验收说明](../research/collection-adjustment-20260930/household1000/candidate_B_v41_20261016/review/本轮修改简明说明.md) · [A方法](../research/collection-adjustment-20260930/household1000/normal_A_v40_20261016/METHODS.md) · [B方法](../research/collection-adjustment-20260930/household1000/candidate_B_v41_20261016/METHODS.md)

复现：`python scripts/generation_life.py A build` → A review/design-review/family-review/export/seal → B build/audit-A/regressions/review/design-review/export/seal/publish → A verify、B verify。A设计复核可先于或后于A export；封存前完成。完整参数来源、试生成修复记录及同源50户见阶段内文件。

**通过的是生成、资源排程和因果设计检查。4个真实壳体HVAC功能探针完成；仍有继承的围护层次/额定曲线和低温制冷警告，不代表舒适或完整物理验收。全量热/电、热水、连续B状态、实际VPP及新问卷尚未验收；旧线上问卷、物理和答案保留原绑定。**
<!-- /current-life-generation-v40-v41 -->
'''
 (PUB/'CURRENT_VPP_GENERATION.md').write_text('# 当前生活日程与VPP生成版本\n\n'+intro)
 for name in ('README.md','PIPELINE.md','REPRODUCTION.md'):
  p=PUB/name;s=p.read_text()
  if '<!-- current-vpp-generation-v39 -->'in s:s=re.sub(r'<!-- current-vpp-generation-v39 -->.*?<!-- /current-vpp-generation-v39 -->',intro,s,count=1,flags=re.S)
  else:s=s.splitlines()[0]+'\n\n'+intro+'\n'+'\n'.join(s.splitlines()[1:])+'\n'
  p.write_text(s)
 print({'published_A':A.name,'published_B':OUT.name,'same_batch_subset50':subset,'physical_acceptance':False,'online_questionnaire_changed':False})
if __name__=='__main__':main()
