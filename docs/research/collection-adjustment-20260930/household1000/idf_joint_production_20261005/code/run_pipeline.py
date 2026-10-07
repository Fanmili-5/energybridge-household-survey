"""Run only in a new, explicit sibling research package, never a sealed output.

Copy this directory's code and raw primary documents to a fresh sibling first.
Private dependencies and prior sealed source packages remain read-only inputs.
"""
import hashlib,json,os,subprocess
from pathlib import Path

OUT=Path(__file__).resolve().parent.parent

def main():
    if (OUT/'PACKAGE_MANIFEST.json').exists():
        raise SystemExit('Refusing to overwrite a sealed package. Reproduce in a fresh sibling directory as REPRODUCE.md describes.')
    runtime=json.loads((OUT/'RUNTIME.json').read_text());lock=json.loads((OUT/'INPUT_LOCK.json').read_text())
    for path,record in lock['files'].items():
        h=hashlib.sha256()
        with Path(path).open('rb') as f:
            for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
        if h.hexdigest()!=record['sha256']:raise SystemExit('Actual input changed: '+path)
    env=dict(os.environ,PYTHONPATH=runtime['stable_PYTHONPATH'])
    for script in ['verify_native_assemblies.py','joint_housing.py','compile_reference_idfs.py','run_shell_smoke.py','audit_reference_idfs.py']:
        subprocess.run([runtime['python_executable'],str(OUT/'code'/script)],env=env,check=True)

if __name__=='__main__':main()
