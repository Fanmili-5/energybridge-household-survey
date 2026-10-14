"""Independent source, policy, calendar, normal-service and evidence gates."""
import collections,copy,datetime as dt,math,statistics
from common import *
from checks import assess
from execution import realize
from type_model import TYPES,candidates,permission_audit

FEATURE_GROUPS={
 'schedule':['daytime_home_fraction','workday_departure_variation'],
 'comfort':['temporary_cooling_delta','maximum_change_duration'],
 'task':['allowed_reschedule_fraction'],
 'price':['cost_priority','saving_explanation_required'],
 'control':['automatic_within_bounds','same_day_confirmation','protected_service_veto'],
 'service_resource':['booked_protection_load','mobility_priority_with_actual_trips']}


def extract(w,pairs):
    """Read actual dated outputs/needs and explicit policy;never a type string."""
    policy=w['role_policy'];subject=policy['schedule_subject_id'];values=[];departures=[];arrivals=[];care=[];trip_days=0
    for pair in pairs:
        day=pair['dated_activity_days'][0];cal=day['member_calendars'][subject]
        if day['day_type']in ('weekday','makeup_workday'):
            values.append(sum(max(0,min(i['end_min'],1080)-max(i['start_min'],480))for i in cal if i['location']=='home')/600)
            dep=day['member_specs'][subject]['departure_min']
            if dep is not None:departures.append(dep)
            arr=day['member_specs'][subject]['arrival_min']
            if arr is not None:arrivals.append(arr)
        care.append(sum(e['end_min']-e['start_min']for e in day['protected_service_ledger']))
        trip_days+=any(n['kind']=='ev'and 480<=n['release_min']<1920 for n in pair['needs_A'])
    if not values:raise RuntimeError('no workday calendar for features')
    return {'daytime_home_fraction':sum(values)/len(values),
        'workday_departure_variation':min(1.,max(statistics.pstdev(departures)if len(departures)>1 else 0.,statistics.pstdev(arrivals)if len(arrivals)>1 else 0.)/60),
        'temporary_cooling_delta':policy['thermal']['temporary_increase_C']/2,
        'maximum_change_duration':policy['thermal']['maximum_change_duration_min']/60,
        'allowed_reschedule_fraction':policy['service_policy']['reschedule_limit_min']/210,
        'cost_priority':int(policy['economics']['cost_priority_given']),
        'saving_explanation_required':int(policy['economics']['explanation_before_agreement']),
        'automatic_within_bounds':int(policy['permissions']['automatic_within_declared_bounds']),
        'same_day_confirmation':int(policy['permissions']['same_day_reconfirmation']),
        'protected_service_veto':int(policy['permissions']['protected_service_veto']),
        'booked_protection_load':min(1.,sum(care)/len(care)/20),
        'mobility_priority_with_actual_trips':int(policy['service_policy']['mobility_service_first']) * min(1.,trip_days/3)}


