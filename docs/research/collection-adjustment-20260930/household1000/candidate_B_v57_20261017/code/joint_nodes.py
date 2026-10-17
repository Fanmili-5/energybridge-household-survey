"""Resolve original A anchors against completed joint B, without rescheduling."""
from common import *

def relation(plan,f):
    node=f['selected_node'];kind=node['kind'];ref=node['reference'];minute=node['minute']
    ops={o['operation_id']:o for o in plan['operations']}
    if kind=='previous_batch_cleared':
        other=next((o for o in plan['operations']if o['need_id']==ref and o['kind']=='unload'),None)
        minute=other['end_min']if other else None
    elif ref in ops:
        other=ops[ref]
        minute=other['start_min']-10 if kind=='before_next_use'else other['start_min']if kind in('original_retrieval','finish_at_original_retrieval')else other['end_min']
    action={'load_min':f['B_load_min'],'unload_min':f['B_unload_min'],'finish_min':f['B_chain_finish_min'],'program_start_min':f['B_start_min']}[node['field']]
    return {'status':'reached_in_joint_B'if action==minute else'A_anchor_shifted_in_joint_B','original_A_node':copy.deepcopy(node),'referenced_joint_B_min':minute,'actual_B_action_min':action,'exact_joint_B_node_reached':action==minute,'does_not_infer_one_visit_from_time_proximity':True,'commands_moved_to_reach_node':False}

def reconcile(pair):
    revised={};changed=[]
    for f in pair['B'].get('program_request_plans',[]):
        if f['selected_node']is None:continue
        r=relation(pair['B'],f);key=(f['controller_key'],f['need_id'])
        revised[key]={'joint_B_node_relation':r,'life_node_reached':r['exact_joint_B_node_reached'],'actual_request_basis':'life_node_request'if r['exact_joint_B_node_reached']else'A_reference_anchor_not_reached_in_joint_B','given_A_anchor_is_design_provenance':True}
        if not r['exact_joint_B_node_reached']:changed.append(f['need_id'])
    def visit(x):
        if isinstance(x,list):
            for a in x:visit(a)
        elif isinstance(x,dict):
            key=(x.get('controller_key'),x.get('need_id'))
            if key in revised and 'selection_rule'in x and 'selected_node'in x:
                x.update(copy.deepcopy(revised[key]))
            for k,v in list(x.items()):
                if k not in('joint_B_node_relation','A','A_source','days','needs_A','needs_B'):visit(v)
    visit(pair)
    return {'life_node_plans':len(revised),'stale_original_A_anchors':changed,'completed_B_checked':True,'no_command_repair':True}
