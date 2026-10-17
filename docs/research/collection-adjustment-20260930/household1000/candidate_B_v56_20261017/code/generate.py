"""Rebuild all B requests in native device units; keep A46 and the whole10000."""
import argparse,collections,shutil
from concurrent.futures import ProcessPoolExecutor
from common import *
from strengths import definitions,construct,selected_levels
from describe_strengths import describe
from proposals import command_signature
from classify import classify,INTENT_CHANGE_KEYS
from assess import assess,integrity
from events import response_reference
from temporal import event_relations
from ev_continuity import continuous_reference


def save_pair(path,pair):
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_name(path.name+'.tmp')
    temp.write_bytes(gzip.compress((canonical(pair)+'\n').encode(),compresslevel=6,mtime=0));temp.replace(path)


def signals(plan,w):
    result={}
    for d in w['parameter_pack']['devices']:
        if 'ac'not in d['types']:continue
        rows=[x for x in plan['controls']if x['kind']=='ac_setpoint'and x['asset_id']==d['asset_id']]
        channels={k:[]for k in('available','fan_mode','heat_sp','cool_sp')}
        for minute in range(-1440,4320,10):
            x=next((x for x in rows if x['start_min']<=minute<x['end_min']),None)
            for k,v in [('available',int(x is not None)),('fan_mode',x.get('fan_operating_mode',0)if x else 0),('heat_sp',x['heating_setpoint_C']if x else 5.),('cool_sp',x['cooling_setpoint_C']if x else 50.)]:channels[k].append(v)
        result[d['asset_id']]=channels
    return result


def attention(w,actual):
    result=[]
    for d in actual:
        for x in d['program_changes']+d['manual_operation_changes']:
            if abs(x['start_shift_minutes'])>w['role_policy']['service_policy']['reschedule_limit_min']:
                result.append({'code':'GIVEN_SCHEDULE_CHANGE_BOUND_EXCEEDED','controller_key':d['controller_key'],
                               'requested_change_min':x['start_shift_minutes']})
        if d['device_family']=='ac':
            for x in d['control_segments']:
                if not x['A']or not x['B']:continue
                delta=x['B']['cooling_setpoint_C']-x['A']['cooling_setpoint_C']
                if delta>w['role_policy']['thermal']['temporary_increase_C']:
                    result.append({'code':'GIVEN_COOLING_INCREASE_BOUND_EXCEEDED','asset_id':x['asset_id'],'requested_change_C':delta})
            result.append({'code':'HEATING_TOLERANCE_NOT_GIVEN','controller_key':d['controller_key'],
                           'cooling_tolerance_not_assumed_as_heating_tolerance':True})
    return result


