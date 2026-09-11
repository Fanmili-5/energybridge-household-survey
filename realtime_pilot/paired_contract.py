"""Frozen household facts -> ordinary schedule -> randomized event -> paired simulation."""
from copy import deepcopy
import random
from common import PROPOSAL_PROFILE_QUESTIONS, digest
from questionnaire_persona import question, components, visible_profile
from proposal_contract import DEVICES, TASKS, executable, at
from eb_execution import physical_defaults, ordinary, validate_shape
from survey_time import LEGACY_STARTS, start_hour

VERSION = 'eb.paired_ep.v2.7'
QUESTIONNAIRE_VERSION = 'eb.persona_questionnaire.v3.9'
QUESTIONS = [deepcopy(q) for q in PROPOSAL_PROFILE_QUESTIONS if q['id'] != 'F_ROUTINES']
for q in QUESTIONS:
    if q['id'] == 'B05':
        q['prompt'] = '请选择家中拥有、要纳入日常用电安排的设备；所选设备都会进入本次模拟。'
        for o in q['options']:
            if o['value']=='home_ev':o['label']='可在家充电的电动汽车（含插混，不含电动自行车）'
# New wording applies only to this version; saved snapshots retain their meanings.
for q in QUESTIONS:
    if q['group']=='attitude':
        q['prompt']=q['prompt'].replace('您家的想法','您综合考虑家人需要后的想法').replace('您家平时的想法','您综合考虑家人需要后的想法').replace('您家的态度','您综合考虑家人需要后的态度')
for q in QUESTIONS:
    if q['id']=='A_EB_CONTROL':
        q['prompt']='让系统安排电器时，您综合考虑家人需要后的主要要求是什么？（选最接近的一项）'
        for o in q['options']:
            if o['value']=='suggestion_first':o['label']='先了解建议和理由，再决定怎样安排'
            if o['value']=='confirm_required':o['label']='每次改动都必须先征得我们明确同意'
# Keep temperature, price and control questions focused on their own concepts.
removed={'A_EB_COMFORT':{'low_control_tolerance'},'A_EB_PRICE':{'event_fatigue'},'A_EB_CONTROL':{'privacy_sensitive'}}
for q in QUESTIONS:
    q['options']=[o for o in q['options'] if o['value'] not in removed.get(q['id'],set())]
from member_questionnaire import QUESTION as MEMBER_QUESTION, validate_count
QUESTIONS.append(deepcopy(MEMBER_QUESTION))
from survey_preferences import FAMILY as FAMILY_PREFERENCES, DEVICES as DEVICE_PREFERENCES
QUESTIONS=[q for q in QUESTIONS if q['id'] not in ('A_EB_COMFORT','A_EB_TASK','A_EB_PRICE')]+deepcopy(FAMILY_PREFERENCES)
HABITS = []
for d, label in DEVICES.items():
    if d == 'ac':
        options = [('afternoon', '下午到睡前（14:00—23:00）'), ('evening', '傍晚到睡前（18:00—23:00）'), ('all_day', '全天使用'),('custom','自己选择使用时段（可跨午夜）')]
    else:
        options = [(next((k for k,v in LEGACY_STARTS.items() if v==i/2),f'{i/2:g}'),f'{i//2:02d}:{(i%2)*30:02d}') for i in range(48)]
    q = question('H_'+d, f'平常一个夏季日，{label}一般什么时候用？', options, group='household_fact')
    if d=='home_ev': q['prompt']='电动汽车通常什么时候在家接入充电设备？'
    if d=='electric_water_heater': q['prompt']='电热水器通常从什么时候开始加热？（请按真实习惯填写；午夜或跨夜安排可保存，暂不能生成模拟）'
    q['device'] = d
    HABITS.append(q)
    if d in TASKS:
        q = question('D_'+d, f'{label}这项任务，通常最晚几点需要完成？', [(str(i),f'{i:02d}:00') for i in range(1,25)], group='household_fact')
        q.update(device=d, active_only=True)
        HABITS.append(q)
        q = question('E_'+d, f'{label}通常从几点起就可以开始？', [(str(i),f'{i:02d}:00') for i in range(24)], group='household_fact')
        q.update(device=d, active_only=True); HABITS.append(q)
        q = question('T_'+d, f'{label}一次通常需要多久？', [(str(v),f'{v:g} 小时') for v in (.5,1.,1.5,2.,2.5,3.,4.)], group='household_fact')
        q.update(device=d, active_only=True); HABITS.append(q)
