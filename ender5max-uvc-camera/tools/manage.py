#!/usr/share/klippy-env/bin/python
"""Conservative installer. Installation never starts services or reboots."""
import argparse
from contextlib import contextmanager
import hashlib
import importlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import struct
import subprocess
import sys
import tempfile

PROJECT = 'ender5max-uvc-camera'
REPO = Path(__file__).resolve().parents[1]
STATE = '/usr/data/e5m-camera-install.json'
SPEC = {
    'lan': {'files': ['e5m-uvc-camera.sh'], 'hook': '/etc/init.d/S99e5m_uvc',
            'entry': 'e5m-uvc-camera.sh'},
    'cloud': {'files': ['e5m-cloud-bridge-daemon.py', 'e5m-cloud-service.py',
                        'e5m-cloud-camera.sh'], 'hook': '/etc/init.d/S99e5m_cloud',
              'entry': 'e5m-cloud-camera.sh'},
}


class InstallError(RuntimeError):
    pass


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def present(path):
    return os.path.lexists(str(path))


def atomic_json(path, value):
    name = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=str(path.parent),
                                         prefix='.e5m-install-', delete=False) as f:
            name = f.name
            json.dump(value, f, indent=2)
            f.write('\n')
            f.flush()
            os.fsync(f.fileno())
        os.chmod(name, 0o600)
        os.replace(name, str(path))
    finally:
        if name and os.path.exists(name):
            os.unlink(name)


def load_package(repo):
    package = json.loads((repo / 'package.json').read_text(encoding='utf-8'))
    expected = {name for component in SPEC.values() for name in component['files']}
    if package.get('project') != PROJECT or set(package.get('files', {})) != expected:
        raise InstallError('Invalid package manifest')
    for name, checksum in package['files'].items():
        if not isinstance(checksum, str) or not re.fullmatch('[0-9a-f]{64}', checksum):
            raise InstallError('Invalid source checksum: ' + name)
        source = repo / 'src' / name
        if source.is_symlink() or not source.is_file() or digest(source) != checksum:
            raise InstallError('Source checksum mismatch: ' + name)
    return package


def preflight(mode, package):
    errors = []
    required = ['/usr/data', '/etc/init.d', '/usr/bin/mjpg_streamer',
                '/usr/lib/mjpg-streamer/input_uvc.so', '/usr/lib/mjpg-streamer/output_http.so']
    for path in required:
        if not Path(path).exists():
            errors.append('Missing ' + path)
    for name in ('nohup', 'pidof', 'netstat', 'grep', 'sh'):
        if shutil.which(name) is None:
            errors.append('Missing command ' + name)
    if mode == 'both':
        if not platform.machine().lower().startswith('mips') or struct.calcsize('P') != 4 or sys.byteorder != 'little':
            errors.append('Cloud bridge requires MIPS32 little-endian printer Python')
        library = Path('/usr/lib/libhardware2.so')
        if not library.is_file() or digest(library) != package['hardware_library_sha256']:
            errors.append('Unsupported libhardware2.so; no firmware or library will be replaced')
        for name in ('PIL.Image', 'fcntl'):
            try:
                importlib.import_module(name)
            except ImportError:
                errors.append('Missing Python module ' + name)
        for name in ('ubus', 'webrtc', 'device_manager'):
            if shutil.which(name) is None:
                errors.append('Missing command ' + name)
        for name in ('memfd_create', 'MFD_CLOEXEC'):
            if not hasattr(os, name):
                errors.append('Printer Python lacks os.' + name)
    for error in errors:
        print('FAIL:', error)
    if errors:
        raise InstallError('Preflight failed; no files changed')
    print('Dependencies match checks; only F004 firmware 1.3.0.14 has been tested.')


