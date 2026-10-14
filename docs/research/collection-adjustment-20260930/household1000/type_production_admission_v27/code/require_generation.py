#!/usr/bin/env python3
"""Only admit static1000 from frozen school evidence; full EP remains held."""
import hashlib,importlib,json,sys
from pathlib import Path

ADMISSION=Path(__file__).resolve().parents[1]
H=ADMISSION.parent
def read(p):return json.loads(p.read_text())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def require_generation(scope='static1000'):
    if scope!='static1000':
        raise RuntimeError('full1000 EP hold: actual new1000 worlds/AB/IDFs,whole coverage and production review still required')
    lock=read(ADMISSION/'LOCK.json');stage=H/lock['stage']
    sys.path.insert(0,str(stage/'code'))
    common=importlib.import_module('common');common.school_guard()
    final=stage/'FINAL_ACCEPTANCE.json';frozen=stage/'FROZEN_COMPOSITION1000.json'
    assert sha(final)==lock['original50_acceptance_sha256']
    assert sha(frozen)==lock['frozen_composition_sha256']
    accepted=read(final);composition=read(frozen)
    assert accepted['new_original50_reference_acceptance_passed']
    importlib.import_module('finalize_pilot').verify_acceptance_inputs(accepted)
    assert composition['original50_acceptance_sha256']==sha(final)
    assert composition['accepted_original50_type_policy_preserved']
    assert not composition['full1000_EP_allowed']
    assert sum(composition['counts'].values())==1000
    assert len(composition['type_assignment_for_future_generation'])==1000
    assert composition['conditional_reference']['solver_status']==0
    for n,s in composition['implementation_code_sha256'].items():assert sha(stage/'code'/n)==s
    source=common.SOURCE;selection=read(source/'SELECTION1000.json')
    assert sha(source/'SELECTION1000.json')==composition['source_selection_sha256']
    for h in selection['records']:assert sha(source/h['world_path'])==h['world_sha256']
    fixed=read(stage/'TYPE_ASSIGNMENT50.json')['assignment']
    assert all(composition['type_assignment_for_future_generation'][h]==t for h,t in fixed.items())
    return {'scope':'static1000','generation_allowed':True,'EP_allowed':False,
        'assignment':composition['type_assignment_for_future_generation'],
        'counts':composition['counts'],'frozen_composition_sha256':sha(frozen),
        'actual1000_outputs_already_accepted':False,
        'required_after_static_generation':'actual coverage/source preservation/normalA/badB/IDF and whole production acceptance'}

if __name__=='__main__':
    try:
        result=require_generation(sys.argv[1]if len(sys.argv)>1 else 'static1000')
        print(json.dumps({k:v for k,v in result.items()if k!='assignment'},ensure_ascii=False))
    except (RuntimeError,AssertionError,FileNotFoundError)as exc:
        print(json.dumps({'generation_allowed':False,'EP_allowed':False,'reason':str(exc)},ensure_ascii=False))
        sys.exit(2)