q = question('H_ac_temp', '平时空调通常设为多少度？（本研究支持22—28℃）', [(f'{i/2:g}',f'{i/2:g}℃') for i in range(44,57)], group='household_fact')
q.update(device='ac', active_only=True); HABITS.append(q)
q = question('D_home_ev', '接入充电后，电动汽车通常几点离家？（早于接入时刻表示次日；请勿选择相同时刻）', [(str(i),f'{i:02d}:00') for i in range(24)], group='household_fact')
q.update(device='home_ev', active_only=True); HABITS.append(q)
q = question('D_electric_water_heater', '电热水器通常加热到几点？（早于开始表示次日；跨夜答案可保存，暂不能生成模拟）', [(f'{i/2:g}',f'{i//2:02d}:{(i%2)*30:02d}') for i in range(49)], group='household_fact')
q.update(device='electric_water_heater', active_only=True); HABITS.append(q)
for qid,prompt,stop in [('H_ac_start','空调通常几点开始使用？',48),('H_ac_end','空调通常几点结束使用？（早于开始时间表示次日）',49)]:
    q=question(qid,prompt,[(f'{i/2:g}',f'{i//2:02d}:{(i%2)*30:02d}') for i in range(stop)],group='household_fact')
    q.update(device='ac',required=True,show_when={'question_id':'H_ac','value':'custom'})
    HABITS.append(q)
HABITS += deepcopy(DEVICE_PREFERENCES)
QUESTIONS = [q for q in QUESTIONS if q['group'] in ('household_fact','member_profile')] + HABITS + [q for q in QUESTIONS if q['group'] in ('attitude','stated_preference')]
for q in QUESTIONS:
    if q['group']=='attitude':q['required']=True
from household_extensions import QUESTIONS as EXTENSION_QUESTIONS
QUESTIONS += deepcopy(EXTENSION_QUESTIONS)
LOOKUP = {q['id']:q for q in QUESTIONS}
CONTEXT = {'id':'tianjin_shared_prototype_paired_v1', 'facts':[
    '请代入一个夏季日，按您家的电器和日常习惯回答。系统会先生成原安排，再提出错峰用电建议。',
    '两份安排使用同一研究住宅和天津典型夏季天气，结果是情境模拟，不是您家实际耗电预测。',
    '电价统一为 0.60 元/度，无额外补偿。仅移动用电时间并不一定省钱。'],
    'tariff':{'cny_per_kwh':.6,'compensation_cny':0},
    'building':{'source':'family_simple_3day.idf','binding':'shared_research_prototype','calibrated_to_household':False},
    'weather':{'file':'CHN_TJ_Tianjin.545270_CSWD.epw','date':'July 4','actual_household_weather':False}}

def value(profile, qid):
    c=profile.get(qid,{})
    return c.get('value') if c.get('response_status')=='answered' else None

def sanitize_profile(profile):
    """Only unselected devices have inapplicable habit answers."""
    owned=value(profile,'B05') or []
    for q in HABITS + EXTENSION_QUESTIONS:
        if not q.get("device"):continue
        if q['device'] not in owned or q.get('show_when') and value(profile,q['show_when']['question_id'])!=q['show_when']['value']:
            profile[q['id']]={'value':None,'response_status':'not_applicable'}
    return profile

