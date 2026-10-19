"""B58: all-controller A-operating opportunities, genuine effects and failures."""
import argparse,collections,shutil
from concurrent.futures import ProcessPoolExecutor
from common import *
from opportunities import catalogue,select,apply,all_definitions
from describe_strengths import describe
from proposals import command_signature
from classify import classify
from assess import assess,integrity
from events import response_reference
from temporal import event_relations
from ev_continuity import continuous_reference
from joint_nodes import reconcile
from scenarios import prepare as prepare_scene

def save_pair(path,p):
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_name(path.name+'.tmp');temp.write_bytes(gzip.compress((canonical(p)+'\n').encode(),compresslevel=6,mtime=0));temp.replace(path)

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

def retained_failure_plan(old):
    plan=copy.deepcopy(old['B']);removed=[]
    ev=old['EV_continuous_reference']
    if ev['status']!='not_installed'and all(ev['A'][k]==ev['B'][k]for k in('charging_steps','trips','end_energy_kWh')):
        removed=[x['need_id']for x in plan['controls']if x['kind']=='ev_charge_window'and x not in old['A']['controls']]
        plan['controls']=[x for x in plan['controls']if x['kind']!='ev_charge_window']+[copy.deepcopy(x)for x in old['A']['controls']if x['kind']=='ev_charge_window']
    return plan,sorted(set(removed))

