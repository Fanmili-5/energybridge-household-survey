#!/usr/bin/env python3
"""B54: feasible VPP opportunities, multi-axis commands and native event states."""
import argparse, subprocess, sys, json
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
STAGE = ROOT / 'docs/research/collection-adjustment-20260930/household1000/candidate_B_v54_20261017'

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('stage', choices=['B'])
    p.add_argument('phase', choices=['build', 'regressions', 'review', 'seal', 'verify', 'publish', 'verify-pointers', 'observations', 'design-review', 'report', 'native-states', 'thermal-check'])
    p.add_argument('--workers', type=int, default=4)
    a = p.parse_args()
    if a.phase == 'build': command = [str(STAGE / 'code/generate.py'), '--workers', str(a.workers)]
    elif a.phase == 'native-states': command = [str(STAGE / 'tools/native_state_runner.py'), '--workers', str(a.workers)]
    elif a.phase == 'thermal-check': command = [str(STAGE / 'tools/thermal_B_validation.py'), '--workers', str(a.workers)]
    elif a.phase == 'review': command = [str(STAGE / 'tools/review.py')]
    elif a.phase == 'report': command = [str(STAGE / 'tools/report.py')]
    elif a.phase == 'design-review': command = [str(STAGE / 'tools/design_review.py')]
    elif a.phase == 'observations': command = [str(STAGE / 'tools/observations.py')]
    elif a.phase == 'regressions': command = [str(STAGE / 'tools/regressions.py')]
    else: command = [str(STAGE / 'tools/lifecycle.py'), a.phase]
    result=subprocess.run([sys.executable, '-B', *command], cwd=ROOT).returncode
    if result:return result
    if a.phase=='native-states':
        if not json.loads((STAGE/'STATE_BINDINGS.json').read_text())['passed']:return 2
        return subprocess.run([sys.executable,'-B',str(STAGE/'tools/resume_state_index.py')],cwd=ROOT).returncode
    if a.phase=='report':return subprocess.run([sys.executable,'-B',str(STAGE/'tools/preview.py')],cwd=ROOT).returncode
    return 0

if __name__ == '__main__': raise SystemExit(main())
