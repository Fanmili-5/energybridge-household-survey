"""Route bounded method changes to offline checks, not cohort experiments."""
import os
import subprocess

ROOTS=('benchmark/ab_generation/unified/','benchmark/research_delivery/','benchmark/family_generation/')
FILES={'README.md','benchmark/README.md','benchmark/ab_generation/README.md',
       'benchmark/ab_generation/PACKAGE_MANIFEST.json','benchmark/PUBLICATION_MANIFEST.json','docs/README.md',
       '.github/workflows/unified-method.yml','.github/workflows/offline-checks.yml',
       '.github/workflows/ab-generation.yml','.github/workflows/ab-collection-plan.yml',
       '.github/workflows/family-generation.yml','.github/workflows/project-interfaces.yml'}


def method_only(paths):
    return bool(paths) and all(p.startswith(ROOTS) or p in FILES for p in paths)


def main():
    base=os.environ.get('BASE_SHA','');event=os.environ.get('EVENT_NAME','workflow_dispatch')
    if event=='workflow_dispatch':answer=False
    else:
        if not base or set(base)=={'0'}:
            base=subprocess.check_output(['git','merge-base','HEAD','origin/'+os.environ.get('DEFAULT_BRANCH','main')],text=True).strip()
        paths=subprocess.check_output(['git','diff','--name-only',base,'HEAD'],text=True).splitlines()
        answer=method_only(paths)
    with open(os.environ['GITHUB_OUTPUT'],'a') as f:f.write('method_only='+str(answer).lower()+'\n')
    print('Bounded method-only change:',answer)


if __name__=='__main__':main()
