"""First-stage supervised-data handoff from verified saved case evidence.

No training prompt, model call, invented reason or acceptance inference. Keep
all additional answers separately. The comparison uses only the saved
participant view, including its displayed precision and observation cutoffs.
"""
from copy import deepcopy
import json
import math
from pathlib import Path
import re
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'realtime_pilot'))
from common import digest, file_hash
from planner_language import planner_household, VERSION as LANGUAGE_VERSION


def clock_h(text):
    match=re.fullmatch(r'(当日|次日)?(\d{2}):(\d{2})',text)
    if not match:raise ValueError('Unknown clock text: '+text)
    day,h,m=match.groups()
    if int(m)>=60 or int(h)>24 or int(h)==24 and int(m)!=0:raise ValueError('Invalid clock')
    return (24 if day=='次日' else 0)+int(h)+int(m)/60


def measure(text):
    patterns=[(r'([\d.]+) 度','kWh'),(r'([\d.]+) 相对成本单位','normalized_cost'),(r'([\d.]+) kW','kW')]
    for pattern,unit in patterns:
        m=re.fullmatch(pattern,text)
        if m:return {'value':float(m[1]),'unit':unit}
    m=re.fullmatch(r'([\d.]+)—([\d.]+)℃',text)
    if m:return {'min':float(m[1]),'max':float(m[2]),'unit':'degC'}
    raise ValueError('Unrecognized displayed measurement; manual mapping required: '+text)


def metric_id(label):
    exact={'24小时用电量':'electricity_24h','24小时相对用电成本':'relative_cost_24h',
           '响应时段用电量':'event_electricity','响应时段平均功率':'event_mean_power',
           '响应时段居住区域室温':'event_room_temperature'}
    if label in exact:return exact[label],None
    m=re.fullmatch(r'(响应前室温|响应结束后室温)（(.+)—(.+)）',label)
    if m:return ('pre_event_room_temperature' if m[1]=='响应前室温' else 'post_event_room_temperature'),{'start_h':clock_h(m[2]),'end_h':clock_h(m[3])}
    raise ValueError('Unrecognized metric; manual mapping required: '+label)


def service(text):
    m=re.fullmatch(r'截至(.+)：(当天|次日)任务(已完成|未完成|尚未到截止时间)',text)
    if m:return {'observed_at_h':clock_h(m[1]),'task_day':1 if m[2]=='当天' else 2,
        'status':{'已完成':'completed','未完成':'not_completed','尚未到截止时间':'deadline_not_reached'}[m[3]]}
    m=re.fullmatch(r'(.+)—(.+)水箱温度 ([\d.]+)℃（平均）',text)
    if m:return {'start_h':clock_h(m[1]),'end_h':clock_h(m[2]),'mean_tank_temperature_c':float(m[3])}
    m=re.fullmatch(r'(.+)离家前电量 ([\d.]+)%（目标 ([\d.]+)%，(达到|未达到)）',text)
    if m:return {'departure_h':clock_h(m[1]),'charge_percent':float(m[2]),'target_percent':float(m[3]),'target_met':m[4]=='达到'}
    raise ValueError('Unrecognized displayed service result; manual mapping required: '+text)


def comparison(view):
    statistics={k:deepcopy(view['statistics_window'][k]) for k in ('start_sim_h','end_sim_h','duration_h','policy')}
    result={'statistics_window':statistics,'has_changes':view['has_changes'],'metrics':[],'device_timeline':[],'service_results':[]}
    for row in view['metrics']:
        name,interval=metric_id(row['label'])
        entry={'metric':name, 'baseline':measure(row['original']),'eb':measure(row['proposal'])}
        if interval:entry['interval']=interval
        result['metrics'].append(entry)
    chart=view['schedule_chart']
    result['timeline_window']={k:deepcopy(chart[k]) for k in ('start_h','end_h','event_start_h','event_end_h')}
    result['timeline_interpretation']='AC bars show cooling setpoints, not room temperatures. Water-heater temperature bars do not imply continuous power consumption. Power bars retain the displayed appliance model values.'
    for row in chart['rows']:
        device={'device_id':row['device_id'],'changed':row['changed'],'baseline':[],'eb':[]}
        for source,target in [('original','baseline'),('proposal','eb')]:
            for span in row[source]:
                clean={k:span[k] for k in ('start_h','end_h','end_status') if k in span}
                m=re.fullmatch(r'([\d.]+)℃( 待机)?',span['label'])
                if m:
                    clean['setpoint_c']=float(m[1]);clean['signal']='cooling_setpoint' if row['device_id']=='ac' else 'water_heater_setpoint'
                    if m[2]:clean['mode']='standby'
                else:
                    m=re.fullmatch(r'([\d.]+) kW',span['label'])
                    if not m:raise ValueError('Unrecognized timeline value: '+span['label'])
                    clean.update(power_kw=float(m[1]),signal='appliance_model_power')
                device[target].append(clean)
        result['device_timeline'].append(device)
    for row in view['service_rows']:
        result['service_results'].append({'device_id':row['device_id'],'baseline':service(row['original']),'eb':service(row['proposal'])})
    return result


