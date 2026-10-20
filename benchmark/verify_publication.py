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
    for name,expected in manifest['collector_files'].items():
        archived=folder/'runtime'/name
        assert sha(archived if archived.exists() else ROOT/'benchmark/collector'/name)==expected,name
    status=read(ROOT/'docs/household1000/STATUS.json');online=read(ROOT/'docs/household1000/CURRENT_QUESTIONNAIRE50.json')
    dataset=online['public_dataset_id']
    assert status['active_stage']==dataset and not status['current_full1000_acceptance']
    assert online['cases']==500 and online['households']==50 and online['questions_per_participant']==10
    assert status['online']==online and status['current_questionnaire50_collection']==online
    if dataset=='reference50-v1':
        assert online['release_sha256']==manifest['online']['release_sha256']
    elif dataset=='reference50-v4-proposal':
        current=read(ROOT/'benchmark/releases/reference50-v4-proposal/MANIFEST.json')
        assert online['release_sha256']==current['release_sha256']
        assert current['outcomes']=='not_computed'and current['cases']==500 and current['households']==50
        assert current['label_condition']=='proposal_judgment_before_physical_results'
        assert current['new_engine_runs']==0 and current['old_B_results_reused']is False
        assert sha(ROOT/current['aggregate_review_path'])==current['aggregate_review_sha256']
        assert online['physical_stage']=='not_run_for_new_B'and online['impact_stage']=='not_computed'
    elif dataset=='reference50-v4-ui91-physics':
        current=read(ROOT/'benchmark/releases/reference50-v4-ui91-physics/MANIFEST.json')
        assert online['release_sha256']==current['release_sha256']
        assert current['cases']==500 and current['households']==50 and current['new_engine_runs']==1000
        assert sum(current['physical_statuses'].values())==500
        assert current['label_condition']=='role_judgment_with_version_bound_physics'
        assert current['old_B_results_reused'] is False and current['original_A_B_commands_modified'] is False
        assert current['presentation_revision']=='eb.questionnaire50.refined.v91.newAB.v1'
        assert sha(ROOT/current['aggregate_review_path'])==current['aggregate_review_sha256']
        assert online['physical_stage']=='all500_frozen_new_AB_attempted'
        assert current['status']=='active_online' and online['physical_statuses']==current['physical_statuses']
        assert sha(ROOT/current['activation_record'])==current['activation_record_sha256']
        activation=read(ROOT/current['activation_record'])
        assert activation['passed'] and activation['release_sha256']==current['release_sha256']
        assert activation['old_records_preserved'] and activation['backup_active']
    elif dataset=='reference50-v4-ui91-complete':
        current=read(ROOT/'benchmark/releases/reference50-v4-ui91-complete/MANIFEST.json')
        assert current['release_sha256']==online['release_sha256']
        assert current['formal_collection_ready']is True and current['physical_statuses']=={'computed':500}
        assert current['cases']==500 and current['households']==50 and current['questions_per_household']==10
        assert current['original_selected_cases_retained']==497 and current['engineering_replenished_cases']==3
        assert current['unchanged_annual_A_hardware_and_family']
        if current.get('operations_record'):
            assert sha(ROOT/current['operations_record'])==current['operations_record_sha256']
            operations=read(ROOT/current['operations_record'])
            assert operations['release_sha256']==current['release_sha256']
            assert operations['retired_records_deleted_at_user_request']and operations['live_records_preserved']
            assert current['old_records_preserved']is False and current['old_records_preserved_at_activation']is True
            assert operations['complete_payload_check']['passed']and operations['public_body_capacity']['passed']
            assert operations['nginx_body_limit_bytes']==262144
        else:assert current['old_records_preserved']
        assert current['UI91_presentation_revision']=='eb.questionnaire50.refined.v91.newAB.v1'
        assert sha(ROOT/current['aggregate_review_path'])==current['aggregate_review_sha256']
        review=read(ROOT/current['aggregate_review_path'])
        assert review['unknown_consequences']==0 and review['physical_statuses']=={'computed':500}
        assert review['paired_integrity_failures']==0 and review['selection_by_VPP_savings_or_service_success']is False
        assert review['HTTP_protocol']['passed'] and review['browser_QA']['passed'] and review['unit_tests']['passed']
        if current['status']=='active_online':
            assert sha(ROOT/current['activation_record'])==current['activation_record_sha256']
            activation=read(ROOT/current['activation_record'])
            assert activation['passed'] and activation['release_sha256']==current['release_sha256']
            assert activation['old_records_preserved'] and activation['backup_active']
        else:
            assert current['status']=='prepared_zero_unknown_waiting_verified_cutover'
            assert online['collection_state']=='paused_waiting_verified_cutover'
    else:raise AssertionError('Unknown current collection dataset: '+str(dataset))
    publication=read(ROOT/'benchmark/PUBLICATION_MANIFEST.json')
    for name,expected in publication['files'].items():assert sha(ROOT/name)==expected,name
    if controlled:
        controlled=Path(controlled);release=read(controlled/'FORMAL_RELEASE.json')
        assert release['release_sha256']==online['release_sha256']
        assert hashlib.sha256(json.dumps({k:v for k,v in release.items()if k!='release_sha256'},ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()==release['release_sha256']
        for name,expected in release['files'].items():assert sha(controlled/name)==expected,name
        if dataset=='reference50-v1':
            for case in cases:
                packet=controlled/'public'/case['path'];profile=controlled/f"public/households/{case['household_id']}.json"
                assert sha(packet)==case['packet_sha256']and sha(profile)==case['profile_sha256']
                value=read(packet);assert value['response']is None and value['bindings']['source_pair_sha256']==case['master_pair_sha256']
        else:
            index=read(controlled/'INDEX50.json')
            assert len(index['cases'])==500 and len(index['households'])==50
            actual_dates={(x['household_id'],x['date'])for x in index['cases']};original_dates={(x['household_id'],x['date'])for x in cases}
            if dataset=='reference50-v4-ui91-complete':
                assert len(actual_dates)==500
                assert release['formal_collection_ready'] and release['physical_statuses']=={'computed':500}
                lineage=release['engineering_replenishment'];assert lineage['retained_original_cases']==497
                assert len(lineage['records'])==3 and lineage['VPP_or_household_success_filters']is False
                added=set();removed=set()
                for entry in lineage['records']:
                    matching=[x for x in index['cases']if x['path'].endswith('/'+entry['new_id']+'.json')]
                    assert len(matching)==1 and matching[0]['date']==entry['new_date']
                    hid=matching[0]['household_id'];added.add((hid,entry['new_date']));removed.add((hid,entry['old_date']))
                assert actual_dates-original_dates==added and original_dates-actual_dates==removed
                assert len(actual_dates&original_dates)==497
                for hid in index['households']:
                    dates=[x['date']for x in index['cases']if x['household_id']==hid]
                    assert dates==sorted(dates) and len(set(dates))==10
            else:assert actual_dates==original_dates
            profiles={x['household_id']:x['profile_sha256']for x in cases}
            if dataset=='reference50-v4-proposal':assert index['profiles_sha256']==profiles
            else:
                for hid,expected in profiles.items():
                    p=read(controlled/'public/households'/(hid+'.json'));assert 'display_housing'in p
                    p.pop('display_housing')
                    raw=(json.dumps(p,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)+'\n').encode()
                    assert hashlib.sha256(raw).hexdigest()==expected
            for row in index['cases']:
                packet=controlled/'public'/row['path'];assert sha(packet)==row['sha256']
                value=read(packet)
                assert value['response']is None
                if dataset=='reference50-v4-proposal':
                    assert value['outcome_status']=='not_computed'and all(value[k]is None for k in ['impact','VPP_results'])
                    assert value['bindings']['label_condition']=='proposal_judgment_before_physical_results'
                else:
                    assert value['outcome_status']==value['physical_review']['status']
                    assert value['bindings']['label_condition']=='role_judgment_with_version_bound_physics'
                    assert value['bindings']['source_pair_sha256']==value['physical_review']['source_frozen_pair_sha256']
                    assert value['bindings']['source_profile_sha256']==profiles[row['household_id']]
                    if value['outcome_status']=='computed':
                        assert value['impact']==value['physical_review']['actual_outcomes']and value['VPP_results']==value['impact']['events']
                        assert value['physical_review']['native_numerical_convergence']['passed']
                        assert value['physical_review']['weather_input_quality']['passed']
                    else:assert value['impact']is None and value['VPP_results']is None and value['physical_review']['actual_outcomes']is None
                assert all(e['start_min']==1080 and e['end_min']==1140 for e in value['VPP_requests'])
            for hid,expected in index['profiles_sha256'].items():assert sha(controlled/'public/households'/(hid+'.json'))==expected
    return {'passed':True,'public_source_files_verified':len(source['files']),'public_payload_files_verified':len(publication['files']),
            'master_input_cases':10000,'same_source_reference_cases':500,'controlled_cases_verified':500 if controlled else 0,
            'archived_master_relationship':'reference50-v1_A46_B57;not_a_claim_that_new_v4_B_is_in_old_master',
            'active_dataset_id':dataset,'active_release_sha256':online['release_sha256'],
            'full1000_physical_complete':False,'human_validity_claim':False,'EP_started':False}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--controlled-release',type=Path);a=p.parse_args();print(json.dumps(check(a.controlled_release)))
