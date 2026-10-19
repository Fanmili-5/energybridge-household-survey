"""Verify the public integration source closure, never build or simulate."""
from pathlib import Path
from benchmark.ab_generation.common import bound, read, sha
from .questionnaire import verify_questionnaire


def main():
    folder=Path(__file__).parent; root=folder.parent.parent
    m=read(folder/'PACKAGE_MANIFEST.json')
    actual={str(p.relative_to(folder)) for p in folder.rglob('*') if p.is_file() and p.name!='PACKAGE_MANIFEST.json' and '__pycache__' not in p.parts and p.suffix!='.pyc'}
    if actual != set(m['files']):raise ValueError('PROJECT_PACKAGE_INVENTORY_CHANGED')
    for name,expected in m['files'].items():
        if sha(bound(folder,name))!=expected:raise ValueError('PROJECT_PACKAGE_FILE_CHANGED:'+name)
    for name,expected in m['dependencies'].items():
        if sha(bound(root,name))!=expected:raise ValueError('PROJECT_PACKAGE_DEPENDENCY_CHANGED:'+name)
    result=verify_questionnaire(folder/'examples/questionnaire')
    print('verified project/v69 package:',len(actual),'files;',result['cases'],'questionnaire cases; no simulation')


if __name__=='__main__':main()
