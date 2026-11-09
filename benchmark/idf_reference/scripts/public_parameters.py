"""Inspect or stage the published fixed inputs; do not copy run/family data."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inside(root, name):
    path = (root / name).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError(f'path outside input root: {name}')
    return path


def materialize(root=ROOT):
    """Restore original input keys without rewriting physics or source hashes.

    Historical path names are retained inside the existing compiler. The files
    staged here are the 18 fixed physical inputs in LAYOUT, never approvals,
    family inputs or native results. Existing different content is an error.
    """
    root = Path(root).resolve()
    layout = read(ROOT / 'parameters/LAYOUT.json')['files']
    pending = []
    for logical_name, item in layout.items():
        source = inside(ROOT, item['path'])
        if sha(source) != item['sha256']:
            raise ValueError(f'published parameter changed: {item["path"]}')
        target = inside(root, logical_name)
        if target.exists() and (not target.is_file() or sha(target) != item['sha256']):
            raise ValueError(f'existing input conflicts: {logical_name}')
        pending.append((source, target))
    for source, target in pending:
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
    return {'fixed_inputs_staged': len(pending), 'native_simulation_executed': False}


def references(value):
    if isinstance(value, dict):
        if set(value) == {'path', 'sha256'}:
            yield value
        else:
            for child in value.values():
                yield from references(child)
    elif isinstance(value, list):
        for child in value:
            yield from references(child)


def check(root=ROOT):
    """Report external inputs for selected catalogs, not scientific acceptance."""
    root = Path(root).resolve()
    initial = [ROOT / 'configs/condition_housing_v3.json', ROOT / 'configs/condition_housing_linux_v3.json']
    initial += list((ROOT / 'parameters/enclosures').glob('*.json'))
    initial += list((ROOT / 'parameters/sites').glob('*.json'))
    found = {}
    for path in initial:
        for item in references(read(path)):
            key = item['path']
            if key in found and found[key] != item['sha256']:
                raise ValueError(f'conflicting source versions: {key}')
            found[key] = item['sha256']
    recipes = read(ROOT / 'configs/condition_envelope_recipes_v3.json')['recipes']
    for recipe in recipes:
        if recipe.get('adapter') == 'complete_reference_constructions_v1':
            for item in references(recipe):
                name = item['path']
                if name in found and found[name] != item['sha256']:
                    raise ValueError(f'conflicting source versions: {name}')
                found[name] = item['sha256']
    files = []
    for name, expected in sorted(found.items()):
        path = inside(root, name)
        state = 'missing' if not path.is_file() else 'present' if sha(path) == expected else 'hash_mismatch'
        files.append({'path': name, 'sha256': expected, 'state': state})
    return {'files': files, 'selected_input_references_present': all(x['state'] == 'present' for x in files),
            'native_runtime_ready_or_physics_accepted': False}


def catalog():
    classes = read(ROOT / 'configs/reference_enclosure_classes_v2.json')['classes']
    sites = read(ROOT / 'configs/condition_housing_v3.json')['sites']
    return {'classes': [{'id': x['id'], 'country': x['country'], 'conditions': x['housing_conditions']}
                        for x in classes],
            'sites': [{'id': x['id'], 'country': x['country']} for x in sites],
            'representation': 'controlled_reference', 'class_wide_native_acceptance_claimed': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('catalog', 'materialize', 'check'))
    parser.add_argument('--root', type=Path, default=ROOT)
    args = parser.parse_args()
    result = catalog() if args.action == 'catalog' else materialize(args.root) if args.action == 'materialize' else check(args.root)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.action == 'check' and not result['selected_input_references_present']:
        raise SystemExit(2)


if __name__ == '__main__':
    main()
