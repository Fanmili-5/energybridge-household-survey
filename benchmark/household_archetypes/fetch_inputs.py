"""Fetch public research inputs by explicit URL and verify bytes; no uploads."""
import argparse
import hashlib
import json
from pathlib import Path
import urllib.request

ROOT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    dest = args.output.resolve()
    if dest.is_relative_to(ROOT):
        raise ValueError('Keep original individual records outside the public method package')
    dest.mkdir(parents=True, exist_ok=True)
    lock = json.loads((ROOT / 'INPUTS.lock.json').read_text())
    jobs = list(lock['files'])
    jobs += [{'filename': 'eb_' + Path(v['path']).name,
              'url': 'https://raw.githubusercontent.com/Agentic-Intelligence-Lab/EnergyBridge/' + lock['EB_commit'] + '/' + v['path'],
              'sha256': v['sha256']} for v in lock['EB_files']]
    for item in jobs:
        path = dest / item['filename']
        if path.exists():
            content = path.read_bytes()
        else:
            req = urllib.request.Request(item['url'], headers={'User-Agent': 'EB-public-research-reproduction/1'})
            with urllib.request.urlopen(req, timeout=120) as response:
                content = response.read()
        if hashlib.sha256(content).hexdigest() != item['sha256']:
            raise ValueError('Source changed; do not silently update the lock: ' + item['filename'])
        if not path.exists():
            path.write_bytes(content)
        print('verified ' + item['filename'], flush=True)


if __name__ == '__main__':
    main()
