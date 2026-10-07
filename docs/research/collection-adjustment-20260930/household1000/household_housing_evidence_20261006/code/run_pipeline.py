"""Serial, locked local research reproduction; never rewrite a sealed package."""
import hashlib,json,os,subprocess,sys
from pathlib import Path
OUT=Path(__file__).resolve().parent.parent
def main():
    from evidence_guard import ensure_unsealed
    ensure_unsealed(OUT)
    if (OUT/'PACKAGE_MANIFEST.json').exists():raise SystemExit('Sealed research package; reproduce only in a new copy without its seal.')
    lock=json.loads((OUT/'INPUT_LOCK.json').read_text())
    for path,expected in lock['files'].items():
        assert hashlib.sha256(Path(path).read_bytes()).hexdigest()==expected,'changed_input:'+path
    env=dict(os.environ);runtime=json.loads((OUT/'RUNTIME.json').read_text());env['PYTHONPATH']=runtime['stable_PYTHONPATH']
    for script in ['build_year_bridge.py','fetch_weather_gap.py','fetch_native_gap.py','inventory_references.py','regional_assemblies.py','admit_native_gap.py','sleep_geometry.py','matching_scenarios.py','regional_pilot.py','verify_evidence.py','write_report.py','lock_inputs.py']:
        subprocess.run([runtime['python_executable'],str(OUT/'code'/script)],env=env,check=True)
if __name__=='__main__':main()
