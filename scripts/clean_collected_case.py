"""First-stage supervised-data handoff from verified saved case evidence.

No training prompt, model call, invented reason or acceptance inference.  The
role-play input is deliberately limited to the household, event, No-DR plan,
EB plan and the rounded simulation results shown to the participant.  Internal
simulation traces remain in the complete collected record.
"""
from copy import deepcopy
import math
from pathlib import Path
import re
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'realtime_pilot'))
from planner_language import planner_household


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
    """Keep member results only; omitted optional fields remain omitted."""
    result=[]
    for member in reported:
        values={}
        for name,cell in member['reported_fields'].items():
            if cell['response_status']=='answered':
                value=cell['label']
                if isinstance(cell.get('value'),list):value=value.split('; ') if value else []
                values[name]=value
        result.append({'member_id':member['member_id'],**values})
    return result


def clock_value(hours):
    """Render ten-minute schedule values without exposing decimal-hour math."""
    minutes=round(float(hours)*60)
    day=minutes//1440+1;within=minutes%1440
    return f"day_{day} {within//60:02d}:{within%60:02d}"


def plan_pair(view):
    """Project the displayed schedule into two plans, without EP outcomes."""
    chart=view['schedule_chart']
    plans={
        'no_dr_plan':{'devices':[]},
        'agent_plan':{'devices':[]},
    }
    for row in chart['rows']:
        for source,name in (('original','no_dr_plan'),('proposal','agent_plan')):
            device={'device_id':row['device_id'],'schedule':[]}
            for span in row[source]:
                clean={'start_time':clock_value(span['start_h']),'end_time':clock_value(span['end_h'])}
                m=re.fullmatch(r'([\d.]+)℃( 待机)?',span['label'])
                if m:
                    clean['setpoint_c']=float(m[1])
                    if m[2]:clean['mode']='standby'
                else:
                    m=re.fullmatch(r'([\d.]+) kW',span['label'])
                    if not m:raise ValueError('Unrecognized timeline value: '+span['label'])
                    clean['power_kw']=float(m[1])
                device['schedule'].append(clean)
            plans[name]['devices'].append(device)
    return plans


def _range_c(value):
    m=re.fullmatch(r'([\d.]+)—([\d.]+)℃',value)
    if not m:raise ValueError('Unrecognized displayed temperature: '+value)
    return {'min':float(m[1]),'max':float(m[2])}


def _shown_clock(value):
    day=2 if value.startswith('次日') else 1
    value=value.removeprefix('次日').removeprefix('当日')
    if not re.fullmatch(r'\d\d:\d\d',value):raise ValueError('Unrecognized displayed time: '+value)
    if value=='24:00':day+=1;value='00:00'
    return f'day_{day} {value}'


def _service_result(device,text):
    if text in ('离家时电量是否达标：本次未验证','使用时热水是否达标：本次未验证'):
        return {'status':'not_verified'}
    if device in ('washer','dishwasher','dryer'):
        m=re.fullmatch(r'截至(.+?)：(.*)',text)
        if not m:
            simple=re.fullmatch(r'截至(.+?)(已完成|未完成)',text)
            if not simple:raise ValueError('Unrecognized displayed task result: '+text)
            return {'observed_until':_shown_clock(simple[1]),
                    'tasks':[{'task_day':1,'status':'completed' if simple[2]=='已完成' else 'not_completed'}]}
        statuses=[]
        for part in m[2].split('；'):
            x=re.fullmatch(r'(当天|次日)任务(已完成|未完成|尚未到截止时间)',part)
            if not x:raise ValueError('Unrecognized displayed task status: '+part)
            statuses.append({'task_day':1 if x[1]=='当天' else 2,
                             'status':{'已完成':'completed','未完成':'not_completed','尚未到截止时间':'deadline_not_reached'}[x[2]]})
        return {'observed_until':_shown_clock(m[1]),'tasks':statuses}
    if device=='electric_water_heater':
        m=re.fullmatch(r'(.+?)—(.+?)水箱温度 ([\d.]+)℃（平均）',text)
        if not m:raise ValueError('Unrecognized displayed water-heater result: '+text)
        return {'interval':{'start':_shown_clock(m[1]),'end':_shown_clock(m[2])},
                'average_tank_temperature_c':float(m[3])}
    if device=='home_ev':
        rows=[]
        for part in text.split('；'):
            m=re.fullmatch(r'(.+?)离家前电量 ([\d.]+)%（目标 ([\d.]+)%，(达到|未达到)）',part)
            if not m:raise ValueError('Unrecognized displayed EV result: '+part)
            rows.append({'departure_time':_shown_clock(m[1]),'charge_percent':float(m[2]),
                         'target_percent':float(m[3]),'target_met':m[4]=='达到'})
        return {'departures':rows}
    raise ValueError('Unsupported displayed service device: '+device)


