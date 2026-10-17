"""Seal updated classifications and their complete provenance before publication."""
import sys
from pathlib import Path
STAGE=Path(__file__).resolve().parents[1];sys.path.insert(0,str(STAGE/'code'))
from common import *
def main():
    verify_inputs();a=read(OUT/'ACCEPTANCE.json');r=read(OUT/'REGRESSION_RESULTS.json');sig=rules_id()
    if not a['accepted']or not r['passed']or a['rules_sha256']!=sig or r['rules_sha256']!=sig:raise ValueError('NOT_ACCEPTED')
    if a['bindings_sha256']!=sha(OUT/'PAIR_BINDINGS10000.json'):raise ValueError('BINDING_CHANGED')
    if(OUT/'FINAL_SEAL.json').exists():raise ValueError('SEAL_EXISTS')
    runs=[]
    for folder in sorted((OUT/'runs').iterdir()):
        rows=[read(p)for p in(folder/'records').glob('*.json')];runs.append({'run':folder.name,'households':len(rows),'errors':sum(not x['passed']for x in rows),'accepted':folder.name==sig[:16],'classification_only':True})
    save(OUT/'DEVELOPMENT_HISTORY.json',{'runs':runs,'no_B_failure_or_unchanged_case_filtered':True,'prior_sealed_B_preserved':SOURCE_B.name})
    files=list((OUT/'code').glob('*.py'))+list((OUT/'tools').glob('*.py'))+list((OUT/'review').iterdir())+list((OUT/'trials').rglob('*'))
    files+=list((OUT/'runs'/sig[:16]/'source_snapshot').iterdir())+list((OUT/'runs'/sig[:16]/'records').glob('*.json'))+list((OUT/'runs'/sig[:16]/'regeneration').glob('*.json'))
    files+=[p for p in OUT.glob('*.json')if p.name!='FINAL_SEAL.json']+[OUT/'METHODS.md']
    save(OUT/'FINAL_SEAL.json',{'schema':'eb.classification_seal.v49','rules_sha256':sig,'stage_files':{rel(p):sha(p)for p in files if p.is_file()},'run':'runs/'+sig[:16],'source_A_seal_sha256':sha(A_STAGE/'FINAL_SEAL.json'),'source_B_seal_sha256':sha(SOURCE_B/'FINAL_SEAL.json'),'source_B_schedule_stage':SOURCE_B.name,'scope':'1000/10000 classification update and preserved schedules;not full physics/human acceptance','physical_acceptance':False,'collection_released':False,'python':sys.version})
    print({'sealed':OUT.name,'schedule_changes':0,'stage_files':len(files),'pointers_changed':False})
if __name__=='__main__':main()
