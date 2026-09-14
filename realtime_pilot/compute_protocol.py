"""Private compute transport contract; no changes to native EB decisions."""
import hashlib
import json
from pathlib import Path, PurePosixPath
import stat
import zipfile

PROTOCOL = 'eb.compute.v1'
MAX_REQUEST = 2 * 1024 * 1024
MAX_ARCHIVE = 512 * 1024 * 1024
MAX_EXPANDED = 2 * 1024 * 1024 * 1024

def release_hash(*,verify_resources=True):
    from common import ROOT, UPSTREAM, file_hash
    # Every executable local module and the pinned upstream tree must agree.
    files = {p.name:file_hash(p) for p in ROOT.glob('*.py')}
    files['planner_english_catalog.json'] = file_hash(ROOT/'planner_english_catalog.json')
    files['codebook_current'] = file_hash(ROOT.parent/'QUESTIONNAIRE_CODEBOOK.json')
    files['codebook_legacy'] = file_hash(ROOT.parent/'QUESTIONNAIRE_CODEBOOK_LEGACY.json')
    resources=ROOT.parent/'simulation_resources'
    catalog_path=resources/'catalog.json'
    if catalog_path.exists():
        files['simulation_resources/catalog.json']=file_hash(catalog_path)
        catalog=json.loads(catalog_path.read_text())
        if catalog.get('validation_sha256'):
            actual=file_hash(resources/'validation.json') if verify_resources else catalog['validation_sha256']
            if actual!=catalog['validation_sha256']:raise ValueError('Regional validation report changed')
            files['simulation_resources/validation.json']=actual
        for row in catalog['models']:
            actual=file_hash(ROOT.parent/row['idf']) if verify_resources else row['sha256']
            if actual!=row['sha256']:raise ValueError('Regional IDF changed')
            files[row['idf']]=actual
        for row in catalog['weather']:
            for pathkey,hashkey in [('epw','epw_sha256'),('ddy','ddy_sha256')]:
                actual=file_hash(ROOT.parent/row[pathkey]) if verify_resources else row[hashkey]
                if actual!=row[hashkey]:raise ValueError('Regional weather changed')
                files[row[pathkey]]=actual
        for name,expected in catalog.get('administrative_source',{}).get('files',{}).items():
            actual=file_hash(ROOT.parent/name)
            if actual!=expected:raise ValueError('Administrative input directory changed')
            files[name]=actual
        from resource_versions import paths
        for archive in sorted((resources/'versions').glob('*/catalog.json')):
            version=archive.parent.name
            if file_hash(archive)!=version:raise ValueError('Archived catalog changed')
            files['archived/'+version+'/catalog.json']=version
            for name,expected in paths(json.loads(archive.read_text())):
                actual=file_hash(archive.parent/name) if verify_resources else expected
                if actual!=expected:raise ValueError('Archived physical resource changed')
                files['archived/'+version+'/'+name]=actual
    # Exclude caches and generated files, include code AND physical resources.
    manifest=json.loads((ROOT.parent/'UPSTREAM_TRACKED_FILES.json').read_text())
    for name,expected in manifest['files'].items():
        actual=file_hash(UPSTREAM/name)
        if actual!=expected:raise ValueError('Pinned upstream file changed: '+name)
        files['upstream/'+name]=actual
    return hashlib.sha256(json.dumps(files,sort_keys=True).encode()).hexdigest()

def safe_unpack(archive, destination):
    """Validate everything before extracting; manifests checked by the caller."""
    with zipfile.ZipFile(archive) as z:
        members=z.infolist()
        if len(members)>20000 or sum(m.file_size for m in members)>MAX_EXPANDED:
            raise ValueError('Compute archive exceeds limits')
        names=set()
        for member in members:
            p=PurePosixPath(member.filename)
            mode=(member.external_attr>>16)&0xffff
            if p.is_absolute() or '..' in p.parts or '\\' in member.filename or stat.S_ISLNK(mode) or member.filename in names:
                raise ValueError('Unsafe compute archive member')
            names.add(member.filename)
        z.extractall(destination)

def archive_job(folder):
    from common import file_hash, write_json
    # Include full native traces, exact model inputs/outputs and EP artifacts.
    excluded={'transport_state.json','result.zip','result.zip.tmp','transport_manifest.json'}
    paths=[p for p in sorted(folder.rglob('*')) if p.is_file() and not p.is_symlink()
           and p.relative_to(folder).as_posix() not in excluded and not p.name.endswith('.tmp')]
    write_json(folder/'transport_manifest.json',{p.relative_to(folder).as_posix():file_hash(p) for p in paths})
    tmp=folder/'result.zip.tmp'
    with zipfile.ZipFile(tmp,'w',zipfile.ZIP_DEFLATED,compresslevel=3) as z:
        for p in paths+[folder/'transport_manifest.json']:z.write(p,p.relative_to(folder).as_posix())
    if tmp.stat().st_size>MAX_ARCHIVE:raise ValueError('Compute archive too large')
    tmp.replace(folder/'result.zip')
    return file_hash(folder/'result.zip')
