"""Grounded real-case direction, new permission, envelope and unavailable-dose tests."""
import sys,copy
from pathlib import Path
STAGE=Path(__file__).resolve().parents[1];sys.path.insert(0,str(STAGE/'code'))
from common import *
from thermal_flex import opportunity_options,make_preconditioning
from event_proposals import eligible,thermal
from events import for_case
from assess import assess
from proposals import command_signature

def fixture(hid,date):
    r=next(r for r in read(A_STAGE/'A_BINDINGS10000.json')['records']if r['household_id']==hid);w=read(A_STAGE/r['A_world_path']);c=read(A_STAGE/next(r['path']for r in r['cases']if r['date']==date));c['VPP_events']=for_case(w,c);return w,c

def main():
    w,c=fixture('ordinary-v6-0016','2025-02-22');e=c['VPP_events'][0];assert e['direction']=='up';pool,_=eligible(c);out=copy.deepcopy(c['A']);z=thermal(out,w,c,pool['ac'],e,1,pause=True)
    assert z['deliberate_reverse_direction']and z['effective_request_direction']=='down'and z['control_action_direction']=='down'and z['requested_event_direction']=='up'and z['adverse_variant']=='pause_opposes_up_request'
    for aid in z['affected_asset_ids']:
        assert not any(x['kind']=='ac_setpoint'and x['asset_id']==aid and overlap((z['start_min'],z['end_min']),(x['start_min'],x['end_min']))for x in out['controls'])
    w,c=fixture('ordinary-v6-0084','2025-12-11');e=c['VPP_events'][0];assert e['direction']=='up'and e['start_min']==720 and e['end_min']==750
    assert opportunity_options(c,e);out=copy.deepcopy(c['A']);z=make_preconditioning(out,w,c,e,1);phase=z['preconditioning']['phases'][0];assert[phase['start_min'],phase['end_min']]==[720,750]
    assert any(phase['A_permission_added_minutes_by_asset'].values())and z['preconditioning']['target_actual_room_use_min']==750
    assert not assess(w,c,out)['integrity_errors']and out['operations']==c['A']['operations']
    assert z['preconditioning']['authorization_required']and z['preconditioning']['human_acceptance']is None and z['preconditioning']['physical_success']is None
    no=copy.deepcopy(c)
    for ctx in no['thermal_control_context'].values():ctx['hardware_request_intervals_min']=[]
    assert not opportunity_options(no,e)
    # The next room use must actually be close enough; moving it late removes opportunity.
    late=copy.deepcopy(c)
    for ctx in late['thermal_control_context'].values():
        ctx['actual_occupied_intervals_min']=[[a+300,b+300]for a,b in ctx['actual_occupied_intervals_min']if a>=750]
    assert not opportunity_options(late,e)
    # A low lead which misses the event stays unchanged; no filler switch-on.
    far=copy.deepcopy(c)
    for ctx in far['thermal_control_context'].values():ctx['actual_occupied_intervals_min']=[[800,900]];ctx['A_permission_intervals_min']=[[800,900]]
    assert opportunity_options(far,e);fp=copy.deepcopy(far['A']);fz=make_preconditioning(fp,w,far,e,0)
    assert fz['preconditioning']['phases']==[]and command_signature(fp)==command_signature(far['A'])
    assert all(x['cooling_setpoint_C']-x['heating_setpoint_C']>=2.-1e-8 for x in out['controls']if x['kind']=='ac_setpoint')
    report={'passed':True,'rules_sha256':rules_id(),'actual0016_up_pause_explicitly_adverse':True,'actual0084_noon_preconditioning_min':[720,750],'actual0084_target_room_use_min':750,'new_request_outside_A_within_hardware':True,'operations_and_demands_unchanged':True,'hardware_restriction_removes_opportunity':True,'later_return_removes_event_opportunity':True,'insufficient_lead_keeps_A_without_filler':True,'minimum2C_gap_retained':True,'consent_and_physical_success_unknown':True}
    save(OUT/'THERMAL_FLEX_REGRESSION.json',report);print(canonical(report))
if __name__=='__main__':main()
