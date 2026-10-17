"""Seal the accepted household phase, its exact sources and input hashes.

This never builds worlds, launches EnergyPlus or accepts downstream results.
"""
import argparse
import datetime as dt
import importlib.metadata
import shutil
import sys
from pathlib import Path

from common import BASE, OUT, REPO, SCHEMA_PATH, read, save, sha, verify_dependencies
from build_master import bundle_id


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verify-only', action='store_true')
    args = parser.parse_args()
    seal_path = OUT / 'FINAL_SEAL.json'
    if args.verify_only:
        seal = read(seal_path)
        assert seal['rules_sha256'] == bundle_id(), 'GENERATOR_CHANGED'
        for item in seal['files']:
            path = (REPO / item['path']) if item['root'] == 'repo' else Path(item['path'])
            assert sha(path) == item['sha256'], 'SEALED_FILE_CHANGED:' + item['path']
        for item in seal['source_snapshot']:
            assert sha(OUT / item['snapshot_path']) == item['sha256'], 'SNAPSHOT_CHANGED'
        print({'sealed_files_verified': len(seal['files']), 'source_files_verified': len(seal['source_snapshot']),
               'household_phase_accepted': True, 'AB_or_physics_accepted': False})
        return

    if seal_path.exists():
        raise RuntimeError('Seal already exists; use --verify-only. Retain an earlier seal before changing inputs.')
    verify_dependencies()
    bindings = read(OUT / 'WORLD_BINDINGS1000.json')
    phase = read(OUT / 'HOUSEHOLD_PHASE_REVIEW.json')
    review = read(OUT / 'INDEPENDENT_WORLD_REVIEW.json')
    signature = bundle_id()
    run = OUT / 'runs' / signature[:16]
    completed = read(run / 'REVIEW.json')
    assert len(bindings['records']) == completed['passed'] == review['households_checked'] == 1000
    assert review['passed'] and not review['failures'] and not completed['failures']
    assert all(c['rejected'] for c in review['negative_controls'])
    assert signature == bindings['rules_sha256'] == phase['rules_sha256'] == completed['rules_sha256']
    assert sha(OUT / 'WORLD_BINDINGS1000.json') == review['world_bindings_sha256'] == phase['world_bindings_sha256']
    assert sha(OUT / 'SUBSET50.json') == phase['subset50_sha256']

    # These development attempts retain the actual records, including failures.
    # Older attempts did not archive every intermediate source revision: do not
    # claim exact reruns of those intermediate code revisions are available.
    attempts = []
    for folder in sorted((OUT / 'runs').iterdir()):
        if not folder.is_dir():
            continue
        records = [read(p) for p in sorted((folder / 'records').glob('*.json'))]
        attempts.append({'run': folder.name, 'record_count': len(records),
                         'successful_records': sum(bool(r.get('passed')) for r in records),
                         'failed_records': sum(not r.get('passed', False) for r in records),
                         'completion_review_written': (folder / 'REVIEW.json').exists(),
                         'interruption_record_written': (folder / 'INTERRUPTION.json').exists(),
                         'accepted_master': folder == run})
    save(OUT / 'DEVELOPMENT_HISTORY.json', {
        'attempts': attempts, 'old_attempt_records_retained': True,
        'intermediate_source_snapshots_complete': False,
        'final_accepted_source_snapshot_complete': True,
        'history_is_not_an_evaluation_sample': True})

    files = set((OUT / 'code').glob('*.py'))
    files.update(OUT.glob('*.json'))
    files.update(OUT.glob('*.md'))
    files.discard(seal_path)
    files.add(REPO / 'scripts/household_master.py')
    files.add(SCHEMA_PATH)
    for name in read(OUT / 'DEPENDENCY_LOCK.json')['files_relative_to_household1000']:
        files.add(BASE / name)
    for name in ('idf_joint_production_20261005/RUNTIME.json',
                 'idf_joint_production_20261005/HOUSEHOLDS1000_JOINT_GEOMETRY_CANDIDATE.json',
                 'substantive_repair_v30_20261015/SELECTION1000.json',
                 'household_housing_evidence_20261006/NATIVE_REFERENCE_REGISTRY.json',
                 'household_housing_evidence_20261006/ADDITIONAL_REGIONAL_REFERENCES.json'):
        files.add(BASE / name)
    plan = read(OUT / 'MODEL_PLAN1000.json')
    for item in plan['records']:
        files.add(Path(item['source_world_path']))
        files.add(Path(item['selected']['source_path']))
        for weather in item['selected']['coordinate_confirmed_WMO_station_candidates']:
            files.add(Path(weather['path']))
    for item in bindings['records']:
        for key in ('world_path', 'background_IDF_path', 'card_path'):
            files.add(OUT / item[key])
        for subdir in ('geometry_metadata', 'records', 'regeneration'):
            files.add(run / subdir / (item['household_id'] + '.json'))
    files.update((OUT / 'native_bundles').glob('*.json'))
    files.update((OUT / 'review').glob('*.csv'))
    files.update((OUT / 'review').glob('*.json'))
    files.update((OUT / 'review/plots').glob('*.png'))
    files.update([run / 'RUN.json', run / 'REVIEW.json'])
    manifest = []
    snapshot = []
    snapshot_root = run / 'source_snapshot'
    for path in sorted(files):
        path = path.resolve()
        relative = path.relative_to(REPO) if path.is_relative_to(REPO) else None
        entry = {'root': 'repo' if relative else 'external',
                 'path': str(relative if relative else path), 'sha256': sha(path)}
        manifest.append(entry)
        if path.suffix in ('.py', '.md') or path == SCHEMA_PATH or (
                path.suffix == '.json' and path.parent == OUT and path.name not in
                ('MODEL_PLAN1000.json', 'WORLD_BINDINGS1000.json', 'SUBSET50.json')):
            target = snapshot_root / (relative if relative else Path('external') / path.name)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
            snapshot.append({'snapshot_path': str(target.relative_to(OUT)), 'sha256': entry['sha256']})
    packages = {}
    for name in ('numpy', 'scipy', 'shapely', 'access-parser', 'matplotlib'):
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = 'metadata unavailable; runtime paths recorded separately'
    save(seal_path, {'schema': 'eb.master_household_phase_seal.v33',
                     'sealed_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
                     'rules_sha256': signature, 'world_bindings_sha256': sha(OUT / 'WORLD_BINDINGS1000.json'),
                     'independent_review_sha256': sha(OUT / 'INDEPENDENT_WORLD_REVIEW.json'),
                     'household_phase_accepted': True, 'households': 1000, 'subset': 50,
                     'AB_or_physics_accepted': False, 'live_questionnaire_replaced': False,
                     'python': sys.version, 'packages': packages,
                     'files': manifest, 'source_snapshot': snapshot,
                     'input_bytes_available_only_in_controlled_workspace': True})
    pointer = read(BASE / 'CURRENT_MASTER_INPUTS.json')
    pointer.update({'household_phase_accepted': True, 'AB_or_physics_accepted': False,
                    'independent_review': 'INDEPENDENT_WORLD_REVIEW.json',
                    'independent_review_sha256': sha(OUT / 'INDEPENDENT_WORLD_REVIEW.json'),
                    'seal': 'FINAL_SEAL.json', 'seal_sha256': sha(seal_path)})
    save(BASE / 'CURRENT_MASTER_INPUTS.json', pointer)
    print({'sealed_files': len(manifest), 'source_snapshot_files': len(snapshot),
           'household_phase_accepted': True, 'AB_or_physics_accepted': False})


if __name__ == '__main__':
    main()
