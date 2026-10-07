"""Read-only seal and actual-input audit; never refresh or rewrite hashes."""
import hashlib,json
from pathlib import Path
OUT=Path(__file__).resolve().parent.parent
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def main():
 m=json.loads((OUT/'PACKAGE_MANIFEST.json').read_text());lock=json.loads((OUT/'INPUT_LOCK.json').read_text())
 for name,h in m['files'].items():assert sha(OUT/name)==h,name
 for path,h in lock['files'].items():assert sha(Path(path))==h,path
 actual={str(p.relative_to(OUT)) for p in OUT.rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.name!='PACKAGE_MANIFEST.json'}
 assert actual==set(m['files']),'unmanifested_or_missing_package_members'
 print(json.dumps({'sealed_package_files':len(m['files']),'actual_input_files_checked':len(lock['files']),
 'manifest_sha256':sha(OUT/'PACKAGE_MANIFEST.json'),'read_only':True}))
if __name__=='__main__':main()
