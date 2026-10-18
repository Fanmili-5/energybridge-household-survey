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
    inventory={str(p.relative_to(root))for p in root.rglob('*')if p.is_file()and p.name!='PACKAGE_MANIFEST.json'
               and '__pycache__'not in p.parts and p.suffix!='.pyc'}
    assert inventory==set(manifest['files']), 'package inventory mismatch'
    sources={s['id']for s in json.loads((root/'SOURCES.json').read_text())['sources']}
    for rule in json.loads((root/'RULES.json').read_text())['rules']:
        assert set(rule['sources'])<=sources, rule['id']
        assert (root/rule['implementation'].split(':')[0]).is_file(), rule['id']
    print(json.dumps({'passed': True, 'files_verified': len(manifest['files']),
                      'cohort_input_required': False, 'EnergyPlus_started': False}))


if __name__ == '__main__':
    main()
