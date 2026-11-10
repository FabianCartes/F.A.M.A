"""Operator CLI and restart contract for persistent, environment-bound files."""
import json
import os
import subprocess
import sys
import shutil
import socket

import pytest
from pathlib import Path

from app.configuration import InstallationStore, load_configuration
from tests.test_cloud_node import node


def configured_node(tmp_path, name='selected', bucket='synthetic-bucket'):
    directory = tmp_path / name
    secret = tmp_path / (name + '.secret')
    secret.write_text('sqlite:///' + (tmp_path / (name + '.sqlite')).as_posix(), encoding='utf-8')
    InstallationStore(directory).save({'DATABASE_URL_FILE': str(secret), 'GCS_BUCKET_NAME': bucket}, completed=True)
    return directory


def test_operator_selects_persistent_directories_and_restart_preserves_selection_and_files(tmp_path):
    selected = configured_node(tmp_path)
    target = tmp_path / 'persistent files'
    response = node('--config-dir', selected, 'runtime', '--directory', target)
    assert response.returncode == 0, response.stdout + response.stderr
    report = json.loads(response.stdout)
    assert report['code'] == 'runtime_ready'
    assert report['directories'] == {
        'raw': str(target / 'data/raw'), 'processed': str(target / 'data/processed'),
        'checkpoints': str(target / 'checkpoints'), 'logs': str(target / 'logs'),
    }
    audio = target / 'data/raw/keep.txt'
    audio.write_text('preserve this dataset', encoding='utf-8')
    restarted = node('--config-dir', selected, 'runtime')
    assert restarted.returncode == 0, restarted.stdout + restarted.stderr
    assert json.loads(restarted.stdout)['directories'] == report['directories']
    assert audio.read_text(encoding='utf-8') == 'preserve this dataset'
    settings = load_configuration({'FAMA_CONFIG_DIR': str(selected)})
    assert settings.installation_status == 'completed'
    assert settings.values['FAMA_RUNTIME_DIR'] == str(target)
    assert 'sqlite:' not in response.stdout


def test_selected_root_is_used_by_public_path_resolvers_and_default_file_consumers(tmp_path):
    selected = configured_node(tmp_path)
    target = tmp_path / 'persistent'
    assert node('--config-dir', selected, 'runtime', '--directory', target).returncode == 0
    program = '''
import json,sys
from app.configuration import load_configuration,activate_configuration
activate_configuration(load_configuration({'FAMA_CONFIG_DIR':sys.argv[1]}),replace_environment=True)
from training.paths import get_raw_data_dir,get_processed_data_dir,get_checkpoints_dir
from app.services.ingestion import IngestionService
from app.services.training import TrainingService
from app.services.feedback import FeedbackService
from app.main import SuperEnsembleService
from app.services.predictors.ensemble_predictor import ChileanBirdsEnsemblePredictor
from app.services.predictors.engine_ensemble_predictor import EngineEnsemblePredictor
birds=ChileanBirdsEnsemblePredictor()
engines=EngineEnsemblePredictor()
print(json.dumps({'raw':str(get_raw_data_dir()),'processed':str(get_processed_data_dir()),
 'checkpoints':str(get_checkpoints_dir()),'ingestion':str(IngestionService().local_base_dir),
 'training':str(TrainingService().checkpoints_dir),'feedback':str(FeedbackService().raw_data_dir),
 'ensemble':str(SuperEnsembleService().checkpoints_dir),
 'predictor_paths':[str(p) for p in birds.checkpoint_paths+list(engines.checkpoint_paths.values())]}))
'''
    environment = {key: value for key, value in os.environ.items()
                   if key.upper() in {'PATH','SYSTEMROOT','TEMP','TMP'}}
    environment['PYTHON_DOTENV_DISABLED'] = '1'
    result = subprocess.run([sys.executable, '-c', program, str(selected)],
                            cwd=Path(__file__).resolve().parents[1], env=environment,
                            capture_output=True, text=True, timeout=180)
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout.splitlines()[-1])
    predictor_paths = report.pop('predictor_paths')
    assert all(Path(path).is_relative_to(target / 'checkpoints') for path in predictor_paths)
    assert report == {
        'raw': str(target / 'data/raw'), 'processed': str(target / 'data/processed'),
        'checkpoints': str(target / 'checkpoints'), 'ingestion': str(target / 'data/raw'),
        'training': str(target / 'checkpoints'), 'feedback': str(target / 'data/raw'),
        'ensemble': str(target / 'checkpoints'),
    }


