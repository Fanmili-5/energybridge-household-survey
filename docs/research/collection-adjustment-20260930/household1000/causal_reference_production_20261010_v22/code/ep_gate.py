"""All EnergyPlus launchers require a reviewed, content-bound production contract."""
from common import *
def input_signature():
    files=['RULE_EVIDENCE.json','REFERENCE_PHYSICS_CONTRACT.json','PURPOSE_CONTRACT.json',
           'PRODUCTION_LOGIC_CHAIN.md','WORLD_BINDINGS1000.json','SELECTION1000.json',
           'IDF_BINDINGS20000.json','STATIC_REVIEW.json','INPUT_AUDIT.json',
           'CALENDAR_AUDIT.json','IDF_INPUT_AUDIT.json','BATH_COMMITMENT_AUDIT.json','VEHICLE_CAUSAL_NEGATIVE_CONTROLS.json',
           'MATERIALS_AUDIT.json','FRONTEND_BROWSER_REVIEW.json',
           'COMPILED50.json','PHYSICAL_INPUT_AUDIT.json','ACTOR_BINDINGS.json','CONSUMER_BINDINGS.json','frontend_release/INDEX50.json',
           'FRONTEND_CLOCK_REVIEW.json','FRONTEND_BINDINGS_REVIEW.json','REFERENCE_MODEL_AUDIT.json']
    out={name:sha(OUT/name) for name in files}
    out.update({'code/'+p.name:sha(p) for p in (OUT/'code').glob('*.py')})
    out.update({str(p.relative_to(OUT)):sha(p) for p in (OUT/'frontend_release/households').glob('*/*.js')})
    return digest(out),out
def require_reviewed_ep(scope='original50'):
    path=OUT/'PRE_EP_SCIENTIFIC_REVIEW.json'
    if not path.exists():raise RuntimeError('EP hold: scientific review has not passed')
    review=read(path);current,_=input_signature()
    assert review['input_signature']==current,'EP hold: inputs/code changed since review'
    assert review['purpose_recheck_passed'] and review['reference_production_accepted']
    assert review['critical_reference_findings']==[]
    assert scope in review['allowed_EP_scopes'],'EP hold: scope not accepted'
    assert not review['national_behavior_validated'] and not review['formal_benchmark_release']
    return review

