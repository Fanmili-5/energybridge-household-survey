"""Read-only structural inventory for the independent production audit."""
import json,sys
from pathlib import Path
O=Path(__file__).resolve().parents[1];H=O.parent;S=O/'source_snapshots'
def read(p):return json.loads(p.read_text())
if sys.platform!='linux':raise RuntimeError('School Linux only')
f=read(S/'v6/ORDINARY_CITY_FRAME.json')
al=read(S/'v6/ORDINARY_ALLOCATION1000.json')
v6=read(S/'v6/HOUSEHOLDS1000_JOINT_CANDIDATE.json')
v7=read(S/'v7/HOUSEHOLDS1000_JOINT_GEOMETRY_CANDIDATE.json')
n=H/'evidence_conditioned_production_20261009_v19';s=read(n/'SELECTION1000.json');w=read(n/s['records'][0]['world_path'])
report={'frame_keys':list(f),'frame_scalars':{k:v for k,v in f.items() if not isinstance(v,(list,dict))},'frame_integer_allocation':f['integer_allocation'],'allocation_keys':list(al),'allocation_report':al['report'],'v6_keys':list(v6),'v7_keys':list(v7),'profile':v7['profiles'][0],'world_keys':list(w),'world_scalars':{k:v for k,v in w.items() if not isinstance(v,(list,dict))},'world_source_links':w.get('source_links'),'world_layout':w['layout'],'world_economic_reference':w['economic_reference'],'world_evidence_layer':w['evidence_layer'],'world_operating_context':w['operating_context'],'member':w['members'][0],'parameter_pack':w['parameter_pack'],'routine':w['routine'],'service_semantics':w['service_semantics'],'selection_record':s['records'][0]}
(O/'STRUCTURE_INVENTORY.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
print({'written':'STRUCTURE_INVENTORY.json','economic_reference':w['economic_reference'],'evidence_layer':w['evidence_layer'],'operating_context':w['operating_context'],'housing':v7['profiles'][0]['housing'],'stock_features':w['layout']['stock_reference_features']},flush=True)
