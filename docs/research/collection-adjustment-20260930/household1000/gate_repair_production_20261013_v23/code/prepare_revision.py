"""Prepare V23 provenance/locks without resampling V22 worlds or A/B."""
from common import *
import collections,copy
ENGINE=Path('/home/hku_user3/energybridge-compute/EnergyPlus-24-1-0/energyplus')
def main():
 school_guard();prior=BASE/'causal_reference_production_20261010_v22'
 sel=read(OUT/'SELECTION1000.json');oldsel=read(prior/'SELECTION1000.json')
 unchanged=[]
 for h,old in zip(sel['records'],oldsel['records']):
  assert h['household_id']==old['household_id']
  for path,key in [(h['world_path'],'world_sha256')]:
   assert sha(OUT/path)==old[key]==sha(prior/path)
  assert [(c['date'],c['pair_sha256']) for c in h['rounds']]==[(c['date'],c['pair_sha256']) for c in old['rounds']]
  for c in h['rounds']:assert sha(OUT/c['pair_path'])==sha(prior/c['pair_path'])==c['pair_sha256']
  unchanged.append({'household_id':h['household_id'],'world_sha256':h['world_sha256'],'original_dates_and_pairs_unchanged':True})
 for name in ['SELECTION1000.json','SELECTION50.json']:
  d=read(OUT/name)
  for h in d['records']:
   old={k:h.pop(k) for k in ('compatible_rounds','compatible_input_dates','excluded_patterns','feasible_patterns') if k in h}
   if old:h['historical_V17_selection_diagnostics']=old
  d['validation_revision']='v23';d['design_data_version']='frozen V22';save(OUT/name,d)
 f=read(OUT/'FIELD_EVIDENCE1000.json')
 for r in f['households']:r['physical_outcomes']='V23 pending current readback; only original50 can become verified, other950 held'
 save(OUT/'FIELD_EVIDENCE1000.json',f)
 proof=read(BASE/'review_20261010_v22_v1/FRONTEND_BROWSER_REVIEW.json')
 prior_js={sha(p) for p in (prior/'frontend_release/households').glob('*/joint-view.js')}
 current_js={sha(p) for p in (OUT/'frontend_release/households').glob('*/joint-view.js')}
 assert prior_js==current_js and len(current_js)==1
 proof.update(renderer_sha256=next(iter(current_js)),source_actual_browser_review='review_20261010_v22_v1',
    inherited_only_for_identical_renderer=True,current_production_acceptance_updated=False)
 save(OUT/'FRONTEND_BROWSER_REVIEW.json',proof)
 files={ENGINE,SCHEMA_PATH,PILOT/'SELECTION50.json',SOURCE/'DELIVERY.json',
  UP/'experiments/models/family_home/family_simple_3day.idf',
  BASE/'data_production_audit_20261009_v1/source_snapshots/v6/ORDINARY_CITY_FRAME.json',
  BASE/'data_production_audit_20261009_v1/source_snapshots/v7/HOUSEHOLDS1000_JOINT_GEOMETRY_CANDIDATE.json'}
 files.update(Path(h['weather']['path']) for h in sel['records'])
 files.update(V12/'background_idfs'/f"{h['household_id']}.idf" for h in sel['records'])
 # Source dependencies used by retained generation/material code remain private and pinned.
 files.update((SOURCE/'worlds').glob('*.json'));files.update((SOURCE/'actors').glob('*.json'))
 tracked=read(OUT/'REFERENCE_UPSTREAM_FILES.json')
 for name in tracked['files']:
  p=UP/name
  if p.suffix in ('.py','.idf','.json') and p.is_file():
   if sha(p)!=tracked['files'][name]:raise RuntimeError('Pinned upstream bytes changed: '+name)
   files.add(p)
 for p in files:
  if not p.is_file():raise RuntimeError('Missing dependency: '+str(p))
 save(OUT/'EXTERNAL_INPUT_LOCK.json',{'schema':'eb.external_input_lock.v23','files':[{'path':str(p),'sha256':sha(p)} for p in sorted(files)],
  'licensed_microdata_uploaded':False,'engine':str(ENGINE),'engine_sha256':sha(ENGINE)})
 save(OUT/'REVISION_PROVENANCE.json',{'schema':'eb.gate_revision.v23','date':'2026-10-13',
  'parent':'causal_reference_production_20261010_v22','design_data_version':'v22','records':unchanged,
  'worlds_and_pairs_regenerated':False,'gate_fixes':['actual-content signature','expected run coverage','A hard power limits'],
  'original50_only':True,'full1000_EP_allowed':False,'human_answers':0})
 print({'worlds_and_10000_pairs_unchanged':len(unchanged)==1000,'external_files_locked':len(files)},flush=True)
if __name__=='__main__':main()
