"""Versioned original50 regeneration. Preserve household facts, assets and dates."""
import copy,collections,datetime as dt
from common import *
from activity_model import dated,ranges
from type_model import candidates,allocate,build_policy,SEED
merge_ranges=ranges


def build(src,typ):
    w=copy.deepcopy(src);old=w.pop('world_content_sha256');hid=w['household_id']
    w['source_V23_world_content_sha256']=old
    w['eb_reference_type_assignment']=typ
    w['role_policy']=build_policy(w,typ)
    policy=w['role_policy'];subject=next(m for m in w['members']if m['member_id']==policy['schedule_subject_id'])
    oldroles={m['member_id']:m['reference_activity_role']for m in w['members']}
    if typ in ('A','D','F'):subject['reference_activity_role']='commuter_reference'
    elif typ=='B':subject['reference_activity_role']=('home_work_reference'if subject['age_years']<75 else 'given_short_work_reference')if subject['employment_status']=='has_work'else 'home_commitments_reference'
    elif typ=='C':
        if subject['age_years']>=18:
            subject['reference_activity_role']=('given_variable_short_work_reference'if subject['age_years']>=75 else 'given_variable_work_reference')if subject['employment_status']=='has_work'else 'given_variable_nonwork_reference'
    elif typ=='E':
        subject['reference_activity_role']=('home_work_reference'if subject['age_years']<75 else 'given_short_work_reference')if subject['employment_status']=='has_work'else 'given_home_care_reference'
        under6=[p['person_id']for p in policy['protected_services']if next(m for m in w['members']if m['member_id']==p['person_id'])['age_years']<6]
        if under6:
            w['care_contract']['caregiver_id']=subject['member_id'];w['care_contract']['caregiver_is_resident']=True
            w['care_contract']['home_care_child_ids']=under6
    subject['activity_scenario_evidence']='explicit V27 EB-adapted reference activity within source eligibility;not observed location or occupation'
    w['activity_contract']['cooling_reference_modes'].update(awake_setpoint_C=policy['thermal']['usual_setpoint_C'],sleep_setpoint_C=policy['thermal']['usual_setpoint_C'])
    w['activity_contract']['role_policy_sha256']=policy['policy_sha256']
    for d in w['parameter_pack']['devices']:
        if 'ac'in d['types']:d['reference_upper_setpoint_C']=policy['thermal']['absolute_upper_control_C']
    if typ=='F':
        tc=w['given_transport_contract'];tc.update(driver_id=subject['member_id'],driver_is_resident=True,
            travelling_member_id=subject['member_id'],handling_operator_id=subject['member_id'],
            mode='given_resident_driver',reference_driving_authorization='explicit given reference;source licence unknown')
        ev=next(d for d in w['parameter_pack']['devices']if 'ev'in d['types']);ev['operator_id']=subject['member_id']
        tc['connection_access_contract']={'place':ev['room_id'],'access':'existing given dedicated parking/charger resource',
            'access_is_observed':False,'authority':'given household access and connection handling','outside_departure_windows_connected':False}
        w['given_external_services']['transport_driver']=copy.deepcopy(tc)
    w['parameter_pack_sha256']=digest(w['parameter_pack'])
    w['service_semantics']['mandatory_services']['cooling']='given role-specific occupied/sleeping control;not calibrated personal comfort'
    w['service_semantics']['negotiable_conditions']['role_policy']=copy.deepcopy(policy)
    w['type_generation_evidence']={'source_roster_housing_dates':'matched existing reference;unchanged',
        'work_status':'preserved coarsened source proxy;unknown unchanged',
        'activity_before':oldroles,'activity_after':'given EB-adapted reference within support',
        'subjective_preferences':'researcher_given policy;source unknown remains unknown',
        'care':'age supports only candidate;actual protected checks and authority explicitly given',
        'EV_access_and_licence':'benchmark given resource;not observed ownership or licence',
        'hardware_parameters':'unchanged EB engineering inputs;only usage/operator/reference-bound metadata changed',
        'sources':'type_composition_evidence_20261014/SOURCE_LEDGER.json and pinned EB_TYPE_REFERENCE.json',
        'seed':SEED}
    # Dated reads need the final policy-sensitive world signature, never a stale
    # V23 cache key. Build exemplars, then seal their serialized content.
    w['world_content_sha256']=digest(w)
    example=[dated(w,dt.date(2025,2,17)+dt.timedelta(days=i))for i in range(7)]
    for m in w['members']:
        mid=m['member_id'];m['weekly_calendar']=[{'weekday':i,'example_date':x['date'],'day_type':x['day_type'],'intervals':x['member_calendars'][mid]}for i,x in enumerate(example)]
        m['daily_reference_specs']=[{'weekday':i,'example_date':x['date'],**x['member_specs'][mid]}for i,x in enumerate(example)]
    for o in w['operating_context']['operators']:o['weekly_windows_min']={str(i):x['operator_windows_min'][o['operator_id']]for i,x in enumerate(example)}
    w['routine']['weekly_family_context']=[{'weekday':i,'example_date':x['date'],**x['family_context']}for i,x in enumerate(example)]
    w['schema']='eb.type_aware_reference_world.v27';w.pop('world_content_sha256');w['world_content_sha256']=digest(w)
    return w


def main():
    school_guard();source=read(SOURCE/'SELECTION50.json');original=read(PILOT/'SELECTION50.json')
    assert {h['household_id']for h in source['records']}=={h['household_id']for h in original['records']}
    worlds=[read(SOURCE/h['world_path'])for h in source['records']]
    for w,h in zip(worlds,source['records']):assert sha(SOURCE/h['world_path'])==h['world_sha256']
    assignment,report=allocate(worlds,minimum=5)
    records=[]
    for src,h in zip(worlds,source['records']):
        w=build(src,assignment[src['household_id']]);path=OUT/'worlds'/f'{w["household_id"]}.json';save(path,w)
        for k in ('N','G','H6','H7','province','population_weight','ego_relationships','random10_date_selection','layout'):assert w[k]==src[k]
        for a,b in zip(w['members'],src['members']):
            for k in ('member_id','age_years','sex','employment_status','employment_evidence','generation_level','ego_relation_code'):assert a[k]==b[k]
        for a,b in zip(w['parameter_pack']['devices'],src['parameter_pack']['devices']):assert a['parameters']==b['parameters']and a['types']==b['types']
        records.append({**{k:copy.deepcopy(v)for k,v in h.items()if k!='rounds'},
            'world_path':str(path.relative_to(OUT)),'world_sha256':sha(path),'parameter_pack_sha256':w['parameter_pack_sha256'],
            'source_V23_world_sha256':h['world_sha256']})
    save(OUT/'WORLD_BINDINGS50.json',{'households':50,'records':records})
    save(OUT/'TYPE_ASSIGNMENT50.json',{'assignment':assignment,'report':report,'source_selection_sha256':sha(SOURCE/'SELECTION50.json')})
    save(OUT/'PROTOCOL.json',{'schema':'eb.type_pilot_protocol.v27','households':50,'dates_per_household':10,
        'source':SOURCE.name,'seed':SEED,'policy_before_calendar_and_A':True,'human_answers':0,'full1000_EP_allowed':False})
    save(OUT/'WORLD_BUILD_REVIEW.json',{'households':50,'members':sum(w['N']for w in worlds),'type_assignment':report,
        'original_ids_rosters_housing_dates_and_EB_hardware_preserved':True,'source_preferences_measured':False,'full1000_EP_allowed':False})
    print(report,flush=True)


if __name__=='__main__':main()
