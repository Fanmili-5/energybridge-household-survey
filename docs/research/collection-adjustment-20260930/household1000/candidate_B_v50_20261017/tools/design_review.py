import json,collections
from pathlib import Path
s=Path(__file__).resolve().parents[1]
b=json.loads((s/'PAIR_BINDINGS10000.json').read_text());counts=collections.Counter();flags=collections.Counter();minutes=collections.Counter();cases={};non_event=[]
for h in b['records']:
 for r in h['rounds']:
  if r['inherited_B49_pair']:continue
  p=json.loads((s/r['path']).read_text());ac=p['classification']['actual_actions'];cs=p['assessment_B']['constraint_flags'];rels=[e['component_request_relation'] for e in ac['events']]
  if cs:
   flags.update(set(x['code'] for x in cs));cases.setdefault('conflict',{'case_id':p['case_id'],'flags':cs,'changes':p['proposal']['changes']})
  if 'opposing'in rels:counts['new_cases_with_opposing_component_request']+=1;cases.setdefault('opposing',{'case_id':p['case_id'],'classification':ac,'changes':p['proposal']['changes']})
  if all(x=='unchanged' for x in rels):counts['changed_commands_but_all_event_components_net_unchanged']+=1;non_event.append(p['case_id'])
  for x in ac['program_changes']:minutes[x['start_shift_minutes']]+=1
  counts['new_manual_changes']+=bool(ac['manual_operation_changes']);counts['new_control_changes']+=bool(ac['control_changes'])
  counts['pre08_B_change']+=any(x['start_min']<480 for x in ac['control_changes'])
  if h['household_id'] in {x['household_id'] for x in json.loads((s/'SUBSET50.json').read_text())['records']}:counts['subset50_revised']+=1
out={'counts':dict(counts),'new_conflict_case_codes':dict(flags),'program_shift_minutes':dict(sorted(minutes.items())),'examples':cases,'all_event_net_unchanged_case_ids':non_event}
(s/'DESIGN_REVIEW.json').write_text(json.dumps(out,ensure_ascii=False,indent=2));print(json.dumps({k:v for k,v in out.items() if k!='examples'},ensure_ascii=False));print('examples',json.dumps(cases,ensure_ascii=False)[:7000])
