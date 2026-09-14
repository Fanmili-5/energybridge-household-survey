"""Respondent-owned household configuration, never a fixed-household assignment.

Mirrors the aggregate household's downstream fields (appliances, calendar,
schedule, tags, prompts) while keeping real questionnaire evidence in native
observable onboarding. No synthetic members, scoring weights or class lookup.
"""
from copy import deepcopy
import json
from common import digest
from questionnaire_persona import visible_profile
from survey_time import clock_label

VERSION='eb.respondent_household.v1'


def occupancy_schedule(profile):
    """Existing study mapping, explicitly not a measured family calendar."""
    value=lambda key:profile[key]['value']
    day={'mostly_occupied':1,'sometimes_occupied':.5,'mostly_absent':0,'variable':.5}[value('B04')]
    evening={'mostly_home':1,'partly_home':.5,'mostly_away':0,'varies':.5}[value('F_EVENING')]
    size=value('B02')
    reported=profile.get('M_MEMBERS',{})
    actual_count=len(reported.get('value') or []) if reported.get('response_status')=='answered' else None
    return {'occupant_count':actual_count if size=='6_plus' and actual_count else 6 if size=='6_plus' else int(size),
            'hourly_fraction':[day if 8<=hour<18 else evening if 18<=hour<22 else 1 for hour in range(24)],
            'source_question_ids':['B02','B04','F_EVENING'],
            'interpretation':'study occupancy mapping; variable/partial maps to 0.5, unasked 22:00-08:00 uses study default 1, 6_plus to 6; not observed occupancy'}


