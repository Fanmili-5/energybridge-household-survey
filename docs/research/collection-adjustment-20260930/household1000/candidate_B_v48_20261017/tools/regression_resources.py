"""Actual reported cases plus control-representation and union-event counterfactuals."""
import sys,copy
from pathlib import Path
STAGE=Path(__file__).resolve().parents[1];sys.path.insert(0,str(STAGE/'code'))
from common import *
from event_proposals import thermal,program,eligible

def fixture(hid,date):
    old=BASE/'candidate_B_v43_20261016';row=next(r for r in read(old/'PAIR_BINDINGS10000.json')['records']if r['household_id']==hid)
    p=read(old/next(r['path']for r in row['rounds']if r['date']==date));w=read(BASE/p['A_source']['stage']/p['A_source']['world_path']);return w,p

def samples(p,aid):
    return [(t,x['heating_setpoint_C'],x['cooling_setpoint_C'],x['fan_operating_mode'])for t in range(480,1920,10)for x in p['controls']if x['kind']=='ac_setpoint'and x['asset_id']==aid and x['start_min']<=t<x['end_min']]

def main():
    w,c=fixture('ordinary-v6-0003','2025-09-28');e=c['VPP_events'][0];pool,_=eligible(c);plan=copy.deepcopy(c['A']);z=thermal(plan,w,c,pool['ac'],e,2)
    assert z['start_min']==e['start_min']and z['end_min']==min(z['available_span_A_min'][1],z['start_min']+120)
    assert z['event_overlap_minutes']==e['end_min']-e['start_min']
    # Splitting the same semantic A permission into ten-minute records must
    # leave the chosen room, time, fan states and actual adjusted bounds equal.
    split=copy.deepcopy(c);parts=[]
    for x in split['A']['controls']:
        if x['kind']!='ac_setpoint':parts.append(x);continue
        parts.extend({**x,'start_min':t,'end_min':min(x['end_min'],t+10),'need_id':str(x.get('need_id'))+':representation:'+str(t)}for t in range(x['start_min'],x['end_min'],10))
    split['A']['controls']=parts
    from planner import _opportunity
    assert _opportunity(c,e,'ac')==_opportunity(split,e,'ac')
    sp,_=eligible(split);bp=copy.deepcopy(split['A']);zz=thermal(bp,w,split,sp['ac'],e,2)
    assert(z['asset_id'],z['start_min'],z['end_min'])==(zz['asset_id'],zz['start_min'],zz['end_min'])
    for aid in z['affected_asset_ids']:
        assert samples(plan,aid)==samples(bp,aid)
        assert [(t,fan)for t,_,_,fan in samples(plan,aid)]==[(t,fan)for t,_,_,fan in samples(c['A'],aid)]
    # A real permission gap is different from a serialization boundary.
    gap=copy.deepcopy(c);gap['A']['controls']=[x for x in parts if x['kind']!='ac_setpoint'or not overlap((x['start_min'],x['end_min']),(e['start_min']+20,e['start_min']+40))]
    gp,_=eligible(gap);gplan=copy.deepcopy(gap['A']);gz=thermal(gplan,w,gap,gp['ac'],e,3)
    assert not overlap((gz['start_min'],gz['end_min']),(e['start_min']+20,e['start_min']+40))
    actual=[]
    for hid,date in [('ordinary-v6-0283','2025-02-03'),('ordinary-v6-0328','2025-01-31')]:
        w0,c0=fixture(hid,date);c0['_joint_events']=c0['VPP_events'];p0,_=eligible(c0);task=next(t for t in p0['dishwasher']if t['start_min']==1120)
        local=min(c0['VPP_events'],key=lambda e:e['start_min']);out=copy.deepcopy(c0['A']);ch=program(out,w0,c0,[task],local,0)
        assert ch['program_start_B_min']==1140 and ch['delta_minutes']==20
        assert len(ch['considered_event_ids'])==2
        # Outside all relevant windows is still a genuine unchanged request.
        no=copy.deepcopy(c0);no['_joint_events']=[{**e,'start_min':600+i*120,'end_min':630+i*120}for i,e in enumerate(c0['VPP_events'])]
        nplan=copy.deepcopy(no['A']);unchanged=program(nplan,w0,no,[task],no['_joint_events'][0],0)
        assert unchanged['delta_minutes']==0
        actual.append({'case_id':c0['case_id'],'old_B_start_min':1120,'new_B_start_min':1140})
    r={'rules_sha256':rules_id(),'passed':True,'actual_0003_high_full_event_overlap_minutes':z['event_overlap_minutes'],'thermal_semantic_controls_invariant_to_serialization':True,'input_opportunity_score_invariant_to_serialization':True,'fan_modes_preserved':True,'actual_permission_gap_not_bridged':True,'joint_noop_actual_cases':actual,'outside_all_events_still_unchanged':True,'all_tests_use_frozen_A_not_B_quality_selection':True}
    save(OUT/'RESOURCE_REGRESSION_RESULTS.json',r);print(canonical(r))
if __name__=='__main__':main()
