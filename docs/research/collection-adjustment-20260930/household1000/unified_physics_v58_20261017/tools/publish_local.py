"""Publish a verified reference-physics companion, without editing frozen A/B."""
import argparse
import hashlib
import json
import sys
from pathlib import Path

STAGE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(STAGE/'code'))
from core import read,save,sha,physics_hash,REPO,BASE

def main():
    p=argparse.ArgumentParser();p.add_argument('--remote-root',required=True);args=p.parse_args()
    acceptance=read(STAGE/'ACCEPTANCE.json');seal=read(STAGE/'FINAL_SEAL.json');verification=read(STAGE/'FINAL_VERIFICATION.json')
    if not acceptance['accepted']or not verification['passed']:raise ValueError('REMOTE_ACCEPTANCE_NOT_COMPLETE')
    if verification['seal_sha256']!=sha(STAGE/'FINAL_SEAL.json'):raise ValueError('SEAL_ASSOCIATION')
    if sha(STAGE/'FILE_MANIFEST.json.gz')!=seal['manifest_sha256']:raise ValueError('FILE_MANIFEST_HASH')
    if physics_hash()!=seal['physics_sha256']:raise ValueError('LOCAL_PHYSICS_SOURCE_MISMATCH')
    manifest=read(STAGE/'INPUT_MANIFEST.json')
    for path,expected in manifest['source_files'].items():
        src=Path(path)if path.startswith('/')else REPO/path
        if sha(src)!=expected:raise ValueError('ORIGINAL_SOURCE_CHANGED:'+path)
    bindings=read(STAGE/'PHYSICAL_BINDINGS10000.json');expected_cases={c['case_id']:c for r in manifest['records']for c in r['cases']}
    if len(bindings['records'])!=10000 or {r['case_id']for r in bindings['records']}!=set(expected_cases):raise ValueError('FULL_CASE_SET')
    bstage=BASE/'candidate_B_v57_20261017';sourceB=read(bstage/'PAIR_BINDINGS10000.json');brows={c['case_id']:c for r in sourceB['records']for c in r['rounds']}
    for record in bindings['records']:
        case=record['case_id'];path=STAGE/record['path']
        if sha(path)!=record['sha256']:raise ValueError('LOCAL_SUMMARY_HASH:'+case)
        if record['source_pair_sha256']!=brows[case]['sha256']or sha(bstage/brows[case]['path'])!=brows[case]['sha256']:raise ValueError('FROZEN_PAIR_CHANGED:'+case)
    subset=read(STAGE/'PHYSICAL_BINDINGS50.json')
    if subset['master_bindings_sha256']!=sha(STAGE/'PHYSICAL_BINDINGS10000.json')or len(subset['records'])!=500:raise ValueError('SAME_MASTER50')
    pointer={'schema':'eb.current_reference_physics.v58','stage':STAGE.name,'A_stage':'normal_A_v46_20261017','B_stage':'candidate_B_v57_20261017',
             'households':1000,'pairs':10000,'all10000_one_dataset':True,'reference_physics_replay_accepted':True,
             'A_B_schedules_modified':False,'B_failures_retained':True,'all_B_success_claimed':False,
             'bindings_path':str((STAGE/'PHYSICAL_BINDINGS10000.json').relative_to(REPO)),
             'bindings_sha256':sha(STAGE/'PHYSICAL_BINDINGS10000.json'),'seal_sha256':sha(STAGE/'FINAL_SEAL.json'),
             'source_B_bindings_sha256':sha(bstage/'PAIR_BINDINGS10000.json'),'source_A_bindings_sha256':sha(BASE/'normal_A_v46_20261017/A_BINDINGS10000.json'),
             'same_master50_type_counts':subset['type_counts'],'history_days':read(STAGE/'PHYSICS_CONTRACT.json')['history_days'],
             'reference_ACH':acceptance['reference_ACH'],'initial_state_scope':'specified and published common A/B state,not an observed household estimate',
             'historical_sensitivity_all_bounds_passed':acceptance['historical_sensitivity_pointwise_bounds_all_passed'],
             'raw_artifact_location':{'host':'connect.weste.seetacloud.com','port':32683,'root':args.remote_root,'credentials_included':False},
             'local_delivery':'all10000 physical summaries,bindings,seals and validation reports;full raw trajectories on compute server',
             'human_labels_created':0,'new_questionnaire_released':False}
    save(BASE/'CURRENT_PHYSICAL_INPUTS.json',pointer)
    save(REPO/'docs/household1000/CURRENT_PHYSICAL.json',pointer)
    save(STAGE/'LOCAL_DELIVERY_REVIEW.json',{'passed':True,'cases':10000,'original_B_pair_hashes_rechecked':10000,'source_files_unchanged':True,
         'same_master50_cases':500,'full_raw_verified_on_compute_server':True,'all_raw_locally_mirrored':False,
         'pointer_sha256':sha(BASE/'CURRENT_PHYSICAL_INPUTS.json'),'original_static_AB_pointers_preserved':True,
         'human_answers_modified':False,'questionnaire_released':False})
    chosen=['ordinary-v6-0001__2025-09-30','ordinary-v6-0011__2025-01-22','ordinary-v6-0001__2025-10-12']
    rows={r['case_id']:r for r in bindings['records']};examples=[]
    for case in chosen:
        rec=rows[case];data=read(STAGE/rec['path'])
        examples.append({'case_id':case,'summary_path':rec['path'],'summary_sha256':rec['sha256'],'A_primary_energy_kWh':data['A']['primary_energy_kWh'],
                         'B_primary_energy_kWh':data['B']['primary_energy_kWh'],'delta_rollout_kWh':data['delta_rollout_kWh'],
                         'mains_C':data['A']['mains_primary_C'],'B_EV_trips':data['B']['EV_trips'],'VPP':data['VPP_events'],
                         'recovery':data['recovery'],'specified_initial_state':data['specified_initial_state']})
    save(STAGE/'REVIEW_CASES.json',{'selection':'same three case IDs fixed before full run','records':examples})
    entry=(f'\n<!-- CURRENT_REFERENCE_PHYSICS_V58 -->\n'
           f'A46/B57的第5项参考物理回放：1000户、10000组A/B已完成并独立复核；原排程及100组相同保留。'
           f'最新仿真入口为 [CURRENT_PHYSICAL_INPUTS.json](docs/research/collection-adjustment-20260930/household1000/CURRENT_PHYSICAL_INPUTS.json)，'
           f'[复核报告](docs/research/collection-adjustment-20260930/household1000/{STAGE.name}/REPORT.md)。'
           '结果基于公开的给定初态；历史敏感性诊断保留，不声称未校准住宅的实测温度精度。'
           '完整轨迹保存在计算服务器，本地有全量摘要与哈希索引；问卷及人类答案尚未接入本版。\n'
           '<!-- /CURRENT_REFERENCE_PHYSICS_V58 -->\n')
    readme=REPO/'README.md';body=readme.read_text()
    if '<!-- CURRENT_REFERENCE_PHYSICS_V58 -->'not in body:readme.write_text(body+entry)
    print(json.dumps({'published_reference_physics':True,'pairs':10000,'same_master50':subset['type_counts'],'static_A46_B57_unchanged':True},ensure_ascii=False))

if __name__=='__main__':main()
