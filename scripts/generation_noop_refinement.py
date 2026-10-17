#!/usr/bin/env python3
"""B51: refine B within the single10000-case dataset;target100 identical requests."""
import argparse, subprocess, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
STAGE = ROOT / 'docs/research/collection-adjustment-20260930/household1000/candidate_B_v51_20261017'

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('stage', choices=['B'])
    p.add_argument('phase', choices=['build', 'regressions', 'review', 'seal', 'verify', 'publish', 'verify-pointers'])
    p.add_argument('--workers', type=int, default=4)
    a = p.parse_args()
    if a.phase == 'build': command = [str(STAGE / 'code/generate.py'), '--workers', str(a.workers)]
    elif a.phase == 'review': command = [str(STAGE / 'tools/review.py')]
    elif a.phase == 'regressions': command = [str(STAGE / 'tools/regressions.py')]
    else: command = [str(STAGE / 'tools/lifecycle.py'), a.phase]
    return subprocess.run([sys.executable, '-B', *command], cwd=ROOT).returncode

if __name__ == '__main__': raise SystemExit(main())