@pytest.mark.parametrize('different_bucket', [False, True])
def test_another_database_cannot_claim_files_and_failed_selection_preserves_installation(tmp_path, different_bucket):
    first = configured_node(tmp_path, 'first')
    second = configured_node(tmp_path, 'second', bucket='other-bucket' if different_bucket else 'synthetic-bucket')
    if different_bucket:
        (tmp_path / 'second.secret').write_text((tmp_path / 'first.secret').read_text(), encoding='utf-8')
    target = tmp_path / 'persistent'
    assert node('--config-dir', first, 'runtime', '--directory', target).returncode == 0
    result = node('--config-dir', second, 'runtime', '--directory', target)
    assert result.returncode == 1
    assert json.loads(result.stdout) == {'code': 'runtime_identity_mismatch'}
    assert 'FAMA_RUNTIME_DIR' not in load_configuration({'FAMA_CONFIG_DIR': str(second)}).values


def test_two_nodes_cannot_use_the_same_root_at_the_same_time(tmp_path):
    from fastapi.testclient import TestClient
    from app.node import create_node_app

    selected = configured_node(tmp_path)
    target = tmp_path / 'persistent'
    assert node('--config-dir', selected, 'runtime', '--directory', target).returncode == 0
    from app.configuration import get_configuration, activate_configuration
    previous = get_configuration()
    previous_environment = os.environ.copy()
    try:
        with TestClient(create_node_app(str(selected))) as first:
            assert first.get('/health').status_code == 200
            with TestClient(create_node_app(str(selected))) as second:
                response = second.get('/ready')
                assert response.status_code == 503
                assert response.json() == {'code': 'runtime_in_use'}
        # Shutdown releases ownership; the next node is blocked only by this fixture's missing security.
        with TestClient(create_node_app(str(selected))) as restarted:
            assert restarted.get('/ready').json() == {'code': 'configuration_incomplete'}
    finally:
        os.environ.clear()
        os.environ.update(previous_environment)
        activate_configuration(previous)


def test_managed_node_does_not_discover_a_weight_from_the_old_repository(tmp_path):
    selected = configured_node(tmp_path)
    target = tmp_path / 'persistent'
    assert node('--config-dir', selected, 'runtime', '--directory', target).returncode == 0
    # Real module under another source tree; the only old checkpoint is synthetic test data.
    copied = tmp_path / 'old-project/backend/app/main.py'
    copied.parent.mkdir(parents=True)
    shutil.copy2(Path(__file__).resolve().parents[1] / 'app/main.py', copied)
    old_weights = tmp_path / 'old-project/checkpoints'
    old_weights.mkdir()
    (old_weights / 'efficientnet_gpu_pipeline_35e_best.pt').write_bytes(b'not an environment weight')
    program = '''
import importlib.util,json,sys
from app.configuration import activate_configuration,load_configuration
activate_configuration(load_configuration({'FAMA_CONFIG_DIR':sys.argv[1]}),replace_environment=True)
spec=importlib.util.spec_from_file_location('isolated_operational',sys.argv[2])
module=importlib.util.module_from_spec(spec)
sys.modules[spec.name]=module
spec.loader.exec_module(module)
print(json.dumps(module.SuperEnsembleService().get_status()['triad_status']))
'''
    environment = {key: value for key, value in os.environ.items()
                   if key.upper() in {'PATH','SYSTEMROOT','TEMP','TMP'}}
    environment['PYTHON_DOTENV_DISABLED'] = '1'
    result = subprocess.run([sys.executable, '-c', program, str(selected), str(copied)],
                            cwd=Path(__file__).resolve().parents[1], env=environment,
                            capture_output=True, text=True, timeout=180)
    assert result.returncode == 0, result.stderr
    assert all(item['weights_available'] is False for item in json.loads(result.stdout.splitlines()[-1]))


