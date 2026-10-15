"""Keep the pilot gate archived; install the separately scoped reviewed gate."""
from pathlib import Path
import hashlib,json,shutil
ROOT=Path(__file__).resolve().parents[1]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    gate=ROOT/'code/ep_gate.py';old=ROOT/'code/pilot_ep_gate_reference.py';assert not old.exists()
    shutil.copy2(gate,old);gate.write_text('"""Content-bound cohort gate; original50 and other950 are reviewed separately."""\nfrom cohort_gate import require_reviewed_ep,guard_job,input_signature\n')
    physics=ROOT/'code/physics.py';s=physics.read_text();before=sha(physics)
    fragment="assert c['household_id'] in {h['household_id'] for h in read(OUT/'SELECTION50.json')['records']},'EP hold: household outside original50'"
    assert s.count(fragment)==1
    physics.write_text(s.replace(fragment,"assert c['household_id'] in lease['allowed_households'],'EP hold: household outside reviewed cohort'",1))
    (ROOT/'COHORT_GATE_INSTALLATION.json').write_text(json.dumps({'pilot_gate_archived_sha256':sha(old),'new_gate_sha256':sha(gate),'physics_before_sha256':before,'physics_after_sha256':sha(physics),'physical_equations_and_SQL_readback_unchanged':True,'original50_first_other950_after_new_acceptance':True,'EP_started':0},indent=2)+'\n')
    print(json.dumps({'cohort_gate_installed':True,'EP_started':0}))
if __name__=='__main__':main()
