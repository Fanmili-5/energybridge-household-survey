"""Freeze scoped A acceptance. Physical results, B and collection stay pending."""
import argparse
import importlib.metadata
from common import *

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--verify-only',action='store_true');args=parser.parse_args()
    verify_inputs();signature=rules_id();report=read(OUT/'ACCEPTANCE.json');bindings=read(OUT/'A_BINDINGS10000.json')
    if not report['accepted']or report['rules_sha256']!=signature or bindings['rules_sha256']!=signature:raise ValueError('SCOPED_A_NOT_ACCEPTED')
    if sha(OUT/'A_BINDINGS10000.json')!=report['bindings_sha256']:raise ValueError('BINDINGS_CHANGED')
    if args.verify_only:
        seal=read(OUT/'FINAL_SEAL.json')
        for name,expected in seal['stage_files'].items():
            if sha(OUT/name)!=expected:raise ValueError('SEALED_STAGE_FILE_CHANGED:'+name)
        for row in bindings['records']:
            for a,b in(('A_world_path','A_world_sha256'),('annual_A_path','annual_A_sha256'),('HVAC_components_path','HVAC_components_sha256')):
                if sha(OUT/row[a])!=row[b]:raise ValueError('OUTPUT_CHANGED:'+row[a])
            if sha(MASTER/row['master_world_path'])!=row['master_world_sha256']:raise ValueError('PARENT_WORLD_CHANGED')
            for case in row['cases']:
                if sha(OUT/case['path'])!=case['sha256']:raise ValueError('CASE_CHANGED')
        print({'verified_households':1000,'verified_cases':10000,'physical_acceptance':False});return
    if(OUT/'FINAL_SEAL.json').exists():raise ValueError('FINAL_SEAL_EXISTS;retain old seal before changing the version')
    history=[]
    for folder in sorted((OUT/'runs').iterdir()):
        records=[read(p)for p in(folder/'records').glob('*.json')]
        history.append({'run':folder.name,'written_records':len(records),'generation_failures':sum(not r.get('passed')for r in records),
            'accepted_A':folder.name==signature[:16],'source_snapshot_exists':(folder/'source_snapshot').exists(),
            'generator_completion_is_not_schedule_or_physical_acceptance':True})
    save(OUT/'DEVELOPMENT_HISTORY.json',{'runs':history,'earlier_intermediate_source_snapshots_complete':False,'final_snapshot_saved':True})
    stage_files={str(p.relative_to(OUT)):sha(p)for p in list((OUT/'code').glob('*.py'))+
        [OUT/n for n in('ACCEPTANCE.json','A_BINDINGS10000.json','SUBSET50.json','INPUT_LOCK.json','GENERATION_RULES.json','USER_DECISIONS.json','DELIVERY_SUMMARY.json','DEVELOPMENT_HISTORY.json','FAMILY_EB_REVIEW.json','METHODS.md','GENERATOR_REPAIR_HISTORY.json')]}
    save(OUT/'FINAL_SEAL.json',{'schema':'eb.normal_A_seal.v46','rules_sha256':signature,'stage_files':stage_files,
        'run':str(Path('runs')/signature[:16]),'scope':'normal A resource,calendar,program and signal production only',
        'physical_acceptance':False,'B_generated':False,'live_questionnaire_replaced':False,
        'python':sys.version,'packages':{n:importlib.metadata.version(n)for n in('numpy','scipy','shapely')}})
    pointer={'schema':'eb.current_normal_A.v46','stage':OUT.name,'households':1000,'cases':10000,
        'A_resource_worlds':'A_BINDINGS10000.json:records[].A_world_path','source_household_master':MASTER.name,
        'source_household_master_unchanged':True,'A_static_accepted':True,'rules_sha256':signature,
        'bindings_sha256':sha(OUT/'A_BINDINGS10000.json'),'seal_sha256':sha(OUT/'FINAL_SEAL.json'),
        'subset50_same_master':True,'subset50_type_counts':read(OUT/'SUBSET50.json')['type_counts'],
        'physical_acceptance':False,'B_generation_pending':True,'new_questionnaire_released':False}
    save(BASE/'CURRENT_NORMAL_A_INPUTS.json',pointer)
    save(REPO/'docs/household1000/CURRENT_NORMAL_A.json',pointer)
    parent=read(BASE/'CURRENT_MASTER_INPUTS.json');parent['current_normal_A']='CURRENT_NORMAL_A_INPUTS.json';parent['A_resource_worlds_are_derived_V34_versions']=True;parent['current_A_resource_world_version']='v40';save(BASE/'CURRENT_MASTER_INPUTS.json',parent)
    print(canonical(pointer))

if __name__=='__main__':main()