def required(profile,qid):
    v=value(profile,qid)
    if v is None: raise ValueError('请填写：'+LOOKUP[qid]['prompt'])
    return v

def prepare(profile, seed):
    owned=required(profile,'B05')
    for qid in ('B02','B04','F_EVENING'): required(profile,qid)
    for q in QUESTIONS:
        if q['group'] in ('attitude','stated_preference') and not q.get('device'):required(profile,q['id'])
    validate_count(profile)
    if owned==['none']: owned=[]
    config=physical_defaults()
    from eb_execution import upstream
    config['ev']['charger_kw']=min(config['ev']['charger_kw'],upstream()[0]._APPL_DESIGN_W['ev']/1000)
    mapping={'electric_water_heater':'water_heater','home_ev':'ev'}
    records={}
    for key in config: config[key]['present']=False
    config['refrigerator']={'present':False}
    for d in owned:
        use=required(profile,'H_'+d)
        if use=='off':
            raise ValueError('所选设备都会进入本次模拟，请填写使用时间；旧版“不用”选项已移除，请刷新问卷。')
        key=mapping.get(d,d); cfg=config[key]; cfg['present']=True
        if d=='ac':
            if use=='custom':
                start=float(required(profile,'H_ac_start'));end=float(required(profile,'H_ac_end'))
                if end==start:raise ValueError('空调开始和结束不能相同，全天使用请直接选择全天。')
                if end<start:end+=24
            else:start,end={'afternoon':(14,23),'evening':(18,23),'all_day':(0,24)}[use]
            temp=float(required(profile,'H_ac_temp'))
            cfg.update(setpoint_preferred_min_c=temp,setpoint_preferred_max_c=temp)
            records[d]={'active':True,'setpoint':temp,'use_start_h':start,'use_end_h':end}
        else:
            start=start_hour(use)
            if d in TASKS:
                earliest=float(required(profile,'E_'+d)); end=float(required(profile,'D_'+d)); duration=float(required(profile,'T_'+d))
                absolute_start=start+24 if end<earliest and start<earliest else start
                # Native ordinary-plan clamping uses the unwrapped task window.
                # Preserve the reported clock in records; only its EB projection is expanded.
                cfg.update(preferred_h=absolute_start, earliest_h=earliest, latest_h=end, duration_h=duration)
                absolute_end=end+24 if end<earliest else end
                if not earliest<=absolute_start<=absolute_end-duration:
                    raise ValueError(DEVICES[d]+'的常用时间无法落在可用时间内，请检查。最晚时间早于最早时间表示次日完成。')
                records[d]={'active':True,'start_h':start,'duration_h':duration,'earliest_h':earliest,'deadline_h':end,'power_kw':cfg['power_kw']}
            elif d=='home_ev':
                end=float(required(profile,'D_home_ev'))
                if end==start: raise ValueError('电动汽车接入与离家不能为相同时刻，请填写实际的接入和离家时间。离家时刻早于接入时刻表示次日。')
                cfg.update(arrival_h=start,departure_h=end)
                records[d]={'active':True,'start_h':start,'duration_h':(end-start)%24,'service':'charging_window'}
            else:
                end=float(required(profile,'D_electric_water_heater'))
                if start==0: raise ValueError('当前热水器执行模型暂不能准确执行午夜00:00开始的加热安排。真实答案可以保存，但暂不能生成这份模拟；请勿为了生成而改填。')
                if end<=start: raise ValueError('当前热水器执行模型暂不支持跨夜或全天加热。真实答案可以保存，但暂不能生成这份模拟；请勿为了生成而改填。')
                if end-start>8: raise ValueError('原EB热水器单次加热窗口上限为8小时。真实答案可以保存，但暂不能生成这份模拟；请勿为了生成而改填。')
                cfg.update(normal_start_h=start,normal_end_h=end)
                records[d]={'active':True,'start_h':start,'duration_h':end-start,'service':'heating_window'}
    for q in DEVICE_PREFERENCES:
        if q['device'] in owned:required(profile,q['id'])
    if 'home_ev' in owned:
        config['ev']['target_soc']=float(required(profile,'P_EV_TARGET'))
        config['ev']['min_soc']=float(required(profile,'P_EV_RESERVE'))
        if config['ev']['min_soc']>config['ev']['target_soc']:raise ValueError('电动汽车保留电量不能超过出发目标电量')
    if 'electric_water_heater' in owned:
        config['water_heater']['bath_required_h']=float(required(profile,'P_HOT_WATER'))
    p0=ordinary(config)
    from eb_execution import upstream
    for device in TASKS:
        record=records.get(device)
        if record and abs(float(p0['appliances'].get(device+'_start_h',-1))-record['start_h'])>1e-6:
            raise ValueError(DEVICES[device]+'的原生原安排与填报时刻不一致，暂不能生成模拟。请保留真实答案，不要为提交而改填。')
    errors=upstream()[0]._adaptive_v3_water_heater_action_errors(p0['appliances'],config)
    if errors: raise ValueError('热水器原安排超出原EB执行支持范围，真实答案可以保存，但暂不能生成模拟。')
    original={'devices':records, 'source':'eb_manual_no_vpp_user_plan',
              'eb_appliance_config':config,'eb_ordinary_plan':p0,
              'assumptions':{'equipment_model_source':'EnergyBridge all_appliances_full.json (physical fields only)',
                'notice':'开始时刻、可用窗口和任务时长来自您的选择。设备功率、电动汽车电池和热水器采用研究模型；充电功率按 EB/EP 接口统一为 7 kW；充电和加热窗口不表示设备始终满功率运行。洗衣、洗碗、烘干按 EB 分别执行。'}}
    rng=random.Random(str(seed)); decision=rng.choice([16,17,18]); duration=rng.choice([.5,1.])
    scenario=deepcopy(CONTEXT)
    scenario.update(decision_h=decision,event={'id':'vpp_'+digest(str(seed))[:12],'trigger_h':decision+1,'end_h':decision+1+duration,'day':4},
                    sampling={'method':'uniform_notification_16_17_18_duration_0.5_1_v1','seed':str(seed),'conditioned_on_response':False})
    from evaluation_window import make_window
    scenario['evaluation_window']=make_window(original)
    return original,scenario

