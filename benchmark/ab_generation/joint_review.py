"""Small frozen joint/load/supply experiment; retain every assigned outcome."""
import argparse
import copy
from pathlib import Path

from .common import code_hash, digest, read, save, seal, sha, verify
from .life import require
from .sampling import SERVICE_FAILURES
from .sensitivity import perturb

HERE = Path(__file__).parent


def runtime_identity():
    root = HERE.parents[1]
    files = list(HERE.glob('*.py')) + list((HERE.parent / 'housing_simulation').rglob('*.py')) + [HERE / 'LAUNDRY_MODEL.json']
    return digest({str(f.relative_to(root)): sha(f) for f in sorted(files)})


def select(result, mode):
    """Only A/static properties enter selection; never read B response."""
    single = {c['id']: c for c in result['candidates']}
    rows = []
    allowed = {'SITE_KNOWN_PROFILE_EXCEEDS_SUPPLY', 'SITE_CAPACITY_NOT_CERTIFIED'}
    for joint in result['joint_candidates']:
        if set(joint['static_issues']) - (allowed if mode == 'capacity_stress' else set()):
            continue
        children = [single[i] for i in joint['candidate_ids']]
        families = {c['family'] for c in children}
        if len(children) < 3:
            continue
        support = sum(c['opportunity']['status'] == 'supported' for c in children)
        peak = joint.get('power_certificate', {}).get('known_profile_peak_W', 0)
        score = (-peak, -len(families), -len(children), -support, joint['id']) if mode == 'capacity_stress' else (
            -len(families), -len(children), -support, joint['id'])
        rows.append((score, joint, children))
    if not rows:
        return None
    _, joint, children = min(rows, key=lambda r: r[0])
    return {'joint_id': joint['id'], 'expected_static_issues': joint['static_issues'],
            'family_composition': joint['family_composition'],
            'children': [{k: c[k] for k in ('id', 'family', 'asset_id', 'factors', 'opportunity')} for c in children],
            'criterion': mode + ';A/static only;max family/unit coverage then A support then stable id',
            'B_outcomes_read': False}


