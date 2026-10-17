#!/usr/share/klippy-env/bin/python
"""Start, supervise and stop only the custom F004 cloud bridge."""
import fcntl
import io
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from PIL import Image

SELF = '/usr/data/e5m-cloud-service.py'
ENGINE = '/usr/data/e5m-cloud-bridge-daemon.py'
WRAPPER = '/usr/data/e5m-cloud-camera.sh'
INIT = Path('/etc/init.d/S99e5m_cloud')
PYTHON = '/usr/share/klippy-env/bin/python'
PID = Path('/var/run/e5m-cloud-service.pid')
READY = Path('/tmp/e5m-cloud-bridge.ready')
CHILD_PID = Path('/tmp/e5m-cloud-bridge.pid')
SOCK = Path('/var/run/main_sock')
STOP = threading.Event()
LOG = logging.getLogger('e5m-cloud')


def read_json(path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def start_ticks(pid):
    # comm may contain spaces; fields after its closing parenthesis start at 3.
    return Path('/proc/%d/stat' % pid).read_text().rsplit(')', 1)[1].split()[19]


def process_matches(pid, path, ticks=None):
    try:
        argv = Path('/proc/%d/cmdline' % pid).read_bytes().split(b'\0')
        return path.encode() in argv and (ticks is None or start_ticks(pid) == ticks)
    except (OSError, ValueError, TypeError):
        return False


def manager():
    meta = read_json(PID)
    pid = meta.get('pid', 0)
    return pid if pid and process_matches(pid, SELF, meta.get('start_ticks')) else None


def available():
    rows = dict(line.split(':', 1) for line in Path('/proc/meminfo').read_text().splitlines())
    return int(rows['MemAvailable'].split()[0])


def status():
    pid = manager()
    ready = read_json(READY)
    child = ready.get('pid', 0)
    live = bool(child and process_matches(child, ENGINE))
    print(json.dumps({'enabled': INIT.is_symlink() and os.readlink(str(INIT)) == WRAPPER,
                      'supervisor_pid': pid, 'bridge_pid': child if live else None,
                      'bridge_online': bool(live and ready.get('online')),
                      'width': 640, 'height': 480, 'fps': 5,
                      'available_kib': available()}, sort_keys=True))
    return 0 if pid else 1


def start():
    if not manager():
        with open('/tmp/e5m-cloud-start.log', 'wb') as log:
            subprocess.Popen([PYTHON, '-u', SELF, 'run'], stdin=subprocess.DEVNULL,
                             stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        for _ in range(30):
            if manager():
                break
            time.sleep(.1)
    return status()


def stop():
    pid = manager()
    if pid:
        os.kill(pid, signal.SIGTERM)
        for _ in range(150):
            if not process_matches(pid, SELF):
                break
            time.sleep(.1)
        else:
            print('Supervisor did not stop; inspect /tmp/e5m-cloud.log')
            return 1
    print('Cloud supervisor stopped; LAN camera unchanged')
    return 0


def source_ready():
    if available() < 80 * 1024:
        return 'waiting for 80 MiB available memory'
    for name in ('webrtc', 'device_manager'):
        if subprocess.run(['pidof', name], stdout=subprocess.DEVNULL).returncode:
            return 'waiting for stock cloud service ' + name
    if subprocess.run(['pidof', 'cam_app', 'e5m-cam-app-eoi-probe'], stdout=subprocess.DEVNULL).returncode == 0:
        return 'waiting for other camera producer to exit'
    try:
        with urllib.request.urlopen('http://127.0.0.1:8080/?action=snapshot', timeout=3) as r:
            jpg = r.read(2097152)
        im = Image.open(io.BytesIO(jpg))
        im.load()
        if im.size != (640, 480):
            return 'waiting for 640x480 LAN JPEG'
    except Exception as exc:
        return 'waiting for LAN JPEG: ' + type(exc).__name__
    return None


def cleanup_child(child):
    if child.poll() is None:
        child.terminate()
        try:
            child.wait(timeout=5)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait(timeout=3)
    # A killed child cannot run finally. Touch only ownership metadata from it.
    ready = read_json(READY)
    if ready.get('pid') == child.pid:
        try:
            owned_socket = SOCK.is_socket() and SOCK.stat().st_ino == ready.get('socket_inode')
            if not os.path.lexists(str(SOCK)) or owned_socket:
                subprocess.run(['ubus', 'call', 'camera', 'set_state', '{"type":0,"online":0}'],
                               timeout=3, stdout=subprocess.DEVNULL)
                if owned_socket:
                    SOCK.unlink()
            READY.unlink()
        except OSError:
            LOG.exception('Could not remove owned stale socket')
    try:
        if CHILD_PID.read_text() == str(child.pid):
            CHILD_PID.unlink()
    except OSError:
        pass


def run():
    lock = open('/var/run/e5m-cloud-service.lock', 'w')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return 0
    handler = RotatingFileHandler('/tmp/e5m-cloud.log', maxBytes=131072, backupCount=1)
    handler.setFormatter(logging.Formatter('%(asctime)s %(message)s'))
    LOG.addHandler(handler)
    LOG.setLevel(logging.INFO)
    me = {'pid': os.getpid(), 'start_ticks': start_ticks(os.getpid())}
    PID.write_text(json.dumps(me))
    for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(sig, lambda signum, frame: STOP.set())
    child = None
    reader = None
    last_output = [time.monotonic()]

    def drain(pipe):
        for line in iter(lambda: pipe.readline(4096), ''):
            last_output[0] = time.monotonic()
            LOG.info('bridge %s', line.rstrip())

    LOG.info('Supervisor started; 640x480 5fps; LAN service is independent')
    waiting = None
    try:
        while not STOP.is_set():
            if child is None:
                reason = source_ready()
                if reason:
                    if reason != waiting:
                        LOG.info(reason)
                        waiting = reason
                    STOP.wait(5)
                    continue
                waiting = None
                last_output[0] = time.monotonic()
                child = subprocess.Popen([PYTHON, '-u', ENGINE, '--seconds', '0', '--fps', '5',
                                          '--no-preview', '--parent-pid', str(os.getpid())],
                                         stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                         stderr=subprocess.STDOUT, universal_newlines=True,
                                         bufsize=1, start_new_session=True)
                reader = threading.Thread(target=drain, args=(child.stdout,), daemon=True)
                reader.start()
                LOG.info('Bridge started pid=%d', child.pid)
            reason = None
            if child.poll() is not None:
                reason = 'bridge exited code=%s' % child.returncode
            elif available() < 60 * 1024:
                reason = 'available memory below 60 MiB'
            elif time.monotonic() - last_output[0] > 40:
                reason = 'no bridge output for 40 seconds'
            if reason:
                LOG.warning('%s; stopping child and retrying', reason)
                cleanup_child(child)
                if reader:
                    reader.join(timeout=2)
                child.stdout.close()
                child = None
                STOP.wait(10)
            else:
                STOP.wait(2)
    finally:
        if child is not None:
            cleanup_child(child)
            if reader:
                reader.join(timeout=2)
            child.stdout.close()
        if read_json(PID) == me:
            PID.unlink()
        LOG.info('Supervisor stopped; LAN service unchanged')
    return 0


def main():
    action = sys.argv[1] if len(sys.argv) == 2 else 'status'
    if action == 'run':
        return run()
    if action == 'start':
        return start()
    if action == 'stop':
        return stop()
    if action == 'status':
        return status()
    if action == 'restart':
        return start() if stop() == 0 else 1
    if action == 'enable':
        if os.path.lexists(str(INIT)):
            assert INIT.is_symlink() and os.readlink(str(INIT)) == WRAPPER, 'Unrelated init entry exists'
        else:
            INIT.symlink_to(WRAPPER)
        return start()
    if action == 'disable':
        if os.path.lexists(str(INIT)):
            assert INIT.is_symlink() and os.readlink(str(INIT)) == WRAPPER, 'Unrelated init entry exists'
            INIT.unlink()
        return stop()
    print('Usage: %s start|stop|restart|status|enable|disable' % WRAPPER)
    return 2


if __name__ == '__main__':
    sys.exit(main())
