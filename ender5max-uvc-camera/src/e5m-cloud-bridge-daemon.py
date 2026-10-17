#!/usr/share/klippy-env/bin/python
"""F004 cloud camera engine; consumes existing LAN JPEG, never opens USB UVC."""
import argparse
import array
import ctypes as C
import fcntl
import hashlib
import io
import json
import mmap
import os
from pathlib import Path
import signal
import socket
import struct
import subprocess
import threading
import time
import urllib.request
from PIL import Image

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--seconds', type=int, default=180)
parser.add_argument('--fps', type=int, default=5, choices=[1, 2, 3, 5])
parser.add_argument('--no-preview', action='store_true')
parser.add_argument('--parent-pid', type=int, default=0)
args = parser.parse_args()
if not 0 <= args.seconds <= 600:
    parser.error('seconds must be 0 (continuous) or between 1 and 600')
if args.parent_pid:
    assert C.CDLL(None).prctl(1, signal.SIGTERM, 0, 0, 0) == 0, 'Cannot set parent-death signal'
    assert os.getppid() == args.parent_pid, 'Supervisor already exited'
lock = open('/tmp/e5m-cloud-bridge.lock', 'w')
fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
assert hashlib.sha256(Path('/usr/lib/libhardware2.so').read_bytes()).hexdigest() == 'fa839e3f2ec2f8d6ee684e3176492ddc7a865c2bfc0f0fd3944f4820d6c2c846', 'Unsupported hardware library'
assert C.sizeof(C.c_void_p) == 4, 'Requires printer MIPS32 runtime'
assert subprocess.run(['pidof', 'cam_app', 'e5m-cam-app-eoi-probe'], stdout=subprocess.DEVNULL).returncode != 0, 'Another camera producer is active'

class EncParams(C.Structure):
    _fields_ = [('node', C.c_char_p), ('w', C.c_int), ('h', C.c_int), ('stride', C.c_int),
                ('fmt', C.c_uint), ('gop', C.c_int), ('bps', C.c_int)]

lib = C.CDLL('/usr/lib/libhardware2.so')
lib.v4l2_h264_encoder_open.argtypes = [C.POINTER(EncParams)]
lib.v4l2_h264_encoder_open.restype = C.c_void_p
lib.v4l2_h264_encoder_work_separate.argtypes = [C.c_void_p, C.c_void_p, C.c_void_p, C.POINTER(C.c_int)]
lib.v4l2_h264_encoder_work_separate.restype = C.c_void_p
lib.v4l2_h264_encoder_close.argtypes = [C.c_void_p]
enc = None
mem = None
fd = None
server = None
owned_inode = None
online = False
stop = threading.Event()
thread = None
preview = None
pidpath = Path('/tmp/e5m-cloud-bridge.pid')
readypath = Path('/tmp/e5m-cloud-bridge.ready')
sockpath = '/var/run/main_sock'
ylut = [16 + round(x * 219 / 255) for x in range(256)]
clut = [round(128 + (x - 128) * 224 / 255) for x in range(256)]

def on_signal(signum, frame):
    stop.set()

def camera_state(value):
    subprocess.run(['ubus', 'call', 'camera', 'set_state', json.dumps({'type': 0, 'online': value})],
                   check=True, timeout=3, stdout=subprocess.DEVNULL)

def pass_fd():
    while not stop.is_set():
        try:
            client, _ = server.accept()
        except socket.timeout:
            continue
        except OSError:
            break
        with client:
            try:
                client.sendmsg([b'\x01'], [(socket.SOL_SOCKET, socket.SCM_RIGHTS, array.array('i', [fd]))])
                print('MEMFD_CLIENT_CONNECTED', flush=True)
            except OSError as exc:
                print('MEMFD_CLIENT_ERROR', repr(exc), flush=True)

