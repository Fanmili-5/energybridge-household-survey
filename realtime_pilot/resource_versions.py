"""Immutable, hash-addressed physical resources; never trust client file paths."""
import json
import re
import shutil
import tempfile
from pathlib import Path
from common import file_hash

def paths(catalog):
    for row in catalog['models']:yield row['idf'],row['sha256']
    for row in catalog['weather']:
        yield row['epw'],row['epw_sha256']
        yield row['ddy'],row['ddy_sha256']
    if catalog.get('validation_sha256'):
        yield 'simulation_resources/validation.json',catalog['validation_sha256']
    yield from catalog.get('administrative_source',{}).get('files',{}).items()

def safe_asset(base,name,expected):
    base=Path(base).resolve();p=(base/name).resolve()
    if base not in p.parents or not p.is_file() or file_hash(p)!=expected:
        raise ValueError('Archived resource missing or changed: '+name)
    return p

def freeze(catalog_path):
    """Copy, verify and atomically publish a catalog plus all referenced bytes."""
    catalog_path=Path(catalog_path);study=catalog_path.parent.parent
    sha=file_hash(catalog_path);catalog=json.loads(catalog_path.read_text())
    versions=catalog_path.parent/'versions';versions.mkdir(exist_ok=True)
    target=versions/sha
    if target.exists():
        assert file_hash(target/'catalog.json')==sha
        for name,expected in paths(catalog):safe_asset(target,name,expected)
        return sha
    with tempfile.TemporaryDirectory(prefix='.freezing-',dir=versions) as tmp:
        tmp=Path(tmp)
        for name,expected in paths(catalog):
            source=safe_asset(study,name,expected);destination=tmp/name
            destination.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(source,destination)
            safe_asset(tmp,name,expected)
        shutil.copyfile(catalog_path,tmp/'catalog.json')
        if file_hash(tmp/'catalog.json')!=sha:raise ValueError('Catalog changed while freezing')
        # Rename a child so TemporaryDirectory still owns a cleanup directory.
        staged=tmp/'ready';staged.mkdir()
        for p in list(tmp.iterdir()):
            if p!=staged:p.rename(staged/p.name)
        staged.rename(target)
    return sha

def resolve_catalog(current,expected):
    current=Path(current)
    if not re.fullmatch(r'[a-f0-9]{64}',str(expected)):
        raise ValueError('Invalid resource version')
    if file_hash(current)==expected:return current,current.parent.parent
    archive=current.parent/'versions'/expected
    path=archive/'catalog.json'
    if not path.is_file() or file_hash(path)!=expected:
        raise ValueError('缺少本次模拟的历史资源版本，请恢复归档；不会替换成当前天气')
    return path,archive
