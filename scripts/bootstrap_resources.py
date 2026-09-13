"""Reconstruct the frozen catalog without changing it or calling model APIs."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import argparse
import hashlib
import io
import json
import lzma
import shutil
import sys
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'realtime_pilot'))
from resource_versions import paths, safe_asset
from build_complete_household_idf import build
import build_regional_resources as builder


def bootstrap(root=ROOT, cache=None, workers=4):
    root = Path(root).resolve()
    catalog = json.loads((root/'simulation_resources/catalog.json').read_text())

    def install(name, expected, body=None):
        target = (root/name).resolve()
        if root not in target.parents:
            raise ValueError('Resource path escapes destination')
        if target.is_file() and hashlib.sha256(target.read_bytes()).hexdigest() == expected:
            return True
        if body is None and cache:
            source = Path(cache)/name
            if source.is_file() and hashlib.sha256(source.read_bytes()).hexdigest() == expected:
                body = source.read_bytes()
        if body is None:
            return False
        if hashlib.sha256(body).hexdigest() != expected:
            raise ValueError('Resource checksum mismatch: '+name)
        target.parent.mkdir(parents=True, exist_ok=True)
        temp = target.with_suffix(target.suffix+'.downloading')
        temp.write_bytes(body)
        temp.replace(target)
        return True

    body, manifest = build()
    base = 'models/tianjin_family_eb_v1/family_all_appliances.idf'
    install(base, catalog['source_idf_sha256'], body.encode())
    builder.BASE = root/base
    for row in catalog['models']:
        install(row['idf'], row['sha256'], builder.model(row['kind'], row['floor'], row['indoor_area_m2']).encode())
    validation = 'simulation_resources/validation.json'
    if not install(validation, catalog['validation_sha256']):
        install(validation, catalog['validation_sha256'], lzma.decompress((root/(validation+'.xz')).read_bytes()))
    for name, checksum in catalog['administrative_source']['files'].items():
        if not install(name, checksum):
            raise ValueError('Missing committed administrative snapshot: '+name)

    def station(row):
        missing = [(key, suffix) for key,suffix in [('epw','.epw'),('ddy','.ddy')]
                   if not install(row[key], row[key+'_sha256'])]
        if not missing:
            return
        url = row['source_url']
        if not url.startswith('https://climate.onebuilding.org/'):
            raise ValueError('Unapproved weather source host')
        request = urllib.request.Request(url, headers={'User-Agent':'EnergyBridge resource bootstrap'})
        with urllib.request.urlopen(request, timeout=90) as response:
            payload = response.read()
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            for key,suffix in missing:
                names = [n for n in archive.namelist() if n.lower().endswith(suffix)]
                if len(names) != 1:
                    raise ValueError('Ambiguous weather archive: '+row['id'])
                install(row[key], row[key+'_sha256'], archive.read(names[0]))

    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(station, catalog['weather']))
    for archived in sorted((root/'simulation_resources/versions').glob('*/catalog.json')):
        old = json.loads(archived.read_text())
        if hashlib.sha256(archived.read_bytes()).hexdigest() != archived.parent.name:
            raise ValueError('Archived catalog checksum mismatch')
        for name, checksum in paths(old):
            target = archived.parent/name
            if target.is_file() and hashlib.sha256(target.read_bytes()).hexdigest() == checksum:
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            compressed=target.with_suffix(target.suffix+'.xz')
            if compressed.is_file():
                body=lzma.decompress(compressed.read_bytes())
                if hashlib.sha256(body).hexdigest()!=checksum:
                    raise ValueError('Archived compressed resource checksum mismatch: '+name)
                target.write_bytes(body)
            else:
                source = safe_asset(root, name, checksum)
                shutil.copyfile(source, target)
    for name, checksum in paths(catalog):
        safe_asset(root, name, checksum)
    print(json.dumps({'verified':True,'models':len(catalog['models']),
                      'weather_stations':len(catalog['weather']),'model_api_calls':0}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=ROOT)
    parser.add_argument('--source-cache',type=Path)
    parser.add_argument('--workers',type=int,choices=range(1,9),default=4)
    args = parser.parse_args()
    bootstrap(args.root, args.source_cache, args.workers)
