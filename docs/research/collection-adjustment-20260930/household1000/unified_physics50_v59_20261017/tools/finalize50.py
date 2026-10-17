"""Freeze only the original 50-household reference replay; never start full runs."""
import argparse
import collections
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

STAGE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(STAGE / 'code'))
from core import ROOT, BASE, REPO, VERSION, read, save, sha, digest, physics_hash, code_hash
from finalize import verify_case


def checked_case(job):
    audit = verify_case(job)
    row, case, record, label = job
    config = read(ROOT / 'results' / label / 'RUN_CONFIG.json')
    folder = ROOT / 'results' / label / row['household_id'] / case['date']
    pair = read(ROOT / case['path'])
    for side in ('A', 'B'):
        result = read(folder / side / 'RESULT.json')
        expected = digest({
            'pair': pair['source_pair_sha256'], 'side': side,
            'pack': sha(ROOT / row['path']), 'physics': physics_hash(),
            'history': config['history'], 'engine_sha256': config['engine_sha256'],
            'reference_ACH': config['reference_ACH'],
            'portal_flow_scale': config['portal_flow_scale'],
        })
        if result['fingerprint'] != expected:
            audit['errors'].append(side + '_PHYSICAL_FINGERPRINT')
        if not result.get('raw_SQL_archive_retained'):
            audit['errors'].append(side + '_MISSING_RAW_SQL')
    summary = read(folder / 'PHYSICAL_SUMMARY.json')
    if summary['common_history_max_normalized_error'] > 1e-7:
        audit['errors'].append('COMMON_PREDECISION_STATE')
    if not summary.get('specified_initial_state'):
        audit['errors'].append('MISSING_SPECIFIED_INITIAL_STATE')
    return audit


