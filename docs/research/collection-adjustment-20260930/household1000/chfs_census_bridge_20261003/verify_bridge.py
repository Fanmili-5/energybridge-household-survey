#!/usr/bin/env python3
"""Check independent synthetic cases, unchanged quotas and conditional H7 scope."""
import json
import math
import re
from collections import Counter
from pathlib import Path
import bridge_rules
from run_bridge import HERE,PARENT,BATCH,sha,write

def main():
    cases=json.loads((HERE/'REGRESSION_CASES.json').read_text())
    assertions=0;results=[]
    for case in cases['cases']:
        result=getattr(bridge_rules,case['api'])(**case['input'])
        for field,expected in case['expected_subset'].items():
            actual=result[field]
            if isinstance(expected,float):assert math.isclose(actual,expected,abs_tol=1e-7),(case['id'],field,expected,actual)
            else:assert actual==expected,(case['id'],field,expected,actual)
            assertions+=1
        results.append({'case_id':case['id'],'pass':True})
    data=json.loads((HERE/'SLOT_BRIDGE_AUDIT.json').read_text())
    qc=json.loads((HERE/'BRIDGE_QC.json').read_text())
    allocation=json.loads((PARENT/'evidence_contract_20261001/POPULATION_ALLOCATION_CANDIDATE_V2.json').read_text())
    authority=json.loads((PARENT/'evidence_contract_20261001/CITY_AUTHORITY_CONSTRAINTS_V2.json').read_text())
    rooms={r['province']:r['generation_room_counts'] for r in authority['complete_province_generation_room_counts']}
    assert len(data['slots'])==len(allocation['slots'])==1000
    for s,original in zip(data['slots'],allocation['slots']):
        for current,old in [('slot_id','slot_id'),('province','province'),('target_census_size_category','size_category'),('target_exact_member_count','exact_member_count'),('target_census_generation_category','generation_category')]:
            assert s[current]==original[old]
        assert s['source_record_assigned'] is False and s['complete_role'] is False and s['cross_province_transport_executed'] is False
        assert 'ordinary' in s['H7_population_scope']
        g=4 if s['target_census_generation_category']=='5+' else int(s['target_census_generation_category'])-1
        row=rooms[s['province']][g]
        expected={str(i+1) if i<4 else '5+':c/sum(row) for i,c in enumerate(row)}
        assert s['conditional_census_H7_distribution_if_ordinary_dwelling']==expected
    for name,summary in qc['stage_support'].items():
        numbers=[s['source_support_same_province_size_generation'][name]['source_count'] for s in data['slots']]
        assert summary['target_slots_with_source']==sum(n>0 for n in numbers)
        assert summary['target_slots_without_source']==sum(n==0 for n in numbers)
        assert summary['target_slots_source_count_under5']==sum(n<5 for n in numbers)
    assert qc['route_candidate_counts']==dict(Counter(s['source_route_candidate'] for s in data['slots']))
    assert sum(qc['temporal_alignment']['status_counts'].values())==9226
    assert qc['temporal_alignment']['time_aligned_member_area_room_proxy_source_records']==qc['stage_support']['time_aligned_area_and_H7_proxy']['source_records']
    for name,digest in qc['code_sha256'].items():assert sha(HERE/name)==digest
    assert qc['raw_records_exported']==qc['source_ids_exported']==qc['new_complete_roles']==0
    assert qc['collection_release'] is False and qc['training_release'] is False
    # Published slot payload contains target descriptors and aggregate support,
    # never source household/member identifiers or source monetary/area values.
    forbidden={'hhid','pline','_local_hhid','total_income','total_consump','recorded_building_area_m2','recorded_usable_area_m2'}
    def check(obj):
        if isinstance(obj,dict):
            assert not (set(obj)&forbidden)
            for v in obj.values():check(v)
        elif isinstance(obj,list):
            for v in obj:check(v)
    check(data)
    # Bind the newly published contract and prose to existing artifacts and
    # independently recorded source-byte checks; do not promote them to census
    # equivalence, donor assignment or role readiness.
    contract=json.loads((HERE/'GENERATION_BRIDGE_CONTRACT.json').read_text())
    ledger=json.loads((HERE/'SOURCE_LEDGER.json').read_text())
    integrity=json.loads((HERE/'SOURCE_INTEGRITY_VERIFICATION.json').read_text())
    assert integrity['ledger_sha256']==sha(HERE/'SOURCE_LEDGER.json')
    assert integrity['builder_sha256']==sha(HERE/'build_source_ledger.py')
    source_ids={e['source_id'] for e in ledger['entries']}
    for field in ['step2_members_and_generations','step3_current_dwelling_area_rooms']:
        assert set(contract[field]['evidence_source_ids'])<=source_ids
    for binding in ledger['rule_evidence_bindings']:
        assert set(binding['source_ids'])<=source_ids
    for field in ['base_generation_contract','population_slots','authoritative_constraints','source_ledger','source_field_rules']:
        assert (HERE/contract[field]).is_file(),field
    for ref in contract['implementation'].values():
        assert (HERE/ref.split(':')[0]).is_file(),ref
    for ref in contract['execution_outputs'].values():
        assert (HERE/ref).is_file(),ref
    local_links=[]
    for ref in re.findall(r'\]\(([^)]+)\)',(HERE/'README.md').read_text()):
        if not ref.startswith(('https://','http://')):
            assert (HERE/ref).is_file(),ref
            local_links.append(ref)
    assert contract['step1_scope']['quotas_changed'] is False
    assert contract['slot_matching_policy']['donor_assignment_executed'] is False
    assert contract['counts']['new_complete_roles']==0
    assert contract['collection_release'] is False and contract['training_release'] is False
    write(HERE/'VERIFICATION.json',{'batch_id':BATCH,'status':'pass_for_bridge_rules_regression_source_links_and_unchanged1000_quota_scope',
        'synthetic_regression_cases':len(results),'regression_assertions':assertions,'case_results':results,
        'target_slots_identity_and_quota_preserved':1000,'ordinary_conditional_H7_vectors_recomputed':1000,
        'stage_coverage_recomputed_from_slot_payload':list(qc['stage_support']),
        'formal_contract_source_ids_resolved':True,'readme_local_links_checked':len(local_links),
        'source_integrity_attestation_bound_to_ledger_and_builder':True,
        'no_original_ids_source_money_or_area_in_slot_payload':True,'new_complete_roles':0,
        'limits':['pure synthetic cases and aggregate verification; no population equivalence validation','actual census residents and H5/H7 remain unidentified','no source-to-human household copying','no physics or actor package verified'],
        'collection_release':False,'training_release':False,'code_sha256':sha(Path(__file__))})
    print(json.dumps({'cases':len(results),'assertions':assertions,'slots_preserved':1000,'conditional_H7_verified':1000,'release':False}))

if __name__=='__main__':main()
