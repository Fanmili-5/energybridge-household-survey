"""Seal only the derived summary revision; sealed V61 physics remains byte-for-byte intact."""
from regenerate import *


def seal():
    verification = read(ROOT / 'VERIFICATION50.json')
    assert verification['passed'] and verification['summaries_verified'] == 500
    assert verification['summary_bindings_sha256'] == sha(ROOT / 'SUMMARY_BINDINGS50.json')
    files = []
    excluded = {'FILE_MANIFEST50.json.gz', 'FINAL_SEAL50.json', 'LOCAL_DELIVERY_REVIEW50.json'}
    for p in sorted(ROOT.rglob('*')):
        if not p.is_file() or p.name in excluded or '__pycache__' in p.parts:
            continue
        files.append({'path': str(p.relative_to(ROOT)), 'bytes': p.stat().st_size, 'sha256': sha(p)})
    assert sum(r['path'].endswith('/IMPACT_SUMMARY.json') for r in files) == 500
    assert sum(r['path'].endswith('/TEMPERATURE_TIMELINE.json.gz') for r in files) == 500
    save(ROOT / 'FILE_MANIFEST50.json.gz', {'schema': SCHEMA, 'files': files, 'source_physics_stage': SOURCE.name,
         'source_physics_seal_sha256': SOURCE_SEAL, 'summaries': 500, 'timelines': 500})
    save(ROOT / 'FINAL_SEAL50.json', {'schema': SCHEMA, 'summary_revision_verified': True,
         'households': 50, 'pairs': 500, 'files': len(files),
         'manifest_sha256': sha(ROOT / 'FILE_MANIFEST50.json.gz'),
         'summary_bindings_sha256': sha(ROOT / 'SUMMARY_BINDINGS50.json'),
         'source_physics_stage': SOURCE.name, 'source_physics_seal_sha256': SOURCE_SEAL,
         'source_physics_bindings_sha256': SOURCE_BINDINGS,
         'physical_trajectories_modified_by_summary_generator':False,'source_physics_replayed_under_repaired_model':True, 'schedules_modified': False, 'B_failures_retained': True,
         'new_energyplus_runs_in_summary_generation': 0, 'human_labels_created': 0, 'full1000_deferred_by_user': True})
    print(json.dumps({'sealed_files': len(files), 'seal_sha256': sha(ROOT / 'FINAL_SEAL50.json')}))


if __name__ == '__main__':
    seal()
