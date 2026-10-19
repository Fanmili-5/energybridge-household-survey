"""Replay frozen research in a temporary tree, never importing production code."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent
ARCHIVE = ROOT / 'research/archive'


def read(path):
    return json.loads(path.read_text())


def same(a, b):
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(same(a[k], b[k]) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(same(x, y) for x, y in zip(a, b))
    if isinstance(a, float) or isinstance(b, float):
        return math.isclose(a, b, rel_tol=1e-10, abs_tol=1e-10)
    return a == b


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--raw-dir', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--refit', choices=['ecape', 'eca', 'iflex', 'dutch'])
    args = parser.parse_args()
    raw, out = args.raw_dir.resolve(), args.output.resolve()
    if out.exists() or out.is_relative_to(ROOT):
        raise ValueError('Use a new output directory outside the method package')
    lock = read(ROOT / 'INPUTS.lock.json')
    needed = {'eca2026.xlsx', 'survey1_questions.csv', 'survey1_answers.csv',
              'survey2_questions.csv', 'survey2_answers.csv', 'dutch.sav', 'dutch_dictionary.docx'}
    if args.refit == 'ecape':
        needed.add('ecape_combined.csv')
    for item in lock['files']:
        if item['filename'] in needed:
            path = raw / item['filename']
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != item['sha256']:
                raise ValueError('Missing or changed research input: ' + item['filename'])
    provenance = read(ROOT / 'research/PROVENANCE.json')
    for rel, info in provenance['files'].items():
        if hashlib.sha256((ARCHIVE / rel).read_bytes()).hexdigest() != info['sha256']:
            raise ValueError('Changed archived research source: ' + rel)
    result = {'schema': 'eb.household_archetypes.replay.v1', 'constructs_match': {},
              'refit_requested': args.refit, 'production_changes': False, 'EP_runs': 0}
    with tempfile.TemporaryDirectory(prefix='eb-archetype-evidence-') as tmp:
        tree = Path(tmp) / 'tree'
        shutil.copytree(ARCHIVE, tree)
        runner = tree / 'artifacts/eb_eca_linkage_audit_20261019'
        commands = [
            [sys.executable, '-B', str(runner / 'run_linkage_audit.py'), '--raw', str(raw / 'eca2026.xlsx')],
            [sys.executable, '-B', str(runner / 'check_external_constructs.py'), '--raw-dir', str(raw)],
        ]
        for cmd in commands:
            proc = subprocess.run(cmd, text=True, capture_output=True, timeout=300)
            if proc.returncode:
                raise RuntimeError(proc.stderr[-4000:])
        out.mkdir(parents=True)
        for name in ['RESULTS.json', 'EXTERNAL_CONSTRUCTS.json']:
            matches = same(read(runner / name), read(ARCHIVE / 'artifacts/eb_eca_linkage_audit_20261019' / name))
            if not matches:
                raise ValueError('Construct evidence differs from the frozen result: ' + name)
            result['constructs_match'][name] = True
            shutil.copyfile(runner / name, out / name)
        if args.refit:
            if args.refit == 'ecape':
                script = tree / 'docs/research/ecape-fixed-six_20261019/run.py'
                cmd = [sys.executable, '-B', str(script), '--raw', str(raw / 'ecape_combined.csv'), '--output', str(out / 'ecape')]
                reference = ARCHIVE / 'docs/research/ecape-fixed-six_20261019/RESULTS.json'
                output = out / 'ecape/RESULTS.json'
            elif args.refit == 'eca':
                script = tree / 'artifacts/eb_eca_context_six_20261019/run_context_six.py'
                cmd = [sys.executable, '-B', str(script), '--raw', str(raw / 'eca2026.xlsx'), '--output', str(out / 'eca')]
                reference = ARCHIVE / 'artifacts/eb_eca_context_six_20261019/RESULTS.json'
                output = out / 'eca/RESULTS.json'
            else:
                # The original runner accepts its raw directory via this explicit environment variable.
                script = tree / 'artifacts/eb_external_validation_20261019/run_validation.py'
                source = {'iflex': 'iflex2020', 'dutch': 'dutch2025'}[args.refit]
                cmd = [sys.executable, '-B', str(script), '--source', source]
                reference = ARCHIVE / 'artifacts/eb_external_validation_20261019' / source / 'RESULTS.json'
                output = tree / 'artifacts/eb_external_validation_20261019' / source / 'RESULTS.json'
            import os
            env = dict(os.environ, EB_COARSE_RAW_DIR=str(raw))
            with (out / 'refit.log').open('w') as log:
                proc = subprocess.run(cmd, text=True, stdout=log, stderr=subprocess.STDOUT, env=env, timeout=3600)
            if proc.returncode:
                raise RuntimeError('Research refit failed; see refit.log')
            result['refit_result_matches_frozen_numeric_tolerance1e_10'] = same(read(output), read(reference))
            if args.refit in ['iflex', 'dutch']:
                shutil.copytree(output.parent, out / args.refit)
        (out / 'REPLAY.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
