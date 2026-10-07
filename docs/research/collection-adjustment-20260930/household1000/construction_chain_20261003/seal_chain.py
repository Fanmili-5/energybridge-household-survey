#!/usr/bin/env python3
"""Seal the completed construction milestone and preserve evidence layers."""
import hashlib
import json
import re
from pathlib import Path

HERE=Path(__file__).resolve().parent
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def read(p):return json.loads(Path(p).read_text())

def main():
    if (HERE/'PACKAGE_MANIFEST.json').exists():raise ValueError('sealed_milestone_requires_new_revision')
    errors=[]
    index=read(HERE/'CANDIDATE1000_CHAIN_INDEX.json')
    if index['slots']!=1000 or len({r['slot_id'] for r in index['rows']})!=1000:errors.append('complete1000_index')
    for p,h in index['input_sha256'].items():
        if sha(Path(p))!=h:errors.append('index_input_changed:'+p)
    for name,key in [('INDEPENDENT_VERIFICATION_final.json','pass'),('CURRENT_BINDER_COMPATIBILITY.json','pass'),
        ('LAYER_VERIFICATION.json','pass'),('AREA_SCORE_CONTROLS.json','pass'),('witnesses_final/CHAIN_VERIFICATION.json','pass')]:
        if not read(HERE/name)[key]:errors.append('failed_current_evidence:'+name)
    references=read(HERE/'references_final/REFERENCE_LOCK.json')
    for p,h in references['inputs'].items():
        if sha(Path(p))!=h:errors.append('reference_input_changed:'+p)
    for p,h in references['outputs'].items():
        if sha(HERE/'references_final'/p)!=h:errors.append('reference_output_changed:'+p)
    vintage=read(HERE/'chfs_vintage_v1/VINTAGE_LOCK.json')
    if sha(HERE/'chfs_vintage_v1/CURRENT_DWELLING_YEAR_AREA_SUPPORT.json')!=vintage['result_sha256']:errors.append('vintage_result_changed')
    evaluation=read(HERE/'area_joint_holdout_v1/EVALUATION_LOCK.json')
    for p,h in evaluation['source_files'].items():
        if sha(Path(p))!=h:errors.append('evaluation_source_changed:'+p)
    if sha(HERE/'area_joint_holdout_v1/AREA_JOINT_HOLDOUT.json')!=evaluation['report_sha256']:errors.append('evaluation_report_changed')
    previous=HERE.parent/'policy_revision_20261003/foundation_20261003'
    old=read(previous/'FOUNDATION_MANIFEST.json')
    for p,h in old['files'].items():
        if sha(previous/p)!=h:errors.append('previous_foundation_modified:'+p)
    links=[]
    for p in HERE.rglob('*.md'):
        for target in re.findall(r'\]\(([^)]+)\)',p.read_text()):
            if target.startswith(('https://','http://','#')):continue
            resolved=p.parent/target;links.append(str(resolved))
            if not resolved.exists():errors.append('broken_link:'+str(p)+':'+target)
    if errors:raise ValueError(errors)
    files={str(p.relative_to(HERE)):sha(p) for p in sorted(HERE.rglob('*')) if p.is_file()
        and '__pycache__' not in p.parts and p.name not in ['PACKAGE_MANIFEST.json','PACKAGE_VERIFICATION.json']}
    manifest={'schema':'eb.household_construction_milestone_manifest.v1','files':files,'self_excluded':True,
        'scope':'completed source/typed-interface/electric-component milestone, including clearly historical attempts; not a formal1000 household/actor release',
        'current_entry':'CURRENT.json','historical_attempts':['references_v1','witnesses_v1','INDEPENDENT_VERIFICATION.json'],
        'read_only_previous_foundation_manifest_sha256':sha(previous/'FOUNDATION_MANIFEST.json')}
    (HERE/'PACKAGE_MANIFEST.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    byte_errors=[p for p,h in files.items() if sha(HERE/p)!=h]
    result={'schema':'eb.household_construction_milestone_verification.v1','pass':not byte_errors,
        'files_checked':len(files),'byte_mismatches':byte_errors,'local_links_checked':len(links),
        'previous_foundation_unchanged':True,'complete1000_fact_context_source_index':True,
        'real_EP_one_day_component_runs':3,'observed_human_answers':0,'actor_ready_roles':0,
        'formal_statistical_generator_approved':False,'collection_release':False,'training_release':False,
        'manifest_sha256':sha(HERE/'PACKAGE_MANIFEST.json'),
        'meaning':'integrity and specified linkage checks; scientific limits and open source/frame/service gaps are in README and layered readiness'}
    (HERE/'PACKAGE_VERIFICATION.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(result,ensure_ascii=False))

if __name__=='__main__':main()
