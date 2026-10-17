"""Requested command chronology; never conflate this with thermal response."""
from common import *
from proposals import command_signature
DERIVED={'actual_charge_end_min','last_step_power_fraction','battery_energy_kWh','grid_energy_kWh','projection_basis','requested_battery_energy_kWh','projected_battery_energy_kWh'}
def prefix(plan,end):
    result={}
    for key in('tasks','operations','controls'):
        seq=[]
        for x in plan[key]:
            if x['start_min']>=end:continue
            q={k:v for k,v in x.items()if k not in DERIVED};q['end_min']=min(end,q['end_min']);seq.append(q)
        result[key]=sorted(seq,key=canonical)
    return result

def event_relations(c,plan,events):
    same=command_signature(c['A'])==command_signature(plan)
    out=[]
    for e in events:
        before=prefix(c['A'],e['start_min'])==prefix(plan,e['start_min']);until_end=prefix(c['A'],e['end_min'])==prefix(plan,e['end_min'])
        kind='no_command_change'if same else'only_after_event'if until_end else'first_changes_during_event'if before else'changes_before_event'
        out.append({'event_id':e['event_id'],'requested_command_relation':kind,'commands_identical_through_event_end':until_end,'physical_response_kw':None,'not_a_success_or_acceptance_label':True,'early_thermal_changes_can_affect_later_events':True})
    return out