def seal(workers):
    manifest = read(ROOT / 'INPUT_MANIFEST.json')
    subset = set(manifest['subset50_ids'])
    households = [r for r in manifest['records'] if r['household_id'] in subset]
    expected = {c['case_id'] for r in households for c in r['cases']}
    types = dict(collections.Counter(r['type'] for r in households))
    if len(subset) != 50 or len(expected) != 500 or types != {'A': 5, 'B': 15, 'C': 16, 'D': 5, 'E': 4, 'F': 5}:
        raise ValueError('ORIGINAL_SAME_MASTER50_CHANGED')
    runs = read(ROOT / 'results/pilot50/RUN_BINDINGS.json')
    review = read(ROOT / 'results/pilot50/REVIEW.json')
    config = read(ROOT / 'results/pilot50/RUN_CONFIG.json')
    for records in (runs['records'], review['records']):
        if len(records) != 500 or {r['case_id'] for r in records} != expected:
            raise ValueError('EXACT500_CASE_SET')
    if not runs['passed'] or not review['passed'] or review['counts']['passed'] != 500:
        raise ValueError('RUN_OR_READBACK_ERRORS')
    if runs['input_manifest_sha256'] != sha(ROOT / 'INPUT_MANIFEST.json'):
        raise ValueError('INPUT_MANIFEST_CHANGED')
    if config['physics_sha256'] != physics_hash() or config['history'] != 112 or config['portal_flow_scale'] != 1:
        raise ValueError('PHYSICAL_MODEL_CHANGED')
    for name in ('CROSS_PLATFORM_REVIEW.json', 'REGRESSION_RESULTS.json', 'AIRFLOW_SENSITIVITY_REVIEW.json'):
        report = read(ROOT / name)
        if not report['passed'] or report['physics_sha256'] != physics_hash():
            raise ValueError('VALIDATION_MISMATCH:' + name)
    records = {r['case_id']: r for r in review['records']}
    jobs = [(r, c, records[c['case_id']], 'pilot50') for r in households for c in r['cases']]
    with ProcessPoolExecutor(max_workers=workers) as pool:
        audits = list(pool.map(checked_case, jobs, chunksize=2))
    errors = [{'case_id': a['case_id'], 'errors': a['errors']} for a in audits if a['errors']]
    if errors:
        save(ROOT / 'SEAL_ERRORS50.json', errors)
        raise ValueError('ARTIFACT_ERRORS50:' + str(len(errors)))
    common = {
        'schema': 'eb.specified_common_initial_state.v59', 'passed': True, 'cases': 500,
        'scope': 'original same-master50 only;published common A/B state,not invariance to alternative histories',
        'physics_sha256': physics_hash(), 'history_days': config['history'],
        'all_predecision_channels_matched': True, 'tolerance_normalized': 1e-7,
        'review_sha256': sha(ROOT / 'results/pilot50/REVIEW.json'),
        'historical_sensitivity_report_sha256': sha(ROOT / 'INITIALIZATION_REVIEW.json'),
        'historical_pointwise_bounds_all_passed': read(ROOT / 'INITIALIZATION_REVIEW.json')['passed'],
    }
    save(ROOT / 'COMMON_INITIAL_STATE_REVIEW50.json', common)
    bindings = {
        'schema': VERSION, 'households': 50, 'pairs': 500, 'same_master': True, 'type_counts': types,
        'master_input_households': 1000, 'master_input_pairs': 10000,
        'master_physics_accepted': False, 'full1000_deferred_by_user': True,
        'subset_selection': 'unchanged original proportional sample;no outcome-based selection',
        'A_stage': 'normal_A_v46_20261017', 'B_stage': 'candidate_B_v57_20261017',
        'input_manifest_sha256': sha(ROOT / 'INPUT_MANIFEST.json'), 'physics_sha256': physics_hash(),
        'household_ids': sorted(subset), 'records': review['records'],
        'human_labels_created': 0, 'schedules_modified': False,
    }
    save(ROOT / 'PHYSICAL_BINDINGS50.json', bindings)
    acceptance = {
        'schema': VERSION, 'accepted': True, 'households': 50, 'pairs': 500, 'engine_runs': 1000,
        'scope': 'paired numerical reference replay and artifact consistency for original50;not B service success,field calibration or human acceptance',
        'full1000_deferred_by_user': True, 'master1000_physics_accepted': False,
        'source_requests_unchanged': True, 'same_master_type_counts': types,
        'identical_command_cases_in_this50': sum(a['identical_requests'] for a in audits),
        'source_B_constraint_conflict_cases': sum(a['source_constraint_conflict'] for a in audits),
        'full_metering_verified': True, 'common_predecision_states_verified': True,
        'specified_initial_state_published': True, 'all_failures_retained': True,
        'historical_sensitivity_pointwise_bounds_all_passed': common['historical_pointwise_bounds_all_passed'],
        'alternative_history_pointwise_invariance_claimed': False,
        'reference_ACH': config['reference_ACH'], 'weather_based_mains': True,
        'physical_counts': review['counts'], 'whole_VPP_event_relations': review['whole_VPP_event_relations'],
        'human_acceptance_labels_created': 0, 'questionnaire_released': False, 'errors': [],
        'bindings_sha256': sha(ROOT / 'PHYSICAL_BINDINGS50.json'), 'physics_sha256': physics_hash(),
        'thermal_environment_policy_sha256': sha(ROOT / 'THERMAL_ENVIRONMENT_POLICY.json'),
        'history_contrast_sensitivity_cases':read(ROOT/'INITIALIZATION_REVIEW.json')['cases'],
        'history_conditional_comparisons_robust':read(ROOT/'INITIALIZATION_REVIEW.json')['conditional_comparisons_robust'],
        'airflow_conditional_comparisons_robust':read(ROOT/'AIRFLOW_SENSITIVITY_REVIEW.json')['conditional_comparisons_robust'],
        'incomplete_services_not_counted_as_savings':True,'evaluation_inclusion_changed':False,
    }
    save(ROOT / 'ACCEPTANCE50.json', acceptance)
    contract = dict(read(ROOT / 'PHYSICS_CONTRACT.json'))
    contract.update(households=50, pairs=500, source_master_households=1000, source_master_pairs=10000,
                    full1000_deferred_by_user=True, identical_cases=acceptance['identical_command_cases_in_this50'],
                    initialization_acceptance='all500 pairs share published common predecision states',
                    source_master_contract_sha256=sha(ROOT / 'PHYSICS_CONTRACT.json'))
    save(ROOT / 'PHYSICS_CONTRACT50.json', contract)
    examples = []
    chosen_ids=['ordinary-v6-0181__2025-05-21','ordinary-v6-0375__2025-07-17','ordinary-v6-0828__2025-07-17','ordinary-v6-0101__2025-07-09','ordinary-v6-0398__2025-12-26']
    chosen = [r for cid in chosen_ids for r in review['records']if r['case_id']==cid]
    for record in chosen:
        summary = read(ROOT / record['path'])
        examples.append({'case_id': record['case_id'], 'summary_path': record['path'],
                         'summary_sha256': record['sha256'], 'B_EV_trips': summary['B']['EV_trips'],
                         'VPP_events': summary['VPP_events'], 'recovery': summary['recovery'],
                         'delta_rollout_kWh': summary['delta_rollout_kWh'],
                         'electricity_comparison':summary['electricity_comparison'],
                         'temperature_exposure':summary['temperature_exposure'],
                         'simulation_uncertainty':summary['simulation_uncertainty']})
    save(ROOT / 'REVIEW_CASES50.json', {'selection': 'five cases identified in prior review;not selected to improve new outcomes', 'records': examples})
    contract['illustrative_case_ids'] = [r['case_id'] for r in examples]
    save(ROOT / 'PHYSICS_CONTRACT50.json', contract)
    c = review['counts']
    report = [
        '# A46/B57：固定50户、500组参考仿真', '',
        '本轮仅固定原同源50户，每户10个日期，共500组A/B（1000次EnergyPlus运行）。六类户数为5/15/16/5/4/5；未重新抽样。1000户主数据及A46/B57排程保留，全量仿真按用户要求暂缓。', '',
        '500组均完成新版运行、指令独立读回、电耗计量闭合和共同初态核对。沿用设备、热罐、进水和EV模型；新增按原房型门洞的房间间空气交换、厨卫/烘干排风及独立风机电耗，渗透与排风按Quadrature组合。所有实际数值来自EnergyPlus，未裁剪高温高湿或按结果调参。', '',
        f"源B约束冲突保留{c['source_constraint_conflict_cases']}组；B有{c['B_EV_target_shortfall_departures']}次出发目标电量不足。{c.get('within_declared_tolerances_to_horizon',0)}组在给定容差内恢复，{c.get('not_restored_within_horizon',0)}组观察期内未恢复，{c.get('no_executable_request_difference',0)}组原指令相同。引擎运行完成不代表B满足需求。", '',
        f"VPP窗口响应：顺向{review['whole_VPP_event_relations'].get('aligned',0)}、反向{review['whole_VPP_event_relations'].get('opposing',0)}、未变化{review['whole_VPP_event_relations'].get('unchanged',0)}个事件；均如实保留，未按B效果筛选。A/B设备程序未执行批次分别为{c['A_unexecuted_batches']}/{c['B_unexecuted_batches']}，供电边界越限案例分别为{c['A_supply_violation_cases']}/{c['B_supply_violation_cases']}。", '',
        f"失败后果统计现在覆盖整个观察期：B后续未执行{c['B_future_unexecuted_batches']}批，未取出{c['B_failed_retrieval_batches']}批。每组分别提供当日/观察期电耗、服务缺口及恢复状态，服务未完成或状态未恢复时不生成等服务节能数值。该口径不决定是否纳入评测，也不代填接受/拒绝。", '',
        f"初态历史验证100组中，{acceptance['history_conditional_comparisons_robust']}组A/B差值在预定敏感性界限内；另50户第6日期进行了门洞交换量0.5/2倍验证，100次比较中{acceptance['airflow_conditional_comparisons_robust']}次在给定界限内。所有超界及VPP判断变化保留于原报告，逐组摘要标明是否实际验证。", '',
        '范围：结果是EB参数、构造住房、典型年天气、明确的门洞/排风条件和公开给定初态下的可复现比较，不是实测校准。历史和空气交换敏感性的所有结果原样保留，超界不删样，也不写成通过；没有声称逐户绝对温度预测准确。热水器沿用EB单节点模型。EnergyPlus警告原样保留于各侧RESULT.json及原始日志。', '',
        '本轮不生成接受/拒绝标签或未绑定电价的收益，不发布新问卷。第5项仅完成50户参考回放；不把它写作1000户全量物理验收。', '',
        '入口：`PHYSICAL_BINDINGS50.json`（500组摘要索引）、`ACCEPTANCE50.json`、`REVIEW_CASES50.json`、`FINAL_SEAL50.json`。方法见`METHODS.md`，实际复核见`results/pilot50/REVIEW.json`。', '',
    ]
    (ROOT / 'REPORT50.md').write_text('\n'.join(report))
    files = {f['path']: f for a in audits for f in a['files']}
    paths = [p for directory in ('code', 'tools') for p in (ROOT / directory).rglob('*.py') if '__pycache__' not in p.parts]
    paths += [ROOT / r['path'] for r in households]
    paths += [ROOT / c['path'] for r in households for c in r['cases']]
    weather_hashes = {read(ROOT / r['path'])['weather_sha256'] for r in households}
    paths += [ROOT / 'inputs/weather' / (h + '.epw') for h in weather_hashes]
    paths += [ROOT / 'inputs' / n for n in ('schema_fields.json.gz', 'native_rows.json.gz')]
    names = ['INPUT_MANIFEST.json', 'SOURCE_MASTER_INPUT_MANIFEST.json','SOURCE_PROVENANCE.json',
             'THERMAL_ENVIRONMENT_POLICY.json','VALIDATION_PLAN.json','AIRFLOW_SENSITIVITY_REVIEW.json',
             'THERMAL_REPAIR_REVIEW.json','THERMAL_REPAIR_REVIEW.md',
             'PHYSICS_CONTRACT.json', 'PHYSICS_CONTRACT50.json', 'METHODS.md',
             'INITIALIZATION_REVIEW.json', 'COMMON_INITIAL_STATE_REVIEW50.json', 'CROSS_PLATFORM_REVIEW.json',
             'REGRESSION_RESULTS.json', 'PHYSICAL_BINDINGS50.json', 'ACCEPTANCE50.json', 'REVIEW_CASES50.json', 'REPORT50.md',
             'results/pilot50/RUN_CONFIG.json', 'results/pilot50/RUN_BINDINGS.json', 'results/pilot50/REVIEW.json']
    paths += [ROOT / n for n in names]
    for label in ('initialization112','initialization224','portal_low','portal_high'):
        for p in (ROOT/'results'/label).rglob('*'):
            if p.is_file()and not p.name.startswith('._')and '.tmp.'not in p.name:
                paths.append(p)
    for p in paths:
        rel = str(p.relative_to(ROOT))
        files[rel] = {'path': rel, 'sha256': sha(p), 'bytes': p.stat().st_size}
    save(ROOT / 'FILE_MANIFEST50.json.gz', {'schema': VERSION, 'households': 50, 'pairs': 500,
         'files': [files[p] for p in sorted(files)], 'source_files': manifest['source_files']})
    save(ROOT / 'FINAL_SEAL50.json', {'schema': VERSION, 'accepted': True, 'households': 50, 'pairs': 500,
         'manifest_sha256': sha(ROOT / 'FILE_MANIFEST50.json.gz'),
         'physical_bindings_sha256': sha(ROOT / 'PHYSICAL_BINDINGS50.json'),
         'input_manifest_sha256': sha(ROOT / 'INPUT_MANIFEST.json'), 'physics_sha256': physics_hash(),
         'source_code_sha256': code_hash(), 'files': len(files), 'full1000_deferred_by_user': True})
    print(acceptance, flush=True)


