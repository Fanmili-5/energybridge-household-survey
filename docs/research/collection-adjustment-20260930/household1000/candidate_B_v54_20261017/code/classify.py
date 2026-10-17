"""Three independent annotation axes; never edits an A/B executable request."""
import collections
from common import *
from proposals import command_signature

INTENT_CHANGE_KEYS=('boundary_variant','deliberate_reverse_direction','adverse_variant','requested_reverse_variant')
INTENT_PROPOSAL_KEYS=('explicit_adverse_request','adverse_design_intent')
BAD_VARIANTS={'opposing_or_excessive_response','beyond_deadline_overreaction','explicit_reverse_bounds','pause_opposes_up_request'}
CONTROL_VALUES={'ac_setpoint':('heating_setpoint_C','cooling_setpoint_C','fan_operating_mode'),'tank_setpoint':('value_C',),'ev_charge_window':('stop_at_target_soc',)}

def sign(value):return 'up'if value>1e-8 else'down'if value< -1e-8 else'unchanged'
def summarize(directions):
    values=set(directions)-{'unchanged'}
    return 'unchanged'if not values else next(iter(values))if len(values)==1 else'mixed'
def relation(direction,request):return 'unchanged'if direction=='unchanged'else'mixed'if direction=='mixed'else'aligned'if direction==request else'opposing'
def state(x):return {k:float(x[k])+0. for k in CONTROL_VALUES[x['kind']]}if x else None

def control_direction(kind,a,b):
    if a is None:return 'up'
    if b is None:return 'down'
    if kind=='ac_setpoint':
        return summarize([sign(b['heating_setpoint_C']-a['heating_setpoint_C']),sign(a['cooling_setpoint_C']-b['cooling_setpoint_C']),sign(b['fan_operating_mode']-a['fan_operating_mode'])])
    key='value_C'if kind=='tank_setpoint'else'stop_at_target_soc'
    return sign(b[key]-a[key])

def control_differences(a,b):
    grouped=collections.defaultdict(lambda:{'A':[],'B':[]});result=[]
    for name,plan in [('A',a),('B',b)]:
        for x in plan['controls']:
            if x['kind']not in CONTROL_VALUES:raise ValueError('UNKNOWN_CONTROL:'+x['kind'])
            grouped[x['kind'],x['asset_id']][name].append(x)
    for (kind,aid),rows in sorted(grouped.items()):
        bounds=sorted({x[k]for seq in rows.values()for x in seq for k in ['start_min','end_min']});parts=[]
        for lo,hi in zip(bounds,bounds[1:]):
            values={}
            for name,seq in rows.items():
                active=[x for x in seq if x['start_min']<=lo<hi<=x['end_min']]
                if len(active)>1:raise ValueError('OVERLAPPING_CONTROL:'+aid)
                values[name]=state(active[0])if active else None
            if values['A']==values['B']:continue
            row={'kind':kind,'asset_id':aid,'start_min':lo,'end_min':hi,'A':values['A'],'B':values['B'],'control_request_direction':control_direction(kind,values['A'],values['B'])}
            if parts and parts[-1]['end_min']==lo and all(parts[-1][k]==row[k]for k in ['A','B','control_request_direction']):parts[-1]['end_min']=hi
            else:parts.append(row)
        result.extend(parts)
    return result

def changed_records(a,b,key,ident,fields):
    aa={x[ident]:x for x in a[key]};bb={x[ident]:x for x in b[key]};result=[]
    if set(aa)!=set(bb):raise ValueError('REQUEST_IDENTITIES_CHANGED:'+key)
    for oid in sorted(aa):
        av={k:aa[oid][k]for k in fields};bv={k:bb[oid][k]for k in fields}
        if av==bv:continue
        delta=bv['start_min']-av['start_min']
        result.append({ident:oid,'asset_id':aa[oid]['asset_id'],'kind':aa[oid]['kind'],'A':av,'B':bv,'start_shift_minutes':delta,'time_direction':'delay'if delta>0 else'advance'if delta<0 else'other_command_change'})
    return result