def rebuild(w,old,ref,coverage,preserved):
    original=old
    same=old['case_id']in preserved['identical_case_ids'];failure=preserved['failure_cases'].get(old['case_id'])
    if not(same or failure):old,definitions,options=prepare_scene(w,old,ref,coverage)
    else:definitions,options=all_definitions(w,old),{}
    selected=[];source=copy.deepcopy(old);removed=[]
    if same:
        plan=copy.deepcopy(old['A']);defs={};ctx={};basis='user_fixed_identical_case'
    elif failure:
        plan,removed=retained_failure_plan(old)
        changed={x['asset_id']for key in('program_changes','manual_operation_changes','control_changes')for x in old['classification']['actual_actions'][key]}
        if removed:changed={x for x in changed if not any(x in d['asset_ids']and d['family']=='ev'for d in definitions.values())}
        defs={k:v for k,v in definitions.items()if set(v['asset_ids'])&changed}
        ctx={x['controller_key']:copy.deepcopy(x['input_state_plan'])for x in old['proposal']['requested_device_strengths']if x['controller_key']in defs}
        for request in old['proposal']['requested_device_strengths']:
            if request['controller_key']in defs:
                defs[request['controller_key']]['base_grade_index']=LEVELS.index(request['grade'])
        basis='preserved_existing_B_failure_not_success_filtered'
        for k,d in defs.items():
            coverage[k]=coverage.get(k,0)+1;coverage['family:'+d['family']]=coverage.get('family:'+d['family'],0)+1
    else:
        selected=select(old,definitions,options,coverage)
        if not selected:raise ValueError('NO_CAUSAL_REQUEST_OPPORTUNITY:'+old['case_id'])
        plan=copy.deepcopy(old['A']);defs={o['controller']['controller_key']:o['controller']for o in selected};ctx={o['controller']['controller_key']:o['context']for o in selected}
        for option in selected:apply(plan,old,option)
        basis='A_only_decision_scene_then_real_event_controller_coverage'
    plan['controls'].sort(key=lambda x:(x['start_min'],x['asset_id'],x['kind']))
    plan['changed_controls']=[] # Recomputed from executable commands below.
    from classify import control_differences
    plan['changed_controls']=control_differences(old['A'],plan)
    bad=integrity(w,old,plan)
    if bad:raise ValueError('INTEGRITY:'+canonical(bad))
    if(command_signature(plan)==command_signature(old['A']))!=same:raise ValueError('IDENTICAL100_MEMBERSHIP_CHANGED')
    source['_B58_contexts']=ctx
    requests,actual,changes=describe(w,source,plan,defs)
    for request in requests:
        if any(o['controller']['controller_key']==request['controller_key']and o['basis']=='exact_existing_life_node'for o in selected):
            request['nominal_grade_not_a_life_node_minute_limit']=True
            request['parameters']['VPP_only_program_shift_cap_min']=request['parameters'].pop('requested_shift_min')
            request['parameters']['life_node_request_bounds']='full original release/decision/loader/occupation/operator/retrieval/deadline window;nearest exact changed node;actual program and manual axes measured separately'
    if failure:
        prior_requests={x['controller_key']:x for x in old['proposal']['requested_device_strengths']}
        for request in requests:
            request['parameters']=copy.deepcopy(prior_requests[request['controller_key']]['parameters'])
            request['retained_B57_requested_dose_parameters']=True
    check=assess(w,old,plan);ev=continuous_reference(w,old,plan)
    # An EV request is not accepted as an effective input opportunity merely
    # because its nominal permission differs. A-only eligibility must have
    # caused a genuinely different continuous charging or readiness state.
    if any(d['family']=='ev'for d in defs.values())and not failure:
        if all(ev['A'][k]==ev['B'][k]for k in('charging_steps','trips','end_energy_kWh')):
            raise ValueError('EV_REQUEST_HAS_NO_CONTINUOUS_EFFECT')
    for ch in changes:
        if ch['behavior']=='opposing_request':ch['requested_reverse_variant']=True
    q={'requested_mechanism':'A_operating_opportunity_portfolio','realized_mechanism':'B60_real_operating_opportunities',
        'input_design_assignment':{'candidate_class':basis,'selection_used_B_results':False,
            'all_configured_controllers_examined':not(same or bool(failure)),
            'preserved_failure_is_explicit_fixed_stress_case':bool(failure)},
        'focus_VPP_event_id':changes[0]['selected_event_id']if changes and len({x['selected_event_id']for x in changes})==1 else None,
        'VPP_event_ids':[e['event_id']for e in old['VPP_events']],
        'multi_event_policy':{'selection':'each_eligible_controller_uses_its_real_A_opportunity',
            'all_events_read_back':True,'combined_target_success_guaranteed':False},
        'changes':changes,'strength_schema':'eb.device_native_strength.v60',
        'requested_device_strengths':requests,'actual_device_strengths':actual,
        'selected_input_vector':'fixed_before_B_execution','equivalent_input_vectors':['fixed_before_B_execution'],
        'actual_unique_dose_count':1,'actual_command_signature':command_signature(plan),'same_command_as_A':same,
        'portfolio_families':sorted({d['family']for d in defs.values()}),
        'requested_portfolio_families':sorted({d['family']for d in defs.values()}),
        'device_grades_independent_of_old_scalar_and_of_other_devices':True,
        'input_vector_is_not_overall_household_strength':True,'overall_actual_grade':None,
        'device_state_plans':[x['input_state_plan']for x in requests],
        'strength_display_schema':'eb.multiaxis_actual_strength.v60',
        'actual_grades_from_executable_commands':[{'controller_key':x['controller_key'],'axes':x['actual_strength_axes'],'display':x['strength_presentation']}for x in actual],
        'human_acceptance':None,'automatic_execution_authorized':False,'LLM_call_occurred':False,
        'selection_uses_physical_B_outcomes_or_acceptance':False,'VPP_conditioned_generation':True,
        'given_role_policy_sha256':w['role_policy']['policy_sha256']}
    p=copy.deepcopy(old)
    for key in('original_schedule_generation','device_strength_rebuild','semantic_finalization','source_B'):p.pop(key,None)
    p.update(schema='eb.alternative_pair.v60',B=plan,proposal=q,assessment_B=check,
        EV_continuous_reference=ev,HVAC_signals_B=signals(plan,w),B_frozen_sha256=digest(plan),
        VPP_response_reference=response_reference(w,old,plan,old['VPP_events'],check,ev),
        event_relations=event_relations(old,plan,old['VPP_events']),classification_only_update=False,
        opportunity_generation={'schema':'eb.real_operating_opportunity.v60','basis':basis,
            'A_operating_reference':{'path':ref['_path'],'sha256':ref['_sha256']},
            'eligible_controllers':{k:{'family':definitions[k]['family'],'candidate_count':len(v)}for k,v in options.items()},
            'selected_requests':[{'controller_key':o['controller']['controller_key'],'family':o['controller']['family'],
                'event_id':o['event']['event_id'],'basis':o['basis'],'behavior':o['behavior'],'evidence':o['evidence']}for o in selected],
            'preserved_failure':failure,'inactive_EV_permission_changes_removed':removed,
            'net_energy_or_B_success_selection':False,'no_extra_plug_unplug_or_household_visit':True})
    p['classification']=classify(p,w);p['classification']['schema']='eb.B_classification.v60'
    p['joint_node_review']=reconcile(p)
    # Old result placeholders are not silently promoted to B58 results.
    p['physical_results']={'status':'pending_B60_EnergyPlus','human_acceptance':None}
    p['selection_or_regeneration_based_on_B_outcome']='none;original_failure_cases_preserved_as_fixed_stress_inputs;new_requests_from_A_only'
    assert p['A']==original['A']and p['needs_A']==original['needs_A']and p['needs_B']==original['needs_B']
    return p

