"""First-stage supervised-data handoff from verified saved case evidence.

No training prompt, model call, invented reason or acceptance inference.  The
role-play input is deliberately limited to the household, event, No-DR plan
and EB plan.  Simulation outcomes remain in the complete collected record.
"""
from copy import deepcopy
import math
from pathlib import Path
import re
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'realtime_pilot'))
from common import digest, file_hash
from planner_language import planner_household, VERSION as LANGUAGE_VERSION


def plan_pair(view):
    """Project the displayed schedule into two plans, without EP outcomes."""
    chart=view['schedule_chart']
    window={k:deepcopy(chart[k]) for k in ('start_h','end_h','event_start_h','event_end_h')}
    plans={
        'no_dr_plan':{'schedule_window':deepcopy(window),'devices':[]},
        'agent_plan':{'schedule_window':deepcopy(window),'devices':[]},
    }
    for row in chart['rows']:
        for source,name in (('original','no_dr_plan'),('proposal','agent_plan')):
            device={'device_id':row['device_id'],'schedule':[]}
            for span in row[source]:
                clean={k:deepcopy(span[k]) for k in ('start_h','end_h','end_status') if k in span}
                m=re.fullmatch(r'([\d.]+)℃( 待机)?',span['label'])
                if m:
                    clean['setpoint_c']=float(m[1])
                    clean['signal']='cooling_setpoint' if row['device_id']=='ac' else 'water_heater_setpoint'
                    if m[2]:clean['mode']='standby'
                else:
                    m=re.fullmatch(r'([\d.]+) kW',span['label'])
                    if not m:raise ValueError('Unrecognized timeline value: '+span['label'])
                    clean.update(power_kw=float(m[1]),signal='appliance_model_power')
                device['schedule'].append(clean)
            plans[name]['devices'].append(device)
    return plans


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
    event_condition={
        'simulation_date':s['simulation_start_date'],
        'season':deepcopy((s.get('questionnaire_context') or {}).get('season')),
        'event':deepcopy(s['event']),
        'tariff':deepcopy(s['tariff']),
    }
    plans=plan_pair(collected['shown_to_participant'])
    return {
        'schema_version':'eb.first_stage_supervision.v2','case_id':collected['questionnaire']['case_id'],
        'household_id':collected['questionnaire']['household_id'],
        'input':{
            'household_profile':{
                'household_answers':answers,
                'members':english.get('reported_members',[]),
                'unanswered_fields':unanswered,
            },
            'event_condition':event_condition,
            **plans,
        },
        'output':target,
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
            'plan_source':'saved participant_view schedule only; EP metrics and service outcomes excluded',
            'supplementary_policy':'Kept separately for later analysis; not automatically added to model input.',
            'selection_policy':'No filter on acceptance, savings, score or technical fallback.',
            'time_unit':'hours from simulation day 1 at 00:00; values above 24 refer to the following day',
            'quality_checks':{'source_links_verified':True,'human_target_complete':True,'paired_simulation_complete':True},
        },
    }
