"""Complete reference original50 acceptance;never a human or national prevalence claim."""
from common import *
from ep_gate import input_signature


def acceptance_inputs():
    signature,files=input_signature()
    additional=['READBACK_all_REVIEW.json','READBACK_sensitivity_REVIEW.json','READBACK_model_form_REVIEW.json',
                'MODEL_FORM_SENSITIVITY.json','MATERIALS_REVIEW.json','ACTOR_BINDINGS.json','CONSUMER_BINDINGS.json',
                'FRONTEND_BINDINGS_REVIEW.json','FRONTEND_CLOCK_REVIEW.json','FRONTEND_BROWSER_REVIEW.json',
                'WEATHER_SOLVER_REVIEW.json','ACCEPTANCE_NEGATIVE_CONTROLS.json','FINAL_RULE_REGRESSION.json']
    for name in additional:files[name]=sha(OUT/name)
    for directory in ['actors','consumers','collection_materials','frontend_release','readback']:
        for p in (OUT/directory).rglob('*'):
            if p.is_file()and '__pycache__'not in p.parts:files[str(p.relative_to(OUT))]=sha(p)
    return digest(files),files


def verify_acceptance_inputs(accepted):
    signature,files=acceptance_inputs()
    if signature!=accepted['acceptance_input_signature']:raise RuntimeError('acceptance input bytes changed')
    return files


def main():
    school_guard();checks={}
    for scope,count in [('all',500),('sensitivity',200),('model_form',50)]:
        r=read(OUT/f'READBACK_{scope}_REVIEW.json')
        checks['fresh_physical_'+scope]=r['acceptance_passed']and r['checked_pairs']==count and r['complete_expected_runs_verified']and r['readback_code_sha256']==sha(OUT/'code/physics.py')
    for name,key in [('INPUT_AUDIT.json','status'),('PHYSICAL_INPUT_AUDIT.json','status'),('REFERENCE_MODEL_AUDIT.json','status'),('FRONTEND_BINDINGS_REVIEW.json','status'),('FRONTEND_CLOCK_REVIEW.json','status'),('FRONTEND_BROWSER_REVIEW.json','status')]:
        checks[name]=read(OUT/name)[key]=='pass'
    checks['actual_six_type_coverage']=read(OUT/'CLUSTER_COVERAGE50_REVIEW.json')['accepted_for_original50_reference_development']
    checks['weather_warning_attribution_and_returned_quantity']=read(OUT/'WEATHER_SOLVER_REVIEW.json')['verification_pass']
    checks['acceptance_negative_controls']=read(OUT/'ACCEPTANCE_NEGATIVE_CONTROLS.json')['status']=='pass'
    checks['final_rules_reproduce_actual_original50']=read(OUT/'FINAL_RULE_REGRESSION.json')['status']=='pass'
    checks['50_cards_500_tasks']=read(OUT/'MATERIALS_REVIEW.json')['actor_cards']==50 and read(OUT/'MATERIALS_REVIEW.json')['consumer_tasks']==500
    checks['no_human_answer_or_population_claim']=read(OUT/'MATERIALS_REVIEW.json')['human_answers']==0
    signature,files=acceptance_inputs();failed=[k for k,v in checks.items()if not v]
    report={'schema':'eb.new_original50_complete_reference_acceptance.v27','checks':checks,'failures':failed,
        'new_original50_reference_acceptance_passed':not failed,'households':50,'members':147,'AB_pairs':500,
        'actual_type_counts':read(OUT/'TYPE_ASSIGNMENT50.json')['report']['integer_counts'],
        'unique_expected_EP_runs':1400,'acceptance_input_signature':signature,'acceptance_inputs':files,
        'reference_matching_calendars_services_AB_IDFs_physics_old_frontend_checked':not failed,
        'given_policies_are_measured_personal_preferences':False,'national_six_type_prevalence_identified':False,
        'human_role_validity_measured':False,'human_answers':0,'formal_benchmark_release':False,
        'full1000_EP_allowed':False,'production1000_worlds_already_generated':False,
        'allowed_next_step':'freeze source-conditioned research1000composition;then separate full static world production and coverage review'}
    save(OUT/'FINAL_ACCEPTANCE.json',report);print({k:v for k,v in report.items()if k!='acceptance_inputs'},flush=True)
    if failed:raise RuntimeError('new original50 acceptance failed')


if __name__=='__main__':main()
