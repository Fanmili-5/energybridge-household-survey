"""Verify the public source/example package separately from generated runs."""
from pathlib import Path
from .common import read, sha


def main():
    root = Path(__file__).parent
    manifest = read(root / 'PACKAGE_MANIFEST.json')
    for name, expected in manifest['files'].items():
        if not (root / name).resolve().is_relative_to(root.resolve()) or sha(root / name) != expected:
            raise ValueError('PACKAGE_FILE_CHANGED:' + name)
    inventory = {str(p.relative_to(root)) for p in root.rglob('*')
                 if p.is_file() and p.name != 'PACKAGE_MANIFEST.json'
                 and '__pycache__' not in p.parts and p.suffix != '.pyc'}
    if inventory != set(manifest['files']):
        raise ValueError('PACKAGE_INVENTORY_CHANGED')
    sources = read(root / 'SOURCES.json')
    from .audit_design import audit
    audit()
    source_ids = {s['key'] for s in sources['papers']} | {s['id'] for s in sources['implementation_sources']}
    source_ids |= {s['key'] for s in sources.get('review_process_sources', [])}
    for rule in read(root / 'LIFE_RULES.json')['rules'] + read(root / 'STRATEGY_RULES.json')['rules']:
        if not set(rule['sources']) <= source_ids:
            raise ValueError('UNKNOWN_RULE_SOURCE:' + rule['id'])
        for implementation in rule['implementation'].split(';'):
            if not (root / implementation.split(':')[0]).is_file():
                raise ValueError('UNKNOWN_RULE_IMPLEMENTATION:' + rule['id'])
    print('verified public A/B package:', len(manifest['files']), 'files')


if __name__ == '__main__':
    main()
