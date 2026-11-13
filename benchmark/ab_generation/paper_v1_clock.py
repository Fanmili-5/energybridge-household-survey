"""Read-only source-bound re-audit;never use later guards to decide admission."""
from pathlib import Path
from types import SimpleNamespace
from collections import Counter,defaultdict
from copy import deepcopy
import ast, json, hashlib, math, gzip, sys, time, os

D=Path(__file__).resolve().parent
SOURCE=D/'paper_v1_clock_source.py'
LOCK=json.loads((D/'paper_v1_clock_source.provenance.json').read_text())
assert hashlib.sha256(SOURCE.read_bytes()).hexdigest()==LOCK['full_source_sha256']
TEXT=SOURCE.read_text()
TREE=ast.parse(TEXT)
FUNCTIONS={n.name:n for n in TREE.body if isinstance(n,ast.FunctionDef)}
NS={'__builtins__':__builtins__,'math':math}
def statements(start,stop):
    for node in ast.walk(TREE):
        for field in ('body','orelse','finalbody'):
            body=getattr(node,field,None)
            if not isinstance(body,list):continue
            if any(isinstance(n,ast.stmt) and n.lineno==start for n in body):
                selected=[deepcopy(n) for n in body if isinstance(n,ast.stmt) and start<=n.lineno and n.end_lineno<stop]
                assert selected and selected[0].lineno==start,(start,stop)
                return selected
    raise AssertionError(('source block missing',start,stop))
def code(nodes):
    future=ast.ImportFrom(module='__future__',names=[ast.alias(name='annotations')],level=0)
    return compile(ast.fix_missing_locations(ast.Module(body=[future]+nodes,type_ignores=[])),str(SOURCE),'exec')
for n in TREE.body:
    if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id in {'SP_MIN','SP_MAX','HTG_SP','AGENT_PRE_VPP_PRECOOL_LEAD_H'} for t in n.targets):
        exec(code([deepcopy(n)]),NS)
assert NS['SP_MIN']==22 and NS['SP_MAX']==28 and NS['HTG_SP']==20
needed=set()
def add_function(name):
    if name in needed:return
    needed.add(name)
    node=FUNCTIONS[name]
    for child in ast.walk(node):
        if isinstance(child,ast.Call) and isinstance(child.func,ast.Name) and child.func.id in FUNCTIONS:add_function(child.func.id)
add_function('_agent_next_vpp_checkpoint_hour')
exec(code([deepcopy(FUNCTIONS[n]) for n in needed]),NS)
# Execute actual source statements,not the later _adaptive_v3_* validators.
DECODE_NEXT=code(statements(7132,7137))
CLAMP=code(statements(7123,7126))
TRIGGER=code(statements(8205,8240))
SCHEDULE=code(statements(8741,8758))

def decode_next(current_min,next_min,total_min=1440):
    local={'data':{'next_check_hour':None if next_min is None else next_min/60},
           'sim_h':current_min/60,'total_sim_hours':total_min/60}
    exec(DECODE_NEXT,NS,local)
    return local['nch']
def clamp(value,low=None,high=None):
    local={'raw_sp':value,'sp_lower':NS['SP_MIN'] if low is None else low,
           'sp_upper':NS['SP_MAX'] if high is None else high}
    exec(CLAMP,NS,local)
    return local['sp']
def cooling_rows(plan):
    groups=defaultdict(list)
    for r in plan['controls']:
        if r['kind']=='ac_setpoint':groups[r['asset_id']].append(r)
    return {k:sorted(v,key=lambda r:r['start_min']) for k,v in groups.items()}
def desired_at(rows,minute):
    return next(r['cooling_setpoint_C'] for r in rows if r['start_min']<=minute<r['end_min'])
def next_change(rows,minute):
    value=desired_at(rows,minute)
    return next((r['start_min'] for r in rows if minute<r['start_min']<1440 and r['cooling_setpoint_C']!=value),None)
def replay_clock(rows,context):
    """Literal planned policy at source decision opportunities;not an LLM run."""
    decision=context['decision_min']
    events=[{'id':e.get('event_id','audit-event'),'trigger_h':e['start_min']/60,
             'end_h':e['end_min']/60,'day':1} for e in context['events']]
    loop=SimpleNamespace(next_check=None,daily_plans_done=set())
    ticks=[];minute=decision;previous=decision-5;guard=0
    while minute<1440:
        guard+=1;assert guard<300
        local={'sim_h':minute/60,'psim':previous/60,'dt':5/60,
               'planning_hour':decision/60,'sim_days':1,'loop':loop,'vpp_events':events}
        exec(TRIGGER,NS,local)
        if local['triggered']:
            wanted=desired_at(rows,minute)
            following=next_change(rows,minute)
            nch=decode_next(minute,following)
            local.update(method='agent',is_vpp=local['triggered_vpp'] is not None,
                         res={'next_check_hour':nch,'setpoint':wanted})
            exec(SCHEDULE,NS,local)
            ticks.append({'minute':minute,'setpoint_C':wanted,
                          'requested_next_min':following,'effective_next_min':None if loop.next_check is None else round(loop.next_check*60,8),
                          'event_start':local['triggered_vpp'] is not None})
        future=[1440]
        if loop.next_check is not None and loop.next_check*60>minute+1e-7:future.append(loop.next_check*60)
        future.extend(e['start_min'] for e in context['events'] if e['start_min']>minute+1e-7)
        previous=minute
        minute=min(future)
        if abs(minute-round(minute))<1e-6:minute=round(minute)
    assert ticks and ticks[0]['minute']==decision
    cuts=sorted({decision,1440}|{r['start_min'] for r in rows if decision<r['start_min']<1440}|{t['minute'] for t in ticks})
    mismatch=[]
    for a,z in zip(cuts,cuts[1:]):
        expected=desired_at(rows,a)
        actual=next(t['setpoint_C'] for t in reversed(ticks) if t['minute']<=a)
        if abs(expected-actual)>1e-8:mismatch.append({'start_min':a,'end_min':z,'requested_C':expected,'replayed_C':actual})
    return {'mismatches':mismatch,'ticks':ticks,'scope':'source trigger/next-check scheduling with literal planned outputs;no full LLM,consent,occupancy or EnergyPlus'}

# The actual V1 appliance command consumer, extracted with its original helper closure.
add_function('_apply_appliance_actions')
exec(code([deepcopy(FUNCTIONS[n]) for n in needed]),NS)
apply_appliance_actions=NS['_apply_appliance_actions']
