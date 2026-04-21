#!/usr/bin/env python3
"""Verify that the bundled Python compatibility layer is complete.

This intentionally uses only the Python standard library so it can run before
Rust dependencies are downloaded and before a Python virtualenv is created.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import py_compile
import subprocess
import sys
from typing import Iterable


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def iter_py_files(root: Path) -> Iterable[Path]:
    for folder in ('diffgr', 'scripts', 'tests'):
        base = root / 'compat' / 'python' / folder
        if base.exists():
            yield from sorted(base.glob('*.py'))


def fail(message: str) -> None:
    print(f'[FAIL] {message}', file=sys.stderr)
    raise SystemExit(1)


def ok(message: str, emit: bool = True) -> None:
    if emit:
        print(f'[OK] {message}')


def run_smoke(root: Path, emit: bool = True) -> None:
    pyroot = root / 'compat' / 'python'
    env = os.environ.copy()
    env['PYTHONPATH'] = str(pyroot) + (os.pathsep + env['PYTHONPATH'] if env.get('PYTHONPATH') else '')
    sample = root / 'examples' / 'multi_file.diffgr.json'
    commands = [
        [sys.executable, str(pyroot / 'scripts' / 'summarize_diffgr.py'), '--input', str(sample), '--json'],
        [sys.executable, str(pyroot / 'scripts' / 'extract_diffgr_state.py'), '--input', str(sample)],
        [sys.executable, str(pyroot / 'scripts' / 'check_virtual_pr_coverage.py'), '--input', str(sample), '--json'],
    ]
    for cmd in commands:
        proc = subprocess.run(cmd, cwd=str(root), env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        # coverage checker may return 2 for coverage problems, matching the original Python behavior.
        allowed = {0, 2} if cmd[1].endswith('check_virtual_pr_coverage.py') else {0}
        if proc.returncode not in allowed:
            print(proc.stdout)
            print(proc.stderr, file=sys.stderr)
            fail(f'smoke command failed: {cmd!r} -> {proc.returncode}')
    ok('compat Python smoke commands ran', emit)


def run_pytest(root: Path, emit: bool = True) -> None:
    pyroot = root / 'compat' / 'python'
    env = os.environ.copy()
    env['PYTHONPATH'] = str(pyroot) + (os.pathsep + env['PYTHONPATH'] if env.get('PYTHONPATH') else '')
    cmd = [sys.executable, '-m', 'pytest', str(pyroot / 'tests')]
    proc = subprocess.run(cmd, cwd=str(pyroot), env=env)
    if proc.returncode != 0:
        fail(f'pytest failed with exit code {proc.returncode}')
    ok('compat Python pytest suite passed', emit)


def main() -> int:
    parser = argparse.ArgumentParser(description='Verify DiffGR Python compatibility coverage.')
    parser.add_argument('--root', default=str(Path(__file__).resolve().parents[1]), help='project root')
    parser.add_argument('--compile', action='store_true', help='py_compile all bundled Python sources')
    parser.add_argument('--smoke', action='store_true', help='run small compatibility smoke commands')
    parser.add_argument('--pytest', action='store_true', help='run the bundled original Python pytest suite')
    parser.add_argument('--json', action='store_true', help='emit machine-readable result')
    args = parser.parse_args()

    root = Path(args.root).resolve()
    audit_path = root / 'COMPLETE_PYTHON_SOURCE_AUDIT.json'
    manifest_path = root / 'PYTHON_PARITY_MANIFEST.json'
    if not audit_path.exists():
        fail(f'missing {audit_path}')
    if not manifest_path.exists():
        fail(f'missing {manifest_path}')

    audit = json.loads(audit_path.read_text(encoding='utf-8'))
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))

    errors: list[str] = []
    entries = audit.get('entries', [])
    for entry in entries:
        path = root / entry['compatPath']
        if not path.exists():
            errors.append(f'missing compat source: {entry["compatPath"]}')
            continue
        actual = sha256_file(path)
        if actual != entry['sha256']:
            errors.append(f'sha256 mismatch: {entry["compatPath"]}')

    scripts = manifest.get('entries', [])
    if manifest.get('scriptCount') != len(scripts):
        errors.append('PYTHON_PARITY_MANIFEST scriptCount does not match entries length')
    for item in scripts:
        stem = item['stem']
        checks = [
            root / 'compat' / 'python' / 'scripts' / f'{stem}.py',
            root / 'scripts' / f'{stem}.ps1',
            root / 'scripts' / f'{stem}.sh',
        ]
        for path in checks:
            if not path.exists():
                errors.append(f'missing wrapper/source for {stem}: {path.relative_to(root)}')

    if errors:
        for e in errors:
            print(f'[FAIL] {e}', file=sys.stderr)
        return 1

    if args.compile:
        compiled = 0
        for path in iter_py_files(root):
            py_compile.compile(str(path), doraise=True)
            compiled += 1
        ok(f'py_compile passed for {compiled} Python files', not args.json)

    if args.smoke:
        run_smoke(root, not args.json)

    if args.pytest:
        run_pytest(root, not args.json)

    result = {
        'ok': True,
        'sourceFilesVerified': len(entries),
        'pythonScriptsVerified': len(scripts),
        'excludedCacheFiles': audit.get('excludedCacheFileCount', 0),
        'compiled': bool(args.compile),
        'smoke': bool(args.smoke),
        'pytest': bool(args.pytest),
    }
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        ok(f'{len(entries)} byte-for-byte Python source/support files verified')
        ok(f'{len(scripts)} Python script wrappers verified')
        if audit.get('excludedCacheFileCount'):
            ok(f'excluded {audit["excludedCacheFileCount"]} __pycache__ files; these are rebuildable caches, not source functionality')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
