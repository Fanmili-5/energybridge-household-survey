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
    verify_inputs(); sig=rules_id(); b=read(OUT/'PAIR_BINDINGS10000.json')
    source=read(SOURCE_B/'PAIR_BINDINGS10000.json')['records']
    oldrows={r['household_id']:r for r in source};counts=collections.Counter();errors=[]
    relations=collections.Counter();families=collections.Counter();examples={};noops=[];changed=[]
    allowed={'schema','B','B_frozen_sha256','proposal','classification','assessment_B','HVAC_signals_B',
             'VPP_response_reference','event_relations','source_B','rules_sha256','source_generation_rules_sha256',
             'classification_only_update','pair_content_sha256','material_revision',
             'selection_or_regeneration_based_on_B_outcome'}
    requested_candidates=0;status_counts=collections.Counter()
    for row in b['records']:
        oldrounds={r['case_id']:r for r in oldrows[row['household_id']]['rounds']};world=None
        if {r['case_id']for r in row['rounds']}!=set(oldrounds):errors.append([row['household_id'],'DATES_CHANGED'])
        for rr in row['rounds']:
            path=OUT/rr['path'];p=read(path);oldref=oldrounds[rr['case_id']];oldpath=SOURCE_B/oldref['path']
            old=p if rr['inherited_B49_pair'] else read(oldpath);case=p['case_id'];counts['cases']+=1
            if sha(path)!=rr['sha256']or sha(oldpath)!=oldref['sha256']:errors.append([case,'SOURCE_OR_NEW_HASH'])
            if rr['inherited_B49_pair']:
                if path.resolve()!=oldpath.resolve()or rr['sha256']!=oldref['sha256']:errors.append([case,'WRONG_INHERITED_REFERENCE'])
            elif old['classification']['actual_actions']['any_command_change']:
                errors.append([case,'CHANGED_OLD_B_REVISED'])
            if old['classification']['actual_actions']['any_command_change']:
                counts['original9500_changed_B_preserved']+=1
                if not rr['inherited_B49_pair']:errors.append([case,'ORIGINAL_CHANGED_B_NOT_FROZEN'])
            if not rr['inherited_B49_pair']:
                counts['revised_old_identical_cases']+=1
                if {k:v for k,v in p.items()if k not in allowed}!={k:v for k,v in old.items()if k not in allowed}:errors.append([case,'FIXED_CONTEXT_CHANGED'])
                body=copy.deepcopy(p);claimed=body.pop('pair_content_sha256')
                if digest(body)!=claimed:errors.append([case,'CONTENT_DIGEST'])
                if p['B_frozen_sha256']!=digest(p['B']):errors.append([case,'B_DIGEST'])
                if p['A']!=old['A']or p['needs_A']!=old['needs_A']or p['needs_B']!=old['needs_B']:errors.append([case,'A_OR_DEMAND_CHANGED'])
                for key,ident in [('tasks','task_id'),('operations','operation_id')]:
                    if sorted(x[ident]for x in p['A'][key])!=sorted(x[ident]for x in p['B'][key]):errors.append([case,'INVENTED_ACTION'])
                evops=lambda plan:[x for x in plan['operations']if x['kind'].startswith('EV_')]
                if evops(p['A'])!=evops(p['B']):errors.append([case,'EV_HANDLING_CHANGED'])
            if p['human_response']!={'accepted':None,'scores':None,'reason':None}or p['physical_results']is not None or p['questionnaire_stimulus']is not None:errors.append([case,'PREFILLED_LABEL_OR_STALE_RESULT'])
            if world is None:world=read(A_STAGE/p['A_source']['world_path']);assets={d['asset_id']:d for d in world['parameter_pack']['devices']}
            actual=p['classification']['actual_actions'];failure=p['classification']['constraint_failure']
            aa,bb=samples(p['A']),samples(p['B']);diff={k:(aa.get(k),bb.get(k))for k in set(aa)|set(bb)if aa.get(k)!=bb.get(k)}
            declared={};direction_at={}
            for x in actual['control_changes']:
                keys={'ac_setpoint':['heating_setpoint_C','cooling_setpoint_C','fan_operating_mode'],'tank_setpoint':['value_C'],'ev_charge_window':['stop_at_target_soc']}[x['kind']]
                av=tuple(x['A'][k]for k in keys)if x['A']else None;bv=tuple(x['B'][k]for k in keys)if x['B']else None;d=value_direction(x['kind'],av,bv)
                if x['control_request_direction']!=d:errors.append([case,'CONTROL_DIRECTION'])
                for t in range(x['start_min'],x['end_min'],10):
                    key=(x['kind'],x['asset_id'],t);declared[key]=(av,bv);direction_at[key]=d
            if declared!=diff:errors.append([case,'CONTROL_DIFF_CLASSIFICATION'])
            anychange=bool(diff)
            for key,ident,outkey,fields in [('tasks','task_id','program_changes',['kind','asset_id','start_min','end_min']),('operations','operation_id','manual_operation_changes',['kind','asset_id','operator_id','room_id','start_min','end_min'])]:
                a={x[ident]:{k:x[k]for k in fields}for x in p['A'][key]};z={x[ident]:{k:x[k]for k in fields}for x in p['B'][key]}
                expected={oid:(a[oid],z[oid])for oid in a if a[oid]!=z[oid]};got={x[ident]:(x['A'],x['B'])for x in actual[outkey]}
                if expected!=got:errors.append([case,'PROGRAM_OR_MANUAL_CLASSIFICATION'])
                anychange=anychange or bool(expected)
            group='changed_commands'if anychange else'identical_commands'
            if actual['any_command_change']!=anychange or actual['comparison_group']!=group or rr['comparison_group']!=group:errors.append([case,'FALSE_CHANGE_CLASS'])
            if failure['flags']!=p['assessment_B']['constraint_flags']or failure['has_given_constraint_conflict']!=bool(failure['flags']):errors.append([case,'FALSE_CONSTRAINT_CLASS'])
            counts['constraint_conflict_cases']+=bool(failure['flags'])
            if old['assessment_B']['constraint_flags']:
                counts['old_constraint_conflicts_preserved']+=p['assessment_B']==old['assessment_B']
            if not rr['inherited_B49_pair']:
                counts['new_constraint_conflict_cases_kept']+=bool(failure['flags'])
                families.update(actual['changed_device_families'])
            counts[group]+=1
            item={'case_id':case,'household_id':p['household_id'],'date':p['date'],'path':rr['path'],'sha256':rr['sha256']}
            (changed if anychange else noops).append(item)
            for e,eventclass in zip(p['VPP_events'],actual['events']):
                expected={};net=0.;n=(e['end_min']-e['start_min'])//10
                for aid in {t['asset_id']for t in p['A']['tasks']+p['B']['tasks']}:
                    values=[]
                    for plan in [p['A'],p['B']]:
                        total=0.
                        for t in range(e['start_min'],e['end_min'],10):
                            for task in plan['tasks']:
                                if task['asset_id']==aid and task['start_min']<=t<task['end_min']:
                                    params=assets[aid]['parameters'];total+=params.get(task['kind'],params)['power_kw']
                        values.append(total/n)
                    delta=values[1]-values[0];net+=delta
                    if abs(delta)>1e-8:expected['program',aid]=direction(delta)
                controls=collections.defaultdict(set)
                for (kind,aid,t),d in direction_at.items():
                    if e['start_min']<=t<e['end_min']:controls[kind,aid].add(d)
                for key,ds in controls.items():expected[key]=combined(ds)
                got={(x.get('control_kind','program'),x['asset_id']):x['direction']for x in eventclass['components']}
                relation=request_relation(combined(expected.values()),e['direction']);relations[relation]+=1
                if got!=expected or eventclass['component_request_relation']!=relation:errors.append([case,'EVENT_DIRECTION_CLASS'])
                response=net*(1 if e['direction']=='up'else-1)
                if abs(response-eventclass['known_program_response_reference_kw'])>1e-7:errors.append([case,'PROGRAM_POWER_REFERENCE'])
                if any(eventclass[k]is not None for k in ['whole_physical_response_kw','whole_target_met','human_acceptance']):errors.append([case,'FABRICATED_OUTCOME'])
            if case in ['ordinary-v6-0244__2025-10-21','ordinary-v6-0001__2025-03-27','ordinary-v6-0619__2025-11-18']:
                examples[case]={'path':rr['path'],'inherited':rr['inherited_B49_pair'],'old_changes':old['proposal']['changes'],'new_changes':p['proposal']['changes'],'classification':p['classification']}
        log=read(OUT/'runs'/sig[:16]/'revision_log'/(row['household_id']+'.json'))
        for item in log['cases']:
            status_counts[item['status']]+=1;requested_candidates+=len(item.get('candidate_checks',[]))
        if counts['cases']%1000==0:print({'reviewed_cases':counts['cases'],'errors':len(errors)},flush=True)
    mainrows={r['household_id']:r for r in b['records']};subset=read(OUT/'SUBSET50.json');oldsubset=read(SOURCE_B/'SUBSET50.json')
    if {r['household_id']for r in subset['records']}!={r['household_id']for r in oldsubset['records']}or any(r!=mainrows[r['household_id']]for r in subset['records']):errors.append(['SUBSET_NOT_SAME_MASTER_ROWS'])
    if subset['type_counts']!={'A':5,'B':15,'C':16,'D':5,'E':4,'F':5}:errors.append(['SUBSET_RATIO_CHANGED'])
    if counts['cases']!=10000 or len(b['records'])!=1000 or counts['original9500_changed_B_preserved']!=9500 or counts['old_constraint_conflicts_preserved']!=1111:errors.append(['COUNTS_OR_FAILURES_LOST'])
    accepted=not errors
    report={'accepted':accepted,'rules_sha256':sig,'bindings_sha256':sha(OUT/'PAIR_BINDINGS10000.json'),'households':1000,'cases':10000,'counts':dict(counts),
            'revised_device_family_counts':dict(families),'event_request_relation_counts':dict(relations),
            'old500_revision_status_counts':dict(status_counts),'new_candidate_integrity_checks':requested_candidates,
            'all10000_retained_in_total_dataset':True,'source_A46_unchanged':True,'original9500_changed_B_preserved':True,
            'subset50_type_counts':subset['type_counts'],'subset50_same_main_rows':True,
            'human_labels_generated':0,'full_physical_acceptance':False,'new_questionnaire_released':False,
            'selection_uses_old_command_equivalence_but_not_delivery_or_acceptance':True,
            'no_minimum_change_count_or_success_quota':True,'errors':errors,
            'scope':'requested action design,classification,source preservation;not physical response or human acceptance'}
    save(OUT/'ACCEPTANCE.json',report);save(OUT/'NO_COMMAND_CHANGE_CASES.json',{'cases':len(noops),'records':noops,'retained_in_total_dataset':True,'preset_acceptance':None})
    save(OUT/'CHANGED_COMMAND_CASES.json',{'cases':len(changed),'records':changed});save(OUT/'review/实际案例.json',examples)
    print(canonical(report))
    if not accepted:raise SystemExit(2)

if __name__=='__main__':main()

