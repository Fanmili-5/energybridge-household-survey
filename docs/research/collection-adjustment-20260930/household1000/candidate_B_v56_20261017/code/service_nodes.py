"""Input-derived service nodes and full load-to-unload asset occupation.

A service node is only reported when its actual operation/time is reached.
Unreachable nodes never become a clipped proxy node. Declared technical-dose
and constraint-boundary requests remain separate, including unsuccessful B.
"""
import math
from common import *
def ceil10(x):return int(math.ceil(x/10-1e-9)*10)

def asset_holds(source,aid,excluded=()):
    ops=source['A']['operations'];result=[]
    for load in ops:
        if load['kind']!='load'or load['asset_id']!=aid or load['need_id']in excluded:continue
        unload=next((o for o in ops if o['kind']=='unload'and o['need_id']==load['need_id']),None)
        result.append({'need_id':load['need_id'],'start_min':load['start_min'],'end_min':unload['end_min']if unload else 4320})
    return result

def hold_conflicts(holds,load_min,unload_min):
    return [x['need_id']for x in holds if overlap((load_min,unload_min+10),(x['start_min'],x['end_min']))]

def input_nodes(source,a,need,load,unload,holds,loading_moves):
    nodes={}
    def add(field,t,kind,reference):
        t=ceil10(t);key=digest([field,t,kind,reference])[:14]
        nodes[key]={'node_id':key,'field':field,'minute':t,'kind':kind,'reference':reference}
    if loading_moves:
        for t,kind in [(need['release_min'],'service_release'),(DECISION,'decision_ready')]:add('load_min',t,kind,need['need_id'])
        for h in holds:add('load_min',h['end_min'],'previous_batch_cleared',h['need_id'])
    else:add('program_start_min',load['end_min'],'original_loading_complete',load['operation_id'])
    add('unload_min',unload['start_min'],'original_retrieval',unload['operation_id'])
    add('finish_min',unload['start_min'],'finish_at_original_retrieval',unload['operation_id'])
    add('unload_min',need['deadline_min']-10,'service_deadline',need['need_id'])
    for op in source['A']['operations']:
        if op['need_id']==need['need_id']:continue
        if loading_moves and(op['operator_id']==load['operator_id']or op['room_id']==load['room_id']):add('load_min',op['end_min'],'prior_commitment_ends',op['operation_id'])
        if op['operator_id']==unload['operator_id']and op['room_id']==unload['room_id']:
            add('unload_min',op['end_min'],'existing_room_visit',op['operation_id'])
        if op['asset_id']==a['asset_id']and op['kind']=='load'and op['start_min']>a['start_min']:add('unload_min',op['start_min']-10,'before_next_use',op['operation_id'])
    for day in source['days']:
        base=(dt.date.fromisoformat(day['date'])-dt.date.fromisoformat(source['date'])).days*1440
        for role,op in [('load',load),('unload',unload)]:
            for lo,hi in day['activity']['operator_windows_min'].get(op['operator_id'],[]):
                if role=='load'and loading_moves:add('load_min',base+lo,'operator_available',op['operator_id']+':'+day['date'])
                if role=='unload':
                    add('unload_min',base+lo,'operator_return',op['operator_id']+':'+day['date'])
                    add('unload_min',base+hi-10,'before_operator_leaves',op['operator_id']+':'+day['date'])
            for reservation in day['shared']['facility_reservations']:
                if reservation['room_id']==op['room_id']:add('load_min'if role=='load'else'unload_min',base+reservation['end_min'],'room_reservation_ends',op['room_id']+':'+day['date'])
    return list(nodes.values())

