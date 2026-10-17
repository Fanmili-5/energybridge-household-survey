"""Event-conditioned control portfolios, including weak, adverse and failing requests."""
import math,itertools,collections
from common import *
from proposals import command_signature,replace_control,operation_slot
from thermal_flex import opportunity_options,make_preconditioning
from joint_timing import considered,program_target,ev_start,subtract_windows

def distance(x,e):return 0 if overlap((x['start_min'],x['end_min']),(e['start_min'],e['end_min']))else min(abs(x['start_min']-e['end_min']),abs(x['end_min']-e['start_min']))
def select(pool,c,e,tag):
    def span(x):
        end=max((t['end_min']for t in c['A']['tasks']if t['need_id']in(x.get('need_id'),str(x.get('need_id'))+':dry')),default=x['end_min'])if x['kind']=='washer'else x['end_min']
        lo=max(x['start_min'],e['start_min']);hi=min(end,e['end_min']);return max(0,hi-lo)
    return min(pool,key=lambda x:(-span(x),distance(x,e),rank(c['case_id'],tag,x)))
def eligible(c):
    p={'ac':[],'washer':[],'dishwasher':[],'ev':[],'water_heater':[]};prefix=c['date']+':'
    for x in c['A']['controls']:
        if x['kind']=='ac_setpoint'and overlap((x['start_min'],x['end_min']),(480,1920)):p['ac'].append(x)
        if x['kind']=='ev_charge_window'and not x.get('automatic_segment_count')and x['need_id'].startswith(prefix)and DECISION<=x['start_min']<1920:p['ev'].append(x)
        if x['kind']=='tank_setpoint'and DECISION<=x['start_min']<1440:p['water_heater'].append(x)
    for x in c['A']['tasks']:
        if x['kind']in('washer','dishwasher')and x['need_id'].startswith(prefix)and x['start_min']>=DECISION:p[x['kind']].append(x)
    future={o['need_id']for o in c['A']['operations']if o['kind']=='load'and o['start_min']>=DECISION}
    return p,future

def mechanism_eligibility(c):
    pool,future=eligible(c);programs=pool['washer']+pool['dishwasher']
    handling=[t for t in programs if t['need_id']in future]
    return {'thermal_precondition':any(opportunity_options(c,e)for e in c.get('VPP_events',[])),'thermal_setpoint':bool(pool['ac']),'thermal_pause':bool(pool['ac']),
        'program_timer':bool(programs),'handling_shift':bool(handling),
        'ev_delay':bool(pool['ev']),'ev_short_window':bool(pool['ev']),
        'hotwater_preheat':bool(pool['water_heater']),'hotwater_target':bool(pool['water_heater']),
        'coordinated':sum(bool(v)for v in pool.values())>=2,'reverse_direction':bool(pool['ac'])}


def continuous_thermal_pool(pool):
    """Availability is a physical resource, independent of fan/need serialization."""
    by=collections.defaultdict(list)
    for x in pool:by[x['asset_id']].append(x)
    merged=[]
    for aid,items in sorted(by.items()):
        spans=[]
        for x in sorted(items,key=lambda x:(x['start_min'],x['end_min'])):
            if spans and x['start_min']<=spans[-1][1]:spans[-1][1]=max(spans[-1][1],x['end_min'])
            else:spans.append([x['start_min'],x['end_min']])
        merged.extend({'kind':'ac_setpoint','asset_id':aid,'start_min':a,'end_min':b}for a,b in spans)
    return merged