def test_windows_launcher_validates_selected_paths_without_starting_servers(tmp_path):
    if os.name != 'nt' or not shutil.which('node'):
        pytest.skip('Lanzador nativo de Windows con Node instalado')
    selected = configured_node(tmp_path)
    target = tmp_path / 'persistent'
    assert node('--config-dir', selected, 'runtime', '--directory', target).returncode == 0
    with socket.socket() as first, socket.socket() as second:
        first.bind(('127.0.0.1', 0))
        second.bind(('127.0.0.1', 0))
        backend_port, frontend_port = first.getsockname()[1], second.getsockname()[1]
    powershell = Path(os.environ['SYSTEMROOT']) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
    script = Path(__file__).resolve().parents[1] / 'scripts/iniciar_nodo.ps1'
    result = subprocess.run([str(powershell), '-NoProfile', '-NonInteractive', '-File', str(script),
        '-ConfigDirectory', str(selected), '-PythonExecutable', sys.executable,
        '-BackendPort', str(backend_port), '-FrontendPort', str(frontend_port), '-ValidateOnly'],
        capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report['code'] == 'native_launch_validated'
    assert report['runtime_root'] == str(target)
    assert report['frontend_dist_dir'] == f'.next-{frontend_port}'
    assert 'backend_pid' not in report


def test_losing_the_root_between_app_creation_and_startup_prevents_startup(tmp_path):
    from fastapi.testclient import TestClient
    from app.configuration import activate_configuration, get_configuration, ConfigurationError
    from app.node import create_node_app

    selected = configured_node(tmp_path)
    target = tmp_path / 'persistent'
    assert node('--config-dir', selected, 'runtime', '--directory', target).returncode == 0
    previous, environment = get_configuration(), os.environ.copy()
    try:
        waiting_app = create_node_app(str(selected))
        with TestClient(create_node_app(str(selected))):
            with pytest.raises(ConfigurationError, match='runtime_in_use'):
                with TestClient(waiting_app):
                    pass
    finally:
        os.environ.clear()
        os.environ.update(environment)
        activate_configuration(previous)


def test_invalid_database_identity_has_a_sanitized_cli_error(tmp_path):
    selected = configured_node(tmp_path)
    (tmp_path / 'selected.secret').write_text('private-invalid-database-identity', encoding='utf-8')
    result = node('--config-dir', selected, 'runtime', '--directory', tmp_path / 'persistent')
    assert result.returncode == 1
    assert json.loads(result.stdout) == {'code': 'runtime_identity_invalid'}
    assert 'private-invalid' not in result.stdout + result.stderr


@pytest.mark.parametrize('url', ['sqlite:///:memory:', 'sqlite:///relative.sqlite'])
def test_persistent_files_reject_memory_or_cwd_dependent_database_identity(tmp_path, url):
    selected = configured_node(tmp_path)
    (tmp_path / 'selected.secret').write_text(url, encoding='utf-8')
    result = node('--config-dir', selected, 'runtime', '--directory', tmp_path / 'persistent')
    assert result.returncode == 1
    assert json.loads(result.stdout) == {'code': 'runtime_database_not_persistent'}


@pytest.mark.parametrize('nonempty', [False, True])
def test_operator_cannot_select_a_relative_or_unidentified_nonempty_tree(tmp_path, nonempty):
    selected = configured_node(tmp_path)
    target = tmp_path / 'existing'
    target.mkdir()
    (target / 'keep.txt').write_text('preserve existing files', encoding='utf-8')
    result = node('--config-dir', selected, 'runtime', '--directory', target if nonempty else 'relative-path')
    assert result.returncode == 1
    assert json.loads(result.stdout)['code'] == ('runtime_directory_not_empty' if nonempty else 'runtime_path_invalid')
    assert (target / 'keep.txt').read_text(encoding='utf-8') == 'preserve existing files'
    assert 'FAMA_RUNTIME_DIR' not in load_configuration({'FAMA_CONFIG_DIR': str(selected)}).values


def test_missing_runtime_subdirectory_blocks_readiness_without_falling_back(tmp_path):
    from fastapi.testclient import TestClient
    from app.node import create_node_app
    from app.configuration import activate_configuration, get_configuration

    selected = configured_node(tmp_path)
    target = tmp_path / 'persistent'
    assert node('--config-dir', selected, 'runtime', '--directory', target).returncode == 0
    (target / 'data/raw').rmdir()
    previous, environment = get_configuration(), os.environ.copy()
    try:
        with TestClient(create_node_app(str(selected))) as client:
            assert client.get('/ready').json() == {'code': 'runtime_layout_invalid'}
            assert client.get('/api/training/datasets').status_code == 503
    finally:
        os.environ.clear()
        os.environ.update(environment)
        activate_configuration(previous)