def enumerate_candidates(source,aid,family,operation_allowed):
    out=[];oldtasks={x['task_id']:x for x in source['B']['tasks']};oldops={x['operation_id']:x for x in source['B']['operations']}
    for a in source['A']['tasks']:
        if a['asset_id']!=aid or a['kind']!=family or a['start_min']<DECISION or a['start_min']==oldtasks[a['task_id']]['start_min']:continue
        need=next(n for n in source['needs_A']if n['need_id']==a['need_id']);excluded={a['need_id'],a['need_id']+':dry'};chain=[t for t in source['A']['tasks']if t['need_id']in excluded]
        load=next(o for o in source['A']['operations']if o['need_id']==a['need_id']and o['kind']=='load');unload=next(o for o in source['A']['operations']if o['need_id']==a['need_id']and o['kind']=='unload')
        moving=oldops[load['operation_id']]['start_min']!=load['start_min'];dose=ceil10((a['end_min']-a['start_min'])*2);duration=max(t['end_min']for t in chain)-a['start_min'];holds=asset_holds(source,aid,excluded);nodes=input_nodes(source,a,need,load,unload,holds,moving)
        lo=max(DECISION,a['start_min']-dose+duration,unload['start_min']-dose);hi=min(need['deadline_min']-10,a['start_min']+dose+duration+need['maximum_retrieval_wait_min'],unload['start_min']+dose)
        available=[t for t in range(ceil10(lo),int(hi)+1,10)if operation_allowed(source,unload,t,excluded)]
        rows=[];boundary=[]
        for delta in range(-dose,dose+1,10):
            start=a['start_min']+delta;lt=load['start_min']+delta if moving else load['start_min'];finish=start+duration
            if start<DECISION or lt<need['release_min']or(moving and lt<DECISION)or lt+10>start or finish>need['deadline_min']:continue
            if not operation_allowed(source,load,lt,excluded):continue
            eligible=[t for t in available if finish<=t<=finish+need['maximum_retrieval_wait_min']]
            if not eligible:continue
            # Preserve meaningful alternative visits without enumerating random
            # retrieval times. Immediate completion is a physical candidate, not
            # an external life node by itself.
            times={eligible[0]}
            if unload['start_min']in eligible:times.add(unload['start_min'])
            times.update(n['minute']for n in nodes if n['field']=='unload_min'and n['minute']in eligible)
            for ut in sorted(times):
                row={'delta_min':delta,'load_min':lt,'unload_min':ut,'finish_min':finish,'program_start_min':start};bad=hold_conflicts(holds,lt,ut)
                row['asset_hold_conflicts']=bad
                row['life_node_ids']=[n['node_id']for n in nodes if row[n['field']]==n['minute']]
                if bad:boundary.append(row)
                else:rows.append(row)
        out.append({'need_id':a['need_id'],'A_start_min':a['start_min'],'A_load_min':load['start_min'],'A_unload_min':unload['start_min'],'release_min':need['release_min'],'deadline_min':need['deadline_min'],'loading_moves':moving,'chain':chain,'asset_holds_A':holds,'life_nodes':nodes,'feasible_candidates':rows,'constraint_boundary_candidates':boundary})
    return out

def _changed(q,c):return q['delta_min']!=0 or q['load_min']!=c['A_load_min']or q['unload_min']!=c['A_unload_min']

def reachable_choice(c,options,policy):
    priorities={'load_then_run':['service_release','previous_batch_cleared','original_loading_complete','operator_available','decision_ready','prior_commitment_ends','finish_at_original_retrieval','original_retrieval','existing_room_visit','operator_return','before_operator_leaves','before_next_use','service_deadline'],
      'retrieve_at_existing_visit':['original_retrieval','finish_at_original_retrieval','existing_room_visit','operator_return','service_release','previous_batch_cleared','original_loading_complete','operator_available','before_operator_leaves','before_next_use','service_deadline'],
      'before_next_service':['before_next_use','service_deadline','before_operator_leaves','original_retrieval','finish_at_original_retrieval','service_release','previous_batch_cleared','original_loading_complete','operator_available','existing_room_visit','operator_return']}
    order=priorities[policy];nodes={x['node_id']:x for x in c['life_nodes']};choices=[]
    ready={'service_release','previous_batch_cleared','original_loading_complete','operator_available','decision_ready','prior_commitment_ends','room_reservation_ends'}
    for q in options:
        matches=[nodes[i]for i in q['life_node_ids']]
        for node in matches:
            # An unchanged A operation cannot itself justify a different timer.
            # The selected exact node must move that command, or make the
            # changed whole chain finish exactly at the original retrieval.
            if node['field']=='load_min'and q['load_min']==c['A_load_min']:continue
            if node['field']=='unload_min'and q['unload_min']==c['A_unload_min']:continue
            if node['field']=='program_start_min'and q['program_start_min']==c['A_start_min']:continue
            if node['field']=='finish_min'and q['delta_min']==0:continue
            if node['kind']not in order:continue
            effort=abs(q['load_min']-c['A_load_min'])+abs(q['unload_min']-c['A_unload_min'])
            choices.append(((order.index(node['kind']),effort,abs(q['delta_min']),q['finish_min'],node['node_id']),q,node))
    if not choices:return None
    _,q,node=min(choices,key=lambda z:z[0]);return {**q,'selected_node':node,'request_basis':'life_node_request','selection_rule':'exact_input_service_node','individual_A_context_feasible':True}

