"""Fail closed before collection/backup if the pinned data volume is missing.

External to the signed collector runtime: storage changes never change case hashes.
The layout file is root-owned and contains paths/UUIDs only, never credentials.
"""
import argparse
import json
import os
import re
import stat
from pathlib import Path


def mountpoints():
    def unescape(value):
        return re.sub(r'\\([0-7]{3})', lambda m: chr(int(m[1], 8)), value)
    return {unescape(line.split()[4])
            for line in Path('/proc/self/mountinfo').read_text().splitlines()}


def verify(layout):
    root = Path(layout['mount_root'])
    device = Path('/dev/disk/by-uuid') / layout['filesystem_uuid']
    if not stat.S_ISBLK(device.stat().st_mode):
        raise RuntimeError('Pinned UUID does not identify a block device')
    if root.stat().st_dev != device.stat().st_rdev:
        raise RuntimeError('Collection volume is absent or has the wrong UUID')
    mounted = mountpoints()
    for path in [str(root), *layout['binds']]:
        if path not in mounted:
            raise RuntimeError('Required mount is absent: ' + path)
    for target, source in layout['binds'].items():
        if not Path(source).is_relative_to(root):
            raise RuntimeError('Bind source is outside the data volume')
        if not os.path.samefile(target, source):
            raise RuntimeError('Bind mount points to the wrong directory: ' + target)
    data = Path(layout['data_root'])
    if not (data / 'formal_responses.sqlite3').is_file():
        raise RuntimeError('Existing collection database is missing')
    pepper = data / 'credential_pepper'
    if not pepper.is_file() or pepper.stat().st_size != 32:
        raise RuntimeError('Existing recovery material is missing')
    if pepper.stat().st_mode & 0o077:
        raise RuntimeError('Recovery material permissions are too broad')
    release = json.loads(Path(layout['release_manifest']).read_text())
    if release['release_sha256'] != layout['release_sha256']:
        raise RuntimeError('Mounted release does not match the pinned collection')
    return {'passed': True, 'filesystem_uuid': layout['filesystem_uuid'],
            'release_sha256': layout['release_sha256'],
            'required_mounts': sorted([str(root), *layout['binds']])}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--layout', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(verify(json.loads(args.layout.read_text()))))