def audit():
    school_guard();selection=read(OUT/'SELECTION50.json');original=read(SOURCE/'SELECTION50.json');idx={h['household_id']:h for h in original['records']}
    assert len(selection['records'])==50 and set(idx)=={h['household_id']for h in selection['records']}
    errors=[];counts=collections.Counter();evidence=[];features=[];group=collections.defaultdict(list)
    for h in selection['records']:
        w=read(OUT/h['world_path']);src=read(SOURCE/idx[h['household_id']]['world_path']);typ=w['eb_reference_type_assignment'];policy=w['role_policy']
        assert sha(SOURCE/idx[h['household_id']]['world_path'])==idx[h['household_id']]['world_sha256']
        local=[]
        if sha(OUT/h['world_path'])!=h['world_sha256']or digest({k:v for k,v in w.items()if k!='world_content_sha256'})!=w['world_content_sha256']:local.append('WORLD_BINDING')
        if digest(policy_without_hash:={k:v for k,v in policy.items()if k!='policy_sha256'})!=policy['policy_sha256']:local.append('POLICY_BINDING')
        if not candidates(src)['allowed'][typ]:local.append('TYPE_SOURCE_SUPPORT')
        for k in ('N','G','H6','H7','province','population_weight','layout','random10_date_selection','ego_relationships'):
            if w[k]!=src[k]:local.append('SOURCE_STRUCTURE_CHANGED:'+k)
        for m,old in zip(w['members'],src['members']):
            for k in ('age_years','member_id','employment_status','employment_evidence','current_work_source_proxy','sex','generation_level','ego_relation_code'):
                if m[k]!=old[k]:local.append('SOURCE_MEMBER_CHANGED:'+k)
            counts['unknown_employment_members']+=m['employment_status']=='unknown'
            counts['members']+=1
        if any(a['parameters']!=b['parameters']or a['types']!=b['types']for a,b in zip(w['parameter_pack']['devices'],src['parameter_pack']['devices'])):local.append('EB_HARDWARE_CHANGED')
        if policy['unmeasured_source_preferences']is not None or policy['human_acceptance_or_rejection']is not None:local.append('FABRICATED_OBSERVED_PREFERENCE')
        pairs=[]
        if [(r['round_index'],r['date'])for r in h['rounds']]!=[(r['round_index'],r['date'])for r in idx[h['household_id']]['rounds']]:local.append('ORIGINAL_DATE_CHANGED')
        for row in h['rounds']:
            p=read(OUT/row['pair_path']);pairs.append(p);counts['pairs']+=1
            if sha(OUT/row['pair_path'])!=row['pair_sha256']or p['world_sha256']!=w['world_content_sha256']:local.append('PAIR_BINDING')
            aa=assess(p)
            if aa['integrity_errors']or aa['constraint_flags']['A']:local.append('PAIR_INTEGRITY_OR_NORMAL_A_CONFLICT')
            if p['needs_A']!=p['needs_B']or p['A']==p['B']:local.append('COMMON_NEEDS_OR_IDENTICAL_AB')
            if p['given_role_policy_sha256']!=policy['policy_sha256']or p['policy_assessment']!=permission_audit(w,p):local.append('POLICY_NOT_CONSUMED')
            for n in p['needs_A']:
                if n['kind']=='ac'and n['reference_setpoint_C']!=policy['thermal']['usual_setpoint_C']:local.append('UNIFORM_TEMPERATURE_REGRESSION')
                if n['kind']in ('washer','dishwasher'):
                    if n['deadline_uses_operator_availability']is not False or n['subjective_importance']is not None or n['willingness_to_change_bound']is not None:local.append('SERVICE_SOURCE_CONFLATION')
                    if n['given_policy_sha256']!=policy['policy_sha256']:local.append('SERVICE_POLICY_BINDING')
            for side in ('A','B'):
                ex=realize(w,p[side],p['world']['operator_windows'],p['needs_A'])
                if ex!=p['service_execution_reference'][side]:local.append('EXECUTION_LEDGER_BINDING')
                counts[side+'_undelivered_programs']+=sum(not x['delivered_before_given_bound']for x in ex['program_services'])
                counts[side+'_failed_operations']+=sum(not x['succeeded']for x in ex['operations'])
                counts[side+'_care_gap_slots']+=len(p['post_operation_care'][side])
            if any(not x['delivered_before_given_bound']for x in p['service_execution_reference']['A']['program_services']):local.append('A_UNDELIVERED')
            if any(not x['succeeded']for x in p['service_execution_reference']['A']['operations'])or p['post_operation_care']['A']:local.append('A_OPERATION_OR_CARE_FAILURE')
            counts['B_given_policy_exceeded_or_confirmation_cases']+=bool(p['policy_assessment']['issues'])
            for day in p['dated_activity_days']:
                if typ=='E'and len(day['protected_service_ledger'])!=2:local.append('E_NO_ACTUAL_PROTECTION')
                for item in day['protected_service_ledger']:
                    spans=[i for i in day['member_calendars'][item['responsible_person_id']]if overlap((i['start_min'],i['end_min']),(item['start_min'],item['end_min']))]
                    if any(i['activity']!='given_protected_service_check'or i['room_id']!=item['room_id']for i in spans):local.append('CARE_CHECK_NOT_IN_CALENDAR')
            broken=copy.deepcopy(p)
            if broken['needs_B']:broken['needs_B'][0]['quantity']+=1
            else:broken['needs_B'].append({'kind':'negative_control_only','quantity':1})
            if 'NEEDS_CHANGED'not in assess(broken)['integrity_errors']:local.append('NEED_TAMPER_NOT_DETECTED')
        if typ=='F'and not any(n['kind']=='ev'and n['given_mobility_priority']for p in pairs for n in p['needs_A']):local.append('F_NO_ACTUAL_MOBILITY')
        f=extract(w,pairs);swapped=copy.deepcopy(w);swapped['eb_reference_type_assignment']='deliberately_invalid';swapped['household_id']='irrelevant_display_id'
        if extract(swapped,pairs)!=f:local.append('FEATURE_LABEL_OR_ID_LEAKAGE')
        altered=copy.deepcopy(pairs)
        for p in altered:p['human_adoption']=True;p['human_relative_preference']=0
        if extract(w,altered)!=f:local.append('FEATURE_ANSWER_LEAKAGE')
        features.append({'household_id':w['household_id'],'features':f,'derived_from':{'world_sha256':h['world_sha256'],'policy_sha256':policy['policy_sha256'],'pair_sha256':[r['pair_sha256']for r in h['rounds']]}})
        group[typ].append(f);counts['households']+=1
        evidence.append({'household_id':w['household_id'],'type':typ,'source_structure':'matched audited census/CHFS-derived reference;not an observed household',
            'exact_age':'inferred/projected within declared source constraints;unchanged','employment':'matched source proxy or unknown;unchanged',
            'schedule_and_protected_services':'researcher_given conditional on source structure;actual calendar verified',
            'hardware_access':'researcher_given EB resources;engineering parameters retained','policy':'researcher_given;source preference unknown',
            'holder_resident':policy['holder']['resident'],'policy_sha256':policy['policy_sha256'],'failures':sorted(set(local))})
        if local:errors.append({'household_id':w['household_id'],'errors':sorted(set(local))})
    variations={t:len({canonical(x)for x in fs})for t,fs in group.items()}
    if any(v<2 for v in variations.values()):errors.append({'error':'NO_WITHIN_TYPE_VARIATION','counts':variations})
    save(OUT/'FIELD_EVIDENCE50.json',{'records':evidence,'source_preferences_observed':False,'human_answers':0})
    save(OUT/'ACTUAL_FEATURES50.json',{'feature_groups':FEATURE_GROUPS,'rows':features,'forbidden_fields_used':False,'source':'actual dated calendars,services and explicit role contracts;not assigned type codes'})
    report={'schema':'eb.type_pilot_input_audit.v27','status':'pass'if not errors else 'fail','counts':dict(counts),'failures':errors,
        'actual_type_counts':{t:len(group[t])for t in TYPES},'distinct_actual_feature_rows_within_type':variations,
        'matched_source_structure_unchanged':not errors,'role_policies_are_given_not_observed':True,
        'source_data_does_not_identify_six_type_prevalence':True,'negative_controls':['changed need detected','type and ID changes leave extracted features unchanged','human answers leave extracted features unchanged'],
        'human_answers':0,'full1000_EP_allowed':False}
    save(OUT/'INPUT_AUDIT.json',report);print(report,flush=True)
    if errors:raise RuntimeError('type pilot input audit failed')


if __name__=='__main__':audit()