def select_program(source,a,native,old_delta,context,parameters):
    c=next(x for x in context['program_service_candidates']if x['need_id']==a['need_id']);e=context['event'];behavior=context['behavior'];direction=e['direction']
    if behavior=='opposing_request':direction='up'if direction=='down'else'down'
    opts=[q for q in c['feasible_candidates']if abs(q['delta_min'])<=native and abs(q['load_min']-c['A_load_min'])<=native and abs(q['unload_min']-c['A_unload_min'])<=native and _changed(q,c)]
    def overlap_minutes(t,delta):return max(0,min(t['end_min']+delta,e['end_min'])-max(t['start_min']+delta,e['start_min']))
    def impact(q):return sum((overlap_minutes(t,q['delta_min'])-overlap_minutes(t,0))/60*parameters.get(t['kind'],parameters)['power_kw']for t in c['chain'])*(1 if direction=='up'else-1)
    responding=[q for q in opts if impact(q)>1e-8]
    if behavior in('normal_response','partial_response','opposing_request')and responding:
        goal=e['target_kw']*(e['end_min']-e['start_min'])/60*(.5 if behavior=='partial_response'else 1.);enough=[q for q in responding if impact(q)>=goal-1e-8]
        cost=lambda q:(abs(q['delta_min']),abs(q['load_min']-c['A_load_min'])+abs(q['unload_min']-c['A_unload_min']),q['delta_min'])
        q=min(enough,key=cost)if enough else min(responding,key=lambda q:(-impact(q),cost(q)))
        return {**q,'request_basis':'feasible_VPP_candidate','selection_rule':'fixed_program_event_target','selected_node':None,'individual_A_context_feasible':True}
    if behavior!='service_pressure':
        choice=reachable_choice(c,opts,context['service_fallback_policy'])
        if choice:return choice
    if opts:
        # A declared technical-dose request is allowed in this benchmark. It is
        # never described as reaching an unavailable life node or VPP benefit.
        sign=1 if old_delta>=0 else -1;desired=sign*native
        q=min(opts,key=lambda q:(abs(q['delta_min']-desired),abs(q['unload_min']-c['A_unload_min']),abs(q['load_min']-c['A_load_min'])))
        return {**q,'request_basis':'dose_boundary_request','selection_rule':'declared_dose_without_reachable_life_node'if behavior!='service_pressure'else'explicit_service_pressure_dose','selected_node':None,'individual_A_context_feasible':True}
    # No malformed data or artificial extra operation: submit the bounded
    # timing request, preserve the failed contract and assess it independently.
    load=next(o for o in source['A']['operations']if o['need_id']==a['need_id']and o['kind']=='load');unload=next(o for o in source['A']['operations']if o['need_id']==a['need_id']and o['kind']=='unload')
    delta=max(native,need_floor(source,a,c,load));lt=load['start_min']+delta if c['loading_moves']else load['start_min'];finish=max(t['end_min']for t in c['chain'])+delta;ut=max(finish,unload['start_min']+delta if c['loading_moves']else unload['start_min'])
    return {'delta_min':delta,'program_start_min':a['start_min']+delta,'load_min':lt,'unload_min':ut,'finish_min':finish,'asset_hold_conflicts':hold_conflicts(c['asset_holds_A'],lt,ut),'request_basis':'boundary_pressure_request','selection_rule':'unavailable_contract_request_retained','selected_node':None,'individual_A_context_feasible':False}

def need_floor(source,a,c,load):
    return max(DECISION-a['start_min'],c['release_min']-load['start_min'],DECISION-load['start_min'])if c['loading_moves']else max(DECISION,load['end_min'])-a['start_min']
