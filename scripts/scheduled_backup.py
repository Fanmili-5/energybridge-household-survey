"""Back up authoritative survey data without invoking models or copying EP traces."""
import argparse
from datetime import datetime, timezone
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'realtime_pilot'))
from backup_backend import backup


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--data-dir', type=Path, required=True)
    parser.add_argument('--backup-dir', type=Path, required=True)
    parser.add_argument('--keep', type=int, default=24)
    args = parser.parse_args()
    if args.keep < 1:
        parser.error('--keep must be positive')
    directory = args.backup_dir.resolve()
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    report = backup(args.data_dir, directory / f'survey-snapshot-{stamp}.tar.gz', include_traces=False)
    # Retire only this script's completed snapshots, after the new one succeeds.
    snapshots = sorted(directory.glob('survey-snapshot-*.tar.gz'), reverse=True)
    for path in snapshots[args.keep:]:
        manifest = path.with_suffix('.manifest.json')
        if manifest.is_file():
            path.unlink()
            manifest.unlink()
    print(f"Survey backup complete; integrity={report['sqlite_integrity']}; jobs={report['jobs']}; bytes={report['bytes']}")


if __name__ == '__main__':
    main()
