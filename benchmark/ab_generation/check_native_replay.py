"""Public-fixture whole-plan command replay against unmodified EB classes.

This verifies appliance command semantics, not household/thermal physics. The
EV capacity/arrival SOC below are declared public-test parameters, not estimates
for a V9 household. No raw household or human answers enter this check.
"""
from pathlib import Path
import argparse,copy,hashlib,importlib.util,json,math,sys
from benchmark.ab_generation.common import read,digest
from benchmark.ab_generation.eb_alignment import audit,compact_plan,runs,CONTIGUOUS
from benchmark.ab_generation.test_eb_alignment import generation_context
from benchmark.ab_generation.unified.candidates import generate_day,prepare
from benchmark.ab_generation.unified.contract import entry_config
from benchmark.ab_generation.model import apply
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--source',action='append',required=True,metavar='LABEL=FILE',help='unmodified EB appliance_sim.py; repeat for source snapshots')
parser.add_argument('--output',type=Path,required=True)
args=parser.parse_args()
sources=[]
for entry in args.source:
 label,path=entry.split('=',1);sources.append((label,Path(path)))
c=generation_context();next(d for d in c['devices'] if 'ev' in d['types'])['parameters']['charge_session_policy']=CONTIGUOUS
cfg=entry_config();cfg.update(rows_per_unit=2,queries_per_row=2,oracle_native_encoding_budget=128)
generated=generate_day(c,cfg);assert generated['rows']
prepared=prepare(c,cfg);plans=[('A',c['A'],[])]
for row in generated['rows']:
 plans.append(('B',apply(prepared['A'],row['patches']),row['components']))
modules=[]
for label,path in sources:
 spec=importlib.util.spec_from_file_location('native_'+label,path);mod=importlib.util.module_from_spec(spec);sys.modules[spec.name]=mod;spec.loader.exec_module(mod)
 blob=hashlib.sha1(b'blob '+str(path.stat().st_size).encode()+b'\0'+path.read_bytes()).hexdigest()
 modules.append((label,mod,blob))
results=[]
for label,mod,blob in modules:
 for index,(side,plan,children) in enumerate(plans):
  # Component summaries deliberately omit charging profiles: replay must be
  # derived from the actual B instruction windows and the fixed A state.
  check=audit(prepared,plan,children,side=side);assert check['passed'],check
  end=math.ceil(max([prepared['horizon_min'][1]]+[t['end_min'] for t in plan['tasks']])/10)*10
  begin=prepared['decision_min']//10*10
  task_results=[]
  for task in plan['tasks']:
   original=next(t for t in c['A']['tasks'] if t['task_id']==task['task_id'])
   device=next(d for d in c['devices'] if d['asset_id']==task['asset_id'])
   power=device['parameters'][task['kind']]['power_kw']
   appliance=mod.ShiftableAppliance(task['kind'],dict(present=True,earliest_h=0,latest_h=24,preferred_h=0,duration_h=(original['end_min']-original['start_min'])/60,power_kw=power),sim_days=end//1440+2,explicit_only=True)
   day=task['start_min']//1440
   assert appliance.shift(day,task['start_min']/60),(label,side,index,task)
   actual=[]
   for t in range(begin,end,10):
    p=appliance.step(t/60,1/6,any(e['start_min']<=t<e['end_min'] for e in prepared['events']))
    expected=power if task['start_min']<=t<task['end_min'] else 0
    assert abs(p-expected)<1e-7,(label,side,index,task['task_id'],t,p,expected)
    if p>1e-8:actual.append(dict(start_min=t,end_min=t+10))
   assert runs(actual)==[[task['start_min'],task['end_min']]]
   task_results.append(dict(kind=task['kind'],continuous=True))
  ev_summary=check['ev_runs'][0];energy=ev_summary['required_A_grid_kWh']
  # These are explicit semantic-test constants, not inferred survey data.
  capacity=10.;efficiency=1.;target=.85;initial=target-energy*efficiency/capacity
  assert 0<=initial<=target
  ev=mod.EVCharger(dict(present=True,charger_kw=3.,capacity_kwh=capacity,target_soc=target,min_soc=0.,initial_soc=initial,arrival_h=18.,departure_h=6.,daily_drive_kwh=0.,efficiency=efficiency),sim_days=end//1440+2,explicit_only=True)
  controls=[r for r in plan['controls'] if r['kind']=='ev_charge_window']
  old=[r for r in c['A']['controls'] if r['kind']=='ev_charge_window']
  changed=digest(controls)!=digest(old)
  for day in range(end//1440+2):
   if not changed:assert ev.set_charge_mode(day,'normal')
   else:
    segments=[]
    for r in controls:
     a=max(r['start_min'],day*1440);z=min(r['end_min'],(day+1)*1440)
     if a<z:segments.append(dict(start_min=a-day*1440,end_min=z-day*1440))
    spans=runs(segments)
    assert len(spans)<=1,'public fixture must encode one native window per day'
    a,z=spans[0] if spans else (0,0)
    assert ev.set_charge_window(day,a/60,z/60)
  actual=[];delivered=0.
  for t in range(begin,end,10):
   power=ev.step(t/60,1/6,any(e['start_min']<=t<e['end_min'] for e in prepared['events']))
   if power>1e-8:actual.append(dict(start_min=t,end_min=t+10))
   delivered+=power/6
  assert runs(actual)==ev_summary['runs_min'],(label,index,runs(actual),ev_summary)
  assert abs(delivered-ev_summary['delivered_nominal_grid_kWh'])<1e-7
  results.append(dict(target=label,source_blob_sha1=blob,side=side,public_plan_index=index,program_checks=len(task_results),EV_check=True,passed=True))
summary=dict(passed=True,scope='actual public A/B instructions replayed through unmodified EB appliance classes; not V9 household production or EnergyPlus',candidate_B_count=len(generated['rows']),plan_count=len(plans),snapshot_count=len(modules),program_and_EV_checks=sum(x['program_checks']+1 for x in results),instruction_digest=digest([p for _,p,_ in plans]),results=results,new_V9_questions=0,EnergyPlus_runs=0,human_answers=0,training_started=False)
args.output.parent.mkdir(parents=True,exist_ok=True)
args.output.write_text(json.dumps(summary,indent=2)+'\n')
print(json.dumps({k:v for k,v in summary.items() if k!='results'}))