def thermal(plan,w,c,pool,e,level,pause=False,reverse=False):
    reverse=bool(reverse or(pause and e['direction']=='up'))
    pool=continuous_thermal_pool(pool)
    if c.get('_joint_events'):
        active=[x for x in pool if overlap((x['start_min'],x['end_min']),(e['start_min'],e['end_min']))]
        if not active:
            x=select(pool,c,e,'thermal');room=next(d['room_id']for d in w['parameter_pack']['devices']if d['asset_id']==x['asset_id'])
            direction=e['direction'];direction='down'if pause else('up'if direction=='down'else'down')if reverse else direction
            return {'device_family':'ac','asset_id':x['asset_id'],'affected_asset_ids':[],'room_id':room,'mode':'dual_thermostat',
                'start_min':e['start_min'],'end_min':e['end_min'],'delta_C':0,'heating_delta_C':0,'cooling_delta_C':0,
                'paused_minutes':0,'event_overlap_minutes':0,'requested_delta_C':0,'effective_request_direction':'unchanged',
                'deliberate_reverse_direction':False,'requested_reverse_variant':reverse,'requested_event_direction':e['direction'],'intended_control_direction':direction,'control_action_direction':'unchanged','adverse_variant':None,'thermal_direction_basis':'availability_withdrawal'if pause else'dual_thermostat_bounds;no_outdoor_mode_guess',
                'minimum_deadband_C':2.,'indoor_state_available':False,'response_status':'uncertain_pending_physics','event_id':e.get('event_id'),'selected_event_id':e.get('event_id'),
                'description':'该事件窗口内A无既有温控许可，本项保留原安排；未新增温控或推定功率响应',
                'thermal_or_energy_consequence':'pending_indoor_state_physics','input_limitation':'no_A_permission_during_window'}
        pool=active
    x=select(pool,c,e,'thermal');a=max(DECISION,x['start_min'],min(e['start_min'],x['end_min']-10));b=min(x['end_min'],a+[30,60,120,240][level])
    room=next(d['room_id']for d in w['parameter_pack']['devices']if d['asset_id']==x['asset_id']);aids={d['asset_id']for d in w['parameter_pack']['devices']if'ac'in d['types']and d['room_id']==room}
    scale=min(1.5,max(.5,e.get('target_kw',1.)));delta=[.5,1.,2.,4.][level]*scale;direction=e['direction'];direction='down'if pause else('up'if direction=='down'else'down')if reverse else direction
    requested_delta=delta
    touched=[old for old in plan['controls']if old['kind']=='ac_setpoint'and old['asset_id']in aids and overlap((a,b),(old['start_min'],old['end_min']))]
    # Unknown indoor mode is not guessed from outdoor weather. Narrowing both
    # thermostat bounds requests extra load in either active mode; widening
    # requests shed. This is a control envelope, never a measured kW claim.
    if direction=='up'and touched:
        smallest_gap=min(old['cooling_setpoint_C']-old['heating_setpoint_C']for old in touched)
        delta=min(delta,max(0.,(smallest_gap-2.)/2))
    dh,dc=(-delta,delta)if direction=='down'else(delta,-delta)
    changed=bool(pause or delta>0)
    for old in list(plan['controls'])if changed else []:
        if old['kind']!='ac_setpoint'or old['asset_id']not in aids or not overlap((a,b),(old['start_min'],old['end_min'])):continue
        lo=max(a,old['start_min']);hi=min(b,old['end_min']);new=[]
        if old['start_min']<lo:new.append({**old,'end_min':lo})
        if not pause:new.append({**old,'start_min':lo,'end_min':hi,'heating_setpoint_C':old['heating_setpoint_C']+dh,'cooling_setpoint_C':old['cooling_setpoint_C']+dc,'value_C':old['cooling_setpoint_C']+dc,'heating_and_cooling_deadband_C':old['cooling_setpoint_C']+dc-old['heating_setpoint_C']-dh})
        if hi<old['end_min']:new.append({**old,'start_min':hi})
        replace_control(plan,old,new)
    return {'device_family':'ac','asset_id':x['asset_id'],'affected_asset_ids':sorted(aids)if changed else [],'room_id':room,'mode':'dual_thermostat','start_min':a,'end_min':b,
      'delta_C':0 if pause else dc,'heating_delta_C':0 if pause else dh,'cooling_delta_C':0 if pause else dc,'paused_minutes':b-a if pause else 0,
      'description':(('暂停该房间温控'if pause else f'该房间制热设定调整{dh:+g}℃，制冷设定调整{dc:+g}℃')+f'；修改时段{time_text(a)}—{time_text(b)}；实际功率和舒适变化待仿真')if changed else'最小温控间隔限制使给定调整量为0℃，保留A；没有实际温控指令变化',
      'event_overlap_minutes':max(0,min(b,e['end_min'])-max(a,e['start_min']))if changed else 0,'thermal_or_energy_consequence':'pending_indoor_state_physics','requested_delta_C':0 if pause else requested_delta,
      'effective_request_direction':direction if changed else'unchanged','deliberate_reverse_direction':reverse and changed,'requested_reverse_variant':reverse,
      'requested_event_direction':e['direction'],'intended_control_direction':direction,'control_action_direction':direction if changed else'unchanged','adverse_variant':('pause_opposes_up_request'if pause and e['direction']=='up'else'explicit_reverse_bounds'if reverse else None)if changed else None,'input_limitation':None if changed else'minimum_deadband_prevents_bound_change','thermal_direction_basis':'availability_withdrawal'if pause else'dual_thermostat_bounds;no_outdoor_mode_guess','availability_basis':'merged_continuous_A_permission;fan_and_need_boundaries_ignored;actual_gaps_retained','requested_duration_min':[30,60,120,240][level],'available_span_A_min':[x['start_min'],x['end_min']],'minimum_deadband_C':2.,
      'indoor_state_available':False,'response_status':'uncertain_pending_physics','event_id':e.get('event_id'),'selected_event_id':e.get('event_id')}