def verify(evidence_only=False):
    seal = read(ROOT / 'FINAL_SEAL50.json')
    if sha(ROOT / 'FILE_MANIFEST50.json.gz') != seal['manifest_sha256']:
        raise ValueError('MANIFEST_CHANGED')
    files = read(ROOT / 'FILE_MANIFEST50.json.gz')['files']
    required = files
    if evidence_only:
        # All exported inputs, code, reports and500 summaries must be local.
        # Raw per-side results stay covered by the server's complete verifier.
        required = [r for r in files if not r['path'].startswith('results/')
                    or r['path'].endswith('/PHYSICAL_SUMMARY.json')
                    or r['path'].endswith(('/RUN_CONFIG.json','/RUN_BINDINGS.json','/REVIEW.json'))]
        if sum(r['path'].endswith('/PHYSICAL_SUMMARY.json') for r in required) != 500:
            raise ValueError('INCOMPLETE500_SUMMARY_MANIFEST')
    errors = [r['path'] for r in required if not (ROOT / r['path']).is_file() or sha(ROOT / r['path']) != r['sha256']]
    report = {'schema': VERSION, 'passed': not errors, 'households': 50, 'pairs': 500,
              'checked_files': len(required), 'errors': errors, 'seal_sha256': sha(ROOT / 'FINAL_SEAL50.json'),
              'verified_artifact_root': str(ROOT), 'evidence_only': evidence_only,
              'all50_raw_locally_present': not evidence_only and not str(ROOT).startswith('/root/')}
    save(ROOT / ('LOCAL_EVIDENCE_REVIEW50.json' if evidence_only else 'FINAL_VERIFICATION50.json'), report)
    print(report, flush=True)
    if errors:
        raise SystemExit(2)


