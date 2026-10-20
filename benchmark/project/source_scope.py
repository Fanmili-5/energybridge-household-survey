"""Avoid rebuilding unchanged source worlds for presentation/metadata-only edits."""
import os
import subprocess
from pathlib import Path

PRESENTATION={
    'benchmark/project/reference_collection_release.py',
    'benchmark/project/collection_questionnaire.py',
    'benchmark/project/test_reference_collection_release.py',
    'benchmark/project/source_scope.py','benchmark/project/test_source_scope.py',
    'benchmark/project/reference_refined_release.py',
    'benchmark/project/reference_presentation_release.py',
    'benchmark/project/questionnaire.py','benchmark/project/preview-client.js',
    'benchmark/collector/ledger.py','benchmark/collector/collection-client.js',
    'benchmark/collector/test_protocol.py','benchmark/collector/test_rounds.py',
    'benchmark/project/reference_collection_physics.py',
    'benchmark/project/reference_physics_results.py',
    'benchmark/project/reference_physics_selfcheck.py',
    'benchmark/project/reference_physical_release.py',
    'benchmark/project/test_reference_collection_physics.py',
    'benchmark/project/verify_refined_display.js',
    'benchmark/project/UI91_VALIDATION.json',
    'benchmark/project/FULL500_PHYSICS_VALIDATION.json',
    'benchmark/verify_publication.py',
}
METADATA={'benchmark/PUBLICATION_MANIFEST.json','docs/household1000/STATUS.json',
          'docs/household1000/CURRENT_QUESTIONNAIRE50.json'}

def requires_source_rebuild(paths):
    for name in paths:
        path=Path(name)
        if name in PRESENTATION or name in METADATA or path.suffix=='.md':continue
        # Display assets and frozen-input export/readback adapters do not alter
        # family, housing or A/B source generation. Their tests still run.
        if name.startswith('benchmark/project/refined91/') and path.suffix in ('.html','.css','.js','.json'):continue
        if name.startswith('benchmark/project/examples/questionnaire/')and(path.name in('MANIFEST.json','SUMMARY.json')or'/source-snapshots/'in name):continue
        if path.name=='PACKAGE_MANIFEST.json'and name.startswith('benchmark/'):continue
        if name.startswith('.github/workflows/')and path.suffix in ('.yml','.yaml'):continue
        if name.startswith('benchmark/ab_generation/validation/')and path.suffix=='.json':continue
        if name.startswith('benchmark/releases/reference50-v4-proposal/')and path.suffix=='.json':continue
        if name.startswith('benchmark/releases/reference50-v4-ui91-physics/')and path.suffix=='.json':continue
        return True
    return False


def main():
    event=os.environ.get('EVENT_NAME','workflow_dispatch');base=os.environ.get('BASE_SHA','')
    if event=='workflow_dispatch':rebuild=True
    else:
        if not base or set(base)=={'0'}:
            base=subprocess.check_output(['git','merge-base','HEAD','origin/'+os.environ.get('DEFAULT_BRANCH','main')],text=True).strip()
        paths=subprocess.check_output(['git','diff','--name-only',base,'HEAD'],text=True).splitlines()
        rebuild=requires_source_rebuild(paths)
    with open(os.environ['GITHUB_OUTPUT'],'a')as f:f.write('rebuild='+str(rebuild).lower()+'\n')
    print('Full source-world rebuild required:',rebuild)

if __name__=='__main__':main()
