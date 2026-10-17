#!/usr/bin/env python3
"""B57 schedule-preserving joint-node/SOC-time closure."""
import argparse,subprocess,sys
from pathlib import Path
REPO=Path(__file__).resolve().parents[1]
STAGE=REPO/'docs/research/collection-adjustment-20260930/household1000/candidate_B_v57_20261017'
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('stage',choices=['B']);p.add_argument('phase',choices=['build','review','report','seal','publish','verify','verify-pointers']);p.add_argument('--workers',type=int,default=4);a=p.parse_args()
    if a.phase=='build':cmd=[STAGE/'code/generate.py','--workers',str(a.workers)]
    elif a.phase=='review':cmd=[STAGE/'tools/review.py']
    elif a.phase=='report':cmd=[STAGE/'tools/report.py']
    else:cmd=[STAGE/'tools/lifecycle.py',a.phase]
    return subprocess.run([sys.executable,'-B',*map(str,cmd)],cwd=REPO).returncode
if __name__=='__main__':raise SystemExit(main())
