"""Update current pointers only after actual final acceptance, preserving history."""
import json,hashlib,datetime,shutil
from pathlib import Path
stage=Path(__file__).resolve().parents[1];base=stage.parent
def read(p):return json.loads(p.read_text())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(p,j):p.write_text(json.dumps(j,ensure_ascii=False,indent=2)+'\n')
f=read(stage/'FINAL_ACCEPTANCE.json');d=read(stage/'DELIVERY.json')
assert f['status']=='pass' and d['final_acceptance_sha256']==sha(stage/'FINAL_ACCEPTANCE.json') and not d['full1000_EP_allowed']
history=stage/'pointer_history';history.mkdir(exist_ok=True)
names=['CURRENT_PRODUCTION_REVIEW.json','CURRENT_REPAIR_CANDIDATE.json','CURRENT_STATIC_INPUTS.json','CURRENT_TEST50.json']
for name in names:
 p=base/name
 if not (history/name).exists():shutil.copy2(p,history/name)
board_path=base/'repair_execution_20261008_v1/EXECUTION_BOARD.json'
if not (history/'EXECUTION_BOARD.json').exists():shutil.copy2(board_path,history/'EXECUTION_BOARD.json')
common={'schema':'eb.current_reference_pointer.v23','date':'2026-10-13','stage':stage.name,
 'delivery_path':stage.name+'/DELIVERY.json','delivery_sha256':sha(stage/'DELIVERY.json'),
 'final_acceptance_path':stage.name+'/FINAL_ACCEPTANCE.json','final_acceptance_sha256':sha(stage/'FINAL_ACCEPTANCE.json'),
 'human_answers':0,'collection_release':False,'training_release':False,'full1000_EP_allowed':False,'other950_EP_executed':False}
save(base/'CURRENT_STATIC_INPUTS.json',{**common,'scope':'accepted reference inputs1000;current physical acceptance original50 only',
 'households':1000,'members':2524,'pairs':10000,'IDF_inputs':20000,'EP_hold':True,
 'EP_hold_scope':'full1000 remains closed;original50 current reference acceptance only','current_test50':'CURRENT_TEST50.json'})
save(base/'CURRENT_TEST50.json',{**common,'delivery':common['delivery_path'],
 'url':'http://127.0.0.1:18803/household50','preview_requires_school_SSH_tunnel':True,
 'scope':'original50 ten fixed dates;500base,200history/inlet,50model-form;current-ledger acceptance',
 'historical_online_frontend':{'stage':'roleplay_mixed_production_20261007_v17','url':'https://47.85.194.154/household50','redeployed_by_this_revision':False},
 'full1000_EP_authorized':False,'server_answer_writes':False})
save(base/'CURRENT_REPAIR_CANDIDATE.json',{**common,'readiness_status':'v23_reference_inputs_and_original50_accepted;human_and_formal_benchmark_pending',
 'reference_world_ready':True,'foundation_revisions_required':False,'reference_EP_households':50,'reference_EP_pairs':500,
 'execution_board':'repair_execution_20261008_v1/EXECUTION_BOARD.json','scientific_benchmark_validity_complete':False,
 'preview_url_when_SSH_tunnel_active':'http://127.0.0.1:18803/household50','baseline_pointers_archived_in':stage.name+'/pointer_history'})
save(base/'CURRENT_PRODUCTION_REVIEW.json',{**common,'review_path':common['final_acceptance_path'],'review_sha256':common['final_acceptance_sha256'],
 'review_document':stage.name+'/PRODUCTION_LOGIC_CHAIN.md','candidate_stage':stage.name,
 'complete_reference_production_accepted':True,'accepted_scope':'1000source-aware declared inputs and original50 physical consequences only',
 'whole_program_scientific_completion':False,'current_EP_gate_closed':False,'current_full1000_EP_gate_closed':True,
 'current_published_stage':'roleplay_mixed_static1000_20261007_v17','latest_candidate_synced_to_GitHub':False,
 'full1000_EP_started':False,'prior_audit_preserved':'review_20261010_v22_v1/REVIEW.json'})
board=read(board_path);board['previous_v19_board_preserved']=stage.name+'/pointer_history/EXECUTION_BOARD.json'
board.update(date='2026-10-13',production=stage.name,design_realism_verdict='scoped_reference_input_and_original50_acceptance;empirical_claims_pending',
 current_repair_candidate='../CURRENT_REPAIR_CANDIDATE.json',latest_reference_repair_acceptance='../'+stage.name+'/FINAL_ACCEPTANCE.json',
 latest_reference_repair_acceptance_sha256=sha(stage/'FINAL_ACCEPTANCE.json'),latest_reference_repair_acceptance_status='v23_scoped_reference_acceptance',
 finalized_delivery='../'+stage.name+'/DELIVERY.json',finalized_delivery_sha256=sha(stage/'DELIVERY.json'),
 original_frontend_export_safe_for_model_input=True,foundation_revisions_required=False,
 scoped_reference_implementation_complete=True,scoped_reference_world_acceptance=True,whole_household_production_semantic_acceptance=True,
 whole_program_scientific_completion=False,actual_human_answers=0)
board['execution_scope'].update(EP_development_households='original selected50 only',other950_EP='held;no outcome substitution',
 new_household_EP_launches_in_v23=0,unique_exact_SQL_reuse=1400,weather_only_diagnostic_launches=1)
board['reference_diagnostics']={k:read(stage/n) for k,n in [('base50','READBACK_all_REVIEW.json'),('history_inlet','READBACK_sensitivity_REVIEW.json'),('model_form','READBACK_model_form_REVIEW.json')]}
limits={
 'G1':'source coding and declared eligible activity verified;true occupation and missing causes unknown',
 'G2':'declared dated activity/care/resource consistency verified;not national detailed diaries',
 'G3':'given needs/usual arrangements/negotiability/unknowns separated;not observed personal preferences',
 'G4':'six B mechanisms and bad B retained;technical flags are not actor answers',
 'G5':'original50 current-ledger and model diagnostics accepted;other950 and field calibration absent',
 'G6':'current original frontend and engineering export verified;human comprehension,role effect and labels absent'}
for row in board['required_repairs']:
 key=row['id'];row['current_v23_engineering_acceptance']=True;row['engineering_verification_complete']=True
 row['implementation_complete']=True;row['scientific_admission_accepted']=False
 row['scoped_verification_complete']=key!='G6';row['complete']=key!='G6'
 row['status']='v23_scoped_reference_verified' if key!='G6' else 'v23_engineering_and_protocol_ready_actual_human_evidence_pending'
 row['completion_scope']='reference inputs1000 and physical original50;no national/field/human claims'
 row['remaining_evidence_or_limits']=limits[key];row['evidence'].append('../'+stage.name+'/FINAL_ACCEPTANCE.json')
for row in board['work_packages']:
 row['implementation_stage']=stage.name
 row['status']='actual_human_evidence_pending' if row['id']=='E07' else 'v23_scoped_reference_acceptance_verified'
board['not_only_G6_is_pending']=True
board['remaining_empirical_evidence']=['joint detailed activity/population calibration if such claims wanted','off-design OEM and household field calibration','actual human comprehension/role effect/independent responses']
save(board_path,board);save(stage/'EXECUTION_BOARD.json',board)
print({'pointers_closed':names,'board':'G1-G5 limited reference checks;G6 actual human evidence pending','full1000_EP_allowed':False})
