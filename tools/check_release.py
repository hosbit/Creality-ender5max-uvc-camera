#!/usr/bin/env python3
"""Static release checks; never connect to a printer or execute runtime code."""
import argparse
import ast
import hashlib
import importlib.util
import re
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
SKIP_DIRS = {'.git', '__pycache__', '.pytest_cache', '.test-tmp', 'work', 'build', 'dist'}
BLOCKED_SUFFIXES = {'.bin', '.so', '.h264', '.nv12', '.pem', '.key', '.log', '.zip', '.png', '.jpg', '.jpeg'}
PRIVATE_PATTERNS = [r'192\.168\.\d+\.\d+', r'C:[/\\]Users[/\\]',
                    r'https://chatgpt\.com/c/', r'BEGIN [A-Z ]*PRIVATE KEY',
                    r'creality_\d{4}', r'(?i)password\s*=\s*[\x22\x27][^\x22\x27]+[\x22\x27]']


def release_files():
    for path in sorted(ROOT.rglob('*')):
        relative = path.relative_to(ROOT)
        if not path.is_file() or any(part in SKIP_DIRS for part in relative.parts):
            continue
        if path.suffix in ('.pyc', '.pyo') or path.name == 'SHA256SUMS':
            continue
        yield path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--shell', help='Path to sh; defaults to sh on PATH')
    parser.add_argument('--write-checksums', action='store_true')
    args = parser.parse_args()
    errors = []
    files = list(release_files())
    shell = args.shell or shutil.which('sh')
    if not shell:
        errors.append('No sh found; provide --shell to perform shell syntax checks')
    spec = importlib.util.spec_from_file_location('installer', ROOT / 'tools/manage.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    try:
        module.load_package(ROOT)
    except (OSError, ValueError, module.InstallError) as exc:
        errors.append(str(exc))
    for path in files:
        relative = path.relative_to(ROOT).as_posix()
        if path.is_symlink() or path.suffix.lower() in BLOCKED_SUFFIXES:
            errors.append('Unexpected release file: ' + relative)
            continue
        try:
            raw = path.read_bytes()
            text = raw.decode('utf-8')
        except (UnicodeError, OSError):
            errors.append('Non-text release file: ' + relative)
            continue
        if b'\r' in raw or raw.startswith(b'\xef\xbb\xbf'):
            errors.append('Use UTF-8 without BOM and LF: ' + relative)
        scan_text = text
        if relative == 'docs/pc-lan-install.md':
            # Intentionally published factory-login reference, not a general secrets exception.
            scan_text = re.sub(r'(?m)^\| SSH 密码（本台已验证） \| `creality_[0-9]{4}` \|$', '', scan_text)
        for pattern in PRIVATE_PATTERNS:
            if re.search(pattern, scan_text):
                errors.append('Potential private data: ' + relative)
                break
        if path.suffix == '.py':
            try:
                ast.parse(text, filename=relative, feature_version=(3, 8))
            except SyntaxError as exc:
                errors.append('Python 3.8 syntax: ' + str(exc))
        if path.suffix == '.sh' and shell:
            result = subprocess.run([shell, '-n', str(path)], capture_output=True, text=True)
            if result.returncode:
                errors.append('Shell syntax: ' + relative + ': ' + result.stderr.strip())
        if path.suffix == '.md':
            for target in re.findall(r'\]\(([^)]+)\)', text):
                target = target.split('#', 1)[0]
                if not target or re.match(r'[a-z]+://', target):
                    continue
                if not (path.parent / target).is_file():
                    errors.append('Broken document link in ' + relative + ': ' + target)
    if errors:
        for error in errors:
            print('FAIL:', error)
        return 1
    if args.write_checksums:
        rows = [hashlib.sha256(p.read_bytes()).hexdigest() + '  ' + p.relative_to(ROOT).as_posix()
                for p in files]
        (ROOT / 'SHA256SUMS').write_bytes(('\n'.join(rows) + '\n').encode('utf-8'))
    print('PASS: %d release files; runtime hashes, Python 3.8 syntax, shell syntax, privacy patterns and links' % len(files))
    print('Pattern scans supplement manual review; they do not guarantee absence of all secrets.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
