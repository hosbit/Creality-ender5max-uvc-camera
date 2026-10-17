"""Filesystem integration tests: no printer services or device nodes are opened."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('installer', REPO / 'tools' / 'manage.py')
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class FakeRunner:
    def __init__(self):
        self.stopped = []

    def stop(self, component):
        self.stopped.append(component)


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='e5m-installer-test-',
                                                dir=os.environ.get('E5M_TEST_TMP'))
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        (self.root / 'usr/data').mkdir(parents=True)
        (self.root / 'etc/init.d').mkdir(parents=True)
        self.runner = FakeRunner()
        self.manager = installer.Manager(self.root, REPO, self.runner)

    def dest(self, name):
        return self.root / 'usr/data' / name

    def hook(self, component):
        return self.manager.path(installer.SPEC[component]['hook'])

    def state(self):
        return self.manager.load_state()

    def preexisting_lan(self):
        dest = self.dest('e5m-uvc-camera.sh')
        shutil.copyfile(REPO / 'src' / dest.name, dest)
        os.chmod(str(dest), 0o755)
        self.hook('lan').symlink_to('/usr/data/e5m-uvc-camera.sh')

    def test_fresh_both_install_and_remove_cloud_keeps_lan(self):
        self.manager.install('both')
        self.assertTrue(self.state()['components']['lan']['files']['e5m-uvc-camera.sh']['owned'])
        self.assertEqual(os.readlink(str(self.hook('cloud'))), '/usr/data/e5m-cloud-camera.sh')
        self.manager.uninstall('cloud')
        self.assertEqual(self.runner.stopped, ['cloud'])
        self.assertTrue(self.dest('e5m-uvc-camera.sh').exists())
        self.assertTrue(self.hook('lan').is_symlink())
        self.assertFalse(installer.present(self.hook('cloud')))

    def test_repeat_install_does_not_rewrite_runtime(self):
        self.manager.install('both')
        path = self.dest('e5m-cloud-service.py')
        before = (path.read_bytes(), path.stat().st_mtime_ns)
        self.manager.install('both')
        self.assertEqual(before, (path.read_bytes(), path.stat().st_mtime_ns))
        self.assertEqual(self.runner.stopped, [])

    def test_preexisting_lan_remains_after_full_uninstall(self):
        self.preexisting_lan()
        before = self.dest('e5m-uvc-camera.sh').read_bytes()
        self.manager.install('both')
        self.assertFalse(self.state()['components']['lan']['hook_owned'])
        self.manager.uninstall('both')
        self.assertEqual(self.runner.stopped, ['cloud'])
        self.assertEqual(self.dest('e5m-uvc-camera.sh').read_bytes(), before)
        self.assertTrue(self.hook('lan').is_symlink())

    def test_lan_can_be_extended_with_cloud(self):
        self.manager.install('lan')
        self.manager.install('both')
        self.assertEqual(set(self.state()['components']), {'lan', 'cloud'})
        self.manager.uninstall('both')
        self.assertEqual(self.runner.stopped, ['cloud', 'lan'])
        self.assertFalse(self.dest('e5m-uvc-camera.sh').exists())
        self.assertFalse(self.manager.path(installer.STATE).exists())

    def test_file_conflict_causes_no_partial_install(self):
        conflict = self.dest('e5m-cloud-service.py')
        conflict.write_text('unrelated')
        with self.assertRaises(installer.InstallError):
            self.manager.install('both')
        self.assertEqual(conflict.read_text(), 'unrelated')
        self.assertFalse(self.dest('e5m-uvc-camera.sh').exists())
        self.assertFalse(installer.present(self.hook('lan')))

    def test_hook_conflict_causes_no_partial_install(self):
        self.hook('cloud').symlink_to('/some/other/service')
        with self.assertRaises(installer.InstallError):
            self.manager.install('both')
        self.assertFalse(self.dest('e5m-uvc-camera.sh').exists())
        self.assertEqual(os.readlink(str(self.hook('cloud'))), '/some/other/service')

    def test_mid_install_failure_rolls_back_only_new_paths(self):
        self.preexisting_lan()
        original_create = self.manager.create_hook
        def fail(component):
            if component == 'cloud':
                raise OSError('simulated full filesystem')
            original_create(component)
        self.manager.create_hook = fail
        with self.assertRaises(OSError):
            self.manager.install('both')
        self.assertTrue(self.dest('e5m-uvc-camera.sh').exists())
        self.assertTrue(self.hook('lan').is_symlink())
        self.assertFalse(self.dest('e5m-cloud-service.py').exists())
        self.assertFalse(self.manager.path(installer.STATE).exists())

    def test_modified_installed_file_is_not_executed_or_deleted(self):
        self.manager.install('both')
        path = self.dest('e5m-cloud-camera.sh')
        path.write_text('modified after install')
        with self.assertRaises(installer.InstallError):
            self.manager.uninstall('cloud')
        self.assertEqual(self.runner.stopped, [])
        self.assertEqual(path.read_text(), 'modified after install')
        self.assertTrue(self.hook('cloud').is_symlink())

    def test_lan_only_removal_refuses_cloud_dependency(self):
        self.manager.install('both')
        with self.assertRaises(installer.InstallError):
            self.manager.uninstall('lan')
        self.assertEqual(self.runner.stopped, [])

    def test_manifest_cannot_inject_deletion_paths(self):
        self.manager.install('both')
        state = self.state()
        state['components']['cloud']['files']['../../unrelated'] = {'owned': True, 'sha256': '0'*64}
        self.manager.path(installer.STATE).write_text(json.dumps(state))
        with self.assertRaises(installer.InstallError):
            self.manager.uninstall('both')
        self.assertEqual(self.runner.stopped, [])
        self.assertTrue(self.dest('e5m-cloud-service.py').exists())

    def test_preexisting_matching_services_are_retained(self):
        self.manager.install('both')
        # Represents scripts and hooks installed before this installer existed.
        self.manager.path(installer.STATE).unlink()
        self.manager.install('both')
        self.manager.uninstall('both')
        self.assertEqual(self.runner.stopped, [])
        self.assertTrue(self.dest('e5m-cloud-service.py').exists())
        self.assertTrue(self.hook('cloud').is_symlink())

    def test_corrupt_package_is_rejected(self):
        copied = self.root / 'package'
        shutil.copytree(REPO / 'src', copied / 'src')
        shutil.copyfile(REPO / 'package.json', copied / 'package.json')
        (copied / 'src/e5m-cloud-service.py').write_text('tampered')
        with self.assertRaises(installer.InstallError):
            installer.Manager(self.root, copied, self.runner)


if __name__ == '__main__':
    unittest.main()