def clean_case(records, collected):
    docs=records['documents'];request=docs['request.json'];source=docs['household_config.json']
    # This English copy is a new rendering, never represented as the actual
    # planner input of historical cases collected before English ingress.
    english=planner_household(source,request)
    answers={};unanswered={}
    for group in ('household_information','stated_attitudes'):
        for row in english['observable_profile'][group]:
            qid=row['question_id']
            if qid=='M_MEMBERS':continue
            if row['response_status']=='answered':
                answers[qid]={'question':row['question'],'answer':row['answer'],'selected_value':deepcopy(request['profile'][qid]['value'])}
            else:unanswered[qid]=row['response_status']
    supplemental={q['id']:deepcopy(docs['questionnaire_submission.json']['normalized_answers'][q['id']])
                  for q in request['questionnaire_snapshot'] if q.get('research_only') and q['id'] in docs['questionnaire_submission.json']['normalized_answers']}
    decision=docs['decision.json'];names=('score','comfort_score','energy_score','vpp_score')
    if decision['choice'] not in ('accept','reject'):raise ValueError('Missing human decision')
    if any(type(decision.get(k)) not in (int,float) or not math.isfinite(decision[k]) or not 1<=decision[k]<=5 for k in names):raise ValueError('Invalid or missing human score; do not fill it')
    if not isinstance(decision.get('comment'),str) or not decision['comment'].strip():raise ValueError('Missing human reason; do not invent it')
    if docs['outcome.json']['simulation_status']!='paired_energyplus_complete':raise ValueError('Incomplete paired simulation')
    target={'decision':decision['choice'],**{k:decision[k] for k in names},'comment':decision['comment']}
    s=request['scenario'];environment=s.get('environment') or {}
    context={'simulation_date':s['simulation_start_date'],'event':deepcopy(s['event']),
             'weather_station':{k:environment.get('weather',{}).get(k) for k in ('id','station_name','wmo')},
             'building':{k:environment.get('building',{}).get(k) for k in ('id','kind','floor','indoor_area_m2')},
             'tariff':deepcopy(s['tariff']), 'is_household_measurement':False}
    return {
        'schema_version':'eb.first_stage_supervision.v1','case_id':collected['questionnaire']['case_id'],
        'household_id':collected['questionnaire']['household_id'],
        'input':{'household_answers':answers,'members':english.get('reported_members',[]),
                 'unanswered_fields':unanswered,'comparison':comparison(collected['shown_to_participant'])},
        'target':target,
        'auxiliary':{'supplementary_answers':supplemental,'simulation_context':context},
        'provenance':{
            'source_collected_record_hash':digest(collected),
            'source_document_hashes':deepcopy(collected['provenance']['source_document_hashes']),
            'cleaner_sha256':file_hash(Path(__file__)), 'language_mapping_version':LANGUAGE_VERSION,
            'input_language':'English; city proper nouns retained in their original form',
            'target_comment_language':'zh','historical_source_rewritten':False,
            'questionnaire_version':collected['questionnaire']['questionnaire_version'],
            'questionnaire_hash':collected['questionnaire']['questionnaire_hash'],
            'target_source':decision['target_source'], 'stored_data_origin':collected['questionnaire']['data_origin'],
            'training_release':False, 'split_group':collected['questionnaire']['household_id'],
            'stage':'first_stage_data_handoff_not_training_messages',
            'comparison_source':'saved participant_view; displayed numeric precision preserved',
            'supplementary_policy':'Kept separately for later analysis; not automatically added to model input.',
            'selection_policy':'No filter on acceptance, savings, score or technical fallback.',
            'time_unit':'hours from simulation day 1 at 00:00; values above 24 refer to the following day',
            'quality_checks':{'source_links_verified':True,'human_target_complete':True,'paired_simulation_complete':True},
        },
    }
