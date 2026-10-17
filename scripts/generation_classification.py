#!/usr/bin/env python3
"""B49 classification-only update on immutable A46/B48 schedules."""
import argparse,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];STAGE=ROOT/'docs/research/collection-adjustment-20260930/household1000/candidate_B_v49_20261017'
def main():
    phases={'build':'code/generate.py','regressions':'tools/regression.py','review':'tools/review.py','export':'tools/export.py','seal':'tools/seal.py','verify':'tools/verify.py','publish':'tools/publish.py','verify-pointers':'tools/verify_pointers.py'}
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('stage',choices=['B']);p.add_argument('phase',choices=list(phases));p.add_argument('--workers',type=int,default=4);a=p.parse_args();cmd=[sys.executable,'-B',str(STAGE/phases[a.phase])]
    if a.phase=='build':cmd+=['--workers',str(a.workers)]
    return subprocess.run(cmd,cwd=ROOT).returncode
if __name__=='__main__':raise SystemExit(main())