def program(plan,w,c,pool,e,level,handling=False):
    x=select(pool,c,e,'program');nid=x['need_id'];group=[t for t in plan['tasks']if t['need_id']in(nid,nid+':dry')];start=x['start_min'];end=max(t['end_min']for t in group);duration=end-start
    load=next(o for o in plan['operations']if o['need_id']==nid and o['kind']=='load');unload=next(o for o in plan['operations']if o['need_id']==nid and o['kind']=='unload');n=next(n for n in c['needs_A']if n['need_id']==nid)
    side='before'if rank(c['case_id'],nid,'event_side')%2 else'after';target=e['start_min']-duration if side=='before'else e['end_min']
    if e['direction']=='up':target=e['start_min']
    target,joint_basis=program_target(c,e,x,duration,load,n,target,handling)
    scale=min(1.5,max(.5,e.get('target_kw',1.)));cap=math.ceil(([30,90,240,600]if handling else[30,90,180,540])[level]*scale/10)*10;delta=max(-cap,min(cap,target-start))
    minimum=max(DECISION-start,n['release_min']-load['start_min'],DECISION-load['start_min'])if handling else max(DECISION,load['end_min'])-start
    delta=max(delta,minimum);variant='event_before_or_after'if e['direction']=='down'else'event_overlap_request'
    # No opportunity is not fixed by arbitrary chores. Some input-assigned high
    # doses intentionally overreact or move in the wrong direction.
    if e['direction']=='down'and not any(z['direction']=='down'and overlap((start,end),(z['start_min'],z['end_min']))for z in considered(c,e))and level<2:delta=0;variant='already_outside_all_considered_down_events;retain_routine'
    if level==3 and rank(c['case_id'],nid,'poor_variant')%3==0:
        delta=max(delta,math.ceil((n['deadline_min']-end)/10)*10+30);variant='beyond_deadline_overreaction'
    elif level>=2 and rank(c['case_id'],nid,'poor_variant')%5==0:
        delta=max(minimum,min(cap,max(-cap,e['start_min']-start)));variant='opposing_or_excessive_response'
    delta=int(delta//10)*10
    for t in group:t['start_min']+=delta;t['end_min']+=delta
    if handling:
        for o in(load,unload):o['start_min']+=delta;o['end_min']+=delta
        resolution='existing operations shifted;unavailable requests retained'
    else:
        probe={**unload,'_bath_room':w['activity_contract']['room_map']['bath']};finish=end+delta
        slot=operation_slot(c,plan,probe,finish,min(n['deadline_min'],finish+n['maximum_retrieval_wait_min']+10,4320),max(finish,unload['start_min']))
        resolution='same existing operator and operation;consent not assumed'
        if slot is None:slot=finish;resolution='requested retrieval unavailable;failure kept'
        unload['start_min']=slot;unload['end_min']=slot+10
    return {'device_family':x['kind'],'asset_id':x['asset_id'],'need_id':nid,'delta_minutes':delta,'direction':'advance'if delta<0 else'delay'if delta>0 else'unchanged','boundary_variant':variant,
      'program_start_A_min':start,'program_start_B_min':start+delta,'completion_A_min':end,'completion_B_min':end+delta,'handling_resolution':resolution,'selected_event_id':e.get('event_id'),'joint_timing_basis':joint_basis,'considered_event_ids':[e.get('event_id')for e in considered(c,e)],
      'description':f'综合{len(considered(c,e))}个VPP窗口，将已有{x["kind"]}程序调整{delta}分钟；保持原洗烘顺序'}

def ev(plan,w,c,pool,e,level,short=False):
    old=select(pool,c,e,'ev');x=plan['controls'][plan['controls'].index(old)];p=next(d['parameters']for d in w['parameter_pack']['devices']if d['asset_id']==x['asset_id'])
    required=x['battery_energy_kWh'];full=required/(p['charger_kw']*p['efficiency'])*60;quantized=math.ceil(full/10-1e-10)*10
    if e['direction']=='down':start=max(old['start_min'],e['end_min']+(0 if short else[0,20,60,180][level]))
    else:start=max(old['start_min'],e['start_min']+(0 if short else[0,0,20,60][level]))
    start,joint_basis=ev_start(c,e,old,quantized,0 if short else[0,20,60,180][level],start)
    start=min(old['end_min']-10,start);x['start_min']=start
    if short:
        usable=[quantized+60,quantized,max(10,math.floor(full*.65/10)*10),max(10,math.floor(full*.2/10)*10)][level];x['end_min']=min(old['end_min'],start+usable)
    available=(x['end_min']-x['start_min'])/60*p['charger_kw']*p['efficiency'];delivered=min(required,available);steps=math.ceil(delivered/(p['charger_kw']*p['efficiency'])*6-1e-10)
    x.update(actual_charge_end_min=start+steps*10,last_step_power_fraction=max(0,min(1,delivered/(p['charger_kw']*p['efficiency'])*6-(steps-1))),requested_battery_energy_kWh=required,projected_battery_energy_kWh=delivered,grid_energy_kWh=delivered/p['efficiency'],projection_basis='common A state at connection,fixed EB charger upper bound;not continuous B physical rollout')
    return {'device_family':'ev','asset_id':x['asset_id'],'need_id':x['need_id'],'window_A_min':[old['start_min'],old['end_min']],'window_B_min':[x['start_min'],x['end_min']],
      'required_battery_kWh':required,'window_energy_upper_bound_kWh':available,'description':'围绕VPP窗口调整已有连接内充电许可；不增加插拔','minimum_full_power_minutes':full,'selected_event_id':e.get('event_id'),'joint_timing_basis':joint_basis,'considered_event_ids':[e.get('event_id')for e in considered(c,e)]}

def time_text(m):
    day=m//1440;return ('前日'if day<0 else'当日'if day==0 else'次日'if day==1 else f'{day}日后')+f'{m%1440//60:02d}:{m%60:02d}'

def tank_description(plan,old,parts,event,target):
    intervals='、'.join(time_text(x['start_min'])+'—'+time_text(x['end_min'])+'（'+str(x['value_C'])+'℃）'for x in parts)or'无许可片段'
    touch=any(overlap((x['start_min'],x['end_min']),(event['start_min'],event['end_min']))for x in parts)
    later=sorted(x['start_min']for x in plan['controls']if x['kind']=='tank_setpoint'and x['asset_id']==old['asset_id']and x['start_min']>=event['end_min'])
    resume='；事件后下一段许可始于'+time_text(later[0])if later else'；已保存尾段内无后续加热许可'
    return '储水目标原参考'+str(old['value_C'])+'℃；修改后加热许可为'+intervals+('；许可与焦点事件有重叠'if touch else'；修改后的许可不与事件重叠')+resume+'；实际加热与供水待仿真'

def tank(plan,w,c,pool,e,level,target=False):
    old=select(pool,c,e,'tank');down=e['direction']=='down';a=old['start_min'];b=old['end_min'];parts=[]
    if c.get('_joint_events')and not target:
        es=c['_joint_events']
        if down:
            early=max(DECISION,a-[20,60,120,210][level])
            parts=[{**old,'start_min':lo,'end_min':hi}for lo,hi in subtract_windows(early,b,[e for e in es if e['direction']=='down'])]
        else:
            bounds=sorted({a,b}|{max(a,min(b,e[k]))for e in es for k in('start_min','end_min')})
            for lo,hi in zip(bounds,bounds[1:]):
                hit=any(e['direction']=='up'and overlap((lo,hi),(e['start_min'],e['end_min']))for e in es)
                parts.append({**old,'start_min':lo,'end_min':hi,'value_C':min(65,old['value_C']+[1,2,3,5][level])if hit else old['value_C']})
    elif target:
        delta=[1,2,5,15][level]*(-1 if down else 1);q={**old,'value_C':max(5,min(65,old['value_C']+delta))};parts=[q]
    elif down:
        early=max(DECISION,a-[20,60,120,210][level]);cut=min(b,e['start_min'])
        if early<cut:parts.append({**old,'start_min':early,'end_min':cut})
        if max(a,e['end_min'])<b:parts.append({**old,'start_min':max(a,e['end_min'])})
        if not parts:parts=[{**old,'start_min':max(DECISION,e['start_min']-30),'end_min':e['start_min']}]
    else:
        q={**old,'start_min':min(b-10,max(a,e['start_min'])),'value_C':min(65,old['value_C']+[1,2,3,5][level])};parts=[q]
    replace_control(plan,old,parts)
    return {'device_family':'water_heater','asset_id':old['asset_id'],'window_A_min':[a,b],'window_B_min':[min(x['start_min']for x in parts),max(x['end_min']for x in parts)]if parts else None,
      'segments_B_min':[[x['start_min'],x['end_min']]for x in parts],'target_A_C':old['value_C'],'target_B_C':max((x['value_C']for x in parts),default=old['value_C']),'target_B_C_values':sorted({x['value_C']for x in parts}),'selected_event_id':e.get('event_id'),'considered_event_ids':[e.get('event_id')for e in considered(c,e)],
      'description':tank_description(plan,old,parts,e,target),'thermal_or_energy_consequence':'pending_tank_state_physics'}

def make(w,c,index,candidate_observer=None):
    events=c['VPP_events'];assignment=c.get('input_design_assignment',{});c=dict(c)
    if assignment.get('multi_event_policy')=='joint_all_events':c['_joint_events']=events
    event=next((e for e in events if e['event_id']==assignment.get('focus_event_id')),events[rank(c['case_id'],'focus_event')%len(events)]);pool,future=eligible(c)
    wanted=assignment.get('mechanism',MECHANISMS[(index+rank(w['household_id'],'mechanism_rotation'))%len(MECHANISMS)]);requested=(index+rank(w['household_id'],'intensity_rotation'))%4
    programs=pool['washer']+pool['dishwasher'];handling=[t for t in programs if t['need_id']in future];families=sorted(k for k,v in pool.items()if v)
    possible=mechanism_eligibility(c)
    if assignment.get('eligibility_checked_before_B')and not possible[wanted]:raise ValueError('INPUT_PLAN_ASSIGNED_UNAVAILABLE_MECHANISM:'+wanted)
    actual=wanted if possible[wanted]else next(k for k in ['program_timer','ev_delay','hotwater_preheat','thermal_setpoint','thermal_pause']if possible[k])
    combinations=list(itertools.combinations(families,2))+list(itertools.combinations(families,3));portfolio=(tuple(assignment['portfolio'])if assignment.get('portfolio')else choose(combinations,[c['case_id'],'portfolio']))if actual=='coordinated'else None
    def build(level):
        plan=copy.deepcopy(c['A']);changes=[]
        def apply(kind,family=None):
            fam=family or ('ac'if kind in('thermal_setpoint','thermal_pause','reverse_direction','thermal_precondition')else'ev'if kind in('ev_delay','ev_short_window')else'water_heater'if kind in('hotwater_preheat','hotwater_target')else None)
            selected_id=assignment.get('family_event_assignments',{}).get(fam,event['event_id'])
            local=next((e for e in events if e['event_id']==selected_id),event)
            if fam=='ac':
                targets=events if c.get('_joint_events')else[local]
                for e in targets:
                    use_pre=kind=='thermal_precondition'or(kind=='coordinated'and assignment.get('thermal_action_variant')=='precondition')
                    if use_pre and opportunity_options(c,e):changes.append(make_preconditioning(plan,w,c,e,level))
                    else:changes.append(thermal(plan,w,c,pool['ac'],e,level,pause=kind=='thermal_pause',reverse=kind=='reverse_direction'))
                return
            if family in('washer','dishwasher')or kind in('program_timer','handling_shift'):
                changes.append(program(plan,w,c,pool[family]if family else handling if kind=='handling_shift'else programs,local,level,handling=kind=='handling_shift'));return
            if fam=='ev':changes.append(ev(plan,w,c,pool['ev'],local,level,short=kind=='ev_short_window'));return
            changes.append(tank(plan,w,c,pool['water_heater'],local,level,target=kind=='hotwater_target'))

        if portfolio:
            for family in portfolio:apply('coordinated',family)
        else:apply(actual)
        plan['changed_controls']=[x for x in plan['controls']if x not in c['A']['controls']];return plan,changes
    candidates=[build(l)for l in range(4)]
    if candidate_observer is not None:
        for level,(candidate,_)in enumerate(candidates):candidate_observer(level,candidate)
    sigs=[command_signature(p)for p,_ in candidates];equiv=[l for l in range(4)if sigs[l]==sigs[requested]];canonical=min(equiv);plan,changes=candidates[canonical]
    proposal={'requested_mechanism':wanted,'realized_mechanism':actual,'requested_intensity_design':LEVELS[requested],'intensity_design':LEVELS[canonical],'equivalent_design_levels':[LEVELS[l]for l in equiv],
      'actual_unique_dose_count':len(set(sigs)),'dose_signatures_by_design_level':dict(zip(LEVELS,sigs)),'input_design_assignment':assignment,'explicit_adverse_request':any(x.get('deliberate_reverse_direction')or x.get('boundary_variant')in('opposing_or_excessive_response','beyond_deadline_overreaction')for x in changes),'actual_command_signature':sigs[requested],'same_command_as_A':command_signature(plan)==command_signature(c['A']),
      'strength_is_within_mechanism_not_cross_device_utility':True,'eligibility':possible,'fallback_reason':None if wanted==actual else'no eligible future command;fixed input-only fallback;no resampling',
      'changes':changes,'portfolio_families':list(portfolio)if portfolio else sorted({x['device_family']for x in changes}),'focus_VPP_event_id':event['event_id'],'VPP_event_ids':[e['event_id']for e in events],
      'multi_event_policy':assignment.get('multi_event_policy','single_event'if len(events)==1 else'single_event_stress'),
      'joint_event_ids_considered':[e['event_id']for e in considered(c,event)],
      'all_window_consideration_is_not_success_guarantee':True,
      'VPP_conditioned_generation':True,'selection_uses_outcomes_or_acceptance':False,'human_acceptance':None,'rationale':'VPP request-conditioned input-only coverage;includes under-response,overreaction,adverse direction and service failure;no optimizer or outcome filtering',
      'automatic_execution_authorized':False,'LLM_call_occurred':False,'given_role_policy_sha256':w['role_policy']['policy_sha256'],'policy_attention_is_not_human_rejection':True,
      'command_comparison_basis':'eb.executable_commands.v48;programs,manual actions,AC availability/dual setpoints/fan,tank permission/target,EV permission/stop target;merge equal adjacent controls;ignore IDs,order,projections',
      'adverse_design_intent':any(x.get('requested_reverse_variant')for x in changes)}
    proposal['actual_command_intensity']='unchanged'if proposal['same_command_as_A']else LEVELS[canonical]
    requested_families=list(proposal['portfolio_families']);actual_families=[]
    for family in requested_families:
        aids={d['asset_id']for d in w['parameter_pack']['devices']if family in d['types']}
        def part(p):return {key:[x for x in p[key]if x['asset_id']in aids]for key in('tasks','operations','controls')}
        if command_signature(part(plan))!=command_signature(part(c['A'])):actual_families.append(family)
    proposal['requested_portfolio_families']=requested_families;proposal['portfolio_families']=actual_families
    attention=[]
    for x in changes:
        if 'delta_minutes'in x and abs(x['delta_minutes'])>w['role_policy']['service_policy']['reschedule_limit_min']:attention.append({'code':'GIVEN_SCHEDULE_CHANGE_BOUND_EXCEEDED','need_id':x['need_id'],'requested_change_min':x['delta_minutes']})
        if x['device_family']=='ac'and x['cooling_delta_C']>w['role_policy']['thermal']['temporary_increase_C']:attention.append({'code':'GIVEN_COOLING_INCREASE_BOUND_EXCEEDED','asset_id':x['asset_id'],'requested_change_C':x['cooling_delta_C']})
        if x['device_family']=='ac':attention.append({'code':'HEATING_TOLERANCE_NOT_GIVEN','asset_id':x['asset_id'],'cooling_bound_not_reused_as_heating_preference':True})
    proposal['policy_attention']=attention;return plan,proposal
