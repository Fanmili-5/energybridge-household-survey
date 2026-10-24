"""Importable CLI for isolated frozen-A or supplied-new-A collection checks."""
import argparse
from pathlib import Path

from benchmark.ab_generation.common import read, save
from .production import audited_build


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--inputs', required=True)
    parser.add_argument('--config', required=True)
    parser.add_argument('--out', required=True)
    parser.add_argument('--workers', type=int, default=2)
    args = parser.parse_args()
    try:
        result = audited_build(args.inputs, args.out, read(args.config), args.workers)
    except Exception as error:
        output = Path(args.out)
        # The original candidate/source artifacts remain untouched on failure.
        if output.exists():
            save(output/'TECHNICAL_FAILURE.json', dict(
                error=type(error).__name__+':'+str(error),
                outcome='generation_technical_error;not_no_opportunity',
                no_reseed=True, physical_runs=0))
        raise
    print(result)


if __name__ == '__main__':
    main()
