"""Observe only: physical diagnostic IDFs must be identical to their native parent dynamics."""
from common import *
def main():
 school_guard();manifest=read(OUT/'COMPILED50.json');fail=[];checked=0
 allowed={h['household_id']:h for h in read(OUT/'SELECTION50.json')['records']}
 for c in manifest['records']:
  h=allowed[c['household_id']];source=next(q for q in h['rounds'] if q['round_index']==c['round_index'])
  if c['pair_sha256']!=source['pair_sha256'] or c['world_sha256']!=h['world_sha256']:fail.append([c['household_id'],'SOURCE_BINDING'])
  for side in ('A','B'):
   b=c[side];native=OUT/b['native_IDF_path'];observed=OUT/b['IDF_path'];checked+=1
   if sha(native)!=b['native_IDF_sha256'] or sha(observed)!=b['IDF_sha256'] or sha(OUT/b['signal_ledger_path'])!=b['signal_ledger_sha256']:fail.append([c['household_id'],side,'CONTENT_CHANGED'])
   inverse={m['curve']:m['original_curve'] for m in b['curve_observation_meta']}
   clones={r[1]:r for r in parse(observed) if r[0].startswith('Curve:') and r[1] in inverse}
   original_curves={r[1]:r for r in parse(native) if r[0].startswith('Curve:')}
   for name,row in clones.items():
    if row[2:]!=original_curves[inverse[name]][2:]:fail.append([c['household_id'],name,'CURVE_COEFFICIENT_OR_LIMIT_CHANGED'])
   stripped=[]
   for row in parse(observed):
    if row[0].startswith('Curve:') and row[1] in inverse:continue
    if row[0]=='Output:Variable' and row[-1]=='Detailed':continue
    stripped.append([inverse.get(x,x) for x in row])
   if stripped!=parse(native):fail.append([c['household_id'],side,'DIAGNOSTIC_ALTERS_DYNAMICS'])
   if b['prior_days'] not in (7,14) or b['inlet_assumption'] not in ('fixed15','seasonal'):fail.append([c['household_id'],side,'UNDECLARED_ASSUMPTION'])
 report={'status':'pass' if not fail else 'fail','paired_variants':len(manifest['records']),'diagnostic_IDFs_checked':checked,
 'same_original50':len(allowed)==50,'failures':fail,'observer_has_identical_physical_equations_and_controls':not fail,'EP_started':0,'field_calibration':False}
 save(OUT/'PHYSICAL_INPUT_AUDIT.json',report);print(report,flush=True)
 if fail:raise RuntimeError(str(fail[:5]))
if __name__=='__main__':main()

