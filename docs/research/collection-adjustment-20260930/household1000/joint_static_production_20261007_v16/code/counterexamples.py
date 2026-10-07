"""Falsification probes on an actual produced case, not a parallel toy implementation."""
import copy
from common import *
from validate import validate
def main():
    school_guard();p=None
    for path in sorted((OUT/'pairs').glob('*/*.json')):
        q=read(path);ks={n['kind'] for n in q['needs_A']}
        if {'washer','dryer','water_heater','ev'}<=ks:p=q;break
    if p is None:raise RuntimeError('No suitable generated counterexample seed')
    assert not validate(p)
    probes=[]
    def check(name,mutation,want):
        q=copy.deepcopy(p);mutation(q);errors=validate(q)
        if want not in errors:raise RuntimeError((name,want,errors))
        probes.append({'name':name,'expected':want,'rejections':errors})
    check('same_need_quantity',lambda q:q['needs_B'][0].update(quantity=999),'DEMAND_CHANGED_BETWEEN_ARMS')
    check('lost_task',lambda q:q['B']['tasks'].pop(),'B:NEED_LOST_OR_DUPLICATED')
    check('operator_context',lambda q:q['world']['operator_windows'].clear(),'B:OPERATOR_UNAVAILABLE')
    check('branch_capacity',lambda q:q['world']['circuit_limit_kw'].update(wet_appliances=.1),'B:DECLARED_CIRCUIT_CAPACITY')
    check('A_independence',lambda q:q['A']['tasks'][0].update(start_min=0),'A_REWRITTEN_AFTER_B')
    def tank(q):next(c for c in q['B']['controls'] if c['kind']=='tank_setpoint').update(value_C=80)
    check('tank_limit',tank,'B:TANK_MAXIMUM')
    def overlap(q):
        wash=next(t for t in q['B']['tasks'] if t['kind']=='washer');dry=next(t for t in q['B']['tasks'] if t['kind']=='dryer')
        dry.update(start_min=wash['start_min'],end_min=wash['start_min']+90)
    check('one_physical_combo',overlap,'B:PHYSICAL_RESOURCE_OVERLAP')
    def ev(q):
        c=next(c for c in q['B']['controls'] if c['kind']=='ev_charge_window');n=next(n for n in q['needs_A'] if n['kind']=='ev');c['end_min']=n['departure_min']+10
    check('departure_bound',ev,'B:EV_CONNECTION')
    def retro(q):
        c=next(c for c in q['B']['controls'] if c['kind']=='tank_setpoint');c['start_min']=q['decision_abs_min']-10
    check('no_retroactive_heat',retro,'CONTROL_PREFIX_CHANGED')
    save(OUT/'COUNTEREXAMPLE_REVIEW.json',{'actual_case_id':p['case_id'],'valid_original':True,'probes':probes,'EP_started':0})
    print({'actual_case_counterexamples':len(probes),'correctly_rejected':len(probes)},flush=True)
if __name__=='__main__':main()
