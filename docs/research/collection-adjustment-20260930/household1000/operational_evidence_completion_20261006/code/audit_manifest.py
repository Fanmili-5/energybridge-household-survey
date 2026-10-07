"""Read-only final audit; no writes, implicit simulations or releases."""
from common import *
def main():
 m=read(OUT/'PACKAGE_MANIFEST.json');actual={str(p.relative_to(OUT)) for p in OUT.rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.name!='PACKAGE_MANIFEST.json'};assert actual==set(m['files'])
 for name,h in m['files'].items():assert sha(OUT/name)==h,'packagechanged:'+name
 inputs=read(OUT/'INPUT_LOCK.json')['files']
 for p,h in inputs.items():assert sha(p)==h,'inputchanged:'+p
 integrity=read(OUT/'INTEGRITY.json');oldcount=0
 for r in integrity['prior_sealed_packages']:
  p=BASE/r['package'];assert sha(p/'PACKAGE_MANIFEST.json')==r['manifest_sha256'];mold=read(p/'PACKAGE_MANIFEST.json')
  for name,h in mold['files'].items():assert sha(p/name)==h,'priorchanged:'+r['package']+'/'+name
  oldcount+=len(mold['files'])
 assert oldcount==28733;latest=read(BASE/'LATEST.json');assert latest['active_stage']==read(OUT/'LATEST_BEFORE_OPERATIONAL_COMPLETION.json')['active_stage'] and latest['operational_evidence_completion_v11']['manifest_sha256']==sha(OUT/'PACKAGE_MANIFEST.json')
 c=read(OUT/'CURRENT.json');assert c['households']==1000 and c['residents']==2524 and c['formal_human_answers']==0 and not c['collection_release'] and not c['scientific_benchmark_release_admitted']
 print({'package_files_verified':len(actual),'inputs_verified':len(inputs),'old_sealed_files_verified_unchanged':oldcount,'activeV5_preserved':True,'manifest_sha256':sha(OUT/'PACKAGE_MANIFEST.json'),'research_scope_and_human_release_boundaries_preserved':True})
if __name__=='__main__':main()
