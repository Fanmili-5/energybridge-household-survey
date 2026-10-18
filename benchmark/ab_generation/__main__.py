"""Command-line entry points, without fixed stage paths or household counts."""
import argparse
import collections
from pathlib import Path
from . import VERSION
from .common import bound, code_hash, digest, read, save, seal, verify
from .generate import DEFAULT_RULES, generate
from .legacy import import_current


def build_batch(input_path, out, rules_path=None):
    input_path, out = Path(input_path), Path(out)
    batch = read(input_path)
    rules = {**DEFAULT_RULES, **(read(rules_path) if rules_path else {})}
    out.mkdir(parents=True, exist_ok=False)
    records, counts, families, gaps, assignments = [], collections.Counter(), collections.Counter(), collections.Counter(), collections.Counter()
    ids = [r['case_id'] for r in batch['records']]
    if len(ids) != len(set(ids)):
        raise ValueError('DUPLICATE_CASE_ID')
    for row in batch['records']:
        context = read(bound(input_path.parent, row['context']))
        if context['case_id'] != row['case_id']:
            raise ValueError('CASE_ID_MISMATCH')
        result = generate(context, rules)
        path = 'cases/' + digest(row['case_id'])[:24] + '.json.gz'
        save(out / path, result)
        counts['cases'] += 1
        counts['candidates'] += len(result['candidates'])
        counts['statically_admissible_candidates'] += sum(not r['static_issues'] for r in result['candidates'])
        counts['joint_candidates'] += len(result['joint_candidates'])
        counts['joint_failures_retained'] += sum(bool(r['static_issues']) for r in result['joint_candidates'])
        families.update(r['family'] for r in result['candidates'])
        gaps.update(r['reason'] for r in result['unavailable'])
        assignments[result['assignment']['mode']] += 1
        records.append({'case_id': row['case_id'], 'path': path, 'input_context_sha256': digest(context)})
    save(out / 'RULES.json', rules)
    summary = {'schema': VERSION, 'counts': dict(counts), 'candidate_family_counts': dict(families),
               'unavailable_reasons': dict(gaps), 'assignments': dict(assignments),
               'paired_simulations_started': 0, 'human_answers_created': 0,
               'production_inputs_modified': False, 'master1000_simulation': 'paused',
               'cost_ranking_scope': 'known_program_and_EV_profiles_only;requires_explicit_tariff'}
    save(out / 'SUMMARY.json', summary)
    seal(out, {'schema': VERSION, 'code_sha256': code_hash(), 'input_batch_sha256': digest(batch),
               'rules_sha256': digest(rules), 'records': records})
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('import-current')
    p.add_argument('--stage', required=True)
    p.add_argument('--out', required=True)
    p.add_argument('--limit', type=int)
    p.add_argument('--tariff')
    p.add_argument('--tariff-sha256')
    p = sub.add_parser('generate')
    p.add_argument('--input', required=True)
    p.add_argument('--out', required=True)
    p.add_argument('--rules')
    p = sub.add_parser('bind-life-worlds')
    p.add_argument('--world-contracts', required=True)
    p.add_argument('--shells', required=True)
    p.add_argument('--out', required=True)
    p = sub.add_parser('assemble-life')
    p.add_argument('--life', required=True)
    p.add_argument('--world-contracts', required=True)
    p.add_argument('--shells', required=True)
    p.add_argument('--weather', required=True)
    p.add_argument('--experiments', required=True)
    p.add_argument('--out', required=True)
    p = sub.add_parser('reference-life')
    p.add_argument('--assembled', required=True)
    p.add_argument('--compiled', required=True)
    p.add_argument('--runs', required=True)
    p.add_argument('--out', required=True)
    p = sub.add_parser('export-life')
    p.add_argument('--assembled', required=True)
    p.add_argument('--contexts', required=True)
    p.add_argument('--generated', required=True)
    p.add_argument('--policy', choices=DEFAULT_RULES['selection_policies'], required=True)
    p.add_argument('--out', required=True)
    p = sub.add_parser('reproduce-life')
    p.add_argument('--input', default='benchmark/ab_generation/examples/life/life_batch.json')
    p.add_argument('--world-contracts', default='benchmark/ab_generation/examples/life/world_contracts.json')
    p.add_argument('--shell-config', default='benchmark/housing_simulation/examples/shell_batch.json')
    p.add_argument('--experiments', default='benchmark/ab_generation/examples/life/experiments.json')
    p.add_argument('--energyplus-dir', required=True)
    p.add_argument('--out', required=True)
    p = sub.add_parser('verify')
    p.add_argument('directory')
    p = sub.add_parser('export-physics')
    p.add_argument('--stage', required=True)
    p.add_argument('--imported', required=True)
    p.add_argument('--generated', required=True)
    p.add_argument('--case', action='append', required=True)
    p.add_argument('--policy', choices=DEFAULT_RULES['selection_policies'], required=True)
    p.add_argument('--candidate-id')
    p.add_argument('--out', required=True)
    p = sub.add_parser('report-physics')
    p.add_argument('--input', required=True)
    p.add_argument('--compiled', required=True)
    p.add_argument('--runs', required=True)
    p.add_argument('--audit', required=True)
    p.add_argument('--out', required=True)
    p.add_argument('--reference-stage')
    p.add_argument('--imported')
    p = sub.add_parser('build-life')
    p.add_argument('--input', required=True)
    p.add_argument('--out', required=True)
    p.add_argument('--rules')
    args = parser.parse_args()
    if args.command == 'bind-life-worlds':
        from .life_physics import bind_life_worlds
        result = bind_life_worlds(args.world_contracts, args.shells, args.out)
    elif args.command == 'assemble-life':
        from .life_physics import assemble_life
        result = assemble_life(args.life, args.world_contracts, args.shells, args.weather, args.experiments, args.out)
    elif args.command == 'reference-life':
        from .life_physics import reference_life
        result = reference_life(args.assembled, args.compiled, args.runs, args.out)
    elif args.command == 'export-life':
        from .life_physics import export_life
        result = export_life(args.assembled, args.contexts, args.generated, args.policy, args.out)
    elif args.command == 'reproduce-life':
        from .life_physics import reproduce_life
        result = reproduce_life(args.input, args.world_contracts, args.shell_config, args.experiments, args.energyplus_dir, args.out)
    elif args.command == 'build-life':
        from .life_pipeline import build_life
        result = build_life(args.input, args.out, args.rules)
    elif args.command == 'import-current':
        result = import_current(args.stage, args.out, args.limit, args.tariff, args.tariff_sha256)
        result = {k: v for k, v in result.items() if k != 'files'}
    elif args.command == 'generate':
        result = build_batch(args.input, args.out, args.rules)
    elif args.command == 'export-physics':
        from .export import export_physics
        result = export_physics(args.stage, args.imported, args.generated, args.case, args.policy, args.out, args.candidate_id)
    elif args.command == 'report-physics':
        from .evaluate import summarize
        result = summarize(args.input, args.compiled, args.runs, args.audit, args.out, args.reference_stage, args.imported)
    else:
        result = verify(args.directory)
        result = {'verified': True, 'files': len(result['files'])}
    from .common import canonical
    print(canonical(result))


if __name__ == '__main__':
    main()
