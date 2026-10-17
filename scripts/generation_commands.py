#!/usr/bin/env python3
"""B48 executable-command equivalence and exogenous multi-window VPP generation on A46."""
import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STAGE = ROOT / 'docs/research/collection-adjustment-20260930/household1000/candidate_B_v48_20261017'

def main():
    phases = {'build':'code/generate.py', 'audit-A':'code/audit_A.py',
              'review':'code/review.py', 'design-review':'tools/review_design.py',
              'command-review':'tools/review_commands.py', 'regressions':'tools/regression.py',
              'thermal-probes':'tools/run_B_thermal_probes.py', 'export':'code/export.py',
              'seal':'tools/seal_stage.py', 'publish':'tools/publish_inputs.py',
              'verify':'code/finalize.py'}
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=['B'])
    parser.add_argument('phase', choices=[*phases, 'status'])
    parser.add_argument('--workers', type=int, default=4)
    args = parser.parse_args()
    if args.phase == 'status':
        print((STAGE/'ACCEPTANCE.json').read_text() if (STAGE/'ACCEPTANCE.json').exists() else '{"accepted":false}')
        return 0
    command = [sys.executable, '-B', str(STAGE/phases[args.phase])]
    if args.phase == 'build': command += ['--workers', str(args.workers), '--limit', '1000']
    if args.phase == 'verify': command += ['--verify-only']
    return subprocess.run(command, cwd=ROOT).returncode

if __name__ == '__main__':
    raise SystemExit(main())
