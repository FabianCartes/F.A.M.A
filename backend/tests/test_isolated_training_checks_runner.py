"""Exercise the runner CLI without importing the application in this process."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


BACKEND = Path(__file__).resolve().parents[1]


def run_runner(backend, *arguments):
    return subprocess.run(
        [sys.executable, *arguments[:1], str(backend / 'tests/run_isolated_training_checks.py'), *arguments[1:]]
        if arguments and arguments[0] == '-O'
        else [sys.executable, str(backend / 'tests/run_isolated_training_checks.py'), *arguments],
        cwd=backend, capture_output=True, text=True, timeout=90,
        env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1',
             'PYTHON_DOTENV_DISABLED': '1', 'DATABASE_URL': 'sqlite://',
             'CUDA_VISIBLE_DEVICES': '', 'PYTEST_DISABLE_PLUGIN_AUTOLOAD': '1'},
    )


def test_runner_is_self_contained_and_preserves_current_sources():
    completed = run_runner(BACKEND, '--ambient-import-probe')
    assert completed.returncode == 0, completed.stdout + completed.stderr
    summary, = [json.loads(line.removeprefix('CHECK_SUMMARY '))
                for line in completed.stdout.splitlines() if line.startswith('CHECK_SUMMARY ')]
    assert summary['ambient_import_probe'] == 'passed'
    assert summary['private_scratch_cleanup'] is True
    assert summary['protected_paths_unchanged'] is True
    assert summary['sqlite_memory_connection_count'] == 0


@pytest.mark.parametrize(('paths', 'optimized', 'error'), [
    (['backend/tests/missing.py'], False, 'Missing protected paths'),
    (['../outside.txt'], False, 'Protected path escapes checkout'),
    ([], True, 'Optimized Python is unsupported'),
])
def test_runner_rejects_invalid_inventory_before_execution(tmp_path, paths, optimized, error):
    backend = tmp_path / 'candidate/backend'
    tests = backend / 'tests'
    tests.mkdir(parents=True)
    shutil.copy2(BACKEND / 'tests/run_isolated_training_checks.py', tests)
    guard = BACKEND / 'tests/training_host_guard.py'
    if guard.exists():
        shutil.copy2(guard, tests)
    receipts = backend.parent / 'docs/receipts'
    receipts.mkdir(parents=True)
    inventory = receipts / 'training-checks-inventory.json'
    inventory.write_text(json.dumps({'paths': paths}))
    before = inventory.read_bytes()
    completed = run_runner(backend, *(['-O'] if optimized else []))
    assert completed.returncode != 0
    assert error in completed.stderr
    assert inventory.read_bytes() == before
    assert not list(backend.glob('.training-consumer-suite-*'))
