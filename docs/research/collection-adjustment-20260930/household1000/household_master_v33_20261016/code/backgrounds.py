"""Construct readable, coherent fictional household support facts before A/B."""
import copy
from common import rank,digest


def build(w,selected,matching):
    w=copy.deepcopy(w);hid=w['household_id'];adults=[m for m in w['members']if m['age_years']>=18]
    minors=[m for m in w['members']if m['age_years']<18];young=[m for m in w['members']if m['age_years']<6]
    original=w['evidence_layer']['original_housing_facets'];configured=w['layout']['stock_reference_features']
    modifications=[{'field':k,'source_reference':v,'configured_reference':configured[k],
                    'reason':'explicit joint housing and service adaptation;source independent marginal is not the constructed dwelling'}
                   for k,v in original.items()if configured[k]!=v]
    support=[];guardian=None
    if not adults:
        oid=w['operating_context']['operators'][0]['operator_id']
        guardian={'person_id':oid,'resident':False,'relationship':'given nonresident adult guardian; exact kinship unobserved',
                  'residence':'nearby separate residence, outside target household count',
                  'presence_windows_min':[[420,480],[1080,1230]],
                  'responsibilities':['daily meal provision/support','household appliance handling','guardian role for decisions'],
                  'remote_contact':'reachable outside the two visits; remote availability is not physical presence',
                  'evidence_kind':'researcher_given_scenario_not_observed_guardianship'}
        support.append('未成年学生在家人提供的住所居住；非同住成年监护人每天早晚到访，负责生活支持和需要成人处理的电器操作。')
        for o in w['operating_context']['operators']:
            if o['operator_id']==oid:o.update(presence_windows_min=guardian['presence_windows_min'],care_scope='given daily guardian visits and separately reachable support; no resident invented')
    if young:
        care=w['care_contract'];provider=care['caregiver_id']
        support.append('幼儿在家期间按日程由同住成人或明确预约的照护者照看；工作时间不自动视为可照护时间。')
    if w['role_policy']['protected_services']:
        support.append('角色中需照顾的家庭成员及约定服务保留；不因年龄自动推定疾病或失能。')
    if not support:support.append('家务由日程中有空且具有操作权的家庭成员承担；未安排通用上门家务服务。')
    w['baseline_assistance_contract']={'enabled':False,'provider_id':None,'window_min':[],
        'authorization':'no generic external appliance-handling fallback; explicit guardian/care contracts are separate',
        'old_contract_sha256':digest(w.get('baseline_assistance_contract'))}
    for op in w['operating_context']['operators']:
        op.setdefault('presence_windows_min',None)
    if 'given_transport_contract'in w:
        t=w['given_transport_contract']
        t['parking_rights']='given exclusive reserved off-dwelling bay with independent supply; not inferred from H6 or property ownership'
        if not t['driver_is_resident']:
            t['external_driver_relationship']='given separately booked adult mobility-support provider; no resident licence inferred'
            support.append('驾车行程由另行预约的成年驾驶支持者执行；未将高龄住户自动设为驾驶员。')
    bridge=matching['historical_envelope_bridge_required']
    envelope={'mode':'explicit_refurbished_envelope_scenario'if bridge else'city_and_building_family_native_reference',
        'given_building_age_bin':configured['effective_building_epoch'],'native_parameter_year':selected['catalogue_reference_epoch'],
        'native_model_key':selected['model_key'],'source_native_sha256':selected['source_sha256'],
        'asbuilt_materials_recovered':False,'national_renovation_probability_estimated':False,
        'full_building_height_or_structural_engineering_reconstructed':False,
        'definition':'reference envelope renewal to the selected same-city/type construction; not a reconstruction of the old building'if bridge else
                     'native constructions used as explicit reference; inferred catalogue period is not proof of historic local compliance'}
    w['background_context']={'schema':'eb.master_household_background.v33','evidence_kind':'source_anchored_synthetic_reference',
        'household_id':hid,'living_arrangement':'guardian_supported_student_home'if not adults else'multigeneration_family'if w['G']>1 else'adult_household',
        'resident_ids':[m['member_id']for m in w['members']],'minor_ids':[m['member_id']for m in minors],
        'daily_support_explanation':support,'nonresident_guardian':guardian,'facility_adaptations':modifications,
        'care_support_contract':{'external_supervision_prebooked':bool(young),'bath_assistance_prebooked':bool(young),
            'home_provider_id':hid+':given_home_caregiver'if young else None,'bath_provider_id':hid+':given_bath_helper'if young else None,
            'provider_role':'given booked nonresident child-care support,not an extra resident'if young else None,
            'booking_scope':'dated home-supervision/bathing gaps identified from family commitments before appliance A/B',
            'additional_appliance_handling_authorized':False,'provider_cost_observed':False},
        'envelope_reference':envelope,'role_known_information_retained':True,
        'income_occupation_diagnoses_and_actual_preferences_imputed':False,
        'simulation_and_human_answers_used_to_choose_background':False}
    w['given_external_services']['baseline_appliance_handling']='none; no generic rescue service'
    if guardian:w['given_external_services']['nonresident_guardian']=guardian
    return w


def context_room_counts(w):
    hid=w['household_id'];q=w['layout']['shared_household_count_design']
    return {hid+f'-aux-{i:02}':1 if w['H6']<40 else 1+rank(hid,i,'neighbor-rooms-v33')%2 for i in range(1,q)}
