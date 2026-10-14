"""Clone accepted reference logic into a fresh full-cohort stage; never edit V27."""
import argparse,hashlib,json,shutil
from pathlib import Path

def main(stage,source):
    assert not (stage/'BOOTSTRAP.json').exists(),'new stage required'
    def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
    assert sha(source/'FINAL_ACCEPTANCE.json')=='db0742371006812e63788fc21f03080ab9e55628a3e50d401892297e7b67dd2d'
    assert sha(source/'FROZEN_COMPOSITION1000.json')=='5b988c2117c55c14c78b4b34b5f11cd0775ed4441bd6c306fb54fc68d5554a16'
    code=stage/'code';code.mkdir(parents=True,exist_ok=True);original={};changes={}
    for p in(source/'code').iterdir():
        if not p.is_file()or p.suffix=='.pyc':continue
        original[p.name]=sha(p)
        target=code/p.name
        if target.exists():raise RuntimeError('code collision: '+p.name)
        shutil.copy2(p,target)
    # Scope adapters only. World/calendar/needs/A/B/compile algorithms retain their
    # exact accepted bytes. generate.main is unused; generate_household is reused.
    targets=['audit_pilot.py','audit_calendar.py','audit_idfs.py','audit_bath.py',
             'mechanism_controls.py','vehicle_causal_controls.py','audit_reference_model.py',
             'audit_physical_inputs.py','cluster_pilot.py']
    for name in targets:
        p=code/name;s=p.read_text();before=s
        for a,b in [('SELECTION50.json','SELECTION1000.json'),('WORLD_BINDINGS50.json','WORLD_BINDINGS1000.json'),
                    ('ACTUAL_FEATURES50.json','ACTUAL_FEATURES1000.json'),('FIELD_EVIDENCE50.json','FIELD_EVIDENCE1000.json'),
                    ('COMPILED50.json','COMPILED1000.json'),('CLUSTER_COVERAGE50_REVIEW.json','CLUSTER_COVERAGE1000_REVIEW.json')]:s=s.replace(a,b)
        if name=='audit_pilot.py':s=s.replace("len(selection['records'])==50", "len(selection['records'])==1000")
        if name=='audit_idfs.py':s=s.replace("manifest['IDF_count']==1000 and len(manifest['households'])==50", "manifest['IDF_count']==20000 and len(manifest['households'])==1000")
        if name=='audit_physical_inputs.py':s=s.replace("'same_original50':len(allowed)==50", "'same_frozen1000':len(allowed)==1000")
        if name=='cluster_pilot.py':
            s=s.replace('correct/50','correct/len(rows)').replace("'households':50", "'households':len(rows)").replace('agree/50','agree/len(rows)').replace('agree==50','agree==len(rows)').replace('accepted_for_original50_reference_development','accepted_for_frozen1000_reference_production')
        p.write_text(s);changes[name]={'before':original[name],'after':sha(p),'scope_adapter_only':True}
    # Accepted original50 runner is left held. A separate fresh full-cohort gate
    # and runner will be reviewed only after all static gates have actually passed.
    receipt={'schema':'eb.formal_cohort_bootstrap.v28','source':str(source),'source_acceptance_sha256':sha(source/'FINAL_ACCEPTANCE.json'),
        'composition_sha256':sha(source/'FROZEN_COMPOSITION1000.json'),'reference_code_sha256':original,'scope_adapters':changes,
        'formal_collection_user_requested':True,'EP_started':0,'EP_allowed_now':False}
    (stage/'BOOTSTRAP.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'bootstrap':'pass','reference_modules':len(original),'scope_adapters':len(changes),'EP_started':0}),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--stage',type=Path,required=True);p.add_argument('--source',type=Path,required=True);a=p.parse_args();main(a.stage,a.source)
