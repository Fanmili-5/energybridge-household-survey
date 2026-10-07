"""Read-only package/input integrity check, safe after research sealing."""
import hashlib,json
from pathlib import Path
OUT=Path(__file__).resolve().parent.parent
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def main():
    manifest=json.loads((OUT/'PACKAGE_MANIFEST.json').read_text());lock=json.loads((OUT/'INPUT_LOCK.json').read_text())
    for path,expected in manifest['files'].items():assert sha(OUT/path)==expected,'changed_package_file:'+path
    for path,expected in lock['files'].items():assert sha(path)==expected,'changed_external_input:'+path
    print(json.dumps({'package_files_verified':len(manifest['files']),'input_files_verified':len(lock['files']),'manifest_sha256':sha(OUT/'PACKAGE_MANIFEST.json'),'read_only':True}))
if __name__=='__main__':main()