def run(plan_path, energyplus_dir, out):
    from .__main__ import build_batch
    from .evaluate import summarize
    from .life_pipeline import build_life
    from .life_physics import assemble_life, bind_life_worlds, export_life, reference_life
    from benchmark.housing_simulation.pipeline import build_shell, compile_pairs, run_pairs
    from benchmark.housing_simulation.validation import audit
    out = Path(out); out.mkdir(parents=True, exist_ok=False)
    plan = read(plan_path)
    require(plan['schema'] == 'eb.ab_joint_load_supply.plan.v1', 'UNKNOWN_JOINT_REVIEW_PLAN')
    engine_dir = Path(energyplus_dir); engine = engine_dir / 'energyplus'
    weather = engine_dir / 'WeatherData/USA_IL_Chicago-OHare.Intl.AP.725300_TMY3.epw'
    source = {'code_sha256': code_hash(), 'runtime_sha256': runtime_identity(), 'plan_sha256': sha(plan_path), 'engine_sha256': sha(engine), 'weather_sha256': sha(weather)}
    save(out / 'PLAN.json', plan); save(out / 'SOURCE.json', source)
    build_shell((HERE.parent / 'housing_simulation/examples/shell_batch.json').resolve(), out / 'shells')
    original_batch = read(HERE / 'examples/strategy_review/life_batch.json')
    original_worlds = read(HERE / 'examples/life/world_contracts.json')
    original_experiments = read(HERE / 'examples/strategy_review/experiments.json')
    records = []
    def execute(folder, label, request):
        cc = compile_pairs((request / 'physics_job.json').resolve(), folder / (label + '_compiled'))
        require(all(r['status'] == 'compiled' for r in cc['records']), 'JOINT_REVIEW_COMPILATION_FAILED')
        rr = run_pairs(folder / (label + '_compiled'), folder / (label + '_runs'), engine, source['engine_sha256'], 300)
        require(all(r['status'] == 'completed' for r in rr['records']), 'JOINT_REVIEW_ENGINE_FAILED')
        return audit(folder / (label + '_compiled'), folder / (label + '_runs'), folder / (label + '_audit')), len(rr['records'])
    for item in plan['cases']:
        require(runtime_identity() == source['runtime_sha256'], 'CODE_CHANGED_DURING_JOINT_REVIEW')
        folder = out / item['id']; folder.mkdir()
        hid = item['household_id']; batch, worlds = copy.deepcopy(original_batch), copy.deepcopy(original_worlds)
        spec = next(h for h in batch['households'] if h['household_id'] == hid)
        raw = next(w for w in worlds['households'] if w['household_id'] == hid)
        spec, raw = perturb(spec, raw, {**plan['base_values'], **item.get('values', {})})
        if 'supply_W' in item:
            raw['electrical_supply_W'] = item['supply_W']
            raw['electrical_capacity_mode'] = 'schedule_resolved'
        batch['households'] = [spec]
        worlds['households'] = [raw if w['household_id'] == hid else w for w in worlds['households']]
        save(folder / 'world_contracts.json', worlds)
        bind_life_worlds(folder / 'world_contracts.json', out / 'shells', folder / 'world_binding')
        batch['worlds'] = {'path': 'world_binding/resource_worlds.json', 'sha256': sha(folder / 'world_binding/resource_worlds.json')}
        save(folder / 'life_batch.json', batch)
        ll = build_life(folder / 'life_batch.json', folder / 'life')
        row = {**item, 'engine_arms': 0, 'life_status': ll['records'][0]['status']}
        if not ll['all_A_constructed']:
            row.update(status='unserved_A_retained', unserved=read(folder / 'life' / ll['records'][0]['path'])['unserved'])
        else:
            ex = copy.deepcopy(original_experiments)
            case = next(c for c in ex['records'] if c['case_id'] == item['experiment_case_id'])
            ex['records'] = [case]; save(folder / 'experiments.json', ex)
            assembled = assemble_life(folder / 'life', folder / 'world_contracts.json', out / 'shells', weather, folder / 'experiments.json', folder / 'assembled')
            require(all(r['status'] == 'assembled' for r in assembled['records']), 'JOINT_REVIEW_ASSEMBLY_FAILED')
            aa, arms = execute(folder, 'baseline', folder / 'assembled'); row['engine_arms'] += arms
            row['baseline_audit'] = aa
            if not aa['passed']:
                row['status'] = 'baseline_service_or_model_failure_retained'
            else:
                reference_life(folder / 'assembled', folder / 'baseline_compiled', folder / 'baseline_runs', folder / 'contexts', folder / 'baseline_audit')
                build_batch(folder / 'contexts/BATCH.json', folder / 'candidates')
                manifest = verify(folder / 'candidates'); result = read(folder / 'candidates' / manifest['records'][0]['path'])
                row['joint_search_coverage'] = result['joint_search_coverage']
                row['single_invalid_retained'] = sum(bool(c['static_issues']) for c in result['candidates'])
                row['joint_invalid_retained'] = sum(bool(c['static_issues']) for c in result['joint_candidates'])
                chosen = select(result, item.get('selection', 'coverage')); row['selection'] = chosen
                save(folder / 'FROZEN_B_SELECTION.json', {'selection': chosen, 'no_B_outcomes_read': True, 'candidate_manifest_sha256': sha(folder / 'candidates/MANIFEST.json')})
                if chosen is None:
                    row['status'] = 'specified_joint_unavailable_retained'
                else:
                    cid = case['case_id']
                    override = {k: chosen[k] for k in ('joint_id', 'expected_static_issues')}
                    export_life(folder / 'assembled', folder / 'contexts', folder / 'candidates', 'known_profile_vpp', folder / 'B', [cid], {cid: override})
                    ba, arms = execute(folder, 'B', folder / 'B'); row['engine_arms'] += arms
                    summarize(folder / 'B/physics_job.json', folder / 'B_compiled', folder / 'B_runs', folder / 'B_audit', folder / 'report', imported=folder / 'contexts', reference_runs=folder / 'baseline_runs')
                    row['B_audit'] = ba; row['physical_records'] = read(folder / 'report/REPORT.json')['records']
                    failures = {k for r in ba['records'] for k, v in r['checks'].items() if not v}
                    row['service_failures'] = sorted(failures & SERVICE_FAILURES)
                    row['model_or_data_failures'] = sorted(failures - SERVICE_FAILURES)
                    row['binding_passed'] = all(r['readback_status'] == 'complete' and r['A_reference_comparison']['passed'] for r in row['physical_records'])
                    row['status'] = 'B_service_failure_retained' if failures else 'paired_B_completed'
        records.append(row); save(out / 'PROGRESS.json', {'records': records, 'planned': len(plan['cases'])})
        print(item['id'] + ': ' + row['status'], flush=True)
    result = {'schema': 'eb.ab_joint_load_supply.result.v1', **source, 'records': records,
              'planned_cases': len(plan['cases']), 'accounted_cases': len(records),
              'engine_arms': sum(r['engine_arms'] for r in records), 'outcome_reselection': False,
              'master1000_simulation_started': False, 'online_questionnaire_changed': False}
    save(out / 'RESULT.json', result); seal(out, {'schema': result['schema'], **source})
    return result


if __name__ == '__main__':
    p = argparse.ArgumentParser(__doc__)
    p.add_argument('--plan', type=Path, default=HERE / 'examples/joint_load_supply/plan.json')
    p.add_argument('--energyplus-dir', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    args = p.parse_args()
    result = run(args.plan, args.energyplus_dir, args.out)
    print({k: v for k, v in result.items() if k != 'records'})
