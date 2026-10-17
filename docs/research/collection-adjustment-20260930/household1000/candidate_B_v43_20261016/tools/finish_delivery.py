"""Prepare scoped audit, publish a matched local pair, or check version pointers."""
import json,hashlib,argparse,runpy
from pathlib import Path
OUT=Path(__file__).resolve().parents[1];BASE=OUT.parent;ROOT=BASE.parents[3];A=BASE/'normal_A_v42_20261016';PUBLIC=ROOT/'docs/household1000'
def read(p):return json.loads(p.read_text())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 p=argparse.ArgumentParser();p.add_argument('phase',choices=['prepare','publish','verify-extra']);arg=p.parse_args()
 if arg.phase=='publish':runpy.run_path(str(OUT/'tools/publish_inputs.py'),run_name='__main__');return
 if arg.phase=='prepare':
  a=read(OUT/'ACCEPTANCE.json');d=read(OUT/'DESIGN_REVIEW.json')
  if not a['accepted']or not d['accepted']:raise ValueError('NOT_ACCEPTED')
  data={'static_and_design_accepted':True,'source_acceptance_sha256':sha(OUT/'ACCEPTANCE.json'),'source_design_review_sha256':sha(OUT/'DESIGN_REVIEW.json'),'A_new_calendar_audit_sha256':sha(OUT/'A_REAUDIT.json'),'input_plan_sha256':sha(OUT/'INPUT_COVERAGE_PLAN.json'),'cases':10000,'households':1000,'requested_known_load_response_signs':a['requested_known_load_response_signs'],'event_chronology':d['event_chronology_counts'],'actual_coordinated_portfolio_counts':a['coordinated_portfolio_counts'],'constraint_failures_kept':a['given_constraint_conflict_cases_kept'],'actual_acceptance_labels_generated':0,'full_physical_acceptance':False,'questionnaire_released':False}
  (OUT/'VPP_AUDIT.json').write_text(json.dumps(data,ensure_ascii=False,sort_keys=True)+'\n');print({'VPP_audit_prepared':True});return
 entry=read(OUT/'ENTRYPOINT_LOCK.json')
 if sha(ROOT/entry['current_entrypoint'])!=entry['sha256']or sha(ROOT/entry['legacy_entrypoint_preserved'])!=entry['legacy_sha256']:raise ValueError('ENTRYPOINT_VERSION_MISMATCH')
 for name,expected in entry.get('additional_preserved_entrypoints',{}).items():
  if sha(ROOT/name)!=expected:raise ValueError('HISTORICAL_ENTRYPOINT_CHANGED:'+name)
 current=read(BASE/'CURRENT_AB_INPUTS.json');normal=read(BASE/'CURRENT_NORMAL_A_INPUTS.json')
 if current['stage']!=OUT.name or normal['stage']!=A.name or current['source_A_stage']!=A.name:raise ValueError('CURRENT_VERSION_MISMATCH')
 if current['source_A_seal_sha256']!=sha(A/'FINAL_SEAL.json')or current['seal_sha256']!=sha(OUT/'FINAL_SEAL.json'):raise ValueError('CURRENT_SEAL_MISMATCH')
 for parent,filename,value in [(PUBLIC,'CURRENT_AB.json',current),(PUBLIC,'CURRENT_NORMAL_A.json',normal)]:
  if read(parent/filename)!=value:raise ValueError('PUBLIC_POINTER_MISMATCH')
 for path in [PUBLIC/'STATUS.json',PUBLIC/'PIPELINE.json',BASE/'CURRENT_GENERATION_REQUIREMENTS.json']:
  status=read(path)
  if status['current_normal_A']!=normal or status['current_static_AB_inputs']!=current:raise ValueError('NESTED_POINTER_MISMATCH')
 print({'private_public_nested_versions_match':True,'source_A_and_B_seals_match':True,'live_site_changed':False})
if __name__=='__main__':main()