def validate(original,plan,scenario):
    if isinstance(plan,dict) and plan.get('execution_mode')=='eb_closed_loop':
        from eb_execution import upstream
        runner,_=upstream();previous=72+scenario['decision_h']-1e-7
        from evaluation_window import window_for
        horizon=window_for(scenario)['end_sim_h']
        if not plan.get('decisions') or plan.get('horizon_end_sim_h')!=horizon: raise ValueError('Incomplete closed-loop plan')
        for row in plan['decisions']:
            now=row['sim_h']
            if not previous<now<horizon or abs(row['observed']['end_h']-now)>1e-6: raise ValueError('Invalid decision chronology')
            bounds=row.get('control_bounds',{'minimum_c':runner.SP_MIN,'maximum_c':runner.SP_MAX})
            errors=runner._adaptive_v3_plan_control_errors(row['requested_plan'],sim_h=now,total_sim_hours=horizon,setpoint_min_c=bounds['minimum_c'],setpoint_max_c=bounds['maximum_c'])
            if errors: raise ValueError('; '.join(errors))
            previous=now
        return deepcopy(plan)
    # Legacy records keep their historical contract; current requests use EB's
    # own scalar contract, then its runtime application (including rejections).
    if 'eb_appliance_config' not in original:
        from legacy_paired_v1_1.paired_contract import validate as legacy_validate
        return legacy_validate(original,plan,scenario)
    return validate_shape(original,plan,scenario)

def profile_components(profile):
    from household_classification import feature_record
    out=components(profile,QUESTIONS);out['questionnaire_version']=QUESTIONNAIRE_VERSION
    out['classification']=feature_record(profile)
    return out

