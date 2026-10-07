#!/usr/bin/env python3
"""Verify local source integrity, field bindings, aggregate counts and scope.

This is a source-admission check, not population validity or role-package QA.
"""
import ast
import json
import re
from pathlib import Path
import pandas as pd
from inspect_package import HERE, PACKAGE, sha, write

def read(name):
    return json.loads((HERE/name).read_text())

def main():
    manifest=read('PACKAGE_MANIFEST.json')
    qc=read('CHFS_SOURCE_QC.json')
    rules=read('FIELD_SOURCE_RULES.json')
    contract=read('GENERATION_SOURCE_CONTRACT.json')
    status=read('ADMISSION_STATUS.json')
    source_checks=[]
    for e in read('SOURCE_LEDGER.json')['entries']:
        if 'local_path' in e:
            p=Path(e['local_path']);assert p.is_file(),p
            assert sha(p)==e['sha256'],p.name
            source_checks.append(e['source_id'])
    for p in HERE.glob('*.py'):
        ast.parse(p.read_text(),filename=str(p))
    for obj,script in [(manifest,'inspect_package.py'),(qc,'audit_chfs.py'),(status,'build_contract.py')]:
        assert obj['script_sha256']==sha(HERE/script),script
    labels={k:read('private_metadata/'+f'chfs2021_{k}_pub_v0_20260131_metadata.json')['variable_labels']
            for k in ['hh','ind','master_hh','master_ind']}
    bindings=0
    for group in rules['groups']:
        for binding in group['bindings']:
            for field in binding['fields']:
                assert labels[binding['table']][field['name']]==field['actual_label']
                bindings+=1
        limits={'usage':17,'questionnaire2021':174,'questionnaire2022':173}
        for doc,pages in group['document_pages_1based'].items():
            if doc in limits:assert all(1<=p<=limits[doc] for p in pages)
    assert [s['step'] for s in contract['steps']]==list(range(1,12))
    assert contract['exclusions'][:3]==['town','rural','collective_households']
    data=PACKAGE/'CHFS2021年调查数据-stata14版本'
    fresh=pd.read_stata(next(data.glob('chfs2021_master_hh_pub_*.dta')),columns=['category','wgt_hh'],convert_categoricals=False)
    city=fresh.category.isin([111,112]);town=fresh.category.isin([121,122,123]);rural=fresh.category.isin([210,220])
    assert int(city.sum())==qc['scope']['city_records']==9226
    assert int(town.sum())==qc['scope']['town_records']==4098
    assert int(rural.sum())==qc['scope']['rural_records']==8703
    assert len(fresh)==qc['rows']['master_hh']==22027
    assert all(qc['key_checks'][k]==0 for k in qc['key_checks'])
    assert qc['rows']['hh']==qc['rows']['master_hh']
    assert qc['rows']['ind']==qc['rows']['master_ind']==68317
    assert status['new_complete_roles']==status['new_A_days']==status['new_B_rounds']==status['new_physics_results']==status['human_answers']==0
    assert status['collection_release']==status['training_release']==contract['collection_release']==contract['training_release']==False
    assert qc['finance_provenance']['cannot_label_entire_consumption_as_pure_2020_recall']
    assert not list(HERE.rglob('*.dta')) and not list(HERE.rglob('*.parquet')) and not list(HERE.rglob('*.csv'))
    links=[]
    for md in [HERE/'README.md',HERE/'DOCUMENT_REVIEW.md']:
        for link in re.findall(r'\]\(([^)]+)\)',md.read_text()):
            if not link.startswith(('https://','http://','#')):
                path=Path(link) if link.startswith('/') else md.parent/link
                assert path.exists(),link
                links.append(link)
    write(HERE/'VERIFICATION.json',{'batch_id':qc['batch_id'],
        'status':'pass_for_local_source_hashes_bindings_counts_links_and_declared_release_boundary',
        'source_files_hash_verified':len(source_checks),'field_bindings_verified':bindings,'field_groups':len(rules['groups']),
        'generation_steps':11,'city_count_independently_recomputed':9226,'local_markdown_links_verified':len(links),
        'independent_public_document_review':'DOCUMENT_REVIEW.md',
        'limits':['no official byte-identity authentication','no census membership/generation bridge validation','no household reconstruction or physical validity','no actor package or human answer verification','Markdown visual rendering not inspected'],
        'collection_release':False,'training_release':False,'code_sha256':sha(Path(__file__))})
    print(json.dumps({'status':'source_admission_verified','source_hashes':len(source_checks),'bindings':bindings,'city_rows':9226,'release':False}))

if __name__=='__main__':main()
