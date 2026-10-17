"""Input-only coverage design. Never optimize or filter on outcomes or consent."""
import math
from common import *

def eligible(c):
    prefix=c['date']+':'
    pool={
        'thermal':[x for x in c['A']['controls']if x['kind']=='ac_setpoint'and overlap((x['start_min'],x['end_min']),(480,1920))],
        'program':[x for x in c['A']['tasks']if x['kind']in('washer','dishwasher')and x['need_id'].startswith(prefix)and x['start_min']>=DECISION],
        'ev':[x for x in c['A']['controls']if x['kind']=='ev_charge_window'and not x.get('automatic_segment_count')and x['need_id'].startswith(prefix)and DECISION<=x['start_min']<1920],
        'tank':[x for x in c['A']['controls']if x['kind']=='tank_setpoint'and DECISION<=x['start_min']<1440]
    }
    future_loads={o['need_id']for o in c['A']['operations']if o['kind']=='load'and o['start_min']>=DECISION}
    pool['handling']=[t for t in pool['program']if t['need_id']in future_loads]
    return pool

def replace_control(plan,old,parts):
    ix=plan['controls'].index(old);plan['controls'][ix:ix+1]=parts

def thermal(plan,c,pool,level,reverse=False,pause=False):
    # Prefer a substantive heating/cooling interval when one actually exists.
    options=[x for x in pool if x['mode']!='recirculation_fan']or pool
    x=choose(options,[c['case_id'],'thermal',reverse,pause]);old=copy.deepcopy(x)
    a=max(DECISION,x['start_min']);b=min(1920,x['end_min'],a+[30,60,120,240][level])
    part=copy.deepcopy(x);part['start_min']=a;part['end_min']=b
    before=copy.deepcopy(x);before['end_min']=a
    after=copy.deepcopy(x);after['start_min']=b
    new=[]
    if before['start_min']<a:new.append(before)
    delta=[0.5,1.,2.,4.][level]
    if pause or x['mode']=='recirculation_fan':
        action='暂停空调送风'if x['mode']=='recirculation_fan'else'暂停空调温控及送风'
        # Absence of a command is explicit off/default in the control compiler.
    else:
        direction=(1 if x['mode']=='cooling'else-1)*(-1 if reverse else 1)
        part['value_C']+=direction*delta
        part['heating_setpoint_C'if x['mode']=='heating'else'cooling_setpoint_C']=part['value_C']
        part['heating_and_cooling_deadband_C']=part['cooling_setpoint_C']-part['heating_setpoint_C']
        new.append(part);action=('制冷设定'if x['mode']=='cooling'else'制热设定')+f"由{x['value_C']:g}℃改为{part['value_C']:g}℃"
    if b<after['end_min']:new.append(after)
    replace_control(plan,old,new)
    return {'device_family':'ac','asset_id':x['asset_id'],'mode':x['mode'],'start_min':a,'end_min':b,
            'delta_C':0 if pause or x['mode']=='recirculation_fan'else part['value_C']-x['value_C'],
            'paused_minutes':b-a if pause or x['mode']=='recirculation_fan'else 0,
            'description':action,'thermal_or_energy_consequence':'pending_physics'}

