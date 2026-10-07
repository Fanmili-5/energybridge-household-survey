"""Saved artifact audit and hard/soft distinction probes on school Linux."""
import collections,copy,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];SRC=ROOT.parent/'joint_static_production_20261007_v16'
from assess import assess
from common import read,save,sha,digest

if __name__=='__main__':
 assert sys.platform=='linux'
 name='SELECTION50.json' if (ROOT/'SELECTION50.json').exists() else 'SELECTION1000.json'
 sel=read(ROOT/name);records=[];counts=collections.Counter();first=None
 for h in sel['records']:
  w=read(ROOT/h['world_path']);old=read(SRC/'worlds'/f'{h["household_id"]}.json')
  for k in ['N','G','H6','H7','province','members','ego_relationships','layout','population_weight']:assert w[k]==old[k],(h['household_id'],k)
  assert [r['date'] for r in h['rounds']]==[r['date'] for r in old['random10_date_selection']['dates']]
  assert digest(w['parameter_pack'])==w['parameter_pack_sha256']
  for d in w['parameter_pack']['devices']:
   original=next(x for x in old['parameter_pack']['devices'] if x['asset_id']==d['asset_id']);assert d['parameters']==original['parameters']
  for row in h['rounds']:
   p=read(ROOT/row['pair_path']);assert sha(ROOT/row['pair_path'])==row['pair_sha256']
   assert p['needs_A']==p['needs_B'] and digest(p['A'])==p['A_frozen_before_B_sha256']
   result=assess(p);assert not result['integrity_errors'],result
   compatible=p['design_condition']=='statically_compatible'
   assert compatible==(not result['constraint_or_service_risk_flags'])
   assert all(p[k] is None for k in ['human_adoption','human_relative_preference','simulated_consequences'])
   counts['compatible' if compatible else 'challenge']+=1;counts['family:'+p['proposal']['family']]+=1
   if compatible and first is None:first=p
   records.append({'case_id':p['case_id'],'pair_sha256':row['pair_sha256'],'assessment':result})
 probes=[]
 for label,change,expected in [
  ('B_need_removed',lambda p:p['needs_B'].pop(),'DEMAND_CHANGED_BETWEEN_ARMS'),
  ('A_changed_after_B',lambda p:p['A'].update(predecision_state_hash='x'),'A_REWRITTEN_AFTER_B'),
  ('B_parameter_pack_changed',lambda p:p['B'].update(parameter_pack_sha256='x'),'B:PARAMETER_PACK_CHANGED')]:
  p=copy.deepcopy(first);change(p);r=assess(p);assert expected in r['integrity_errors'],(label,r)
  probes.append({'name':label,'rejected_as_integrity_error':expected})
 report={'status':'pass','host':'school Linux','households':len(sel['records']),'pairs':len(records),'counts':dict(counts),'original_dates_and_source_anchors_preserved':True,'physical_device_parameters_preserved':True,'human_labels_prefilled':0,'EP_runs':0,'hard_error_probes':probes,'records':records}
 save(ROOT/'STATIC_REVIEW.json',report);print(json.dumps({k:v for k,v in report.items() if k!='records'},ensure_ascii=False))