def publish():
    acceptance = read(ROOT / 'ACCEPTANCE50.json')
    verification = read(ROOT / 'FINAL_VERIFICATION50.json')
    local = read(ROOT / 'LOCAL_EVIDENCE_REVIEW50.json')
    if not acceptance['accepted'] or not verification['passed'] or not local['passed']:
        raise ValueError('VERIFIED50_NOT_READY')
    if verification['seal_sha256'] != sha(ROOT / 'FINAL_SEAL50.json'):
        raise ValueError('LOCAL_SEAL_ASSOCIATION')
    if local['seal_sha256'] != sha(ROOT / 'FINAL_SEAL50.json'):
        raise ValueError('LOCAL_EVIDENCE_SEAL_ASSOCIATION')
    manifest = read(ROOT / 'INPUT_MANIFEST.json')
    for rel, expected in manifest['source_files'].items():
        path = Path(rel) if rel.startswith('/') else REPO / rel
        if sha(path) != expected:
            raise ValueError('FROZEN_SOURCE_CHANGED:' + rel)
    bindings = read(ROOT / 'PHYSICAL_BINDINGS50.json')
    bstage = BASE / 'candidate_B_v57_20261017'
    source = read(bstage / 'PAIR_BINDINGS10000.json')
    original = {c['case_id']: c for r in source['records'] for c in r['rounds']}
    for record in bindings['records']:
        case = original[record['case_id']]
        if record['source_pair_sha256'] != case['sha256'] or sha(bstage / case['path']) != case['sha256']:
            raise ValueError('FROZEN_PAIR_CHANGED:' + record['case_id'])
    pointer = {
        'schema': 'eb.current_reference_physics50.v59', 'stage': ROOT.name,
        'A_stage': 'normal_A_v46_20261017', 'B_stage': 'candidate_B_v57_20261017',
        'households': 50, 'pairs': 500, 'same_master': True,
        'type_counts': acceptance['same_master_type_counts'], 'reference_physics_replay_accepted': True,
        'master1000_physics_accepted': False, 'full1000_deferred_by_user': True,
        'A_B_schedules_modified': False, 'all_B_success_claimed': False, 'B_failures_retained': True,
        'bindings_path': str((ROOT / 'PHYSICAL_BINDINGS50.json').relative_to(REPO)),
        'bindings_sha256': sha(ROOT / 'PHYSICAL_BINDINGS50.json'), 'seal_sha256': sha(ROOT / 'FINAL_SEAL50.json'),
        'report_path': str((ROOT / 'REPORT50.md').relative_to(REPO)),
        'local_delivery': 'all500 summaries,original inputs,bindings,seals and validation reports',
        'all50_raw_results_available_locally': False, 'full_raw_verified_on_compute_server': True,
        'raw_artifact_location': {'host':'connect.weste.seetacloud.com','port':32683,
            'root':verification['verified_artifact_root']+'/results/pilot50','credentials_included':False},
        'human_labels_created': 0, 'questionnaire_released': False,
    }
    save(BASE / 'CURRENT_PHYSICAL50_INPUTS.json', pointer)
    save(REPO / 'docs/household1000/CURRENT_PHYSICAL50.json', pointer)
    save(ROOT / 'LOCAL_DELIVERY_REVIEW50.json', {
        'passed': True, 'households': 50, 'pairs': 500, 'all_raw_locally_mirrored': False,
        'full_raw_verified_on_compute_server': True, 'original_source_pairs_rechecked': 500,
        'frozen_source_files_rechecked': len(manifest['source_files']), 'original_static_AB_pointers_preserved': True,
        'pointer_sha256': sha(BASE / 'CURRENT_PHYSICAL50_INPUTS.json'), 'full1000_deferred_by_user': True,
    })
    print(pointer, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('phase', choices=['seal', 'verify', 'publish'])
    parser.add_argument('--workers', type=int, default=8)
    parser.add_argument('--evidence-only', action='store_true')
    args = parser.parse_args()
    if args.phase == 'seal':
        seal(args.workers)
    elif args.phase == 'verify':
        verify(args.evidence_only)
    else:
        publish()
