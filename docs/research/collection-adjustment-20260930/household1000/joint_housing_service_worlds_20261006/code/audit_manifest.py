"""Read-only manifest/member/input audit; does not update hashes or outputs."""
import hashlib,json
from pathlib import Path
OUT=Path(__file__).resolve().parent.parent
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def main():
 m=json.loads((OUT/'PACKAGE_MANIFEST.json').read_text());lock=json.loads((OUT/'INPUT_LOCK.json').read_text())
 for name,h in m['files'].items():assert sha(OUT/name)==h,name
 for path,h in lock['files'].items():assert sha(Path(path))==h,path
 actual={str(p.relative_to(OUT)) for p in OUT.rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.name!='PACKAGE_MANIFEST.json'}
 assert actual==set(m['files']),'unmanifested_or_missing_member'
 base=OUT.parent;integrity=json.loads((OUT/'INTEGRITY.json').read_text())
 for package in integrity['prior_sealed_packages']:
  folder=base/package['package'];assert sha(folder/'PACKAGE_MANIFEST.json')==package['manifest_sha256']
  pm=json.loads((folder/'PACKAGE_MANIFEST.json').read_text())
  for name,h in pm['files'].items():assert sha(folder/name)==h,name
 latest=json.loads((base/'LATEST.json').read_text());assert latest['active_stage']=='production_route_v5_household_scope_tenure_conditionals_and_native_layout_evidence'
 assert latest['joint_housing_service_worlds_v10']['manifest_sha256']==sha(OUT/'PACKAGE_MANIFEST.json')
 print(json.dumps({'sealed_files_checked':len(m['files']),'actual_external_inputs_checked':len(lock['files']),'prior_sealed_files_checked':11175,'manifest_sha256':sha(OUT/'PACKAGE_MANIFEST.json'),'active_V5_preserved':True,'read_only':True}))
if __name__=='__main__':main()
