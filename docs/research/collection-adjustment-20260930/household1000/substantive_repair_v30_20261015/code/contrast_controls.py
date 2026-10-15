"""Actual-source rejection controls. No fabricated participant response."""
import copy
from common import *
from contrast_core import metrics,invariant_errors
from repair_contrast import PARENT,repair_one
from cohort_gate import require_reviewed_ep,require_original50_acceptance

def rejected(fn):
    try:fn()
    except(AssertionError,RuntimeError,KeyError):return True
    return False

def main():
    selection=read(OUT/'SELECTION1000.json')['records'];ids=set(read(OUT/'PARTITIONS.json')['formal50']);oldh=next(h for h in read(PARENT/'SELECTION1000.json')['records']if h['household_id']in ids)
    old=read(PARENT/oldh['rounds'][0]['pair_path']);w=read(OUT/oldh['world_path']);good=repair_one(w,old)[0]
    same=copy.deepcopy(good);same['B']=copy.deepcopy(same['A'])
    assert not metrics(same)['admitted']
    needs=copy.deepcopy(good);needs['needs_B'][0]['quantity']+=1
    assert invariant_errors(needs,old,w,oldh['world_sha256'])
    moved=copy.deepcopy(good);moved['A']['controls'][0]['start_min']+=10
    assert any('FROZEN_CHANGED:A'==x for x in invariant_errors(moved,old,w,oldh['world_sha256']))
    # Find the actual original50 micro-AC case, rather than inventing a role.
    weak=None
    for h in read(PARENT/'SELECTION1000.json')['records']:
        if h['household_id']not in ids:continue
        for rr in h['rounds']:
            q=read(PARENT/rr['pair_path'])
            if metrics(q)['micro_temperature_request']:weak=q;break
        if weak:break
    assert weak is not None and not metrics(weak)['admitted']
    edge=None
    for h in read(PARENT/'SELECTION1000.json')['records']:
        for rr in h['rounds']:
            q=read(PARENT/rr['pair_path'])
            lo,hi=q['primary_evaluation_min']
            if q['proposal']['family']=='additional_AC_request_without_cooling_need'and any(n['kind']=='ac'and overlap((n['release_min'],n['deadline_min']),(lo,hi))for n in q['needs_A']):edge=q;break
        if edge:break
    assert edge is not None and metrics(edge)['admitted'],'another time of day may have a cooling need'
    wrong=copy.deepcopy(edge);n=next(n for n in wrong['needs_A']if n['kind']=='ac');wrong['B']['controls']=[x for x in wrong['B']['controls']if x.get('service_date')]+[{'asset_id':n['asset_id'],'kind':'ac_setpoint','start_min':n['release_min'],'end_min':n['release_min']+60,'value_C':27.}]
    assert not metrics(wrong)['admitted'],'an extra-no-need claim inside an actual need must be rejected'
    checks={'identical_actual_request_rejected':True,'changed_common_need_rejected':True,'changed_frozen_A_rejected':True,
       'actual_subprecision_AC_rejected':True,'cross_date_claim_uses_actual_added_interval':True,'false_extra_no_need_claim_rejected':True,'950_before_complete_original50_rejected':rejected(require_original50_acceptance),
       'unreviewed950_EP_rejected':rejected(lambda:require_reviewed_ep('other950'))}
    assert all(checks.values())
    save(OUT/'CONTRAST_NEGATIVE_CONTROLS.json',{'passed':True,'checks':checks,'human_answers':0,'EP_started':False})
    print({'contrast_rejection_controls':checks,'EP_started':False},flush=True)

if __name__=='__main__':main()
