"""Verify the public source/example package separately from generated runs."""
from pathlib import Path
from .common import read, sha


def main():
    root = Path(__file__).parent
    manifest = read(root / 'PACKAGE_MANIFEST.json')
    for name, expected in manifest['files'].items():
        if not (root / name).resolve().is_relative_to(root.resolve()) or sha(root / name) != expected:
            raise ValueError('PACKAGE_FILE_CHANGED:' + name)
    print('verified public A/B package:', len(manifest['files']), 'files')


if __name__ == '__main__':
    main()