def displayed_results(records,collected):
    """Keep the rounded EP evidence actually shown before the human label."""
    prediction=records['documents']['outcome.json']['prediction'];view=collected['shown_to_participant']
    a=prediction['original'];b=prediction['proposal'];window=prediction['comparison_window']
    result={
        'comparison_window':{'start_time':clock_value(window['start_sim_h']),
                             'end_time':clock_value(window['end_sim_h']),
                             'duration_hours':window['duration_h']},
        'energy_use_kwh':{'no_dr':round(a['daily_kwh'],2),'agent':round(b['daily_kwh'],2)},
        'event_energy_use_kwh':{'no_dr':round(a['event_kwh'],2),'agent':round(b['event_kwh'],2)},
        'event_average_power_kw':{'no_dr':round(a['event_mean_kw'],2),'agent':round(b['event_mean_kw'],2)},
        'event_indoor_temperature_c':{
            'no_dr':{'min':round(a['event_temp_min_c'],1),'max':round(a['event_temp_max_c'],1)},
            'agent':{'min':round(b['event_temp_min_c'],1),'max':round(b['event_temp_max_c'],1)}},
    }
    if prediction['cost_unit']=='normalized TOU cost/kWh':
        result['electricity_cost']={'unit':'relative_cost_units',
            'no_dr':round(a['daily_cost_normalized'],2),'agent':round(b['daily_cost_normalized'],2)}
    else:
        result['electricity_cost']={'unit':'CNY','no_dr':round(a['daily_cost_cny'],2),'agent':round(b['daily_cost_cny'],2)}
    extra=[]
    for row in view['metrics']:
        m=re.fullmatch(r'(响应前|响应结束后)室温（(.+?)—(.+?)）',row['label'])
        if m:
            extra.append({'period':'before_event' if m[1]=='响应前' else 'after_event',
                          'start_time':_shown_clock(m[2]),'end_time':_shown_clock(m[3]),
                          'no_dr':_range_c(row['original']),'agent':_range_c(row['proposal'])})
    if extra:result['additional_indoor_temperature_periods_c']=extra
    result['service_results']=[{'device_id':row['device_id'],
        'no_dr':_service_result(row['device_id'],row['original']),
        'agent':_service_result(row['device_id'],row['proposal'])} for row in view['service_rows']]
    return result


def clean_case(records, collected):
    docs=records['documents'];request=docs['request.json'];source=docs['household_config.json']
    # This English copy is a new rendering, never represented as the actual
    # planner input of historical cases collected before English ingress.
    english=planner_household(source,request)
    answers={}
    for group in ('household_information','stated_attitudes'):
        for row in english['observable_profile'][group]:
            qid=row['question_id']
            if qid=='M_MEMBERS':continue
            name=HOUSEHOLD_FIELDS.get(qid)
            if name is None:raise ValueError('Missing supervised feature name for '+qid)
            if row['response_status']=='answered':
                value=row['answer']
                if name=='included_appliances':value=value.split('; ') if value else []
                answers[name]=value
    decision=docs['decision.json'];names=('score','comfort_score','energy_score','vpp_score')
    if decision['choice'] not in ('accept','reject'):raise ValueError('Missing human decision')
    if any(type(decision.get(k)) not in (int,float) or not math.isfinite(decision[k]) or not 1<=decision[k]<=5 for k in names):raise ValueError('Invalid or missing human score; do not fill it')
    if not isinstance(decision.get('comment'),str) or not decision['comment'].strip():raise ValueError('Missing human reason; do not invent it')
    if docs['outcome.json']['simulation_status']!='paired_energyplus_complete':raise ValueError('Incomplete paired simulation')
    target={'decision':decision['choice'],**{k:decision[k] for k in names},'comment':decision['comment']}
    s=request['scenario']
    event_condition={
        'simulation_date':s['simulation_start_date'],
        'season':deepcopy((s.get('questionnaire_context') or {}).get('season')),
        'event_window':{'start_time':clock_value(s['event']['trigger_h']),
                        'end_time':clock_value(s['event']['end_h'])},
        'tariff':{'type':'time_of_use','cost_unit':'relative_cost_units_per_kwh'
                  if s['tariff'].get('unit')=='normalized TOU cost/kWh' else s['tariff'].get('unit')},
    }
    plans=plan_pair(collected['shown_to_participant'])
    return {
        'input':{
            'household_profile':{
                'household_facts_and_preferences':answers,
                'members':clean_members(english.get('reported_members',[])),
            },
            'event_condition':event_condition,
            **plans,
            'displayed_results':displayed_results(records,collected),
        },
        'output':target,
    }
