#!/usr/bin/env python3
"""Replay the saved reviewer counterexamples into a NEW output directory.

Does not edit the sealed binder or any production profile. Exit 0 means the
recorded counterexample pattern was reproduced, not that the binder passed.
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
CHAIN = HERE.parent / 'construction_chain_20261003'
BASE = HERE.parent / 'household_to_idf_v3_20261003/revised_generation_contexts_v2/cases/revised_context_cityslot-0001'
sys.path.insert(0, str(CHAIN))
from typed_chain import compile_gains
from run_chain_witnesses import runtime


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args()
    if args.output.exists():
        raise ValueError('new_review_witness_output_directory_required')
    lock = json.loads((HERE / 'SCHEDULE_GRID_REVIEW.json').read_text())
    for path, key in [(CHAIN / 'typed_chain.py', 'source_typed_chain_sha256'),
                      (CHAIN / 'run_chain_witnesses.py', 'source_runtime_sha256'),
                      (BASE / 'building.idf', 'source_base_IDF_sha256')]:
        if sha(path) != lock[key]:
            raise ValueError('reviewed_source_changed: ' + str(path))
    status = json.loads((BASE / 'STATUS.json').read_text())
    weather = Path(status['weather_epw_path'])
    if sha(weather) != status['weather_epw_sha256']:
        raise ValueError('reviewed_weather_changed')
    args.output.mkdir(parents=True)
    results = []
    for recorded in lock['cases']:
        name = recorded['case']
        bundle_path = HERE / 'schedule_grid_witnesses' / name / 'INPUT_BUNDLE.json'
        bundle = json.loads(bundle_path.read_text())
        body, report = compile_gains(bundle, BASE)
        if body is None:
            raise ValueError({'case': name, 'unexpected_compile_rejection': report})
        out = args.output / name
        out.mkdir()
        (out / 'INPUT_BUNDLE.json').write_bytes(bundle_path.read_bytes())
        (out / 'COMPILE_CHECK.json').write_text(json.dumps(report, indent=2) + '\n')
        measured = runtime(out / 'physical', body, weather, report)
        pattern_matches = (measured['pass'] == recorded['readback_pass']
                           and abs(measured['facility_kWh'] - recorded['actual_kWh']) < 1e-7
                           and measured['warning_markers'] == recorded['warning_markers'])
        results.append({'case': name, 'counterexample_pattern_reproduced': pattern_matches,
                        'expected_kWh': measured['expected_total_kWh'],
                        'actual_kWh': measured['facility_kWh'], 'binder_readback_pass': measured['pass']})
    result = {'counterexample_pattern_reproduced': all(x['counterexample_pattern_reproduced'] for x in results),
              'cases': results, 'collection_release': False, 'training_release': False}
    (args.output / 'REPLAY_RESULT.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))
    if not result['counterexample_pattern_reproduced']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
