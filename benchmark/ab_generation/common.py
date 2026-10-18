"""Portable JSON, immutable output directories, and dependency identities."""
import gzip
import hashlib
import json
from pathlib import Path


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    path = Path(path)
    return json.loads(gzip.decompress(path.read_bytes()) if path.suffix == '.gz'
                      else path.read_text())


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (canonical(value) + '\n').encode()
    path.write_bytes(gzip.compress(raw, mtime=0) if path.suffix == '.gz' else raw)


def bound(root, relative):
    path = (Path(root) / relative).resolve()
    if not path.is_relative_to(Path(root).resolve()):
        raise ValueError('RESOURCE_OUTSIDE_ROOT')
    return path


def code_hash():
    root = Path(__file__).parent
    return digest({p.name: sha(p) for p in sorted(root.glob('*.py'))})


def seal(root, metadata):
    root = Path(root)
    files = {str(p.relative_to(root)): sha(p) for p in sorted(root.rglob('*'))
             if p.is_file() and p.name != 'MANIFEST.json'}
    save(root / 'MANIFEST.json', {**metadata, 'files': files})


def verify(root):
    root = Path(root)
    manifest = read(root / 'MANIFEST.json')
    for name, expected in manifest['files'].items():
        if sha(bound(root, name)) != expected:
            raise ValueError('ARTIFACT_CHANGED:' + name)
    actual = {str(p.relative_to(root)) for p in root.rglob('*')
              if p.is_file() and p.name != 'MANIFEST.json'}
    if actual != set(manifest['files']):
        raise ValueError('ARTIFACT_SET_CHANGED')
    return manifest
