"""Seal and publish a bounded schedule-preserving annotation finalization."""
import sys,re
from pathlib import Path
STAGE=Path(__file__).resolve().parents[1];sys.path.insert(0,str(STAGE/'code'))
from common import *
PUB=REPO/'docs/household1000';ENTRY=REPO/'scripts/generation_semantic_closure.py'

def check():
 verify_inputs();a=read(OUT/'ACCEPTANCE.json');r=read(OUT/'REGRESSION_RESULTS.json');binding=sha(OUT/'PAIR_BINDINGS10000.json');preview=read(OUT/'review/多轴强度展示数据.json');physical=read(OUT/'PHYSICAL_REFERENCE_REUSE.json')
 assert a['accepted']and not a['errors']and r['passed']and a['rules_sha256']==r['rules_sha256']==rules_id()and a['bindings_sha256']==binding
 assert a['counts']['cases']==10000 and a['counts']['B56_schedule_unchanged_cases']==10000 and a['counts']['identical_commands']==100
 assert preview['bindings_sha256']==physical['bindings_sha256']==binding and len(preview['cases'])==10000 and physical['passed']and physical['cases']==49
 assert (OUT/'review/多轴强度预览.html').exists()and(OUT/'review/收尾复核.md').exists()
 return a

def seal():
 check();assert not(OUT/'FINAL_SEAL.json').exists()
 files=[p for p in OUT.rglob('*')if p.is_file()and p.name!='FINAL_SEAL.json'and 'pairs'not in p.parts and '__pycache__'not in p.parts]
 save(OUT/'FINAL_SEAL.json',{'schema':'eb.annotation_finalization_seal.v57','rules_sha256':rules_id(),'stage_files':{rel(p):sha(p)for p in files},'external_files':{str(ENTRY.relative_to(REPO)):sha(ENTRY)},'source_A_seal_sha256':sha(A_STAGE/'FINAL_SEAL.json'),'parent_B_seal_sha256':sha(PARENT_B/'FINAL_SEAL.json'),'physical_acceptance':False,'collection_released':False,'scope':'joint-B node associations and separate actual SOC/intervention times;B56 schedules fixed'})
 print({'sealed':OUT.name,'cases':10000,'schedules_changed':0})

def verify():
 check();s=read(OUT/'FINAL_SEAL.json')
 for stage in(PARENT_B,OUT):
  for name,h in read(stage/'FINAL_SEAL.json')['stage_files'].items():
   if sha(stage/name)!=h:raise ValueError('SEALED_FILE_CHANGED:'+str(stage/name))
 for name,h in s['external_files'].items():assert sha(REPO/name)==h
 for stage in(PARENT_B,OUT):
  for row in read(stage/'PAIR_BINDINGS10000.json')['records']:
   for rr in row['rounds']:assert sha(stage/rr['path'])==rr['sha256']
 print({'verified':True,'pairs':10000,'A46_B56_commands_preserved':True})

def pointer():
 a=check();p=read(OUT/'SOURCE_CURRENT_POINTER.json');assert p['stage']==PARENT_B.name
 p.update(schema='eb.current_AB_inputs.v57',stage=OUT.name,source_B_parent_stage=PARENT_B.name,source_B_parent_seal_sha256=sha(PARENT_B/'FINAL_SEAL.json'),source_B_schedule_stage=OUT.name,source_generation_rules_sha256=rules_id(),source_B_schedule_seal_sha256=sha(OUT/'FINAL_SEAL.json'),bindings_sha256=sha(OUT/'PAIR_BINDINGS10000.json'),rules_sha256=rules_id(),seal_sha256=sha(OUT/'FINAL_SEAL.json'),annotation_only_schedule_preserving_update=True,B56_executable_schedules_preserved=True,joint_B_node_associations_validated=True,actual_SOC_match_and_intervention_time_separate=True,thermal_phases_rebuilt=False,thermal_control_source_stage=PARENT_B.name,paired_thermal_reference_reused_on_identical_controls=True,new_physical_runs=0,physical_reference_reuse_manifest=str((OUT/'PHYSICAL_REFERENCE_REUSE.json').relative_to(REPO)),native_A_state_bindings_path=str((PARENT_B/'STATE_BINDINGS.json').relative_to(REPO)),generation_design_points_3_4_scoped_review_complete=True,minor_annotation_closure_complete=True)
 return p

