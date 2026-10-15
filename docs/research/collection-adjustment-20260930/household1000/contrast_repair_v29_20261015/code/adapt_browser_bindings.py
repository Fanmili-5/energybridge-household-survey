"""Same frontend canonicalization and verification with dynamic cohort counts."""
import json,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    records={}
    for name in('bind_frontend.js','verify_case_bindings.js'):
        p=ROOT/'code'/name;s=p.read_text();old=sha(p)
        s=s.replace("'INDEX50.json'","'INDEX'+path.basename("+('release'if name=='bind_frontend.js'else'root')+").match(/(50|950)$/)[1]+'.json'")
        if name=='bind_frontend.js':s=s.replace('case_bindings:500','case_bindings:index.households.length*10')
        else:s=s.replace('assert.equal(checked,500)','assert.equal(checked,index.households.length*10)')
        p.write_text(s);records[name]={'before_sha256':old,'after_sha256':sha(p)}
    (ROOT/'BROWSER_SCOPE_ADAPTER.json').write_text(json.dumps({'same_browser_canonicalization_and_verifier':True,'cohorts':[50,950],'source_files':records},indent=2)+'\n')
    print(json.dumps({'browser_bindings_cohorts':[50,950]}))
if __name__=='__main__':main()
