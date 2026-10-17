"""Population design readback: clipping, EV failure shape and event-state linkage."""
import sys,collections
from pathlib import Path
STAGE=Path(__file__).resolve().parents[1];sys.path.insert(0,str(STAGE/'code'))
from common import *

def main():
    sig=rules_id();bindings_sha=sha(OUT/'PAIR_BINDINGS10000.json')
    counts=collections.Counter();ev_grade_outcomes=collections.Counter();shortfalls=collections.Counter();windows=collections.Counter();state_relations=collections.Counter();examples={}
    special={'ordinary-v6-0001__2025-03-22','ordinary-v6-0002__2025-05-15','ordinary-v6-0048__2025-04-02','ordinary-v6-0145__2025-07-08'}
    for row in read(OUT/'PAIR_BINDINGS10000.json')['records']:
        for rr in row['rounds']:
            p=read(OUT/rr['path']);counts['cases']+=1
            for req,obs in zip(p['proposal']['requested_device_strengths'],p['proposal']['actual_device_strengths']):
                fam=req['device_family'];par=req['parameters'];ctx=req['input_state_plan'];counts[fam+'_device_requests']+=1
                if fam in('ac','water_heater'):
                    both=[x for x in obs['control_segments']if x['A']and x['B']];keys=['heating_setpoint_C','cooling_setpoint_C']if fam=='ac'else['value_C'];actual=max([abs(x['A'][k]-x['B'][k])for x in both for k in keys]+[0]);intended=par['setpoint_delta_C'if fam=='ac'else'target_delta_C']
                    if actual:counts[fam+'_paired_temperature_requests']+=1;counts[fam+'_temperature_less_than_draft']+=actual<intended-1e-8
                if fam in('washer','dishwasher'):
                    actual=max([abs(x['start_shift_minutes'])for x in obs['program_changes']if x['kind']==fam]+[0]);counts[fam+'_program_clipped_below_draft']+=0<actual<par['requested_shift_min']
                if fam=='ev':
                    for m in obs['EV_window_metrics']:
                        negative=m['B_window_slack_minutes']<0;length=m['B_window_min'][1]-m['B_window_min'][0]
                        counts['EV_negative_slack']+=negative;counts['EV_10min_windows']+=length==10;windows[str(length)]+=1;ev_grade_outcomes[str((req['grade'],negative))]+=1
                        if negative:shortfalls[str(round(-m['B_window_slack_minutes'],3))]+=1
                    if ctx['behavior']in('normal_response','partial_response'):
                        event=next(e for e in p['classification']['actual_actions']['events']if e['event_id']==ctx['event']['event_id'])
                        for ref in event['EV_event_state_reference']['devices']:
                            if ref['asset_id']in obs['asset_ids']:state_relations[ref['response_relation']]+=1
            if p['case_id']in special:
                examples[p['case_id']]={'case_id':p['case_id'],'path':rr['path'],'requests':p['proposal']['requested_device_strengths'],'actual':p['proposal']['actual_device_strengths'],'event_state':[{'event_id':x['event_id'],'requested_direction':x['requested_direction'],'EV_reference':x['EV_event_state_reference'],'literal_components':x['components']}for x in p['classification']['actual_actions']['events']],'constraint_flags':p['assessment_B']['constraint_flags']}
    report={'rules_sha256':sig,'bindings_sha256':bindings_sha,'counts':dict(counts),'EV_failures_by_draft_grade':dict(ev_grade_outcomes),'EV_failed_charge_time_shortfall_minutes':dict(shortfalls),'EV_window_length_minutes':dict(windows),'normal_or_partial_EV_selected_event_reference_relations':dict(state_relations),'all10000_retained':True,'new_failures_not_filtered':True,'thermal_state_and_whole_physics_pending':True,'scope':'generation-rule readback and fixed-input references;not user acceptance or full physical success'}
    if rules_id()!=sig or sha(OUT/'PAIR_BINDINGS10000.json')!=bindings_sha:raise ValueError('INPUTS_CHANGED_DURING_DESIGN_REVIEW')
    save(OUT/'DESIGN_REVIEW.json',report);save(OUT/'review/三项修改案例.json',examples);print(canonical(report))

if __name__=='__main__':main()
