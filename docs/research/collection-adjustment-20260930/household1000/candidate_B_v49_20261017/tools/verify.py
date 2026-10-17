"""Verify full A46/B48 provenance and every updated classification file."""
import sys
from pathlib import Path
STAGE=Path(__file__).resolve().parents[1];sys.path.insert(0,str(STAGE/'code'))
from common import *
def main():
    verify_inputs();sig=rules_id();accept=read(OUT/'ACCEPTANCE.json');b=read(OUT/'PAIR_BINDINGS10000.json');seal=read(OUT/'FINAL_SEAL.json')
    if not accept['accepted']or accept['rules_sha256']!=sig or b['rules_sha256']!=sig or seal['rules_sha256']!=sig or accept['bindings_sha256']!=sha(OUT/'PAIR_BINDINGS10000.json'):raise ValueError('UNMATCHED_ACCEPTANCE')
    for stage in [A_STAGE,SOURCE_B,OUT]:
        for p,h in read(stage/'FINAL_SEAL.json')['stage_files'].items():
            if sha(stage/p)!=h:raise ValueError('SEALED_FILE_CHANGED:'+str(stage/p))
    for stage in [A_STAGE,SOURCE_B]:
        for p,h in read(stage/'INPUT_LOCK.json')['files'].items():
            if sha(REPO/p)!=h:raise ValueError('SOURCE_INPUT_CHANGED:'+p)
    for row in read(A_STAGE/'A_BINDINGS10000.json')['records']:
        for pk,hk in [('A_world_path','A_world_sha256'),('annual_A_path','annual_A_sha256'),('HVAC_components_path','HVAC_components_sha256')]:
            if sha(A_STAGE/row[pk])!=row[hk]:raise ValueError('A_OUTPUT_CHANGED')
        for rr in row['cases']:
            if sha(A_STAGE/rr['path'])!=rr['sha256']:raise ValueError('A_CASE_CHANGED')
    oldrows={r['household_id']:r for r in read(SOURCE_B/'PAIR_BINDINGS10000.json')['records']};count=0
    for row in b['records']:
        old={x['case_id']:x for x in oldrows[row['household_id']]['rounds']}
        for rr in row['rounds']:
            if sha(OUT/rr['path'])!=rr['sha256']or sha(SOURCE_B/old[rr['case_id']]['path'])!=old[rr['case_id']]['sha256']:raise ValueError('NEW_OR_SOURCE_PAIR_CHANGED')
            count+=1
    if count!=10000:raise ValueError('NOT10000')
    print({'verified_households':1000,'verified_pairs':count,'A46_and_B48_sources_preserved':True,'classification_only':True,'physical_acceptance':False})
if __name__=='__main__':main()