def build_household_config(profile, questions, original, household_id, simulation_days=None):
    public=visible_profile(profile,questions)
    facts={};tags={};onboarding=[];sources={};reported_preferences={}
    # Attitudes first to keep all four even if a native memory view limits length.
    ordered=sorted(questions,key=lambda q:q['group']!='attitude')
    public_by_id={r['question_id']:r for group in ('household_information','stated_attitudes') for r in public[group]}
    for question in ordered:
        if question.get("research_only"):continue
        qid=question['id'];cell=deepcopy(profile[qid]);row=public_by_id[qid]
        if question['group']=='attitude':
            if cell['response_status']!='answered':raise ValueError('请填写：'+question['prompt'])
            tags[question['eb_dimension']]=cell['value']
            sources['tags.'+question['eb_dimension']]={'kind':'questionnaire','question_id':qid}
        elif question['group']=='stated_preference':
            reported_preferences[question['eb_dimension']]={**cell,'question_id':qid,'answer':row['answer']}
        else:facts[qid]=cell
        if cell['response_status']=='answered':
            values=cell['value'] if isinstance(cell['value'],list) else [cell['value']]
            onboarding.append({'id':qid,'question':question['prompt'],'answer':row['answer'],
                               'selected_option_ids':[str(v) for v in values]})
    appliances=deepcopy(original['eb_appliance_config'])
    for device,config in appliances.items():
        for key in config:sources[f'appliances.{device}.{key}']={'kind':'simulation_model','source':'pinned EB equipment defaults'}
    names={'water_heater':'electric_water_heater','ev':'home_ev'}
    for device in appliances:
        qdevice=names.get(device,device)
        sources[f'appliances.{device}.present']={'kind':'derived_questionnaire','question_ids':['B05','H_'+qdevice]} if device!='refrigerator' else {'kind':'study_scope','value':False}
        mapping={'ac':{'setpoint_preferred_min_c':'H_ac_temp','setpoint_preferred_max_c':'H_ac_temp'},
                 'water_heater':{'normal_start_h':'H_electric_water_heater','normal_end_h':'D_electric_water_heater'},
                 'ev':{'arrival_h':'H_home_ev','departure_h':'D_home_ev'}}.get(device,
                 {'preferred_h':'H_'+device,'earliest_h':'E_'+device,'latest_h':'D_'+device,'duration_h':'T_'+device})
        for field,qid in mapping.items():
            if appliances[device].get('present') and qid in facts and facts[qid]['response_status']=='answered':
                sources[f'appliances.{device}.{field}']={'kind':'questionnaire','question_id':qid}
                if field=='preferred_h' and appliances[device].get(field)!=original['devices'][qdevice]['start_h']:
                    sources[f'appliances.{device}.{field}']={'kind':'derived_questionnaire','question_ids':[qid,'E_'+qdevice,'D_'+qdevice],
                        'rule':'overnight_start_unwrap_v1','reported_clock_h':original['devices'][qdevice]['start_h'],
                        'projected_window_hour':appliances[device][field],'interpretation':'Add 24 only when the reported start belongs to the next day of an overnight task window; original answer remains unchanged.'}
    deadlines={}
    for device in ('washer','dishwasher','dryer'):
        record=original['devices'].get(device,{})
        if record.get('active'):
            day='次日' if record['deadline_h']<record['earliest_h'] else '当日'
            deadlines[device]=f"{day}{clock_label(record['deadline_h'])} 前完成；可开始时刻 {clock_label(record['earliest_h'])}；时长 {round(record['duration_h']*60)} 分钟"
    if simulation_days is None:
        from native_scenario import window
        simulation_days=window(original)['simulation_days']
    constraints={'appliance_deadlines':deadlines}
    if appliances['ev'].get('present'):constraints['next_departure_h']=appliances['ev']['departure_h']
    schedule=occupancy_schedule(profile)
    if profile.get('M_MEMBERS',{}).get('response_status')=='answered' and profile['B02']['value']=='6_plus':
        schedule['source_question_ids'].append('M_MEMBERS')
        schedule['interpretation']=schedule['interpretation'].replace('6_plus to 6','6_plus uses the reported member count')
    calendar={'schema_version':'household_calendar_v1','household_id':household_id,'source':'respondent_questionnaire_study_projection',
              'household_occupancy_hourly':[deepcopy(schedule['hourly_fraction']) for _ in range(simulation_days)],
              'days':[{'day':i,'summary':'家庭填报的常用设备时间和任务窗口；不是实测日程。','events':[],
                       'constraints':deepcopy(constraints)} for i in range(1,simulation_days+1)]}
    prompt='以下是一个真人代表全家的回答。按该家庭自己的事实与态度考虑安排；不属于预设家庭类别，不推断未填写的成员、评分权重或授权。\n'+json.dumps(public,ensure_ascii=False)
    result={'schema_version':VERSION,'id':household_id,'display_name':'本次填报家庭',
            'tags':tags,'preferences':{},'household_facts':facts,'appliances':appliances,
            'schedule':schedule,'calendar':calendar,'llm_prompts':{'agent_context':prompt},
            'onboarding':{'source':'household_representative_questionnaire','answers':onboarding},
            'observable_profile':public,'ordinary_plan':deepcopy(original['eb_ordinary_plan']),
            'field_sources':sources,'questionnaire_hash':digest(questions),'answers_hash':digest(profile),
            'meta':{'persona_type':'household_representative','preset_household_id':None,
                    'classification_used_for_configuration':False,'respondent_represents_entire_household':True,
                    'unmeasured':['member_personas','comfort_range','thermostat_change_tolerance_c','scoring_weights','acceptance_probability'],
                    'ac_semantics':'appliances preferred_min/max currently carry the usual P0 setpoint, not a reported acceptable range; do not project them into thermostat_flexibility onboarding'}}

    member_question=next((q for q in questions if q['type']=='member_list'),None)
    if member_question:
        from member_questionnaire import reported_members
        cell=profile[member_question['id']]
        result['reported_members']=reported_members(cell['value'],member_question) if cell['response_status']=='answered' else []
        result['schema_version']='eb.respondent_household.v2'
        result['reported_preferences']=reported_preferences
        for key,cell in reported_preferences.items():
            result['field_sources']['reported_preferences.'+key]={'kind':'questionnaire','question_id':cell['question_id']}
        # Literal preferences are visible to the planner, never hidden scoring policy.
        if reported_preferences.get('notice_required_h',{}).get('response_status')=='answered':
            result['preferences']['notice_required_h']=float(reported_preferences['notice_required_h']['value'])
            result['field_sources']['preferences.notice_required_h']={'kind':'questionnaire','question_id':'P_NOTICE'}
        for device,field,qid in [('ev','target_soc','P_EV_TARGET'),('ev','min_soc','P_EV_RESERVE'),('water_heater','bath_required_h','P_HOT_WATER')]:
            if profile.get(qid,{}).get('response_status')=='answered' and appliances[device].get('present'):
                result['field_sources'][f'appliances.{device}.{field}']={'kind':'questionnaire','question_id':qid}
        for dimension,field in [('preferred_room_temperature','comfort_range'),('temperature_change_tolerance','thermostat_change_tolerance_c')]:
            if reported_preferences.get(dimension,{}).get('response_status')=='answered':result['meta']['unmeasured'].remove(field)
        result['meta']['ac_semantics']='Usual thermostat setting defines P0; preferred room-temperature range and tolerated room-temperature change are separate direct answers in reported_preferences. Neither authorizes this event.'
        result['meta']['feedback_scope']='respondent_judgment_considering_household_needs'
        result['meta']['member_information_source']='household_representative_report'
        result['meta']['respondent_member_link_collected']=False
        result['field_sources']['reported_members']={'kind':'questionnaire','question_id':member_question['id']}
        for answer in result['onboarding']['answers']:
            if answer['id']==member_question['id']:answer['selected_option_ids']=[]
    return result