def publish():
 verify();p=pointer();ap=read(BASE/'CURRENT_NORMAL_A_INPUTS.json');current=read(BASE/'CURRENT_AB_INPUTS.json');assert current['stage']in(PARENT_B.name,OUT.name)and ap['stage']==A_STAGE.name
 names=('README.md','PIPELINE.md','REPRODUCTION.md','CURRENT_VPP_GENERATION.md');pattern=r'<!-- current-life-generation-v46-v(?:56|57) -->.*?<!-- /current-life-generation-v46-v(?:56|57) -->'
 intro='''<!-- current-life-generation-v46-v57 -->
当前本地输入：**A46/B57，1000户、整批10000组**。A46与全部B56实际排程保留。联合B节点按实际操作重新关联，原A节点失效时如实说明；EV分别展示实际持续追平SOC、干预结束及结束后确认时刻，后续补电和原失败记录保留。每日设备任务、100组相同及原比例同源50户保持，评分与接受未预填。

本轮是两处说明与摘要的收尾。第3、4项生成设计按已有范围收口；后续优先处理会改变排程有效性、用户判断或论文结论的问题。49组既有热控参考按相同控制输入和源文件哈希复用，完整物理与人类接受保持各自验收范围。[方法](../research/collection-adjustment-20260930/household1000/candidate_B_v57_20261017/METHODS.md) · [收尾复核](../research/collection-adjustment-20260930/household1000/candidate_B_v57_20261017/review/收尾复核.md)

复现：`python -B scripts/generation_semantic_closure.py B <phase>`。历史版本封存，新问卷尚未发布。
<!-- /current-life-generation-v46-v57 -->'''
 edits={}
 for name in names:
  text,n=re.subn(pattern,lambda _:intro,(PUB/name).read_text(),flags=re.S);assert n==1;edits[PUB/name]=text
 for path in(BASE/'CURRENT_AB_INPUTS.json',PUB/'CURRENT_AB.json'):save(path,p)
 for path in(PUB/'STATUS.json',PUB/'PIPELINE.json',BASE/'CURRENT_GENERATION_REQUIREMENTS.json'):
  d=read(path);d.update(current_static_AB_inputs=p,current_normal_A=ap,latest_static_input_stage=OUT.name,current_local_static_scope='A46/B57 all B56 schedules fixed;two annotation fixes closed;generation design scoped review complete',current_B_classification_audit=str((OUT/'ACCEPTANCE.json').relative_to(REPO)),current_VPP_generation_audit=str((OUT/'ACCEPTANCE.json').relative_to(REPO)))
  d['current_generation_points_3_4']={'status':'generation_design_scoped_review_complete','annotation_closure':'completed_without_schedule_changes','B_review':str((OUT/'ACCEPTANCE.json').relative_to(REPO)),'A_review':str((A_STAGE/'DESIGN_REVIEW.json').relative_to(REPO)),'all10000_retained_in_total_dataset':True,'full_physical_acceptance':False,'human_acceptance_known':False};save(path,d)
 m=read(BASE/'CURRENT_MASTER_INPUTS.json');m.update(current_static_AB_version='v57',current_static_AB_accepted=True);save(BASE/'CURRENT_MASTER_INPUTS.json',m)
 for path,text in edits.items():path.write_text(text)
 print({'published':OUT.name,'schedule_changes':0,'scope':'two annotation issues closed','online_frontend_changed':False})

def verify_pointers():
 p=pointer()
 for path in(BASE/'CURRENT_AB_INPUTS.json',PUB/'CURRENT_AB.json'):assert read(path)==p
 for path in(PUB/'STATUS.json',PUB/'PIPELINE.json',BASE/'CURRENT_GENERATION_REQUIREMENTS.json'):assert read(path)['current_static_AB_inputs']==p
 assert read(BASE/'CURRENT_MASTER_INPUTS.json')['current_static_AB_version']=='v57'
 print({'all_current_versions_match':True,'stage':OUT.name,'same_source50':p['subset50_type_counts']})
if __name__=='__main__':{'seal':seal,'verify':verify,'publish':publish,'verify-pointers':verify_pointers}[sys.argv[1]]()