def operation_slot(c,plan,old,earliest,latest,preferred):
    """Find a real slot for existing retrieval; no extra visit or new operator."""
    other=[o for o in plan['operations']if o['operation_id']!=old['operation_id']]
    for t in sorted(range(math.ceil(earliest/10)*10,math.floor((latest-10)/10)*10+1,10),key=lambda t:(abs(t-preferred),t)):
        day=next((d for d in c['days']if d['date']==str(dt.date.fromisoformat(c['date'])+dt.timedelta(days=t//1440))),None)
        if day is None:continue
        local=t%1440
        if not any(a<=local and local+10<=b for a,b in day['activity']['operator_windows_min'].get(old['operator_id'],[])):continue
        if any(overlap((t,t+10),(o['start_min'],o['end_min']))and(old['operator_id']==o['operator_id']or old['room_id']==o['room_id'])for o in other):continue
        base=(dt.date.fromisoformat(day['date'])-dt.date.fromisoformat(c['date'])).days*1440
        blocks=[(r['room_id'],base+r['start_min'],base+r['end_min'])for r in day['shared']['facility_reservations']]
        # Native bath resource is reserved for the complete ten-minute appointment.
        bath_room=old.get('_bath_room')
        if bath_room:blocks +=[(bath_room,base+m,base+m+10)for m in day['activity']['family_context']['bath_times_min'].values()]
        if any(room==old['room_id']and overlap((t,t+10),(a,b))for room,a,b in blocks):continue
        return t
    return None

def program(plan,c,w,pool,level,handling=False,reverse=False):
    x=choose(pool,[c['case_id'],'program',handling,reverse]);nid=x['need_id']
    group=[t for t in plan['tasks']if t['need_id']in(nid,nid+':dry')]
    delta=([30,90,240,600]if handling else[20,60,180,540])[level]
    load=next(o for o in plan['operations']if o['need_id']==nid and o['kind']=='load')
    unload=next(o for o in plan['operations']if o['need_id']==nid and o['kind']=='unload')
    lookup={n['need_id']:n for n in c['needs_A']};need=lookup[nid]
    if level==3 and not reverse:
        # A next-day postponement can cross a real service deadline. The
        # deadline stays fixed; this is an intentionally poor alternative.
        delta=max(delta,math.ceil((need['deadline_min']-max(t['end_min']for t in group))/10)*10+30)
    if reverse:
        # Earlier only if both release and the common 08:00 decision allow it.
        room=min(x['start_min']-max(DECISION,load['end_min']),delta)
        if room>=10:delta=-room
    old_start=x['start_min'];old_end=max(t['end_min']for t in group)
    for t in group:t['start_min']+=delta;t['end_min']+=delta
    if handling:
        for op in (load,unload):op['start_min']+=delta;op['end_min']+=delta
        resolution='existing_operations_shifted_as_requested;unavailable_requests_retained'
    else:
        end=old_end+delta;preferred=max(end,unload['start_min'])
        probe={**unload,'_bath_room':w['activity_contract']['room_map']['bath']}
        slot=operation_slot(c,plan,probe,end,min(need['deadline_min'],end+need['maximum_retrieval_wait_min']+10,4320),preferred)
        if slot is None:
            # A coherent request to collect when the cycle ends; may be impossible.
            slot=math.ceil(end/10)*10
            resolution='no_existing_operator_slot;request_kept_for_failure_assessment'
        else:resolution='same_operator_existing_slot;consent_not_assumed'
        unload['start_min']=slot;unload['end_min']=slot+10
    return {'device_family':x['kind'],'asset_id':x['asset_id'],'need_id':nid,'delta_minutes':delta,
            'program_start_A_min':old_start,'program_start_B_min':old_start+delta,'completion_A_min':old_end,'completion_B_min':old_end+delta,
            'handling_resolution':resolution,'description':('装取和程序一起后移'if handling else'调整已有程序的预约启动')+f'{delta}分钟；保留洗烘顺序'}

def ev(plan,c,w,pool,level,short=False):
    old=choose(pool,[c['case_id'],'ev',short]);x=plan['controls'][plan['controls'].index(old)]
    dev=next(d for d in w['parameter_pack']['devices']if d['asset_id']==x['asset_id']);p=dev['parameters']
    required=x['battery_energy_kWh'];full_minutes=required/(p['charger_kw']*p['efficiency'])*60
    if short:
        # Demand is NOT lowered: these are deliberately restricted permission windows.
        usable=max(10,math.floor(full_minutes*[.9,.65,.4,.15][level]/10)*10)
        x['end_min']=min(old['end_min'],x['start_min']+usable)
    else:
        slack=old['end_min']-old['start_min']-math.ceil(full_minutes/10)*10
        delta=max(10,math.floor(max(0,slack)*[.1,.4,.8,1.05][level]/10)*10)
        x['start_min']=min(old['end_min']-10,old['start_min']+delta)
    available=max(0,(x['end_min']-x['start_min'])/60*p['charger_kw']*p['efficiency'])
    delivered=min(required,available);steps=math.ceil(delivered/(p['charger_kw']*p['efficiency'])*6-1e-10)
    x['actual_charge_end_min']=x['start_min']+steps*10
    x['last_step_power_fraction']=max(0,min(1,delivered/(p['charger_kw']*p['efficiency'])*6-(steps-1)))if steps else 0
    x['requested_battery_energy_kWh']=required
    x['projected_battery_energy_kWh']=delivered
    x['grid_energy_kWh']=delivered/p['efficiency']
    x['projection_basis']='fixed EB charger power/efficiency;common A state at this connection;not EP output'
    return {'device_family':'ev','asset_id':x['asset_id'],'need_id':x['need_id'],
            'window_A_min':[old['start_min'],old['end_min']],'window_B_min':[x['start_min'],x['end_min']],
            'required_battery_kWh':required,'window_energy_upper_bound_kWh':available,
            'description':'缩短已有连接内的充电许可窗口'if short else'在原有插枪和拔枪之间推迟自动充电；操作不变'}

def tank(plan,c,w,pool,level,target=False,reverse=False):
    old=choose(pool,[c['case_id'],'tank',target,reverse]);x=plan['controls'][plan['controls'].index(old)]
    if target:
        x['value_C']=min(65.,old['value_C']+[1,2,3,5][level])if reverse else[58.,55.,50.,35.][level]
        desc=f"热水器储水设定由{old['value_C']:g}℃改为{x['value_C']:g}℃；洗澡时间和目标水温不变"
    else:
        delta=[20,60,120,210][level]
        x['start_min']=min(old['end_min']-10,old['start_min']+delta)
        desc=f"热水器启动加热后移{x['start_min']-old['start_min']}分钟；洗澡安排不变"
    return {'device_family':'water_heater','asset_id':x['asset_id'],'window_A_min':[old['start_min'],old['end_min']],
            'window_B_min':[x['start_min'],x['end_min']],'target_A_C':old['value_C'],'target_B_C':x['value_C'],
            'description':desc,'thermal_or_energy_consequence':'pending_physics'}

def make(w,c,index):
    pool=eligible(c);offset=rank(w['household_id'],'mechanism_rotation')%10
    wanted=MECHANISMS[(index+offset)%10];level=(index+rank(w['household_id'],'intensity_rotation'))%4
    possible={'thermal_setpoint':bool(pool['thermal']),'thermal_pause':bool(pool['thermal']),
              'program_timer':bool(pool['program']),'handling_shift':bool(pool['handling']),
              'ev_delay':bool(pool['ev']),'ev_short_window':bool(pool['ev']),
              'hotwater_preheat':bool(pool['tank']),'hotwater_target':bool(pool['tank']),
              'coordinated':bool(pool['thermal'])and any(pool[k]for k in('program','ev','tank')),
              'reverse_direction':any(x['mode']!='recirculation_fan'for x in pool['thermal'])or bool(pool['tank'])}
    fallback=['program_timer','ev_delay','hotwater_preheat','thermal_setpoint','thermal_pause']
    actual=wanted if possible[wanted]else next(k for k in fallback if possible[k])
    plan=copy.deepcopy(c['A']);changes=[]
    def apply(kind):
        if kind in('thermal_setpoint','thermal_pause'):return thermal(plan,c,pool['thermal'],level,pause=kind=='thermal_pause')
        if kind in('program_timer','handling_shift'):return program(plan,c,w,pool['handling'if kind=='handling_shift'else'program'],level,handling=kind=='handling_shift')
        if kind in('ev_delay','ev_short_window'):return ev(plan,c,w,pool['ev'],level,short=kind=='ev_short_window')
        if kind in('hotwater_preheat','hotwater_target'):return tank(plan,c,w,pool['tank'],level,target=kind=='hotwater_target')
    if actual=='coordinated':
        changes.append(thermal(plan,c,pool['thermal'],level))
        choices=[k for k,p in [('program_timer','program'),('ev_delay','ev'),('hotwater_preheat','tank')]if pool[p]]
        changes.append(apply(choose(choices,[c['case_id'],'secondary'])))
    elif actual=='reverse_direction':
        if any(x['mode']!='recirculation_fan'for x in pool['thermal']):changes.append(thermal(plan,c,pool['thermal'],level,reverse=True))
        else:changes.append(tank(plan,c,w,pool['tank'],level,target=True,reverse=True))
    else:changes.append(apply(actual))
    plan['changed_controls']=[x for x in plan['controls']if x not in c['A']['controls']]
    proposal={'requested_mechanism':wanted,'realized_mechanism':actual,'intensity_design':LEVELS[level],
              'eligibility':possible,'fallback_reason':None if wanted==actual else'original device/date has no eligible future command;fixed fallback order;no resampling',
              'changes':changes,'selection_uses_outcomes_or_acceptance':False,'human_acceptance':None,
              'rationale':'predeclared alternative-control benchmark coverage;not an optimizer or a claim of real proposal prevalence',
              'automatic_execution_authorized':False,'LLM_call_occurred':False}
    attention=[];policy=w['role_policy']
    for change in changes:
        if 'delta_minutes'in change and abs(change['delta_minutes'])>policy['service_policy']['reschedule_limit_min']:
            attention.append({'code':'GIVEN_SCHEDULE_CHANGE_BOUND_EXCEEDED','need_id':change['need_id'],'given_bound_min':policy['service_policy']['reschedule_limit_min'],'requested_change_min':change['delta_minutes']})
        if change['device_family']=='ac':
            if change['mode']=='cooling'and change['delta_C']>policy['thermal']['temporary_increase_C']:
                attention.append({'code':'GIVEN_COOLING_INCREASE_BOUND_EXCEEDED','asset_id':change['asset_id'],'given_bound_C':policy['thermal']['temporary_increase_C'],'requested_change_C':change['delta_C']})
            if change['mode']=='heating':attention.append({'code':'HEATING_TOLERANCE_NOT_GIVEN','asset_id':change['asset_id'],'cooling_bound_not_reused_as_heating_preference':True})
    proposal['given_role_policy_sha256']=policy['policy_sha256']
    proposal['policy_attention']=attention
    proposal['policy_attention_is_not_human_rejection']=True
    return plan,proposal
