"""Verify portable method/code files; no study data or engine needed."""
import hashlib
import json
from pathlib import Path


def main():
    root = Path(__file__).resolve().parent
    manifest = json.loads((root / 'PACKAGE_MANIFEST.json').read_text())
    for name, expected in manifest['files'].items():
        p = (root / name).resolve()
        assert p.is_relative_to(root), name
        assert hashlib.sha256(p.read_bytes()).hexdigest() == expected, name
    print(json.dumps({'passed': True, 'files_verified': len(manifest['files']),
                      'cohort_input_required': False, 'EnergyPlus_started': False}))


if __name__ == '__main__':
    main()
