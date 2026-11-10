"""Operator CLI and real temporary files; no application or cloud services."""
import csv
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


BACKEND = Path(__file__).resolve().parents[1]


@pytest.fixture
def conversion(tmp_path):
    raw = tmp_path / 'raw'
    audio = raw / 'Clase con espacios' / '0042.wav'
    audio.parent.mkdir(parents=True)
    audio.write_bytes(b'synthetic-audio')
    source = tmp_path / 'histórico.csv'
    original = ('nombre_archivo,clase,xc_id,recordist\r\n'
                '0042.wav,Clase original,00042,Autor sintético\r\n').encode('utf-8')
    source.write_bytes(original)
    candidate = tmp_path / 'candidato.csv'
    snapshot = tmp_path / 'original.csv'

    def cli(*extra, input_path=None, candidate_path=None, raw_path=None):
        return subprocess.run(
            [sys.executable, '-m', 'scripts.convert_dataset_index',
             '--index', 'metadata', str(input_path or source),
             str(candidate_path or candidate), str(snapshot),
             '--stage', 'raw', '--raw-root', str(raw_path or raw),
             '--processed-root', str(tmp_path / 'processed-absent'), *extra],
            cwd=BACKEND, capture_output=True, text=True, encoding='utf-8',
            env=dict(os.environ, PYTHONUTF8='1', PYTHON_DOTENV_DISABLED='1'), timeout=20)

    return {'cli':cli, 'raw':raw, 'source':source, 'original':original,
            'candidate':candidate, 'snapshot':snapshot, 'root':tmp_path}


def test_operator_previews_native_paths_without_publishing_indices(conversion):
    d = conversion
    result = d['cli']()
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report['apply'] is False
    assert report['indices']['metadata']['rows'] == [{
        'nombre_archivo':'0042.wav', 'clase':'Clase original', 'xc_id':'00042',
        'recordist':'Autor sintético', 'file_path':'Clase con espacios/0042.wav',
        'file_stage':'raw'}]
    assert d['source'].read_bytes() == d['original']
    assert not d['candidate'].exists() and not d['snapshot'].exists()


def test_operator_publishes_a_separate_candidate_and_preserves_the_original(conversion):
    d = conversion
    result = d['cli']('--apply', raw_path=d['raw'].as_posix())
    assert result.returncode == 0, result.stderr
    assert d['source'].read_bytes() == d['snapshot'].read_bytes() == d['original']
    with d['candidate'].open(encoding='utf-8', newline='') as stream:
        row = list(csv.DictReader(stream))[0]
    assert row['file_path'] == 'Clase con espacios/0042.wav'
    assert row['file_stage'] == 'raw'
    assert row['clase'] == 'Clase original' and row['xc_id'] == '00042'
    again = d['cli']('--apply')
    assert again.returncode != 0
    assert d['source'].read_bytes() == d['original']


@pytest.mark.parametrize('spelling', ['relative', 'dot', 'parent', 'duplicate_separator',
                                    'alternate_stream', 'device', 'unc', 'reserved'])
def test_noncanonical_or_nonlocal_destination_is_rejected_before_any_output(conversion, spelling):
    d = conversion
    native = str(d['root'])
    separator = os.sep
    target = {
        'relative':'candidate.csv',
        'dot':native + separator + '.' + separator + 'candidate.csv',
        'parent':native + separator + '..' + separator + 'candidate.csv',
        'duplicate_separator':native + separator*2 + 'candidate.csv',
        'alternate_stream':native + separator + 'candidate.csv:stream',
        'device':'\\\\?\\' + native + separator + 'candidate.csv',
        'unc':'\\\\server\\share\\candidate.csv',
        'reserved':native + separator + 'NUL.csv',
    }[spelling]
    if os.name != 'nt' and spelling in {'device','unc','reserved'}:
        pytest.skip('Windows-only spelling')
    result = d['cli']('--apply', candidate_path=target)
    assert result.returncode != 0
    assert not d['snapshot'].exists()
    assert d['source'].read_bytes() == d['original']


@pytest.mark.skipif(os.name != 'nt', reason='Windows junction filesystem contract')
def test_operator_cannot_publish_through_a_windows_junction(conversion):
    d = conversion
    target = d['root'] / 'outside'
    target.mkdir()
    alias = d['root'] / 'alias'
    subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command',
                    "$ErrorActionPreference='Stop'; New-Item -ItemType Junction "
                    '-Path $env:FAMA_TEST_JUNCTION_PATH -Target $env:FAMA_TEST_JUNCTION_TARGET | Out-Null'],
                   env=dict(os.environ, FAMA_TEST_JUNCTION_PATH=str(alias),
                            FAMA_TEST_JUNCTION_TARGET=str(target)),
                   capture_output=True, check=True, timeout=15)
    result = d['cli']('--apply', candidate_path=alias / 'candidate.csv')
    assert result.returncode != 0
    assert not (target / 'candidate.csv').exists()
    assert not d['snapshot'].exists()
    assert d['source'].read_bytes() == d['original']


@pytest.mark.skipif(os.name != 'nt', reason='Windows junction filesystem contract')
def test_indexed_reference_cannot_traverse_an_internal_junction(conversion):
    d = conversion
    alias = d['raw'] / 'compat'
    subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command',
                    "$ErrorActionPreference='Stop'; New-Item -ItemType Junction "
                    '-Path $env:FAMA_TEST_JUNCTION_PATH -Target $env:FAMA_TEST_JUNCTION_TARGET | Out-Null'],
                   env=dict(os.environ, FAMA_TEST_JUNCTION_PATH=str(alias),
                            FAMA_TEST_JUNCTION_TARGET=str(d['raw'] / 'Clase con espacios')),
                   capture_output=True, check=True, timeout=15)
    source = d['root'] / 'explicit.csv'
    original = b'file_path,file_stage\ncompat/0042.wav,raw\n'
    source.write_bytes(original)
    result = d['cli']('--apply', input_path=source)
    assert result.returncode != 0
    assert not d['candidate'].exists() and not d['snapshot'].exists()
    assert source.read_bytes() == original
