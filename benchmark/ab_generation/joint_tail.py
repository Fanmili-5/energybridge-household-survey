"""One household-balanced tail frame across sealed A-only reference scenarios."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .common import bound, code_hash, digest, read, save, seal, sha, verify
from .joint_review import runtime_identity
from .sampling import (catalogue, command_hash, coverage_report, interactions,
                       require, sample_catalogue, validate_plan)

HERE = Path(__file__).parent
STAGES = ('assembled', 'contexts', 'baseline_compiled', 'baseline_runs', 'baseline_audit')


def frame(reference_root, references_path, plan_path, out, frozen_contexts=False):
    from .__main__ import build_batch
    root, out = Path(reference_root), Path(out)
    references, plan = read(references_path), read(plan_path)
    require(references['schema'] == 'eb.ab_joint_tail.references.v1', 'UNKNOWN_REFERENCE_SUITE')
    validate_plan(plan)
    refs = references['records']
    require(refs and len({r['id'] for r in refs}) == len(refs), 'EMPTY_OR_DUPLICATE_REFERENCE_SUITE')
    out.mkdir(parents=True, exist_ok=False)
    runtime = runtime_identity()
    save(out / 'PLAN.json', plan); save(out / 'REFERENCES.json', references)
    unique, receipts, generation = {}, [], []
    frozen_receipts = ({r['reference_id']: r for r in read(root / 'A_STAGE_RECEIPTS.json')}
                       if frozen_contexts else {})
    for ref in refs:
        source = bound(root, ref['path'])
        # Never read the previous study's RESULT, B reports, choices or answers.
        receipt = ({**frozen_receipts[ref['id']], 'frozen_contexts_manifest_sha256': sha(source / 'contexts/MANIFEST.json')}
                   if frozen_contexts else {'reference_id': ref['id'], 'path': ref['path'],
                   'A_stage_manifests': {stage: sha(source / stage / 'MANIFEST.json') for stage in STAGES}})
        receipt['baseline_reverified_during_frame'] = not frozen_contexts
        for stage in (('contexts',) if frozen_contexts else STAGES):
            verify(source / stage)
        receipts.append(receipt)
        batch = read(source / 'contexts/BATCH.json')
        contexts = {r['case_id']: read(bound(source / 'contexts', r['context'])) for r in batch['records']}
        require(len(contexts) == len(batch['records']), 'DUPLICATE_REFERENCE_CASE')
        for variant in plan['variants']:
            rel = 'variants/' + digest([ref['id'], variant['id']])[:24]
            rules = out / ('rules/' + digest(variant['id'])[:24] + '.json')
            save(rules, variant['overrides'])
            build_batch(source / 'contexts/BATCH.json', out / rel, rules)
            manifest = verify(out / rel)
            results = {r['case_id']: read(out / rel / r['path']) for r in manifest['records']}
            rows = catalogue(contexts, {variant['id']: results}, plan.get('stress_admissions'))
            for case_id, result in results.items():
                generation.append({'reference_id': ref['id'], 'variant': variant['id'], 'case_id': case_id,
                                   'coverage': result['joint_search_coverage']})
            for row in rows:
                for alias in row['aliases']:
                    alias.update(reference_id=ref['id'], generated_path=rel)
                if row['sample_id'] not in unique:
                    unique[row['sample_id']] = row
                else:
                    prior = unique[row['sample_id']]
                    require(prior['features'] == row['features'] and prior['static_issues'] == row['static_issues'],
                            'CONFLICTING_REFERENCE_ALIASES')
                    prior['aliases'].extend(row['aliases'])
        print('joint-tail frame ' + ref['id'], flush=True)
    require(runtime_identity() == runtime, 'JOINT_TAIL_RUNTIME_CHANGED_DURING_FRAME')
    rows = sorted(unique.values(), key=lambda r: r['sample_id'])
    selection = sample_catalogue(rows, plan)
    selection.update(schema='eb.ab_tail_selection.v1', plan_sha256=digest(plan),
                     response_checks=plan.get('response_checks'), unique_catalogue_size=len(rows),
                     raw_aliases=sum(len(r['aliases']) for r in rows),
                     interaction_coverage=interactions(rows, selection['records'], plan['coverage_axes']),
                     runtime_sha256=runtime, code_sha256=code_hash(), B_outcomes_read=False,
                     representative_population_sample=False, human_acceptance_inferred=False)
    save(out / 'CATALOGUE.json.gz', rows); save(out / 'SELECTION.json', selection)
    save(out / 'REFERENCE_RECEIPTS.json', receipts); save(out / 'GENERATION_COVERAGE.json', generation)
    seal(out, {'schema': 'eb.ab_joint_tail.frame.v1', 'runtime_sha256': runtime,
               'selection_sha256': sha(out / 'SELECTION.json'), 'B_outcomes_read': False,
               'frozen_context_replay_only': frozen_contexts})
    return {k: selection[k] for k in ('unique_catalogue_size', 'raw_aliases', 'selection_coverage_passed')}


def execute(reference_root, sample_root, energyplus_dir, out, workers=2):
    from .evaluate import summarize
    from .life_physics import export_life
    from benchmark.housing_simulation.pipeline import compile_pairs, run_pairs
    from benchmark.housing_simulation.validation import audit
    root, sample_root, out = map(Path, (reference_root, sample_root, out))
    require(type(workers) is int and 1 <= workers <= 4, 'INVALID_JOINT_TAIL_WORKERS')
    frame_manifest = verify(sample_root)
    selection = read(sample_root / 'SELECTION.json')
    require(runtime_identity() == frame_manifest['runtime_sha256'], 'JOINT_TAIL_RUNTIME_CHANGED_AFTER_SELECTION')
    refs = {r['reference_id']: bound(root, r['path']) for r in read(sample_root / 'REFERENCE_RECEIPTS.json')}
    engine = Path(energyplus_dir).resolve() / 'energyplus'; engine_sha = sha(engine)
    for receipt in read(sample_root / 'REFERENCE_RECEIPTS.json'):
        source = refs[receipt['reference_id']]
        for stage, expected in receipt['A_stage_manifests'].items():
            verify(source / stage)
            require(sha(source / stage / 'MANIFEST.json') == expected, 'JOINT_TAIL_A_REFERENCE_CHANGED')
        require(all(read(source / 'baseline_runs' / r['id'] / r['side'] / 'RESULT.json')['engine_sha256'] == engine_sha
                    for r in read(source / 'baseline_runs/MANIFEST.json')['records']), 'JOINT_TAIL_ENGINE_CHANGED')
    out.mkdir(parents=True, exist_ok=False)
    save(out / 'FROZEN_SELECTION.json', selection)
    save(out / 'SOURCE.json', {'runtime_sha256': runtime_identity(), 'engine_sha256': engine_sha,
                             'sample_manifest_sha256': sha(sample_root / 'MANIFEST.json'), 'workers': workers})

    def one(sample):
        require(runtime_identity() == frame_manifest['runtime_sha256'], 'JOINT_TAIL_RUNTIME_CHANGED_DURING_EXECUTION')
        alias = min(sample['aliases'], key=lambda a: (a['reference_id'], a['variant'], digest(a)))
        source, generated = refs[alias['reference_id']], bound(sample_root, alias['generated_path'])
        prefix = out / 'executions' / sample['sample_id'][:24]
        folder, compiled, runs, audits, report = [prefix / name for name in ('export', 'compiled', 'runs', 'audit', 'report')]
        exported, arms, report_receipt = None, 0, None
        try:
            export_life(source / 'assembled', source / 'contexts', generated, 'known_profile_vpp', folder,
                        [sample['case_id']], {sample['case_id']: alias['override']})
            job = read(folder / 'physics_job.json'); pair = read(bound(folder, job['pairs'][0]['pair']['path']))
            exported = command_hash(pair['B'])
            require(exported == sample['B_commands_sha256'], 'JOINT_TAIL_EXPORTED_B_CHANGED')
            cc = compile_pairs((folder / 'physics_job.json').resolve(), compiled)
            require(all(r['status'] == 'compiled' for r in cc['records']), 'JOINT_TAIL_COMPILATION_FAILED')
            rr = run_pairs(compiled, runs, engine, engine_sha, 300); arms = len(rr['records'])
            audit(compiled, runs, audits)
            summarize(folder / 'physics_job.json', compiled, runs, audits, report,
                      imported=source / 'contexts', reference_runs=source / 'baseline_runs')
            verify(report); data = read(report / 'REPORT.json')
            require(len(data['records']) == 1, 'JOINT_TAIL_REPORT_CASE_COUNT')
            record, report_receipt = data['records'][0], sha(report / 'MANIFEST.json')
        except (ValueError, OSError, KeyError) as error:
            record = {'case_id': sample['case_id'], 'readback_status': 'incomplete', 'error_type': type(error).__name__,
                      'error': str(error), 'actual_results_used_for_reselection': False, 'human_acceptance': None}
        return {'sample_id': sample['sample_id'], 'reference_id': alias['reference_id'], 'engine_arms': arms,
                'exported_B_commands_sha256': exported, 'report_manifest_sha256': report_receipt, 'report': record}

    selected = [s for s in selection['records'] if s['features']['admission'] != 'static_diagnostic']
    observations = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for observation in pool.map(one, selected):
            observations.append(observation); save(out / 'OBSERVATIONS.json', observations)
            print('joint-tail executed ' + str(len(observations)) + '/' + str(len(selected)), flush=True)
    result = coverage_report(sample_root, observations)
    generation = read(sample_root / 'GENERATION_COVERAGE.json')
    generation_passed = all(r['coverage'].get('coverage_passed') is True for r in generation)
    result.update(generation_coverage_passed=generation_passed,
                  passed=result['passed'] and generation_passed,
                  full_declared_strata_covered=all(r['passed'] for r in result['coverage']),
                  engine_arms=sum(o['engine_arms'] for o in observations),
                  sample_manifest_sha256=sha(sample_root / 'MANIFEST.json'), runtime_sha256=runtime_identity(),
                  engine_sha256=engine_sha, master1000_simulation_started=False, online_questionnaire_changed=False)
    save(out / 'RESULT.json', result)
    lines = ['# 新联合目录的正式长尾覆盖', '',
             '| 分层 | 必验 | 独占目录 | 要求 | 抽中 | 验证 | 缺额 |', '| --- | --- | ---: | ---: | ---: | ---: | ---: |']
    for r in result['coverage']:
        lines.append('| {stratum} | {required} | {assigned_unique} | {requested} | {selected} | {verified} | {verification_deficit} |'.format(**r))
    lines += ['', '必验合同通过：' + str(result['passed']), '全部声明层覆盖：' + str(result['full_declared_strata_covered']),
              '结果分类：' + str(result['outcome_counts']), '响应分类：' + str(result['response_coverage']['patterns']),
              '诊断层只验证静态拒绝；物理层须有完整读回。所有无效、无响应、服务失败和缺额原样保留，未重抽。',
              '完整单因素及两因素抽样覆盖表见 RESULT.json；高阶剂量并非全部穷举，非人口代表性证明。', '']
    (out / 'COVERAGE.md').write_text('\n'.join(lines))
    verify(sample_root)
    seal(out, {'schema': 'eb.ab_joint_tail.execution.v1', 'passed': result['passed'],
               'sample_manifest_sha256': sha(sample_root / 'MANIFEST.json'), 'runtime_sha256': runtime_identity()})
    return {k: result[k] for k in ('passed', 'full_declared_strata_covered', 'engine_arms', 'outcome_counts')}


if __name__ == '__main__':
    p = argparse.ArgumentParser(__doc__); p.add_argument('mode', choices=('frame', 'frame-frozen', 'execute'))
    p.add_argument('--reference-root', type=Path, required=True)
    p.add_argument('--references', type=Path, default=HERE / 'examples/joint_tail/references.json')
    p.add_argument('--plan', type=Path, default=HERE / 'examples/joint_tail/plan.json')
    p.add_argument('--sample', type=Path); p.add_argument('--energyplus-dir', type=Path)
    p.add_argument('--workers', type=int, default=2); p.add_argument('--out', type=Path, required=True)
    a = p.parse_args()
    print(frame(a.reference_root, a.references, a.plan, a.out, a.mode == 'frame-frozen') if a.mode != 'execute' else
          execute(a.reference_root, a.sample, a.energyplus_dir, a.out, a.workers))