class PrinterRunner:
    def running(self, component):
        try:
            if component == 'lan':
                pid = int(Path('/var/run/e5m-uvc.pid').read_text())
                expected = b'/usr/data/e5m-uvc-camera.sh'
            else:
                pid = json.loads(Path('/var/run/e5m-cloud-service.pid').read_text())['pid']
                expected = b'/usr/data/e5m-cloud-service.py'
            argv = Path('/proc/%d/cmdline' % pid).read_bytes().split(b'\0')
            return expected in argv
        except (OSError, ValueError, KeyError, TypeError):
            return False

    def stop(self, component):
        if not self.running(component):
            return
        entry = '/usr/data/' + SPEC[component]['entry']
        subprocess.run(['/bin/sh', entry, 'stop'], check=True, timeout=20)
        # The original LAN wrapper sends TERM and returns before its child exits.
        import time
        for _ in range(100):
            if not self.running(component):
                return
            time.sleep(.1)
        raise InstallError('Service did not stop; files preserved: ' + component)


class Manager:
    """The root parameter is a Python test seam, never a CLI option."""
    def __init__(self, root, repo, runner=None):
        self.root = Path(root).resolve()
        self.repo = Path(repo)
        self.package = load_package(self.repo)
        self.runner = runner

    def path(self, absolute):
        return self.root / absolute.lstrip('/')

    def load_state(self):
        path = self.path(STATE)
        if not present(path):
            return {'project': PROJECT, 'schema': 1, 'components': {}}
        if path.is_symlink():
            raise InstallError('Install manifest must not be a symlink')
        value = json.loads(path.read_text(encoding='utf-8'))
        if value.get('project') != PROJECT or value.get('schema') != 1:
            raise InstallError('Unrecognized install manifest; refusing to replace it')
        components = value.get('components')
        if not isinstance(components, dict) or not set(components).issubset(SPEC):
            raise InstallError('Invalid component manifest')
        for component, record in components.items():
            if not isinstance(record, dict) or set(record) != {'files', 'hook_owned'}:
                raise InstallError('Invalid component record')
            if type(record['hook_owned']) is not bool or set(record['files']) != set(SPEC[component]['files']):
                raise InstallError('Invalid ownership manifest')
            for item in record['files'].values():
                if not isinstance(item, dict) or set(item) != {'owned', 'sha256'}:
                    raise InstallError('Invalid file record')
                if type(item['owned']) is not bool or not re.fullmatch('[0-9a-f]{64}', str(item['sha256'])):
                    raise InstallError('Invalid ownership or checksum')
        return value

    def validate_destination(self, name, checksum):
        path = self.path('/usr/data/' + name)
        if present(path) and (path.is_symlink() or not path.is_file() or digest(path) != checksum):
            raise InstallError('Existing different file; nothing overwritten: ' + str(path))
        if path.exists() and name.endswith('.sh') and os.name == 'posix' and not path.stat().st_mode & 0o111:
            raise InstallError('Existing shell entry is not executable: ' + str(path))

    def validate_hook(self, component):
        spec = SPEC[component]
        path = self.path(spec['hook'])
        target = '/usr/data/' + spec['entry']
        if present(path) and (not path.is_symlink() or os.readlink(str(path)) != target):
            raise InstallError('Existing different init entry; nothing overwritten: ' + str(path))

    def create_file(self, name, checksum):
        """Hard-link a complete same-filesystem staging file; never replace a target."""
        dest = self.path('/usr/data/' + name)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=str(dest.parent), prefix='.e5m-src-', delete=False) as f:
                temporary = Path(f.name)
                f.write((self.repo / 'src' / name).read_bytes())
                f.flush()
                os.fsync(f.fileno())
            os.chmod(str(temporary), 0o755 if name.endswith('.sh') else 0o644)
            if digest(temporary) != checksum:
                raise InstallError('Staging checksum mismatch')
            os.link(str(temporary), str(dest))
        finally:
            if temporary and temporary.exists():
                temporary.unlink()

    def create_hook(self, component):
        spec = SPEC[component]
        self.path(spec['hook']).symlink_to('/usr/data/' + spec['entry'])

    def install(self, mode):
        chosen = ['lan'] if mode == 'lan' else ['lan', 'cloud']
        state = self.load_state()
        # Validate the entire plan before touching any destination.
        for component in chosen:
            for name in SPEC[component]['files']:
                self.validate_destination(name, self.package['files'][name])
            self.validate_hook(component)
        created = []
        try:
            for component in chosen:
                previous = state['components'].get(component, {})
                record = {'files': {}, 'hook_owned': previous.get('hook_owned', False)}
                for name in SPEC[component]['files']:
                    checksum = self.package['files'][name]
                    owned = previous.get('files', {}).get(name, {}).get('owned', False)
                    if not present(self.path('/usr/data/' + name)):
                        self.create_file(name, checksum)
                        created.append(('file', name, checksum))
                        owned = True
                    record['files'][name] = {'owned': owned, 'sha256': checksum}
                if not present(self.path(SPEC[component]['hook'])):
                    self.create_hook(component)
                    created.append(('hook', component, None))
                    record['hook_owned'] = True
                state['components'][component] = record
            atomic_json(self.path(STATE), state)
        except Exception:
            # No services were started, so rollback touches only newly created paths.
            for kind, name, checksum in reversed(created):
                if kind == 'file':
                    path = self.path('/usr/data/' + name)
                    if path.is_file() and not path.is_symlink() and digest(path) == checksum:
                        path.unlink()
                else:
                    path = self.path(SPEC[name]['hook'])
                    if path.is_symlink() and os.readlink(str(path)) == '/usr/data/' + SPEC[name]['entry']:
                        path.unlink()
            raise
        print('Installed mode=%s. No services restarted; start them explicitly or reboot when idle.' % mode)

    def uninstall(self, mode):
        state = self.load_state()
        chosen = ['cloud', 'lan'] if mode == 'both' else [mode]
        cloud_hook = self.path(SPEC['cloud']['hook'])
        if mode == 'lan' and ('cloud' in state['components'] or present(cloud_hook)):
            raise InstallError('Cloud depends on LAN; uninstall cloud first or select --mode both')
        # Do not execute modified installed code or remove changed paths.
        for component in chosen:
            record = state['components'].get(component)
            if not record:
                continue
            for name, item in record['files'].items():
                self.validate_destination(name, item['sha256'])
            self.validate_hook(component)
        for component in chosen:
            record = state['components'].get(component)
            if not record:
                continue
            owns_files = any(item['owned'] for item in record['files'].values())
            if owns_files:
                if self.runner is None:
                    raise InstallError('A service runner is required for uninstall')
                self.runner.stop(component)
            hook = self.path(SPEC[component]['hook'])
            if record['hook_owned'] and present(hook):
                hook.unlink()
            for name, item in record['files'].items():
                path = self.path('/usr/data/' + name)
                if item['owned'] and present(path):
                    path.unlink()
            del state['components'][component]
            # Save after each component, so an interruption can be resumed safely.
            atomic_json(self.path(STATE), state)
        if not state['components'] and present(self.path(STATE)):
            self.path(STATE).unlink()
        print('Uninstalled owned %s components; pre-existing files and services were retained.' % mode)


@contextmanager
def install_lock():
    import fcntl
    with open('/var/run/e5m-camera-install.lock', 'w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['check', 'install', 'uninstall'], nargs='?', default='check')
    parser.add_argument('--mode', choices=['lan', 'cloud', 'both'], default=None)
    args = parser.parse_args()
    mode = args.mode or ('cloud' if args.action == 'uninstall' else 'both')
    if mode == 'cloud' and args.action != 'uninstall':
        parser.error('For installation choose lan or both; cloud requires LAN')
    try:
        package = load_package(REPO)
        if args.action == 'check':
            preflight(mode, package)
            return 0
        if not hasattr(os, 'geteuid') or os.geteuid() != 0:
            raise InstallError('Run on the printer as root')
        with install_lock():
            manager = Manager(Path('/'), REPO, PrinterRunner())
            if args.action == 'install':
                preflight(mode, package)
                manager.install(mode)
            else:
                manager.uninstall(mode)
        return 0
    except (InstallError, OSError, ValueError, subprocess.SubprocessError) as exc:
        print('ERROR:', exc, file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