def rebuild(w,old):
    defs=definitions(w,old);vectors=[];plans=[]
    for i in range(4):
        plan=construct(w,old,defs,i);bad=integrity(w,old,plan)
        if bad:raise ValueError('VECTOR_INTEGRITY:'+canonical({'vector':i,'errors':bad}))
        vectors.append({'input_vector_id':'vector_'+str(i),'device_grade_indices':selected_levels(defs,i),
                        'command_signature':command_signature(plan),'integrity_errors':bad})
        plans.append(plan)
    plan=plans[0];same=command_signature(plan)==command_signature(old['A'])
    oldsame=not old['classification']['actual_actions']['any_command_change']
    if same!=oldsame:raise ValueError('COMMAND_DIFFERENCE_STATUS_CHANGED;no_stronger_vector_retry_or_filler')
    requests,actual,changes=describe(w,old,plan,defs)
    oldintent=old['classification']['design_intent']
    for change in changes:
        tags=[x['variant_markers']for x in oldintent['action_designs']if x['device_family']==change['device_family']]
        if tags:change.update({k:v for tag in tags for k,v in tag.items()if k in INTENT_CHANGE_KEYS})
    q={'requested_mechanism':old['proposal']['requested_mechanism'],'realized_mechanism':'opportunity_multiaxis_state_requests',
       'input_design_assignment':copy.deepcopy(old['proposal']['input_design_assignment']),
       'source_B53_focus_VPP_event_id':old['proposal']['focus_VPP_event_id'],'focus_VPP_event_id':next(iter({x['selected_event_id']for x in changes}))if len({x['selected_event_id']for x in changes})==1 else None,'VPP_event_ids':[e['event_id']for e in old['VPP_events']],
       'source_B53_multi_event_policy':old['proposal']['multi_event_policy'],'multi_event_policy':{'selection':'per_device_eligible_input_opportunity','all_events_read_back':True,'combined_target_success_guaranteed':False},'changes':changes,
       'strength_schema':'eb.device_native_strength.v56','requested_device_strengths':requests,
       'actual_device_strengths':actual,'selected_input_vector':'vector_0',
       'candidate_input_vectors':vectors,'equivalent_input_vectors':[x['input_vector_id']for x in vectors if x['command_signature']==vectors[0]['command_signature']],
       'actual_unique_dose_count':len({x['command_signature']for x in vectors}),
       'actual_command_signature':vectors[0]['command_signature'],'same_command_as_A':same,
       'device_grades_independent_of_old_scalar_and_of_other_devices':True,
       'input_vector_is_not_overall_household_strength':True,
       'source_B53_proposal_sha256':digest(old['proposal']),
       'device_state_plans':[x['input_state_plan']for x in requests],'strength_display_schema':'eb.multiaxis_actual_strength.v56','overall_actual_grade':None,
       'actual_grades_from_executable_commands':[{'controller_key':x['controller_key'],'axes':x['actual_strength_axes'],'display':x['strength_presentation']}for x in actual],
       'portfolio_families':sorted({x['device_family']for x in changes if x['actual_command_changed']}),
       'requested_portfolio_families':sorted({x['device_family']for x in requests}),
       'policy_attention':attention(w,actual),'policy_attention_is_not_human_rejection':True,
       'human_acceptance':None,'automatic_execution_authorized':False,'LLM_call_occurred':False,
       'VPP_conditioned_generation':True,'selection_uses_physical_outcomes_or_acceptance':False,
       'source_device_and_task_identities_fixed':True,'phase_and_direction_replanned_from_A_state':True,
       'command_comparison_basis':'eb.executable_commands.v48;device_native_parameters_not_record_boundaries',
       'given_role_policy_sha256':w['role_policy']['policy_sha256']}
    p=copy.deepcopy(old);check=assess(w,old,plan);ev=continuous_reference(w,old,plan)
    p.update(B=plan,proposal=q,assessment_B=check,HVAC_signals_B=signals(plan,w),
             B_frozen_sha256=digest(plan),classification_only_update=False,
             VPP_response_reference=response_reference(w,old,plan,old['VPP_events'],check,ev),
             event_relations=event_relations(old,plan,old['VPP_events']))
    p['EV_continuous_reference']=ev
    p['classification']=classify(p,w)
    p['classification']['design_intent']['source_B53_design_intent']=copy.deepcopy(oldintent)
    for change in q['changes']:
        for key in INTENT_CHANGE_KEYS:change.pop(key,None)
    q['classification_record']='classification'
    return p


PARENT_ROWS={r['household_id']:r for r in read(PARENT_B/'PAIR_BINDINGS10000.json')['records']}

