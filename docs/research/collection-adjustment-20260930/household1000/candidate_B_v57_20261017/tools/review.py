"""Bounded closure audit: fixed B56 schedules, joint-node truth and SOC time semantics."""
import sys,collections
from pathlib import Path
STAGE=Path(__file__).resolve().parents[1];sys.path.insert(0,str(STAGE/'code'))
from common import *
from concurrent.futures import ProcessPoolExecutor

def audit(row):
    errors=[];c=collections.Counter();examples={}
    def fail(p,code):errors.append([p['case_id'],code])
    def clean_plan(plan):
        q=copy.deepcopy(plan);q.pop('program_request_plans',None)
        for x in q['tasks']:x.pop('request_formation',None)
        return q
    def clean_forms(x):
        if isinstance(x,list):return [clean_forms(y)for y in x]
        if not isinstance(x,dict):return x
        y={k:clean_forms(v)for k,v in x.items()if k not in('joint_B_node_relation','actual_request_basis','given_A_anchor_is_design_provenance')}
        if 'selected_node'in y and 'selection_rule'in y:y['life_node_reached']=y['selected_node']is not None
        if 'continuous_reference_sha256'in y:y['continuous_reference_sha256']='separately verified'
        return y
    for rr in row['rounds']:
        p=read(OUT/rr['path']);ref=p['revision_parent'];old=read(PARENT_B/ref['case_path']);c['cases']+=1
        if sha(OUT/rr['path'])!=rr['sha256']or sha(PARENT_B/ref['case_path'])!=ref['case_sha256']:fail(p,'PAIR_HASH')
        body=copy.deepcopy(p);claimed=body.pop('pair_content_sha256')
        if digest(body)!=claimed or digest(p['B'])!=p['B_frozen_sha256']:fail(p,'BODY_HASH')
        for k in ('A','needs_A','needs_B','A_source','days','assessment_B','event_relations','HVAC_signals_B','human_response','physical_results','questionnaire_stimulus'):
            if k=='assessment_B':
                if clean_forms(p[k])!=clean_forms(old[k]):fail(p,'FROZEN_'+k)
            elif p[k]!=old[k]:fail(p,'FROZEN_'+k)
        if clean_plan(p['B'])!=clean_plan(old['B']):fail(p,'B56_COMMAND_OR_SERVICE_CHANGED')
        c['B56_schedule_unchanged_cases']+=clean_plan(p['B'])==clean_plan(old['B'])
        if clean_forms(p['proposal'])!=clean_forms(old['proposal'])or clean_forms(p['classification'])!=clean_forms(old['classification']):fail(p,'UNAUTHORIZED_PROPOSAL_OR_CLASSIFICATION_CHANGE')
        if p['classification']['actual_actions']['any_command_change']:c['changed_commands']+=1
        else:
            c['identical_commands']+=1
            if p['B']!=old['B']:fail(p,'FIXED100_B_PAYLOAD_CHANGED')
        c['constraint_conflict_cases']+=bool(p['assessment_B']['constraint_flags'])
        for f in p['B'].get('program_request_plans',[]):
            node=f['selected_node']
            if node is None:continue
            c['life_node_plans_checked']+=1;kind=node['kind'];refid=node['reference'];expected=node['minute']
            if kind=='previous_batch_cleared':expected=next(o['end_min']for o in p['B']['operations']if o['need_id']==refid and o['kind']=='unload')
            else:
                op=next((o for o in p['B']['operations']if o['operation_id']==refid),None)
                if op:expected=op['start_min']-10 if kind=='before_next_use'else op['start_min']if kind in('original_retrieval','finish_at_original_retrieval')else op['end_min']
            field=node['field'];nid=f['need_id']
            if field in('load_min','unload_min'):action=next(o['start_min']for o in p['B']['operations']if o['need_id']==nid and o['kind']==('load'if field=='load_min'else'unload'))
            else:
                tasks=[x for x in p['B']['tasks']if x['need_id']in(nid,nid+':dry')];action=max(x['end_min']for x in tasks)if field=='finish_min'else min(x['start_min']for x in tasks)
            reached=action==expected;r=f['joint_B_node_relation']
            if r['referenced_joint_B_min']!=expected or r['actual_B_action_min']!=action or r['exact_joint_B_node_reached']!=reached or f['life_node_reached']!=reached:fail(p,'JOINT_NODE_NOT_LITERAL_B')
            if not reached:
                c['stale_A_anchors_corrected']+=1
                if f['actual_request_basis']!='A_reference_anchor_not_reached_in_joint_B':fail(p,'STALE_REASON_RETAINED')
                examples[p['case_id']]={'formation':f,'schedule_unchanged':True}
        ev=p['EV_continuous_reference'];prior=old['EV_continuous_reference'];summary=p['VPP_response_reference']['EV_continuous_impact']
        if summary['continuous_reference_sha256']!=digest(ev):fail(p,'EV_SUMMARY_BINDING')
        if ev['status']=='not_installed':continue
        c['EV_cases']+=1
        for k in ('A','B','events','initial_energy_kWh','interval_min','changed_need_ids'):
            if ev[k]!=prior[k]:fail(p,'EV_TRAJECTORY_OR_ENERGY_CHANGED')
        c['EV_target_unmet_departures']+=sum(x['target_SOC_unmet']for x in ev['B']['trips']);c['EV_min_reserve_unmet_departures']+=sum(x['minimum_reserve_unmet_after_trip']for x in ev['B']['trips'])
        delta=collections.defaultdict(float)
        for side,sign in [('A',-1),('B',1)]:
            for x in ev[side]['charging_steps']:delta[x['end_min']]+=sign*x['battery_kWh']
        value=0.;had=False;actual=None
        for t,z in sorted(delta.items()):
            before=value;value+=z
            if abs(value)>1e-7:had=True;actual=None
            elif had and abs(before)>1e-7:actual=t
        if any(ev[side]['stop_at_unexecutable_trip_min']is not None for side in('A','B')):actual=None
        if ev['actual_stable_SOC_match_min']!=actual or summary['common_SOC_restored_min']!=actual or summary['actual_stable_SOC_match_min']!=actual:fail(p,'ACTUAL_SOC_MATCH_TIME')
        end=prior['last_changed_permission_end_min']if ev['changed_need_ids']else None
        if ev['intervention_end_min']!=end or summary['intervention_end_min']!=end or summary['post_intervention_SOC_confirmation_min']!=prior['common_SOC_restored_after_request_min']:fail(p,'INTERVENTION_CONFIRMATION_TIME_MIXED')
        c['earlier_actual_SOC_match_cases']+=actual is not None and summary['post_intervention_SOC_confirmation_min']is not None and actual<summary['post_intervention_SOC_confirmation_min']
        # All prior energy amounts, deficiencies and event response references stay identical.
        def energy_view(v):
            q=copy.deepcopy(v)
            for k in ('common_SOC_restored_min','actual_stable_SOC_match_min','intervention_end_min','post_intervention_SOC_confirmation_min','time_display_basis','continuous_reference_sha256'):q.pop(k,None)
            return q
        if energy_view(summary)!=energy_view(old['VPP_response_reference']['EV_continuous_impact']):fail(p,'EV_ENERGY_OR_FAILURE_SUMMARY_CHANGED')
        for k,v in p['VPP_response_reference'].items():
            if k!='EV_continuous_impact'and v!=old['VPP_response_reference'][k]:fail(p,'VPP_ENERGY_CHANGED')
        if p['case_id']in('ordinary-v6-0001__2025-10-12','ordinary-v6-0001__2025-09-30'):examples[p['case_id']]={'EV_summary':summary,'schedule_unchanged':True}
    return errors,dict(c),examples

