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


# Stable, semantic feature names for the supervised model input.  Questionnaire
# IDs and wording remain in the source records/provenance; the model sees the
# reported result under a meaningful English key, not the question it answered.
HOUSEHOLD_FIELDS = {
    'B02':'household_size',
    'B04':'daytime_occupancy',
    'B05':'included_appliances',
    'F_EVENING':'evening_occupancy',
    'F_REGULARITY':'routine_regularity',
    'F_LATE_USE':'late_night_appliance_use',
    'F_ROUTINES':'protected_household_routines',
    'H_ac':'air_conditioner_usual_period',
    'H_ac_start':'air_conditioner_start_time',
    'H_ac_end':'air_conditioner_end_time',
    'H_ac_temp':'air_conditioner_setpoint',
    'H_washer':'washing_machine_usual_start_time',
    'D_washer':'washing_machine_deadline',
    'E_washer':'washing_machine_earliest_start_time',
    'T_washer':'washing_machine_duration',
    'H_dishwasher':'dishwasher_usual_start_time',
    'D_dishwasher':'dishwasher_deadline',
    'E_dishwasher':'dishwasher_earliest_start_time',
    'T_dishwasher':'dishwasher_duration',
    'H_dryer':'dryer_usual_start_time',
    'D_dryer':'dryer_deadline',
    'E_dryer':'dryer_earliest_start_time',
    'T_dryer':'dryer_duration',
    'H_electric_water_heater':'water_heater_usual_start_time',
    'D_electric_water_heater':'water_heater_usual_end_time',
    'H_home_ev':'ev_home_connection_time',
    'D_home_ev':'ev_departure_time',
    'P_AC_RANGE':'preferred_temperature_range',
    'P_AC_CHANGE':'maximum_acceptable_temperature_change',
    'P_EV_TARGET':'ev_departure_target_charge',
    'P_EV_RESERVE':'ev_minimum_reserve_charge',
    'P_HOT_WATER':'hot_water_needed_time',
    'P_PREHEAT':'water_heater_preheating_acceptance',
    'A_EB_COMFORT':'household_comfort_attitude',
    'A_EB_TASK':'task_scheduling_attitude',
    'A_EB_PRICE':'electricity_price_attitude',
    'A_EB_CONTROL':'automation_control_preference',
    'P_COMFORT':'comfort_importance',
    'P_COST':'electricity_cost_importance',
    'P_GRID':'load_shifting_importance',
    'P_NOTICE':'advance_notice_preference',
    'X_REGION':'province',
    'X_CITY':'city',
    'X_BUILDING':'dwelling_type',
    'X_AREA':'dwelling_area_band',
    'X_AREA_BASIS':'dwelling_area_basis',
    'X_FLOOR':'apartment_floor_position',
}


def clean_members(reported):
    """Keep member results only; move missingness out of the value cells."""
    result=[]
    for member in reported:
        values={};unanswered={}
        for name,cell in member['reported_fields'].items():
            if cell['response_status']=='answered':
                value=cell['label']
                if isinstance(cell.get('value'),list):value=value.split('; ') if value else []
                values[name]=value
            else:unanswered[name]=cell['response_status']
        row={'member_id':member['member_id'],'values':values}
        if unanswered:row['unanswered_fields']=unanswered
        result.append(row)
    return result


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
    answers={};unanswered={};field_sources={}
    for group in ('household_information','stated_attitudes'):
        for row in english['observable_profile'][group]:
            qid=row['question_id']
            if qid=='M_MEMBERS':continue
            name=HOUSEHOLD_FIELDS.get(qid)
            if name is None:raise ValueError('Missing supervised feature name for '+qid)
            field_sources[name]=qid
            if row['response_status']=='answered':
                answers[name]=row['answer']
            else:unanswered[name]=row['response_status']
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
        'schema_version':'eb.first_stage_supervision.v3','case_id':collected['questionnaire']['case_id'],
        'household_id':collected['questionnaire']['household_id'],
        'input':{
            'household_profile':{
                'household_facts_and_preferences':answers,
                'members':clean_members(english.get('reported_members',[])),
                'unanswered_fields':unanswered,
            },
            'event_condition':event_condition,
            **plans,
        },
        'output':target,
        'auxiliary':{'supplementary_answers':supplemental,'simulation_context':context,
                     'source_question_ids':field_sources,'member_source_question_id':'M_MEMBERS'},
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
            'input_projection':'semantic English result values only; questionnaire prompts and display labels excluded',
            'plan_source':'saved participant_view schedule only; EP metrics and service outcomes excluded',
            'supplementary_policy':'Kept separately for later analysis; not automatically added to model input.',
            'selection_policy':'No filter on acceptance, savings, score or technical fallback.',
            'time_unit':'hours from simulation day 1 at 00:00; values above 24 refer to the following day',
            'quality_checks':{'source_links_verified':True,'human_target_complete':True,'paired_simulation_complete':True},
        },
    }
