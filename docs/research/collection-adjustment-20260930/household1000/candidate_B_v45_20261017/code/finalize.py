"""Seal source/data/review lineage and publish only a static AB input pointer."""
import argparse
import sys
from common import *

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--verify-only',action='store_true');args=parser.parse_args();verify_inputs()
    sig=rules_id();report=read(OUT/'ACCEPTANCE.json');b=read(OUT/'PAIR_BINDINGS10000.json')
    if not report['accepted']or report['rules_sha256']!=sig or b['rules_sha256']!=sig or report['bindings_sha256']!=sha(OUT/'PAIR_BINDINGS10000.json'):raise ValueError('STATIC_B_NOT_ACCEPTED')
    if args.verify_only:
        for path,h in read(A_STAGE/'FINAL_SEAL.json')['stage_files'].items():
            if sha(A_STAGE/path)!=h:raise ValueError('A_SEALED_FILE_CHANGED:'+path)
        for path,h in read(A_STAGE/'INPUT_LOCK.json')['files'].items():
            if sha(REPO/path)!=h:raise ValueError('A_PINNED_INPUT_CHANGED:'+path)
        for row in read(A_STAGE/'A_BINDINGS10000.json')['records']:
            for pathkey,hashkey in [('A_world_path','A_world_sha256'),('annual_A_path','annual_A_sha256'),('HVAC_components_path','HVAC_components_sha256')]:
                if sha(A_STAGE/row[pathkey])!=row[hashkey]:raise ValueError('A_OUTPUT_CHANGED:'+row[pathkey])
            for c in row['cases']:
                if sha(A_STAGE/c['path'])!=c['sha256']:raise ValueError('A_CASE_CHANGED')
        for path,h in read(OUT/'FINAL_SEAL.json')['stage_files'].items():
            if sha(OUT/path)!=h:raise ValueError('SEALED_FILE_CHANGED:'+path)
        for r in b['records']:
            for c in r['rounds']:
                if sha(OUT/c['path'])!=c['sha256']:raise ValueError('PAIR_BYTES_CHANGED')
        print({'verified_households':1000,'verified_pairs':10000,'physical_acceptance':False});return
    if (OUT/'FINAL_SEAL.json').exists():raise ValueError('SEAL_EXISTS;new rules require new retained run and seal version')
    history=[]
    for run in sorted((OUT/'runs').iterdir()):
        records=[read(p)for p in(run/'records').glob('*.json')]
        history.append({'run':run.name,'written_households':len(records),'generation_errors':sum(not r['passed']for r in records),'accepted':run.name==sig[:16],
                        'source_snapshot_complete':{p.name for p in(OUT/'code').glob('*.py')}<={p.name for p in(run/'source_snapshot').glob('*.py')}})
    save(OUT/'DEVELOPMENT_HISTORY.json',{'runs':history,'B_constraint_failures_are_data_not_generator_errors':True})
    files=list((OUT/'code').glob('*.py'))+[OUT/n for n in('INPUT_LOCK.json','GENERATION_RULES.json','ACCEPTANCE.json','PAIR_BINDINGS10000.json','SUBSET50.json','A_REAUDIT.json','REGRESSION_RESULTS.json','GENERATOR_REPAIR_HISTORY.json','DEVELOPMENT_HISTORY.json','REVIEW_EXPORT_MANIFEST.json','METHODS.md','VPP_AUDIT.json','INPUT_COVERAGE_PLAN.json','DESIGN_REVIEW.json')]
    files+=list((OUT/'tools').glob('*.py'))+list((OUT/'review').iterdir())+list((OUT/'runs'/sig[:16]/'regeneration').glob('*.json'))+list((OUT/'runs'/sig[:16]/'source_snapshot').iterdir())
    save(OUT/'FINAL_SEAL.json',{'schema':'eb.alternative_seal.v45','rules_sha256':sig,'stage_files':{rel(p):sha(p)for p in files if p.is_file()},
                               'scope':'1000-household10000 alternative proposals and static checks only','physical_acceptance':False,'collection_released':False,'python':sys.version})
    pointer={'schema':'eb.current_AB_inputs.v45','stage':OUT.name,'households':1000,'pairs':10000,'source_A_stage':A_STAGE.name,
             'source_A_bindings_sha256':sha(A_STAGE/'A_BINDINGS10000.json'),'source_A_seal_sha256':sha(A_STAGE/'FINAL_SEAL.json'),
             'bindings_sha256':sha(OUT/'PAIR_BINDINGS10000.json'),'rules_sha256':sig,'seal_sha256':sha(OUT/'FINAL_SEAL.json'),
             'given_constraints_feasible_cases':report['given_constraints_feasible_cases'],'given_constraint_conflict_cases_kept':report['given_constraint_conflict_cases_kept'],
             'subset50_same_master':True,'subset50_type_counts':read(OUT/'SUBSET50.json')['type_counts'],
             'A_and_B_static_accepted':True,'physical_acceptance':False,'human_labels_generated':0,'new_questionnaire_released':False}
    save(BASE/'CURRENT_AB_INPUTS.json',pointer);save(REPO/'docs/household1000/CURRENT_AB.json',pointer)
    current=read(BASE/'CURRENT_NORMAL_A_INPUTS.json');current['B_generation_pending']=False;current['current_AB_inputs']='CURRENT_AB_INPUTS.json'
    save(BASE/'CURRENT_NORMAL_A_INPUTS.json',current);save(REPO/'docs/household1000/CURRENT_NORMAL_A.json',current)
    print(canonical(pointer))

if __name__=='__main__':main()