def main():
    verify_inputs();sig=rules_id();b=read(OUT/'PAIR_BINDINGS10000.json');errors=[];c=collections.Counter();examples={}
    with ProcessPoolExecutor(max_workers=4)as pool:
        for e,cc,xx in pool.map(audit,b['records']):errors+=e;c.update(cc);examples.update(xx)
    subset=read(OUT/'SUBSET50.json');master={r['household_id']:r for r in b['records']};expected_ids={r['household_id']for r in read(PARENT_B/'SUBSET50.json')['records']}
    assert {r['household_id']for r in subset['records']}==expected_ids and all(r==master[r['household_id']]for r in subset['records'])
    assert subset['type_counts']=={'A':5,'B':15,'C':16,'D':5,'E':4,'F':5}and c['cases']==10000 and c['B56_schedule_unchanged_cases']==10000
    assert sig==rules_id()
    tests=['all10000_B56_schedules_and_A46_daily_services_unchanged','fixed100_B_payloads_unchanged','joint_B_node_references_checked_against_actual_commands','actual_stable_SOC_match_independently_reconstructed','intervention_end_and_confirmation_time_separate','EV_energy_deficits_and_VPP_response_values_unchanged','all_B56_failures_and_no_human_labels_retained','subset50_exact_main_rows_and_original_ratio']
    save(OUT/'ACCEPTANCE.json',{'accepted':not errors,'rules_sha256':sig,'bindings_sha256':sha(OUT/'PAIR_BINDINGS10000.json'),'counts':dict(c),'subset50_type_counts':subset['type_counts'],'errors':errors,'scope':'B56 schedule-preserving association/time finalization;no new physical or human acceptance'})
    save(OUT/'REGRESSION_RESULTS.json',{'passed':not errors,'count':len(tests),'tests':tests,'rules_sha256':sig,'no_repeated_unrelated_checks':True});save(OUT/'review/收尾案例.json',examples)
    print(canonical({'passed':not errors,'counts':dict(c),'errors':errors[:5]}))
    if errors:raise SystemExit(2)
if __name__=='__main__':main()
