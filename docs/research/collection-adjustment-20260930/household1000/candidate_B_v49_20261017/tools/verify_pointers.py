"""Check all current local pointers and unchanged A version after publication."""
import sys
from pathlib import Path
STAGE=Path(__file__).resolve().parents[1];sys.path.insert(0,str(STAGE/'code'))
from common import *
def main():
    b=read(BASE/'CURRENT_AB_INPUTS.json');a=read(BASE/'CURRENT_NORMAL_A_INPUTS.json');pub=REPO/'docs/household1000'
    if b['stage']!=OUT.name or b['source_B_schedule_stage']!=SOURCE_B.name or a['stage']!=A_STAGE.name:raise ValueError('CURRENT_VERSION_MISMATCH')
    if b['seal_sha256']!=sha(OUT/'FINAL_SEAL.json')or b['source_B_schedule_seal_sha256']!=sha(SOURCE_B/'FINAL_SEAL.json')or b['source_A_seal_sha256']!=sha(A_STAGE/'FINAL_SEAL.json'):raise ValueError('CURRENT_SEAL_MISMATCH')
    if read(pub/'CURRENT_AB.json')!=b or read(pub/'CURRENT_NORMAL_A.json')!=a:raise ValueError('PUBLIC_POINTER_MISMATCH')
    for path in [pub/'STATUS.json',pub/'PIPELINE.json',BASE/'CURRENT_GENERATION_REQUIREMENTS.json']:
        p=read(path)
        if p['current_static_AB_inputs']!=b or p['current_normal_A']!=a:raise ValueError('NESTED_POINTER_MISMATCH')
    if read(BASE/'CURRENT_MASTER_INPUTS.json')['current_static_AB_version']!='v49':raise ValueError('MASTER_POINTER_MISMATCH')
    verify_inputs();print({'private_public_nested_versions_match':True,'A46_unchanged':True,'B48_schedule_source_seal_matches':True,'same_batch_subset50':b['subset50_type_counts'],'new_questionnaire_released':False})
if __name__=='__main__':main()
