#!/usr/bin/env python3
"""V36 A / V37 B generation-design revision. Historical entrypoints stay pinned."""
import argparse,subprocess,sys
from pathlib import Path
REPO=Path(__file__).resolve().parents[1]
BASE=REPO/'docs/research/collection-adjustment-20260930/household1000'
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('stage',choices=['A','B']);p.add_argument('phase',choices=['build','review','export','seal','verify','status','audit-A','probe']);p.add_argument('--workers',type=int,default=4);a=p.parse_args()
    stage=BASE/('normal_A_v36_20261016'if a.stage=='A'else'candidate_B_v37_20261016')
    if a.phase=='status':print((stage/'ACCEPTANCE.json').read_text()if(stage/'ACCEPTANCE.json').exists()else'{"accepted":false}');return 0
    if a.phase=='probe':
        if a.stage!='A':p.error('probe is an A functional validation only')
        return subprocess.run([sys.executable,'-B',str(stage/'tools/thermal_probe.py')],cwd=REPO).returncode
    names={'build':'generate.py','review':'review.py','export':'export.py','seal':'finalize.py','verify':'finalize.py','audit-A':'audit_A.py'}
    cmd=[sys.executable,'-B',str(stage/'code'/names[a.phase])]
    if a.phase=='build':cmd+=['--workers',str(a.workers),'--limit','1000']
    if a.phase=='verify':cmd+=['--verify-only']
    return subprocess.run(cmd,cwd=REPO).returncode
if __name__=='__main__':raise SystemExit(main())
