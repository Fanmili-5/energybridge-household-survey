"""Verify the current public contract and optional authorized controlled release.

Read-only; never generates schedules, starts EP, contacts model APIs or reads answers.
"""
import argparse
import collections
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def read(path):return json.loads(path.read_text())
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def jsonl(path):return [json.loads(line)for line in path.read_text().splitlines()if line]

def check(controlled=None):
    folder=ROOT/'benchmark/releases/reference50-v1';manifest=read(folder/'MANIFEST.json')
    assert manifest['dataset_id']=='reference50-v1'and manifest['cohort']['households']==50 and manifest['cohort']['cases']==500
    assert manifest['master']['households']==1000 and manifest['master']['cases']==10000 and manifest['master']['physical_complete']is False
    assert manifest['online']['questions_per_participant']==10 and manifest['online']['invitation_required']is False
    assert manifest['training_release']is False and manifest['human_validity_verified']is False
    master=jsonl(folder/'MASTER_INPUT_INDEX10000.jsonl');cases=jsonl(folder/'CASE_INDEX50.jsonl')
    assert len(master)==10000 and len(cases)==500
    master_by_id={r['case_id']:r for r in master};by_id={r['case_id']:r for r in cases}
    assert len(master_by_id)==10000 and len(by_id)==500 and set(by_id)<=set(master_by_id)
    master_counts=collections.Counter(r['household_id']for r in master);counts=collections.Counter(r['household_id']for r in cases)
    assert len(master_counts)==1000 and set(master_counts.values())=={10}
    assert len(counts)==50 and set(counts.values())=={10}
    types={r['household_id']:r['type']for r in cases}
    assert collections.Counter(types.values())==manifest['cohort']['type_counts']
    for case in cases:
        assert case['master_pair_sha256']==master_by_id[case['case_id']]['B57_sha256']
    source=read(ROOT/'benchmark/generation/SOURCE_CATALOG.json')
    for item in source['files']:
        path=ROOT/item['path'];assert path.resolve().is_relative_to(ROOT)and sha(path)==item['sha256'],item['path']
    for name,expected in manifest['collector_files'].items():assert sha(ROOT/'benchmark/collector'/name)==expected,name
    status=read(ROOT/'docs/household1000/STATUS.json');online=read(ROOT/'docs/household1000/CURRENT_QUESTIONNAIRE50.json')
    assert status['active_stage']=='reference50-v1'and not status['current_full1000_acceptance']
    assert online['release_sha256']==manifest['online']['release_sha256']and online['cases']==500 and online['questions_per_participant']==10
    publication=read(ROOT/'benchmark/PUBLICATION_MANIFEST.json')
    for name,expected in publication['files'].items():assert sha(ROOT/name)==expected,name
    if controlled:
        controlled=Path(controlled);release=read(controlled/'FORMAL_RELEASE.json')
        assert release['release_sha256']==manifest['online']['release_sha256']
        for case in cases:
            packet=controlled/'public'/case['path'];profile=controlled/f"public/households/{case['household_id']}.json"
            assert sha(packet)==case['packet_sha256']and sha(profile)==case['profile_sha256']
            value=read(packet);assert value['response']is None and value['bindings']['source_pair_sha256']==case['master_pair_sha256']
        for name,expected in release['files'].items():assert sha(controlled/name)==expected,name
    return {'passed':True,'public_source_files_verified':len(source['files']),'public_payload_files_verified':len(publication['files']),
            'master_input_cases':10000,'same_source_reference_cases':500,'controlled_cases_verified':500 if controlled else 0,
            'full1000_physical_complete':False,'human_validity_claim':False,'EP_started':False}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--controlled-release',type=Path);a=p.parse_args();print(json.dumps(check(a.controlled_release)))