try:
    for sig in [signal.SIGTERM, signal.SIGINT, signal.SIGHUP]:
        signal.signal(sig, on_signal)
    # Only remove a stale Unix socket, never replace a live producer.
    if os.path.lexists(sockpath):
        import stat
        assert stat.S_ISSOCK(os.lstat(sockpath).st_mode), 'Existing main_sock is not a socket'
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as probe:
            probe.settimeout(0.3)
            try:
                probe.connect(sockpath)
            except ConnectionRefusedError:
                os.unlink(sockpath)
            else:
                raise RuntimeError('Existing main_sock producer is active')
    enc = lib.v4l2_h264_encoder_open(C.byref(EncParams(b'/dev/video1', 640, 480, 640,
                                                   int.from_bytes(b'NV12', 'little'), args.fps * 2, 768000)))
    assert enc, 'Cannot open stock H264 encoder'
    fd = os.memfd_create('/var/run/main_memfd', os.MFD_CLOEXEC)
    os.ftruncate(fd, 1048576)
    mem = mmap.mmap(fd, 1048576)
    struct.pack_into('<8I', mem, 0, 32, 640, 480, args.fps, 32, 32, 32, 32)
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(sockpath)
    os.chmod(sockpath, 0o600)
    owned_inode = os.lstat(sockpath).st_ino
    server.listen(4)
    server.settimeout(0.5)
    thread = threading.Thread(target=pass_fd, daemon=True)
    thread.start()
    pidpath.write_text(str(os.getpid()))
    ready = {'pid': os.getpid(), 'fps': args.fps, 'seconds': args.seconds,
             'socket_inode': owned_inode, 'online': False}
    readypath.write_text(json.dumps(ready))
    if not args.no_preview:
        preview = open('/tmp/e5m-bridge-preview.h264', 'wb')
    start = time.monotonic()
    cpu_start = time.process_time()
    count = 0
    last = 524288
    while (args.seconds == 0 or time.monotonic() - start < args.seconds) and not stop.is_set():
        frame_start = time.monotonic()
        with urllib.request.urlopen('http://127.0.0.1:8080/?action=snapshot', timeout=4) as response:
            jpg = response.read(2097152)
        im = Image.open(io.BytesIO(jpg))
        assert im.size == (640, 480), 'LAN JPEG dimensions changed'
        y, u, v = im.convert('YCbCr').split()
        y = y.point(ylut).tobytes()
        u = u.resize((320, 240), Image.BOX).point(clut).tobytes()
        v = v.resize((320, 240), Image.BOX).point(clut).tobytes()
        uv = bytearray(153600)
        uv[0::2] = u
        uv[1::2] = v
        yp = C.create_string_buffer(y)
        up = C.create_string_buffer(bytes(uv))
        size = C.c_int()
        bs = lib.v4l2_h264_encoder_work_separate(enc, yp, up, C.byref(size))
        assert bs and 0 < size.value < 524252, 'H264 encode failed or oversized frame'
        payload = C.string_at(bs, size.value)
        assert payload.startswith(b'\x00\x00\x00\x01'), 'Expected Annex B'
        off = 32 if last == 524288 else 524288
        struct.pack_into('<I', mem, 16, off)
        struct.pack_into('<I', mem, off, len(payload))
        mem[off + 4:off + 4 + len(payload)] = payload
        struct.pack_into('<I', mem, 20, off)
        last = off
        if preview and count < 24:
            preview.write(payload)
            preview.flush()
        count += 1
        if not online:
            camera_state(1)
            online = True
            ready['online'] = True
            readypath.write_text(json.dumps(ready))
            print('BRIDGE_READY', readypath.read_text(), flush=True)
        if count % (args.fps * 10) == 0:
            elapsed = time.monotonic() - start
            print(json.dumps({'frames': count, 'elapsed': round(elapsed, 2),
                              'cpu_core_percent': round(100 * (time.process_time() - cpu_start) / elapsed, 1)}), flush=True)
        stop.wait(max(0, 1 / args.fps - (time.monotonic() - frame_start)))
finally:
    stop.set()
    if 'start' in globals():
        elapsed = time.monotonic() - start
        print('BRIDGE_FINAL', json.dumps({'frames': count, 'elapsed': round(elapsed, 2),
              'cpu_core_percent': round(100 * (time.process_time() - cpu_start) / max(elapsed, .01), 1)}), flush=True)
    if online:
        try:
            camera_state(0)
        except Exception as exc:
            print('OFFLINE_REPORT_ERROR', repr(exc), flush=True)
    if server:
        server.close()
    if thread:
        thread.join(timeout=2)
    if mem:
        mem.close()
    if fd is not None:
        os.close(fd)
    if enc:
        lib.v4l2_h264_encoder_close(enc)
    if preview:
        preview.close()
    if owned_inode is not None and os.path.lexists(sockpath) and os.lstat(sockpath).st_ino == owned_inode:
        os.unlink(sockpath)
    if pidpath.exists() and pidpath.read_text() == str(os.getpid()):
        pidpath.unlink()
        if readypath.exists():
            readypath.unlink()
    print('BRIDGE_STOPPED_LAN_SERVICE_UNCHANGED', flush=True)