def ensure_household_config(request):
    from paired_contract import QUESTIONS
    household_id=request.get('household_id') or request.get('household_config',{}).get('id') or 'unidentified_local_fixture'
    expected=build_household_config(request['profile'],request.get('questionnaire_snapshot',QUESTIONS),request['original_plan'],household_id,
        simulation_days=request.get('scenario',{}).get('evaluation_window',{}).get('simulation_days',1))
    environment=request.get('scenario',{}).get('environment')
    if environment:
        expected['simulation_environment']=deepcopy(environment)
        text={'id':'SIMULATION_ENVIRONMENT','question':'本次研究仿真采用的环境（由系统匹配，不是用户实测事实）',
              'answer':{'city':environment['weather']['city'],'date':environment['simulation_start_date'],
                        'model_id':environment['building']['id'],'indoor_area_m2':environment['building']['indoor_area_m2'],
                        'assumptions':environment['assumptions'],'tariff_scope':environment['tariff_scope']},
              'source':'resolved_simulation_context'}
        expected['onboarding']['answers'].append({**text,'answer':json.dumps(text['answer'],ensure_ascii=False),'selected_option_ids':[]})
        expected['llm_prompts']['agent_context']+='\nSimulation environment (matched research assumptions): '+json.dumps(text['answer'],ensure_ascii=False)
        expected['field_sources']['simulation_environment']={'kind':'matched_research_environment',
            'environment_hash':environment['environment_hash']}
    config=request.get('household_config')
    if config is not None and digest(config)!=digest(expected):raise ValueError('Household configuration does not match questionnaire snapshot')
    request['household_config']=expected
    request['household_config_hash']=digest(expected)
    return expected


def bind_household(loop, request):
    """Enter EB through its observable profile, memory and calendar interfaces."""
    from eb_execution import upstream
    upstream()
    from energybridge.harness.memory_v3 import initialize_memory_v3
    from energybridge.harness.profile_v3 import initialize_household_model
    from energybridge.harness.operations_knowledge_v3 import initialize_operations_knowledge
    config=ensure_household_config(request)
    loop.household_config=deepcopy(config)
    loop.agent_preference_memory=initialize_memory_v3(config['onboarding'],household_id=config['id'])
    native_onboarding=deepcopy(config['onboarding'])
    # Only exact semantic aliases. Other qualitative answers remain literal
    # evidence for EB's own inference; no invented numerical comfort range.
    aliases={'confirm_required':'confirm_before_changes',
             'high_trust_auto':'automatic_optimization_ok'}
    mapping=[]
    for answer in native_onboarding['answers']:
        if answer['id']=='A_EB_CONTROL':
            for option in list(answer['selected_option_ids']):
                if option in aliases:
                    answer['selected_option_ids'].append(aliases[option])
                    mapping.append({'question_id':answer['id'],'reported_option':option,'native_option':aliases[option]})
    loop.agent_household_model=initialize_household_model(native_onboarding,
        household_id=config['id'],calendar=config['calendar'],devices=config['appliances'])
    loop.agent_operations_knowledge=initialize_operations_knowledge(config['appliances'])
    loop.agent_preference_memory['operations_knowledge']=deepcopy(loop.agent_operations_knowledge)
    loop.household_binding_audit={'native_onboarding':native_onboarding,'option_aliases':mapping,
        'inference_source':'pinned profile_v3.initialize_household_model',
        'unrecognised_answers':'retained literally; native uncertain traits are not forced'}
    # Keep literal respondent answers authoritative. Do not translate qualitative
    # choices into numeric tolerance options or synthesize inferred_profile.
    loop.agent_profile_capsule_by_event_id={request['scenario']['event']['id']:deepcopy(config['observable_profile'])}
    return config
