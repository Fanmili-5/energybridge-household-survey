"""Full-population verification from raw10min states, independent of classifier functions."""
import sys,collections,math
from pathlib import Path
STAGE=Path(__file__).resolve().parents[1];sys.path.insert(0,str(STAGE/'code'))
from common import *

TOP_CHANGED={'schema','rules_sha256','pair_content_sha256','proposal','classification','source_B','B_frozen_sha256','source_generation_rules_sha256','classification_only_update'}
PFLAGS={'explicit_adverse_request','adverse_design_intent'}
CFLAGS={'boundary_variant','deliberate_reverse_direction','adverse_variant','requested_reverse_variant'}
BAD_TAGS={'opposing_or_excessive_response','beyond_deadline_overreaction','explicit_reverse_bounds','pause_opposes_up_request'}
def direction(n):return 'up'if n>1e-8 else'down'if n< -1e-8 else'unchanged'
def combined(ds):
    ds=set(ds)-{'unchanged'}
    return 'unchanged'if not ds else'mixed'if len(ds)>1 else next(iter(ds))
def request_relation(d,r):return 'unchanged'if d=='unchanged'else'mixed'if d=='mixed'else'aligned'if d==r else'opposing'
def value_direction(kind,a,b):
    if a is None:return 'up'
    if b is None:return 'down'
    if kind=='ac_setpoint':return combined([direction(b[0]-a[0]),direction(a[1]-b[1]),direction(b[2]-a[2])])
    return direction(b[0]-a[0])
def samples(plan):
    result={}
    for x in plan['controls']:
        fields={'ac_setpoint':['heating_setpoint_C','cooling_setpoint_C','fan_operating_mode'],'tank_setpoint':['value_C'],'ev_charge_window':['stop_at_target_soc']}[x['kind']]
        state=tuple(float(x[k])+0. for k in fields)
        for t in range(x['start_min'],x['end_min'],10):
            key=(x['kind'],x['asset_id'],t)
            if key in result:raise ValueError('overlapping control')
            result[key]=state
    return result

