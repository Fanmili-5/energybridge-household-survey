"""Grounded cases test intent, actions and resource conflicts as independent axes."""
import sys
from pathlib import Path
STAGE=Path(__file__).resolve().parents[1];sys.path.insert(0,str(STAGE/'code'))
from common import *
from classify import classify,update_pair

def main():
    rows={r['household_id']:r for r in read(SOURCE_B/'PAIR_BINDINGS10000.json')['records']}
    def fixture(hid,date):
        rr=next(r for r in rows[hid]['rounds']if r['date']==date);p=read(SOURCE_B/rr['path']);w=read(A_STAGE/p['A_source']['world_path']);return p,w,rr
    p,w,rr=fixture('ordinary-v6-0244','2025-10-21');c=classify(p,w)
    assert c['design_intent']['unfavourable_variant_selected']and c['actual_actions']['comparison_group']=='identical_commands'
    assert not c['actual_actions']['any_command_change']and not c['constraint_failure']['has_given_constraint_conflict']
    assert all(e['component_direction_summary']=='unchanged'for e in c['actual_actions']['events'])
    source={'stage':SOURCE_B.name,'case_path':rr['path'],'case_sha256':rr['sha256']};u=update_pair(p,w,source,rules_id());assert u['A']==p['A']and u['B']==p['B']
    assert 'explicit_adverse_request'not in u['proposal']and 'adverse_design_intent'not in u['proposal']and all('boundary_variant'not in x for x in u['proposal']['changes'])
    findings=read(OUT/'trials/B48_review_findings.json');fixed=[]
    for x in findings['no_change_but_old_adverse']:
        pp=read(SOURCE_B/x['path']);ww=read(A_STAGE/pp['A_source']['world_path']);cc=classify(pp,ww)
        assert cc['design_intent']['unfavourable_variant_selected']and not cc['actual_actions']['any_command_change']and not cc['constraint_failure']['has_given_constraint_conflict']
        assert all(e['component_request_relation']=='unchanged'for e in cc['actual_actions']['events']);fixed.append(pp['case_id'])
    positive=[]
    for x in findings['positive_program_reference_examples']:
        pp=read(SOURCE_B/x['path']);ww=read(A_STAGE/pp['A_source']['world_path']);cc=classify(pp,ww);eid=pp['proposal']['changes'][0]['selected_event_id'];e=next(e for e in cc['actual_actions']['events']if e['event_id']==eid)
        assert cc['design_intent']['unfavourable_variant_selected']and e['known_program_response_reference_kw']>0 and e['component_request_relation']=='aligned'and not cc['constraint_failure']['has_given_constraint_conflict'];positive.append(pp['case_id'])
    # An up-event AC pause is an opposing control request, without claiming kW or refusal.
    found=None;failure=None
    for row in rows.values():
        for r in row['rounds']:
            pp=read(SOURCE_B/r['path']);ee={e['event_id']:e for e in pp['VPP_events']}
            if found is None and any(ch['device_family']=='ac'and ch['paused_minutes']>0 and ee[ch['selected_event_id']]['direction']=='up'for ch in pp['proposal']['changes']):found=pp
            if failure is None and pp['assessment_B']['constraint_flags']:failure=pp
        if found and failure:break
    for pp in [found,failure]:
        ww=read(A_STAGE/pp['A_source']['world_path']);cc=classify(pp,ww)
        assert cc['constraint_failure']['flags']==pp['assessment_B']['constraint_flags']and cc['constraint_failure']['full_physical_failure']is None and cc['constraint_failure']['human_rejection']is None
    cc=classify(found,read(A_STAGE/found['A_source']['world_path']));assert any(x['request_relation']=='opposing'and x.get('control_kind')=='ac_setpoint'for e in cc['actual_actions']['events']for x in e['components'])
    assert classify(failure,read(A_STAGE/failure['A_source']['world_path']))['constraint_failure']['has_given_constraint_conflict']
    # Empty thermal permission has no measured-load consequence inferred from setpoints.
    assert all(e['whole_physical_response_kw']is None and e['whole_target_met']is None and e['human_acceptance']is None for e in cc['actual_actions']['events'])
    report={'passed':True,'rules_sha256':rules_id(),'reported13_unchanged_cases_corrected':fixed,'aligned_program_examples_keep_intent_but_not_false_opposing_label':positive,'actual_up_event_pause_is_opposing_control_request':found['case_id'],'constraint_failure_copied_without_relabeling_as_rejection':failure['case_id'],'A_B_schedules_preserved':True,'all_physics_and_human_labels_unknown':True}
    save(OUT/'REGRESSION_RESULTS.json',report);print(canonical(report))
if __name__=='__main__':main()
