"""Exercise fixed-scope,physical-receipt and live-code guards without engine calls."""
import copy
from common import *
import physics,ep_gate


def main():
    school_guard();tests=[]
    def blocked(name,fn):
        try:fn()
        except (RuntimeError,AssertionError,KeyError):tests.append({'name':name,'blocked':True});return
        raise RuntimeError('negative control was accepted:'+name)
    rows=physics.scoped_rows('first');runs=read(OUT/'EP_first_REVIEW.json')['records']
    assert physics.check_run_coverage(rows,runs)
    blocked('missing_expected_arm',lambda:physics.check_run_coverage(rows,runs[:1]))
    blocked('duplicate_run_receipt',lambda:physics.check_run_coverage(rows,runs+[copy.deepcopy(runs[0])]))
    altered=copy.deepcopy(runs);altered[0]['signature']['IDF_sha256']='0'*64
    blocked('changed_IDF_receipt',lambda:physics.check_run_coverage(rows,altered))
    bad=copy.deepcopy(runs);bad[0]['runtime_pass']=False
    blocked('failed_run_receipt',lambda:physics.check_run_coverage(rows,bad))
    blocked('full1000_scope',lambda:ep_gate.require_reviewed_ep('full1000'))
    # Mock only bytes returned by the hashing boundary;do not mutate any sealed
    # input. This invokes the production signature verifier,not a copy of it.
    realsha=ep_gate.sha;target=OUT/'code/plans.py'
    ep_gate.sha=lambda p:'f'*64 if Path(p)==target else realsha(p)
    try:blocked('changed_actual_source_code',lambda:ep_gate.require_reviewed_ep('original50'))
    finally:ep_gate.sha=realsha
    report={'schema':'eb.type_pilot_acceptance_negative_controls.v27','status':'pass',
            'tests':tests,'EP_calls':0,'production_inputs_mutated':False,'human_answers':0}
    save(OUT/'ACCEPTANCE_NEGATIVE_CONTROLS.json',report);print(report,flush=True)


if __name__=='__main__':main()