def one(job):
    row,run,sig=job;run=Path(run);hid=row['household_id'];target=run/'records'/(hid+'.json')
    if target.exists():
        prior=read(target)
        if prior['passed']:return prior
    frozen=read(OUT/'PRESERVED_CASES.json');world=None;rounds=[];coverage={};audits=[]
    try:
        # Dates stay fixed. Ordering uses only saved dates and household ID,
        # so the least-covered controller design cannot depend on B outcomes.
        for rr in sorted(row['rounds'],key=lambda x:x['date']):
            source=PARENT_B/rr['path'];assert sha(source)==rr['sha256'];old=read(source)
            if world is None:
                wp=A_STAGE/old['A_source']['world_path'];assert sha(wp)==old['A_source']['world_sha256'];world=read(wp)
                assert sha(A_STAGE/old['A_source']['annual_A_path'])==old['A_source']['annual_A_sha256']
            rp=OUT/'A_reference/records'/hid/(old['date']+'.json.gz');ref=read(rp);ref.update(_path=str(rp.relative_to(OUT)),_sha256=sha(rp))
            assert ref['case_id']==old['case_id']and ref['B_results_or_human_labels_read']is False
            assert ref['A_schedule_sha256']==digest({k:old['A'][k]for k in('tasks','operations','controls')})
            p=rebuild(world,old,ref,coverage,frozen)
            p.update(rules_sha256=sig,source_generation_rules_sha256=sig,
                revision_parent={'stage':PARENT_B.name,'case_path':rr['path'],'case_sha256':rr['sha256'],
                    'seal_sha256':read(OUT/'INPUT_LOCK.json')['parent_B_seal_sha256']})
            p.pop('pair_content_sha256',None);p['pair_content_sha256']=digest(p)
            path=run/'pairs'/hid/(p['date']+'.json.gz');save_pair(path,p)
            rounds.append({'case_id':p['case_id'],'date':p['date'],'path':rel(path),'sha256':sha(path),
                'mechanism':p['proposal']['realized_mechanism'],'strength_schema':p['proposal']['strength_schema'],
                'given_constraints_feasible':p['assessment_B']['given_constraints_feasible'],
                'comparison_group':p['classification']['actual_actions']['comparison_group'],
                'classification_schema':p['classification']['schema'],'parent_B57_sha256':rr['sha256']})
            audits.append({'case_id':p['case_id'],'families':p['proposal']['portfolio_families'],
                'same':p['proposal']['same_command_as_A'],'constraint_flags':p['assessment_B']['constraint_flags'],
                'opportunity':p['opportunity_generation']})
        order={x['case_id']:i for i,x in enumerate(row['rounds'])};rounds.sort(key=lambda x:order[x['case_id']])
        result={**row,'passed':True,'rounds':rounds};save(run/'opportunity_audits'/(hid+'.json'),{'household_id':hid,'coverage':coverage,'cases':audits})
    except Exception as exc:
        import traceback
        result={'household_id':hid,'type':row['type'],'passed':False,'error':str(exc),'traceback':traceback.format_exc()}
    save(target,result);return result

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--workers',type=int,default=4);parser.add_argument('--limit',type=int,default=1000);parser.add_argument('--household');args=parser.parse_args()
    verify_inputs();sig=rules_id();run=OUT/'runs'/sig[:16]
    if(OUT/'FINAL_SEAL.json').exists():raise ValueError('ALREADY_SEALED')
    for f in list((OUT/'code').glob('*.py'))+[OUT/'INPUT_LOCK.json',OUT/'GENERATION_RULES.json',OUT/'PRESERVED_CASES.json']:
        dst=run/'source_snapshot'/f.name;dst.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(f,dst)
    rows=read(PARENT_B/'PAIR_BINDINGS10000.json')['records']
    if args.household:rows=[r for r in rows if r['household_id']==args.household]
    rows=rows[:args.limit];results=[]
    with ProcessPoolExecutor(max_workers=args.workers)as pool:
        for r in pool.map(one,[(r,str(run),sig)for r in rows]):
            results.append(r)
            if len(results)%25==0 or not r['passed']:print(canonical({'households':len(results),'errors':sum(not x['passed']for x in results),'last_error':r.get('error')}),flush=True)
    assert rules_id()==sig
    errors=[x for x in results if not x['passed']];save(run/'BUILD_REVIEW.json',{'rules_sha256':sig,'households':len(results),'errors':errors})
    if errors:print(canonical(errors[:5]));raise SystemExit(2)
    if len(results)!=1000:print(canonical({'trial_households':len(results),'rules_sha256':sig}));return
    assert sum(x['comparison_group']=='identical_commands'for r in results for x in r['rounds'])==100
    save(OUT/'PAIR_BINDINGS10000.json',{'schema':'eb.alternative_bindings.v60','rules_sha256':sig,'households':1000,'cases':10000,'records':results,'all10000_used_as_one_dataset':True,'source_B':PARENT_B.name})
    ids={r['household_id']for r in read(PARENT_B/'SUBSET50.json')['records']};subset=[r for r in results if r['household_id']in ids]
    save(OUT/'SUBSET50.json',{'schema':'eb.alternative_subset.v60','records':subset,'type_counts':dict(collections.Counter(r['type']for r in subset)),'same_pairs_and_hashes':True,'separate_generation':False})
    save(OUT/'COLLECTION_SCOPE.json',{'source_households':1000,'source_cases':10000,'subset50_ids':sorted(ids),
        'additional950_ids':sorted({r['household_id']for r in results}-ids),'overlap':[],
        'prior_answers_copied_to_B58':False,'old50_release_preserved_as_separate_version':True})
    print(canonical({'households':1000,'cases':10000,'identical':100,'rules_sha256':sig}))

if __name__=='__main__':main()