def main():
    verify_inputs();b=read(OUT/'PAIR_BINDINGS10000.json');parent=read(SOURCE_B/'PAIR_BINDINGS10000.json');oldrows={r['household_id']:r for r in parent['records']};sig=rules_id();counts=collections.Counter();cube=collections.Counter();relations=collections.Counter();noops=[];changed=[];examples={};errors=[];intent_variants=collections.Counter();noop_reasons=collections.Counter();inherited_same=0
    for ri,row in enumerate(b['records']):
        oldrow=oldrows[row['household_id']];oldcases={r['case_id']:r for r in oldrow['rounds']};w=None
        if row['source_B_record_sha256']!=digest(oldrow):errors.append([row['household_id'],'SOURCE_RECORD_MISMATCH'])
        if {r['case_id']for r in row['rounds']}!=set(oldcases):errors.append([row['household_id'],'DATE_OR_CASE_LOST'])
        for rr in row['rounds']:
            pp=OUT/rr['path'];p=read(pp);oldref=oldcases[rr['case_id']];oldpath=SOURCE_B/oldref['path'];old=read(oldpath);cl=p['classification'];actual=cl['actual_actions'];intent=cl['design_intent'];failure=cl['constraint_failure'];case=p['case_id'];counts['cases']+=1
            if sha(pp)!=rr['sha256']or sha(oldpath)!=oldref['sha256']:errors.append([case,'PAIR_OR_SOURCE_HASH'])
            content=copy.deepcopy(p);claimed=content.pop('pair_content_sha256')
            if digest(content)!=claimed:errors.append([case,'CONTENT_HASH'])
            if p['rules_sha256']!=sig or p['source_B']['case_sha256']!=oldref['sha256']:errors.append([case,'WRONG_CLASSIFICATION_LINEAGE'])
            if {k:v for k,v in p.items()if k not in TOP_CHANGED}!={k:v for k,v in old.items()if k not in TOP_CHANGED}:errors.append([case,'SCHEDULE_DEMAND_EVENT_RESULT_OR_CONTEXT_CHANGED'])
            if p['B_frozen_sha256']!=digest(old['B'])or p['B']!=old['B']or p['A']!=old['A']:errors.append([case,'A_OR_B_CHANGED'])
            if p['source_generation_rules_sha256']!=old['rules_sha256']:errors.append([case,'ORIGINAL_GENERATION_LINEAGE_LOST'])
            oq=old['proposal'];nq=p['proposal'];expected=copy.deepcopy(oq)
            for key in PFLAGS:expected.pop(key,None)
            for ch in expected['changes']:
                for key in CFLAGS:ch.pop(key,None)
            expected.update(classification_record='classification',source_B_proposal_sha256=digest(oq))
            if nq!=expected:errors.append([case,'PROPOSAL_FIELDS_CHANGED_OUTSIDE_CLASSIFICATION_MIGRATION'])
            if PFLAGS&set(nq)or any(CFLAGS&set(ch)for ch in nq['changes']):errors.append([case,'LEGACY_BAD_FLAG_STILL_ACTIVE'])
            if intent['source_markers']!={k:oq[k]for k in PFLAGS if k in oq}:errors.append([case,'SOURCE_MARKER_PROVENANCE_LOST'])
            wanted_intent=[]
            for i,ch in enumerate(oq['changes']):
                markers={k:ch[k]for k in CFLAGS if k in ch};selected=bool(ch.get('requested_reverse_variant'))or any(isinstance(v,str)and v in BAD_TAGS for v in markers.values());wanted_intent.append(selected)
                design=intent['action_designs'][i]
                if design['variant_markers']!=markers or design['unfavourable_variant_selected']!=selected:errors.append([case,'DESIGN_INTENT_MISMATCH'])
                for v in markers.values():
                    if isinstance(v,str):intent_variants[v]+=1
            if intent['unfavourable_variant_selected']!=any(wanted_intent):errors.append([case,'INTENT_AXIS_FALSE'])
            if w is None:w=read(A_STAGE/p['A_source']['world_path']);assets={d['asset_id']:d for d in w['parameter_pack']['devices']}
            aa,bb=samples(p['A']),samples(p['B']);expected_diff={k:(aa.get(k),bb.get(k))for k in set(aa)|set(bb)if aa.get(k)!=bb.get(k)};declared={};direction_at={}
            for x in actual['control_changes']:
                keys={'ac_setpoint':['heating_setpoint_C','cooling_setpoint_C','fan_operating_mode'],'tank_setpoint':['value_C'],'ev_charge_window':['stop_at_target_soc']}[x['kind']]
                av=tuple(x['A'][k]for k in keys)if x['A']else None;bv=tuple(x['B'][k]for k in keys)if x['B']else None;d=value_direction(x['kind'],av,bv)
                if x['control_request_direction']!=d:errors.append([case,'CONTROL_DIRECTION_MISMATCH'])
                for t in range(x['start_min'],x['end_min'],10):
                    key=(x['kind'],x['asset_id'],t)
                    if key in declared:errors.append([case,'DUPLICATE_CLASSIFIED_CONTROL_CHANGE'])
                    declared[key]=(av,bv);direction_at[key]=d
            if declared!=expected_diff:errors.append([case,'SAMPLED_ACTUATOR_CHANGE_MISMATCH'])
            changed_any=bool(expected_diff)
            for key,ident,outkey,fields in [('tasks','task_id','program_changes',['kind','asset_id','start_min','end_min']),('operations','operation_id','manual_operation_changes',['kind','asset_id','operator_id','room_id','start_min','end_min'])]:
                a={x[ident]:{k:x[k]for k in fields}for x in p['A'][key]};z={x[ident]:{k:x[k]for k in fields}for x in p['B'][key]};different={oid:(a[oid],z[oid])for oid in a if a[oid]!=z[oid]};decl={x[ident]:(x['A'],x['B'])for x in actual[outkey]}
                if different!=decl:errors.append([case,'ACTUAL_PROGRAM_OR_MANUAL_CHANGE_MISMATCH'])
                changed_any=changed_any or bool(different)
                for x in actual[outkey]:
                    delta=x['B']['start_min']-x['A']['start_min'];d='delay'if delta>0 else'advance'if delta<0 else'other_command_change'
                    if x['start_shift_minutes']!=delta or x['time_direction']!=d:errors.append([case,'ACTUAL_TIME_DIRECTION_MISMATCH'])
            if actual['any_command_change']!=changed_any or actual['comparison_group']!=('changed_commands'if changed_any else'identical_commands')or oq['same_command_as_A']==changed_any:errors.append([case,'FALSE_NO_CHANGE_CLASS'])
            if actual['actual_command_intensity']!=oq['actual_command_intensity']or actual['actual_unique_dose_count']!=oq['actual_unique_dose_count']or actual['equivalent_design_levels']!=oq['equivalent_design_levels']:errors.append([case,'DOSE_CLASS_CHANGED'])
            inherited_same+=not changed_any
            if failure['flags']!=old['assessment_B']['constraint_flags']or failure['has_given_constraint_conflict']!=bool(old['assessment_B']['constraint_flags']):errors.append([case,'CONSTRAINT_AXIS_CHANGED'])
            if failure['full_physical_failure']is not None or failure['human_rejection']is not None:errors.append([case,'FABRICATED_FAILURE_OR_REJECTION'])
            has_conflict=failure['has_given_constraint_conflict'];counts['constraint_conflict_cases']+=has_conflict;counts['design_unfavourable_variant_cases']+=intent['unfavourable_variant_selected'];cube[str((intent['unfavourable_variant_selected'],changed_any,has_conflict))]+=1
            if not changed_any:
                counts['identical_commands_cases']+=1;noops.append({'case_id':case,'household_id':p['household_id'],'date':p['date'],'path':rr['path'],'sha256':rr['sha256'],'reasons':actual['no_change_reasons']})
                if not actual['no_change_reasons']or has_conflict:errors.append([case,'UNEXPLAINED_OR_FALSE_FAILED_NOOP'])
                noop_reasons.update(set(x['basis']for x in actual['no_change_reasons']));counts['intent_unfavourable_but_unchanged']+=intent['unfavourable_variant_selected'];counts['source_false_adverse_noops_corrected']+=bool(oq['explicit_adverse_request'])
            else:changed.append({'case_id':case,'household_id':p['household_id'],'date':p['date'],'path':rr['path'],'sha256':rr['sha256']})
            # Recompute fixed-program electricity per10min; never use the producer's interval energy helper.
            if len(actual['events'])!=len(p['VPP_events']):errors.append([case,'MISSING_EVENT_CLASSIFICATION'])
            for e,eventclass in zip(p['VPP_events'],actual['events']):
                counts['event_windows']+=1;expected_components={};net_kw=0.;steps=range(e['start_min'],e['end_min'],10);n=(e['end_min']-e['start_min'])//10
                for aid in {t['asset_id']for t in p['A']['tasks']+p['B']['tasks']}:
                    powers=[]
                    for name in ['A','B']:
                        values=[]
                        for t in steps:
                            load=0.
                            for task in p[name]['tasks']:
                                if task['asset_id']==aid and task['start_min']<=t<task['end_min']:
                                    params=assets[aid]['parameters'];load+=params.get(task['kind'],params)['power_kw']
                            values.append(load)
                        powers.append(sum(values)/n)
                    delta=powers[1]-powers[0];net_kw+=delta
                    if abs(delta)>1e-8:expected_components[('program',aid)]=direction(delta)
                ctrl=collections.defaultdict(set)
                for (kind,aid,t),d in direction_at.items():
                    if e['start_min']<=t<e['end_min']:ctrl[kind,aid].add(d)
                for (kind,aid),ds in ctrl.items():expected_components[(kind,aid)]=combined(ds)
                got={}
                for comp in eventclass['components']:
                    key=(comp.get('control_kind','program'),comp['asset_id']);got[key]=comp['direction']
                    if comp['request_relation']!=request_relation(comp['direction'],e['direction']):errors.append([case,'FALSE_EVENT_COMPONENT_RELATION'])
                overall=combined(expected_components.values());expected_relation=request_relation(overall,e['direction']);relations[expected_relation]+=1
                if got!=expected_components or eventclass['component_direction_summary']!=overall or eventclass['component_request_relation']!=expected_relation:errors.append([case,'SAMPLED_EVENT_ACTION_DIRECTION_MISMATCH'])
                response=net_kw*(1 if e['direction']=='up'else-1)
                if abs(response-eventclass['known_program_response_reference_kw'])>1e-7 or eventclass['known_program_net_direction']!=direction(net_kw):errors.append([case,'KNOWN_PROGRAM_REFERENCE_MISMATCH'])
                if any(eventclass[k]is not None for k in ['whole_physical_response_kw','whole_target_met','human_acceptance']):errors.append([case,'FABRICATED_WHOLE_RESPONSE_OR_ACCEPTANCE'])
            if case in ['ordinary-v6-0244__2025-10-21','ordinary-v6-0619__2025-11-18','ordinary-v6-0010__2025-12-19','ordinary-v6-0001__2025-10-12']:examples[case]={'path':rr['path'],'classification':cl}
        if(ri+1)%100==0:print({'reviewed_households':ri+1,'errors':len(errors)},flush=True)
    byid={r['household_id']:r for r in b['records']};sub=read(OUT/'SUBSET50.json');original_ids={r['household_id']for r in read(MASTER/'SUBSET50.json')['records']}
    if {r['household_id']for r in sub['records']}!=original_ids or any(r!=byid[r['household_id']]for r in sub['records']):errors.append(['SUBSET_NOT_EXACT_SAME_MAIN_RECORDS'])
    expected_types={'A':5,'B':15,'C':16,'D':5,'E':4,'F':5}
    if sub['type_counts']!=expected_types:errors.append(['SUBSET_RATIO_CHANGED'])
    if inherited_same!=500 or counts['constraint_conflict_cases']!=1111:errors.append(['PRESERVED_SCHEDULE_GROUPS_CHANGED'])
    counts['changed_commands_cases']=len(changed)
    accepted=not errors and counts['cases']==10000 and len(b['records'])==1000
    report={'accepted':accepted,'rules_sha256':sig,'households':1000,'cases':counts['cases'],'bindings_sha256':sha(OUT/'PAIR_BINDINGS10000.json'),'counts':dict(counts),'errors':errors,'intent_change_conflict_cross_counts':dict(cube),'event_component_request_relation_counts':dict(relations),'design_variant_counts':dict(intent_variants),'no_change_reason_counts':dict(noop_reasons),'subset50_same_main_records':True,'subset50_type_counts':sub['type_counts'],'source_A_and_B_schedules_unchanged':True,'full_physical_acceptance':False,'human_labels_generated':0,'evaluation_inclusion_changed':False,'inherited_B48_candidate_proof':{'path':str((SOURCE_B/'COMMAND_AND_VPP_REVIEW.json').relative_to(BASE)),'sha256':sha(SOURCE_B/'COMMAND_AND_VPP_REVIEW.json'),'candidate_count':40000,'candidates_rebuilt_this_round':False},'scope':'classification,preservation and independent requested-command readback only;not observed physical or human outcomes'}
    save(OUT/'ACCEPTANCE.json',report);save(OUT/'NO_COMMAND_CHANGE_CASES.json',{'group':'identical_commands','cases':len(noops),'not_removed_or_rewritten':True,'evaluation_inclusion_not_changed':True,'records':noops});save(OUT/'CHANGED_COMMAND_CASES.json',{'group':'changed_commands','cases':len(changed),'records':changed});save(OUT/'review/分类实际案例.json',examples)
    print(canonical(report))
    if not accepted:raise SystemExit(2)
if __name__=='__main__':main()