def one(job):
    row,run,sig=job;run=Path(run);hid=row['household_id'];output=run/'records'/(hid+'.json')
    if output.exists():return read(output)
    try:
        rounds=[];world=None;logs=[]
        for rr in row['rounds']:
            source=SOURCE_B/rr['path']
            if sha(source)!=rr['sha256']:raise ValueError('SOURCE_B53_PAIR_CHANGED')
            old=read(source)
            parentrow=next(r for r in PARENT_ROWS[hid]['rounds']if r['case_id']==old['case_id']);parentpath=PARENT_B/parentrow['path']
            if sha(parentpath)!=parentrow['sha256']:raise ValueError('PARENT_B55_CHANGED')
            parent=read(parentpath)
            if old['A']!=parent['A']or old['needs_A']!=parent['needs_A']:raise ValueError('PARENT_A46_MISMATCH')
            if world is None:
                wp=A_STAGE/old['A_source']['world_path']
                if sha(wp)!=old['A_source']['world_sha256']:raise ValueError('A46_WORLD_CHANGED')
                world=read(wp)
            p=rebuild(world,old)
            p.update(schema='eb.alternative_pair.v56',rules_sha256=sig,source_generation_rules_sha256=sig,
                source_B={'stage':SOURCE_B.name,'case_path':rr['path'],'case_sha256':rr['sha256'],
                          'seal_sha256':read(OUT/'INPUT_LOCK.json')['source_B_seal_sha256']},
                device_strength_rebuild={'input_stage':'B53','source_device_and_task_identities_preserved':True,'phase_and_direction_replanned':True,
                    'old_scalar_grade_used':False,'old_physical_or_human_outcomes_used':False,
                    'selected_vector_fixed_before_construction':0},
                selection_or_regeneration_based_on_B_outcome='none;source100_command_identical_cases_preserved;device_grades_fixed_before_B')
            p['revision_parent']={'stage':PARENT_B.name,'case_path':parentrow['path'],'case_sha256':parentrow['sha256'],'seal_sha256':read(OUT/'INPUT_LOCK.json')['parent_B_seal_sha256']}
            p.pop('material_revision',None);p.pop('pair_content_sha256',None);p['pair_content_sha256']=digest(p)
            path=run/'pairs'/hid/(p['date']+'.json.gz');save_pair(path,p)
            actual=p['classification']['actual_actions']
            rounds.append({'case_id':rr['case_id'],'date':rr['date'],'path':rel(path),'sha256':sha(path),
                'mechanism':p['proposal']['realized_mechanism'],'strength_schema':'eb.device_native_strength.v56',
                'given_constraints_feasible':p['assessment_B']['given_constraints_feasible'],
                'comparison_group':actual['comparison_group'],'classification_schema':p['classification']['schema'],
                'source_B53_sha256':rr['sha256']})
            logs.append({'case_id':rr['case_id'],'source_B53_sha256':rr['sha256'],
                'old_given_constraint_conflict':bool(old['assessment_B']['constraint_flags']),
                'new_given_constraint_conflict':bool(p['assessment_B']['constraint_flags']),
                'old_B_unchanged':old['B']==p['B'],
                'requested_device_strengths':p['proposal']['requested_device_strengths'],
                'candidate_input_vectors':p['proposal']['candidate_input_vectors'],
                'no_case_or_failure_filtered':True})
        result={'household_id':hid,'type':row['type'],'passed':True,'rounds':rounds,
                'source_B_record_sha256':digest(row),'A_record_sha256':row['A_record_sha256']}
        save(run/'revision_log'/(hid+'.json'),{'household_id':hid,'records':logs})
    except Exception as error:result={'household_id':hid,'type':row['type'],'passed':False,'error':str(error)}
    save(output,result);return result


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--workers',type=int,default=4);parser.add_argument('--limit',type=int,default=1000);args=parser.parse_args()
    verify_inputs();sig=rules_id();run=OUT/'runs'/sig[:16]
    if (OUT/'FINAL_SEAL.json').exists():raise ValueError('STAGE_ALREADY_SEALED')
    for p in list((OUT/'code').glob('*.py'))+[OUT/'GENERATION_RULES.json',OUT/'INPUT_LOCK.json',OUT/'EB_REFERENCES.json']:
        dest=run/'source_snapshot'/p.name;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(p,dest)
    rows=read(SOURCE_B/'PAIR_BINDINGS10000.json')['records'][:args.limit];records=[]
    save(run/'RUN.json',{'rules_sha256':sig,'source_A':A_STAGE.name,'source_B':SOURCE_B.name,
        'all10000_used_as_one_dataset':True,'old_scalar_grade_used':False,'selected_vector':0,'household_limit':args.limit})
    with ProcessPoolExecutor(max_workers=args.workers)as pool:
        for r in pool.map(one,[(r,str(run),sig)for r in rows]):
            records.append(r)
            if len(records)%50==0:print({'households':len(records),'errors':sum(not x['passed']for x in records)},flush=True)
    if rules_id()!=sig:raise ValueError('CODE_CHANGED_DURING_BUILD')
    errors=[r for r in records if not r['passed']];save(run/'BUILD_REVIEW.json',{'rules_sha256':sig,'households':len(records),'errors':errors})
    if errors:print(canonical(errors[:12]));raise SystemExit(2)
    if len(records)!=1000:print(canonical({'trial_households':len(records),'errors':0,'rules_sha256':sig}));return
    save(OUT/'PAIR_BINDINGS10000.json',{'schema':'eb.alternative_bindings.v56','rules_sha256':sig,
         'households':1000,'cases':10000,'records':records,'all10000_used_as_one_dataset':True,'source_B':SOURCE_B.name})
    ids={r['household_id']for r in read(MASTER/'SUBSET50.json')['records']};subset=[r for r in records if r['household_id']in ids]
    save(OUT/'SUBSET50.json',{'schema':'eb.alternative_subset.v56','records':subset,
         'type_counts':dict(collections.Counter(r['type']for r in subset)),'same_master_household_ids':True,
         'same_pairs_and_hashes':True,'separate_generation':False})
    print(canonical({'households':1000,'cases':10000,'errors':0,'rules_sha256':sig}))

if __name__=='__main__':main()
