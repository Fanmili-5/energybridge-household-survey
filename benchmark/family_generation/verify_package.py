"""Check the public family method package and its declared input dependencies."""
from .core import HERE, read, require, sha


def check():
    manifest = read(HERE / 'PACKAGE_MANIFEST.json')
    actual = {str(p.relative_to(HERE)) for p in HERE.rglob('*')
              if p.is_file() and p.name != 'PACKAGE_MANIFEST.json'
              and '__pycache__' not in p.parts and p.suffix != '.pyc'}
    require(actual == set(manifest['files']), 'PACKAGE_INVENTORY_CHANGED')
    for name, expected in manifest['files'].items():
        path = (HERE / name).resolve()
        require(path.is_relative_to(HERE.resolve()) and sha(path) == expected,
                'PACKAGE_FILE_CHANGED:' + name)
    root = HERE.parents[1]
    for name, expected in manifest['dependencies'].items():
        path = (root / name).resolve()
        require(path.is_relative_to(root) and sha(path) == expected,
                'METHOD_DEPENDENCY_CHANGED:' + name)
    cfg = read(HERE / 'examples/batch.json')
    require(sha(HERE / 'examples' / cfg['pool']['path']) == cfg['pool']['sha256'],
            'DEFAULT_POOL_CHANGED')
    require(read(HERE / 'SOURCES.json')['public_reference_pool']['sha256'] == cfg['pool']['sha256'],
            'SOURCE_POOL_LOCK_CHANGED')
    return {'passed': True, 'package_files': len(actual),
            'dependencies': len(manifest['dependencies']), 'EP_runs': 0}


if __name__ == '__main__':
    import json
    print(json.dumps(check()))