def display_pair(original,plan,scenario,prediction):
    rows=[]; event=scenario['event']; window=at(event['trigger_h'])+'—'+at(event['end_h'])
    for d,r in original['devices'].items():
        if not r.get('active'): before=after='本情境不使用'
        elif d=='ac':
            before=f"{at(r['use_start_h'])}—{at(r['use_end_h'])}，设定 {r['setpoint']:g}℃"
            after=before if plan['setpoint']==r['setpoint'] else f"从通知时间 {at(scenario['decision_h'])} 起，原使用时段内设为 {plan['setpoint']:g}℃"
        else:
            start=plan['appliances'].get(d+'_start_h',r['start_h'])
            duration=r['duration_h']
            if d=='home_ev':
                start=plan['appliances'].get('ev_charge_start_h',r['start_h'])
                end=plan['appliances'].get('ev_charge_end_h',(r['start_h']+duration)%24)
                duration=(end-start)%24
            elif d=='electric_water_heater':
                start=plan['appliances'].get('water_heater_preheat_start_h',r['start_h'])
                duration=plan['appliances'].get('water_heater_preheat_end_h',r['start_h']+duration)-start
            before=f"{at(r['start_h'])}—{at(r['start_h']+r['duration_h'])}"
            after=f"{at(start)}—{at(start+duration)}"
            if d=='electric_water_heater':
                before+='，60℃'
                after+=f"，{plan['appliances'].get('water_heater_preheat_temp_c',60):g}℃"
                if plan['appliances'].get('water_heater_preheat') is False: after='不主动加热（模型待机）'
            if d in TASKS and plan['appliances'].get(d+'_skip') is True: after='本次不运行'
        rows.append({'device_id':d,'device':DEVICES[d],'original':before,'proposal':after,'changed':before!=after,'change':'有调整' if before!=after else '不变'})
    return {'title':'按家庭习惯生成的原安排与 EB 建议','rows':rows,'context':scenario,'prediction':prediction,
            'has_changes':any(r['changed'] for r in rows),'baseline_source':original['source'],
            'notice':f"模拟通知时间 {at(scenario['decision_h'])}；希望在 {window} 减少集中用电。两份方案均已完成 EnergyPlus 仿真。本次比较一次 EB 建议到当日结束的结果。室温为同一居住区域的模拟值，费用统计到当日24点；跨日任务的次日用电未计入，金额差不代表完成全部任务的总节省。无额外补偿，未控制真实电器。",
            'assumptions':original['assumptions']['notice'],'question':'您是否同意用 EB 建议替换原安排？'}


def participant_view(display):
    """Exact texts and rounding shown to the human, also used as SFT input."""
    prediction=display['prediction']; metrics=[]
    for label,key,unit in [('当日用电量','daily_kwh','度'),('当日电费（无补偿）','daily_cost_cny','元'),('响应时段用电量','event_kwh','度'),('响应时段平均功率','event_mean_kw','kW')]:
        metrics.append({'label':label, **{side:f"{prediction[side][key]:.2f} {unit}" for side in ('original','proposal')}})
    metrics.append({'label':'响应时段居住区域室温',**{side:f"{prediction[side]['event_temp_min_c']:.1f}—{prediction[side]['event_temp_max_c']:.1f}℃" for side in ('original','proposal')}})
    for metric in display.get('comparison_metrics',[]):metrics.append(deepcopy(metric))
    return {key:deepcopy(display[key]) for key in ('title','rows','notice','assumptions','question','selection_reason','execution_notice')} | {'scenario_facts':display['context']['facts'],'metrics':metrics,'timeline':deepcopy(display.get('timeline',[])),'service_rows':deepcopy(display.get('service_rows',[])), 'schedule_chart':deepcopy(display.get('schedule_chart')), 'temperature_chart':deepcopy(display.get('temperature_chart'))}
