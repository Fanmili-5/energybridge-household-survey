"""Package accepted A and its review artifacts without changing model rules."""
import subprocess
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'code'))
from common import OUT,BASE,REPO,MASTER,read,save,sha,rules_id,digest

def main():
    report=read(OUT/'ACCEPTANCE.json');schema=read(OUT/'review/HVAC_COMPONENT_SCHEMA_REVIEW.json')
    if not report['accepted']or not schema['passed']or schema['households_checked']!=1000 or schema['rules_sha256']!=rules_id():raise ValueError('ACCEPTED_REVIEW_NOT_COMPLETE')
    decisions=read(OUT/'USER_DECISIONS.json');decisions['new1000_A_accepted']=True;decisions['acceptance_scope']='calendar,resources,programs and control signals;not physical delivery';save(OUT/'USER_DECISIONS.json',decisions)
    subprocess.run([sys.executable,'-B',str(OUT/'tools/finish_review_exports.py')],check=True,cwd=REPO)
    bindings=read(OUT/'A_BINDINGS10000.json');signature=rules_id();run=OUT/'runs'/signature[:16];save(run/'ACCEPTANCE.json',report)
    ledger=[]
    for row in bindings['records']:
        old=read(MASTER/row['master_world_path']);new=read(OUT/row['A_world_path']);hid=row['household_id']
        changed={k:{'before_sha256':digest(old.get(k)),'after_sha256':digest(new.get(k))}for k in set(old)|set(new)if old.get(k)!=new.get(k)}
        path=run/'regeneration'/(hid+'.json')
        save(path,{'household_id':hid,'source_V33_file_sha256':row['master_world_sha256'],'new_A_world_file_sha256':row['A_world_sha256'],
            'rules_sha256':signature,'changed_fields':changed,'reason':'user-authorized daily configured-appliance benchmark with winter heating',
            'source_world_overwritten':False,'old_AB_physics_or_answers_reused':False})
        ledger.append({'path':str(path.relative_to(OUT)),'sha256':sha(path)})
    save(OUT/'REGENERATION_BINDINGS1000.json',{'rules_sha256':signature,'records':ledger,'households':1000})
    subprocess.run([sys.executable,'-B',str(REPO/'scripts/normal_a.py'),'seal'],check=True,cwd=REPO)
    seal=read(OUT/'FINAL_SEAL.json')
    paths=[OUT/'METHODS_AND_ACCEPTANCE.md',OUT/'REVIEW_EXPORT_MANIFEST.json',OUT/'REGENERATION_BINDINGS1000.json']+list((OUT/'tools').glob('*.py'))
    paths += [OUT/name for name in read(OUT/'REVIEW_EXPORT_MANIFEST.json')['files']]
    paths += [OUT/item['path']for item in ledger]
    seal['stage_files'].update({str(path.relative_to(OUT)):sha(path)for path in paths})
    seal['review_artifact_packaging_separate_from_generation']=True
    save(OUT/'FINAL_SEAL.json',seal)
    pointer=read(BASE/'CURRENT_NORMAL_A_INPUTS.json');pointer['seal_sha256']=sha(OUT/'FINAL_SEAL.json');pointer['review_exports_manifest_sha256']=sha(OUT/'REVIEW_EXPORT_MANIFEST.json')
    save(BASE/'CURRENT_NORMAL_A_INPUTS.json',pointer);save(REPO/'docs/household1000/CURRENT_NORMAL_A.json',pointer)
    print({'sealed_generation_rules':signature,'sealed_additional_review_files':len(paths),'regeneration_ledgers':len(ledger)})

if __name__=='__main__':main()
