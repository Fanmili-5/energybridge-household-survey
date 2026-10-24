"""Frozen missing mechanisms: direct-root singleton versus joint extension."""
import argparse
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
import time

from benchmark.ab_generation.common import read, save, sha, digest
from benchmark.ab_generation.model import apply
from benchmark.ab_generation.unified.candidates import prepare, Oracle, direct
from benchmark.ab_generation.unified.contract import code_hash
from benchmark.ab_generation.unified.independent import audit
from benchmark.ab_generation.unified.semantics import mechanism
from .acceptance import record_sources
from .interval_gap_review import restore
from .causal_audit import direct_path


def job(task):
    slot, context, profile, gaps, cfg, out = task
    catalogue = read(slot['path'])
    grammar = restore(catalogue)
    c = prepare(read(context), cfg)
    profile = read(profile)
    records = []
    for gap in gaps:
        identity = (gap['asset_id'], gap['need_id'], gap['mechanism'], gap['axis'])
        required = {}
        for i, values in enumerate(grammar['values']):
            ids = [j for j, r in enumerate(values) if r and
                   (r['asset_id'], r.get('service_need_id'), mechanism(r['mechanism']),
                    r['magnitude'].get('axis')) == identity and direct(c, r, cfg['event'])]
            if ids:
                required[i] = ids
        if not required:
            records.append(dict(**gap, status='no_direct_root_in_native_grammar',
                                family_opportunity_impossible=False))
            continue
        if len(required) != 1:
            raise ValueError('AMBIGUOUS_MECHANISM_FACTOR')
        factor = next(iter(required))
        started = time.perf_counter()
        oracle = Oracle(c, grammar, cfg, profile)
        singleton = oracle({i: 0 for i in range(len(grammar['values'])) if i != factor},
                           native_required=required)
        joint = None if singleton[0] == 'feasible' else oracle({}, native_required=required)
        answer = singleton if singleton[0] == 'feasible' else joint
        checks = []
        for row in oracle.rows.values():
            b = apply(c['A'], row['patches'])
            children = [ch for ch in row['components'] if
                        (ch['asset_id'], ch['service_need_id'], mechanism(ch['mechanism']),
                         ch['magnitude'].get('axis')) == identity]
            checks.append(dict(id=row['id'], errors=audit(c, c['A'], b),
                               target_direct_path=any(direct_path(c, ch, c['A'], b) for ch in children)))
        records.append(dict(**gap, status=answer[0], singleton=singleton, joint=joint,
            answer=answer, rows=list(oracle.rows.values()), diagnostics=oracle.diagnostics,
            checks=checks, propagation=oracle.propagation_log, forward=oracle.forward_search_log,
            calls=oracle.calls, materializations=oracle.materializations,
            elapsed_seconds=time.perf_counter()-started))
    path = Path(out)/'records'/(digest([slot['household_id'], slot['date']])+'.json.gz')
    save(path, dict(records=records, catalogue_sha256=sha(slot['path']),
                    context_sha256=sha(context), official_selection_changed=False))
    return dict(household_id=slot['household_id'], date=slot['date'], path=str(path),
                counts=dict(Counter(r['status'] for r in records)),
                independent_failures=sum(bool(check['errors']) or not check['target_direct_path']
                    for r in records for check in r.get('checks', [])))


def run(collection, gap_file, out, workers=2):
    collection, gap_file, out = map(Path, (collection, gap_file, out))
    out.mkdir(parents=True, exist_ok=False)
    pre, contexts = record_sources(collection)
    grouped = defaultdict(list)
    for r in read(gap_file)['records']:
        grouped[(r['household_id'], r['date'])].append(r)
    tasks = []
    for slot in read(collection/'GENERATION.json'):
        key = slot['household_id'], slot['date']
        if key not in grouped:
            continue
        profile = [p for p in pre['source_sha256'] if Path(p).name == slot['household_id']+'.json']
        if len(profile) != 1:
            raise ValueError('AMBIGUOUS_PROFILE_SOURCE')
        tasks.append(({**slot, 'path': str(collection/slot['path'])}, str(contexts[key]),
                      profile[0], grouped[key], pre['configuration'], str(out)))
    frozen = code_hash()
    save(out/'PROTOCOL.json', dict(tasks=tasks, code_sha256=frozen, helper_sha256=sha(__file__),
        gaps_sha256=sha(gap_file), gap_count=sum(map(len, grouped.values())),
        independent_target='same mechanism must have a direct event path',
        outcome_blind=True, physical_runs=0, no_reseed=True))
    results = []
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for row in pool.map(job, tasks, buffersize=workers*2):
            results.append(row)
            save(out/'PROGRESS.json', results)
            print(len(results), '/', len(tasks), row['household_id'], row['counts'], flush=True)
    if code_hash() != frozen:
        raise ValueError('GENERATOR_CHANGED_DURING_REVIEW')
    summary = dict(counts=dict(sum((Counter(r['counts']) for r in results), Counter())),
                   independent_failures=sum(r['independent_failures'] for r in results),
                   official_selection_changed=False, physical_runs=0)
    save(out/'SUMMARY.json', summary)
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--collection', required=True)
    parser.add_argument('--gaps', required=True)
    parser.add_argument('--out', required=True)
    parser.add_argument('--workers', type=int, default=2)
    args = parser.parse_args()
    print(run(args.collection, args.gaps, args.out, args.workers))