def program_energy(plan,assets,aid,lo,hi):
    total=0.
    for t in plan['tasks']:
        if t['asset_id']!=aid:continue
        p=assets[aid]['parameters'];kw=p.get(t['kind'],p)['power_kw'];minutes=max(0,min(t['end_min'],hi)-max(t['start_min'],lo));total+=kw*minutes/60
    return total

def no_change_reasons(p):
    return [{'basis':'source_B51_unchanged_commands_preserved;no_acceptance_or_no_flexibility_inference'}]if command_signature(p['A'])==command_signature(p['B'])else[]

def classify(p,w):
    q=p['proposal'];a=p['A'];b=p['B'];assets={d['asset_id']:d for d in w['parameter_pack']['devices']};same=command_signature(a)==command_signature(b)
    controls=control_differences(a,b);programs=changed_records(a,b,'tasks','task_id',('kind','asset_id','start_min','end_min'));operations=changed_records(a,b,'operations','operation_id',('kind','asset_id','operator_id','room_id','start_min','end_min'))
    action_designs=[]
    for i,ch in enumerate(q['changes']):
        tags={k:ch[k]for k in INTENT_CHANGE_KEYS if k in ch};selected=any(v in BAD_VARIANTS for v in tags.values()if isinstance(v,str))or bool(ch.get('requested_reverse_variant'))
        action_designs.append({'action_index':i,'device_family':ch['device_family'],'selected_event_id':ch['selected_event_id'],'variant_markers':tags,'unfavourable_variant_selected':selected,'state_aware_request_behavior':ch.get('behavior'),'actual_input_request_basis':ch.get('actual_input_request_basis')})
    intent={'requested_mechanism':q['requested_mechanism'],'generator_branch':q['realized_mechanism'],'requested_device_strengths':q['requested_device_strengths'],'selected_input_vector':q['selected_input_vector'],'candidate_class':q['input_design_assignment']['candidate_class'],'multi_event_policy':q['multi_event_policy'],'action_designs':action_designs,'unfavourable_variant_selected':any(x['unfavourable_variant_selected']for x in action_designs),'source_markers':{k:q[k]for k in INTENT_PROPOSAL_KEYS if k in q},'markers_are_design_provenance_not_observed_badness':True}
    program_aids=sorted({t['asset_id']for t in a['tasks']+b['tasks']});event_records=[]
    family_map={aid:sorted(set(d['types'])&{'ac','washer','dryer','dishwasher','ev','water_heater'})for aid,d in assets.items()}
    for e in p['VPP_events']:
        lo,hi=e['start_min'],e['end_min'];components=[];net=0.
        for aid in program_aids:
            aa=program_energy(a,assets,aid,lo,hi);bb=program_energy(b,assets,aid,lo,hi);delta=bb-aa;net+=delta
            if abs(delta)<=1e-8:continue
            direction=sign(delta)
            components.append({'asset_id':aid,'device_families':family_map[aid],'basis':'literal_fixed_program_power_reference;washer_and_auto_dryer_net_together','direction':direction,'request_relation':relation(direction,e['direction']),'A_requested_kWh':aa,'B_requested_kWh':bb,'requested_power_delta_kw':delta*60/(hi-lo)})
        grouped=collections.defaultdict(list)
        for x in controls:
            if max(lo,x['start_min'])<min(hi,x['end_min']):grouped[x['kind'],x['asset_id']].append(x['control_request_direction'])
        for (kind,aid),directions in sorted(grouped.items()):
            direction=summarize(directions)
            components.append({'asset_id':aid,'device_families':family_map[aid],'basis':'actual_permission_setpoint_fan_or_stop_target_request;not_measured_power','control_kind':kind,'direction':direction,'request_relation':relation(direction,e['direction'])})
        direction=summarize([x['direction']for x in components]);net_kw=net*60/(hi-lo)
        event_records.append({'event_id':e['event_id'],'requested_direction':e['direction'],'target_kw':e['target_kw'],'components':components,'component_direction_summary':direction,'component_request_relation':relation(direction,e['direction']),'known_program_net_direction':sign(net_kw),'known_program_response_reference_kw':net_kw*(1 if e['direction']=='up'else-1),'known_program_reference_scope':'fixed program requests only;EV,HVAC,tank and physical feasibility excluded','whole_physical_response_kw':None,'whole_target_met':None,'human_acceptance':None,'component_relation_is_not_a_whole_portfolio_success_failure_or_acceptance_label':True})
    # This is a fixed-charge input-state reference, separate from literal
    # permission direction and from continuous-SOC/full-physics delivery.
    for e,record in zip(p['VPP_events'],event_records):
        evrefs=[]
        for aid,device in assets.items():
            if 'ev'not in device['types']:continue
            values=[]
            for plan in (a,b):
                minutes=sum(max(0,min(x['actual_charge_end_min'],e['end_min'])-max(x['start_min'],e['start_min']))-max(0,min(x['actual_charge_end_min'],e['end_min'])-max(x['actual_charge_end_min']-10,x['start_min'],e['start_min']))*(1-x['last_step_power_fraction']) for x in plan['controls']if x['kind']=='ev_charge_window'and x['asset_id']==aid)
                values.append(minutes/60*device['parameters']['charger_kw'])
            delta=(values[1]-values[0])*60/(e['end_min']-e['start_min'])
            evrefs.append({'asset_id':aid,'A_reference_kWh':values[0],'B_reference_kWh':values[1],'power_delta_kw':delta,'response_relation':relation(sign(delta),e['direction'])})
        record['EV_event_state_reference']={'devices':evrefs,'basis':'fixed charger and A common connection-state projection;not continuous B SOC or measured power','literal_permission_relation_is_separate':True}
    changed_aids={x['asset_id']for x in controls+programs+operations};families=sorted({f for aid in changed_aids for f in family_map[aid]if f!='dryer'})
    actual={'any_command_change':not same,'comparison_group':'identical_commands'if same else'changed_commands','actual_device_strengths':q['actual_device_strengths'],'equivalent_input_vectors':q['equivalent_input_vectors'],'actual_unique_dose_count':q['actual_unique_dose_count'],'changed_device_families':families,'program_changes':programs,'manual_operation_changes':operations,'control_changes':controls,'events':event_records,'no_change_reasons':no_change_reasons(p),'input_reference_not_observed_execution':True}
    failure={'has_given_constraint_conflict':bool(p['assessment_B']['constraint_flags']),'flags':copy.deepcopy(p['assessment_B']['constraint_flags']),'status':'given_request_conflict'if p['assessment_B']['constraint_flags']else'no_conflict_in_given_checks','full_physical_failure':None,'human_rejection':None,'scope':'literal requested operations and given resources;not inevitable realized execution'}
    if same and(controls or programs or operations):raise ValueError('NOOP_WITH_CHANGED_ACTIONS')
    return {'schema':'eb.B_classification.v54','design_intent':intent,'actual_actions':actual,'constraint_failure':failure,'classification_does_not_choose_modify_repair_or_filter_B':True}

def update_pair(p,w,source_ref,rules_sha):
    result=copy.deepcopy(p);classification=classify(p,w);q=result['proposal']
    for key in INTENT_PROPOSAL_KEYS:q.pop(key,None)
    for ch in q['changes']:
        for key in INTENT_CHANGE_KEYS:ch.pop(key,None)
    q['classification_record']='classification';q['source_B_proposal_sha256']=digest(p['proposal'])
    result.update(schema='eb.alternative_pair.v49',classification=classification,rules_sha256=rules_sha,source_B=source_ref,B_frozen_sha256=digest(p['B']),source_generation_rules_sha256=p['rules_sha256'],classification_only_update=True)
    result.pop('pair_content_sha256',None);result['pair_content_sha256']=digest(result)
    return result
