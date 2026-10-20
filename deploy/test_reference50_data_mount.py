"""Bounded negative storage checks; no root, disks, network, or simulations."""
import stat
import types
import unittest
from unittest.mock import patch
from deploy.verify_reference50_data_mount import verify


class DataMountTest(unittest.TestCase):
    def setUp(self):
        self.layout = {'mount_root': '/srv/energybridge-data', 'filesystem_uuid': 'pinned',
            'binds': {'/var/lib/energybridge-current50': '/srv/energybridge-data/collections/current50',
                      '/opt/energybridge-current50': '/srv/energybridge-data/programs/current50'},
            'data_root': '/var/lib/energybridge-current50/collection/example',
            'release_manifest': '/opt/energybridge-current50/example/release/FORMAL_RELEASE.json',
            'release_sha256': 'example'}
        self.device = 42
        self.pepper_size = 32
        self.pepper_mode = stat.S_IFREG | 0o600
        self.mounted = {self.layout['mount_root'], *self.layout['binds']}

    def fake_stat(self, path):
        path = str(path)
        if path.startswith('/dev/'):
            return types.SimpleNamespace(st_mode=stat.S_IFBLK | 0o600, st_rdev=42)
        if path == self.layout['mount_root']:
            return types.SimpleNamespace(st_dev=self.device)
        return types.SimpleNamespace(st_mode=self.pepper_mode, st_size=self.pepper_size)

    def checked(self, *, same=True, exists=True):
        with patch('pathlib.Path.stat', lambda path: self.fake_stat(path)), \
             patch('deploy.verify_reference50_data_mount.mountpoints', return_value=self.mounted), \
             patch('os.path.samefile', return_value=same), \
             patch('pathlib.Path.is_file', return_value=exists), \
             patch('pathlib.Path.read_text', return_value='{"release_sha256":"example"}'):
            return verify(self.layout)

    def test_correct_uuid_and_binds(self):
        self.assertTrue(self.checked()['passed'])

    def test_wrong_device_stops_before_database_use(self):
        self.device = 9
        with self.assertRaisesRegex(RuntimeError, 'wrong UUID'):
            self.checked()

    def test_missing_bind(self):
        self.mounted.remove('/opt/energybridge-current50')
        with self.assertRaisesRegex(RuntimeError, 'mount is absent'):
            self.checked()

    def test_wrong_bind_source(self):
        with self.assertRaisesRegex(RuntimeError, 'wrong directory'):
            self.checked(same=False)

    def test_database_is_never_created_by_guard(self):
        with self.assertRaisesRegex(RuntimeError, 'database is missing'):
            self.checked(exists=False)

    def test_bind_outside_pinned_volume(self):
        self.layout['binds']['/opt/energybridge-current50'] = '/opt/other'
        with self.assertRaisesRegex(RuntimeError, 'outside'):
            self.checked()

    def test_release_binding(self):
        self.layout['release_sha256'] = 'another'
        with self.assertRaisesRegex(RuntimeError, 'release'):
            self.checked()

    def test_invalid_recovery_material(self):
        self.pepper_size = 0
        with self.assertRaisesRegex(RuntimeError, 'recovery material is missing'):
            self.checked()

    def test_recovery_permissions(self):
        self.pepper_mode = stat.S_IFREG | 0o644
        with self.assertRaisesRegex(RuntimeError, 'permissions are too broad'):
            self.checked()


if __name__ == '__main__':
    unittest.main()
