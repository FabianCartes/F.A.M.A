"""Persistence through public training seams with tiny, synthetic ML execution."""
import hashlib
import json

import pytest
import torch
import timm
from sqlalchemy import event

from app.models.dataset import ConjuntoDatos
from app.models.training import Modelo, ModelEvaluation
from app.services.evaluations import EvaluationService
from app.services import training
from tests.test_training_flow import training_env, partitions, register


@pytest.fixture
def persistence_env(training_env, monkeypatch):
    service, sessions, root, thread = training_env
    dataset_id = register(sessions, "engine_diagnostics")
    partitions(root, "engine_diagnostics")
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    # External ML library boundaries: no pretrained downloads or real audio input.
    def tiny_model(*args, num_classes, **kwargs):
        model = torch.nn.Sequential(torch.nn.AdaptiveAvgPool2d(1), torch.nn.Flatten(),
                                    torch.nn.Linear(1, num_classes))
        for parameter in model.parameters():
            torch.nn.init.zeros_(parameter)
        return model
    monkeypatch.setattr(timm, "create_model", tiny_model)
    monkeypatch.setattr(training, "DataLoader", lambda *a, **k: [(torch.ones(1, 512), torch.zeros(1, dtype=torch.long))])

    class InlineThread:
        def __init__(self, target, args, **kwargs):
            self.target, self.args = target, args
        def start(self):
            self.target(*self.args)
    thread.side_effect = InlineThread
    yield service, sessions, root, dataset_id


def start(service, **kwargs):
    return service.start_training(
        "engine_diagnostics", architecture="fixture", epochs=1, batch_size=1,
        audio_config={"target_sr": 8000, "duration_seconds": 0.064, "n_mels": 32,
                      "n_fft": 256, "hop_length": 64, "f_min": 0.0, "f_max": kwargs.pop('f_max', 4000.0)},
        regularization_config={"loss_type": "cross_entropy"}, early_stopping=False, **kwargs)


def history(service, sessions):
    with sessions() as db:
        return service.get_history(db)


def test_checkpoint_retains_admitted_preparation_after_index_changes(persistence_env, monkeypatch):
    service, sessions, root, _ = persistence_env
    marker = root / "prepared/engine_diagnostics/.complete"
    manifest = json.loads(marker.read_bytes())
    original_factory = service._process_factory
    def mutate_after_admission(*args, **kwargs):
        index = root / "raw/engine_diagnostics/metadata.csv"
        index.write_bytes(index.read_bytes() + b"\n")
        return original_factory(*args, **kwargs)
    monkeypatch.setattr(service, "_process_factory", mutate_after_admission)
    start(service)
    assert service.get_progress()["status"] == "completed", service.get_progress()["error_message"]
    entry, = history(service, sessions)
    payload = torch.load(service.checkpoints_dir / entry["filename"], weights_only=True)
    assert payload["preparation"] == {"manifest": manifest, "historical": False}


def evaluations(sessions, model_id):
    with sessions() as db:
        service = EvaluationService(db)
        return [service.read(row.id_evaluation) for row in db.query(ModelEvaluation)
                .filter_by(id_modelo=model_id).order_by(ModelEvaluation.id_evaluation)]


def test_main_persists_two_final_reports_before_success_and_activation(persistence_env, request):
    service, sessions, _, _ = persistence_env
    registered = []
    publications = []
    def observe_publication(db):
        if any(isinstance(row, Modelo) and row.estado == 'standard_eval_completed'
               and row.activo for row in db.identity_map.values()):
            publications.append((service.get_progress()['status'],
                                 [row.status for row in db.query(ModelEvaluation).order_by(ModelEvaluation.id_evaluation)]))
    event.listen(sessions, 'before_commit', observe_publication)
    def observe(mapper, connection, target):
        registered.append((target.activo, target.estado))
    event.listen(Modelo, 'after_insert', observe)
    request.addfinalizer(lambda: event.remove(Modelo, 'after_insert', observe))
    start(service)
    assert service.get_progress()['status'] == 'completed', service.get_progress()['error_message']
    entry, = history(service, sessions)
    payload = torch.load(service.checkpoints_dir / entry['filename'], weights_only=True)
    assert registered == [(False, 'standard_eval_pending')]
    attempts = evaluations(sessions, entry['id'])
    assert [(a['split'], a['status']) for a in attempts] == [('val', 'completed'), ('test', 'completed')]
    assert all(a['checkpoint_sha256'] == entry['sha256'] for a in attempts)
    assert attempts[0]['manifest_sha256'] != attempts[1]['manifest_sha256']
    pair = attempts[0]['predictor_config']['admitted_val_test_manifest_pair']
    assert pair == attempts[1]['predictor_config']['admitted_val_test_manifest_pair']
    canonical_pair = json.dumps({
        'domain': 'fama.standard-evaluation.admitted-val-test-manifest-pair',
        'version': 1,
        'val_manifest_sha256': attempts[0]['manifest_sha256'],
        'test_manifest_sha256': attempts[1]['manifest_sha256'],
    }, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode('utf-8')
    assert pair == {'version': 1, 'sha256': hashlib.sha256(canonical_pair).hexdigest()}
    assert all(a['report']['sample_count'] == 1 for a in attempts)
    assert all(a['report']['rejection']['count'] == 1 for a in attempts)
    assert entry['active'] is True
    assert entry['status'] == 'standard_eval_completed'
    assert publications == [('evaluating', ['completed', 'completed'])]
    assert attempts[0]['preprocessing_config']['target_sr'] == 8000
    assert attempts[0]['predictor_config']['training_config']['audio']['target_sr'] == 8000
    assert attempts[0]['predictor_config']['training_mismatch'] is False
    assert attempts[0]['predictor_config']['training_config']['frontend']['normalize'] is True
    assert attempts[0]['preprocessing_config']['normalization'] == 'per-example-zscore'
    assert attempts[0]['preprocessing_config']['frontend_contract'] == payload['preprocessing_contract']
    assert not any('discrepancia' in log['message'].lower() for log in service.logs)


def test_main_accepts_schema_configs_without_substituting_training_physics(persistence_env):
    from app.schemas.training import AudioConfigSchema, WindowingConfigSchema, RegularizationConfigSchema
    service, sessions, _, _ = persistence_env
    audio = AudioConfigSchema(target_sr=8000, duration_seconds=.5, n_mels=32,
                              n_fft=256, hop_length=64, f_min=0, f_max=4000)
    windowing = WindowingConfigSchema(hop_seconds=.25, aggregation_mode='mean')
    service.start_training('engine_diagnostics', architecture='fixture', epochs=1,
                           audio_config=audio, windowing_config=windowing,
                           regularization_config=RegularizationConfigSchema(loss_type='cross_entropy'))
    assert service.get_progress()['status'] == 'completed', service.get_progress()['error_message']
    entry, = history(service, sessions)
    payload = torch.load(service.checkpoints_dir / entry['filename'], weights_only=True)
    attempts = evaluations(sessions, entry['id'])
    assert attempts[0]['predictor_config']['training_config']['windowing'] == windowing.model_dump()
    assert attempts[0]['aggregation_config']['windowing'] == 'fixed-center-crop'
    assert payload['audio_config'] == audio.model_dump()


def old_active(sessions):
    with sessions() as db:
        model = Modelo(arquitectura='legacy', epocas=1, tasa_aprendizaje=.01,
                       tamano_lote=1, ruta_binario_gcp='legacy.pt', activo=True, estado='entrenado')
        db.add(model)
        db.commit()
        return model.id_modelo


@pytest.mark.parametrize('failure', ['val', 'test', 'persistence'])
def test_final_evaluation_failure_preserves_artifact_and_previous_active(persistence_env, monkeypatch, failure):
    service, sessions, _, _ = persistence_env
    previous_id = old_active(sessions)
    calls = []
    real_predict = training.published_predictor.TrainedModelPredictor.predict
    def predict(predictor, path):
        calls.append(path)
        assert service.get_progress()['status'] == 'evaluating'
        with pytest.raises(RuntimeError, match='Ya existe'):
            service.start_training('engine_diagnostics')
        with sessions() as db:
            assert db.get(Modelo, previous_id).activo is True
            newest = db.query(Modelo).order_by(Modelo.id_modelo.desc()).first()
            assert newest.activo is False
            assert service.set_active_model(newest.id_modelo, db)['success'] is False
        if len(calls) == (1 if failure == 'val' else 2) and failure != 'persistence':
            raise RuntimeError(f'{failure} inference failed')
        return real_predict(predictor, path)
    monkeypatch.setattr(training.published_predictor.TrainedModelPredictor, 'predict', predict)
    if failure == 'persistence':
        fired = []
        def reject_once(db):
            if not fired and db.query(ModelEvaluation).filter_by(status='completed').count():
                fired.append(True)
                raise RuntimeError('report persistence failed')
        event.listen(sessions, 'before_commit', reject_once)
    start(service)
    progress = service.get_progress()
    assert progress['status'] == 'failed'
    assert failure in progress['error_message']
    entries = history(service, sessions)
    new = next(e for e in entries if e['id'] != previous_id)
    assert new['status'] == 'standard_eval_failed'
    assert new['active'] is False
    assert (service.checkpoints_dir / new['filename']).is_file()
    assert next(e for e in entries if e['id'] == previous_id)['active'] is True
    attempts = evaluations(sessions, new['id'])
    assert len(attempts) == 2
    assert [a['status'] for a in attempts] == (['completed', 'failed'] if failure == 'test' else ['failed', 'failed'])
    with sessions() as db:
        assert service.set_active_model(new['id'], db)['success'] is False
        assert db.get(Modelo, previous_id).activo is True
    assert not any('finalizado exitosamente' in log['message'] for log in progress['logs'])


def test_evaluation_revalidates_admitted_reference_after_training(persistence_env, request):
    import pandas as pd
    service, sessions, root, _ = persistence_env
    previous_id = old_active(sessions)
    frame = pd.read_csv(root / 'prepared/engine_diagnostics/val_metadata.csv')
    path = root / 'raw/engine_diagnostics' / frame.iloc[0]['file_path']
    def introduce_alias(mapper, connection, target):
        actual = path.with_suffix('.original.wav')
        path.rename(actual)
        path.symlink_to(actual)
    event.listen(Modelo, 'after_insert', introduce_alias)
    request.addfinalizer(lambda: event.remove(Modelo, 'after_insert', introduce_alias))
    start(service)
    assert service.get_progress()['status'] == 'failed'
    assert 'symlink' in service.get_progress()['error_message']
    new = next(e for e in history(service, sessions) if e['id'] != previous_id)
    assert (service.checkpoints_dir / new['filename']).is_file()
    assert new['active'] is False
    assert next(e for e in history(service, sessions) if e['id'] == previous_id)['active'] is True


def test_restored_predictor_failure_marks_both_attempts_failed_without_activation(persistence_env, monkeypatch):
    service, sessions, _, _ = persistence_env
    previous_id = old_active(sessions)
    create_model = timm.create_model
    calls = []
    def restore_fails(*args, **kwargs):
        calls.append(True)
        if len(calls) > 1:
            raise RuntimeError('checkpoint restoration failed')
        return create_model(*args, **kwargs)
    monkeypatch.setattr(timm, 'create_model', restore_fails)
    start(service)
    assert service.get_progress()['status'] == 'failed'
    new = next(e for e in history(service, sessions) if e['id'] != previous_id)
    assert (service.checkpoints_dir / new['filename']).is_file()
    assert [a['status'] for a in evaluations(sessions, new['id'])] == ['failed', 'failed']
    assert next(e for e in history(service, sessions) if e['id'] == previous_id)['active'] is True


def test_component_reports_do_not_publish_an_unevaluated_combined_ensemble(persistence_env):
    service, sessions, _, _ = persistence_env
    previous_id = old_active(sessions)
    start(service, models=[{'architecture': 'fixture', 'epochs': 1},
                           {'architecture': 'fixture2', 'epochs': 1}])
    assert service.get_progress()['status'] == 'completed', service.get_progress()['error_message']
    entries = history(service, sessions)
    assert next(e for e in entries if e['id'] == previous_id)['active'] is True
    for entry in entries:
        if entry['id'] == previous_id:
            continue
        assert entry['status'] == 'standard_component_evaluated'
        assert entry['active'] is False
        assert [a['status'] for a in evaluations(sessions, entry['id'])] == ['completed', 'completed']
        with sessions() as db:
            assert service.set_active_model(entry['id'], db)['success'] is False
    assert any('sin evaluar ni publicar' in log['message'] for log in service.logs)


@pytest.mark.parametrize('event_name', ['before_commit', 'after_commit'])
def test_publication_commit_error_restores_previous_active_and_reports_failure(persistence_env, event_name):
    service, sessions, _, _ = persistence_env
    previous_id = old_active(sessions)
    fired = []
    def reject_publication(db):
        if not fired and any(isinstance(row, Modelo) and row.estado == 'standard_eval_completed'
                             and row.activo for row in db.identity_map.values()):
            fired.append(True)
            raise RuntimeError('publication acknowledgement failed')
    event.listen(sessions, event_name, reject_publication)
    start(service)
    assert fired == [True]
    assert service.get_progress()['status'] == 'failed'
    assert service.get_progress()['error_message'] == 'publication acknowledgement failed'
    entries = history(service, sessions)
    assert next(e for e in entries if e['id'] == previous_id)['active'] is True
    new = next(e for e in entries if e['id'] != previous_id)
    assert new['active'] is False
    assert new['status'] == 'standard_eval_failed'
    assert (service.checkpoints_dir / new['filename']).is_file()
    assert [a['status'] for a in evaluations(sessions, new['id'])] == ['completed', 'completed']


@pytest.mark.parametrize('state', ['standard_eval_pending', 'standard_eval_failed', 'standard_component_evaluated'])
def test_manual_activation_blocks_new_incomplete_models_but_preserves_legacy(persistence_env, state):
    service, sessions, _, _ = persistence_env
    previous_id = old_active(sessions)
    with sessions() as db:
        new = Modelo(arquitectura='new', epocas=1, tasa_aprendizaje=.01,
                     tamano_lote=1, ruta_binario_gcp='new.pt', activo=False, estado=state)
        db.add(new)
        db.commit()
        assert service.set_active_model(new.id_modelo, db)['success'] is False
        assert db.get(Modelo, previous_id).activo is True
        # Legacy activation bypasses standard reports, not existing behavior.
        assert service.set_active_model(previous_id, db)['success'] is True


def test_manual_activation_preserves_same_artifact_pair_after_failed_retry(persistence_env):
    service, sessions, _, _ = persistence_env
    start(service)
    entry, = history(service, sessions)
    with sessions() as db:
        from app.schemas.evaluation import EvaluationIdentity

        target = db.get(Modelo, entry['id'])
        active_before = [row.id_modelo for row in db.query(Modelo).filter(Modelo.activo.is_(True))]
        val = db.query(ModelEvaluation).filter_by(id_modelo=entry['id'], split='val').one()
        identity = {field: getattr(val, field) for field in EvaluationIdentity.model_fields}
        attempts = EvaluationService(db)
        retry = attempts.create(identity)
        attempts.start(retry['id_evaluation'])
        attempts.fail(retry['id_evaluation'], 'synthetic retry failure')
        assert target.estado == 'standard_eval_completed'
        assert [row.id_modelo for row in db.query(Modelo).filter(Modelo.activo.is_(True))] == active_before

        result = service.set_active_model(entry['id'], db)
        assert result['success'] is True, result
        assert [row.id_modelo for row in db.query(Modelo).filter(Modelo.activo.is_(True))] == active_before


@pytest.mark.parametrize('fault', ['hash', 'job', 'classes', 'dataset', 'report', 'config'])
def test_manual_activation_rejects_wrong_report_identity(persistence_env, fault):
    service, sessions, _, _ = persistence_env
    previous_id = old_active(sessions)
    start(service)
    entry = next(e for e in history(service, sessions) if e['id'] != previous_id)
    with sessions() as db:
        assert service.set_active_model(previous_id, db)['success'] is True
        row = db.query(ModelEvaluation).filter_by(id_modelo=entry['id'], split='test').one()
        if fault == 'hash':
            row.checkpoint_sha256 = 'f' * 64
        elif fault == 'job':
            row.predictor_config = {**row.predictor_config, 'job_id': 'previous-job'}
        elif fault == 'classes':
            row.classes = ['wrong-class']
        elif fault == 'dataset':
            row.dataset = 'different-dataset'
        elif fault == 'config':
            row.preprocessing_config = {**row.preprocessing_config, 'crop': 'wrong'}
        else:
            row.report = {**row.report, 'sample_count': 99}
        db.commit()
        assert service.set_active_model(entry['id'], db)['success'] is False
        assert db.get(Modelo, previous_id).activo is True
        assert db.get(Modelo, entry['id']).activo is False


def test_activation_without_persistence_cannot_announce_success(persistence_env):
    service, _, _, _ = persistence_env
    assert service.set_active_model(123)['success'] is False


def test_manual_activation_rechecks_checkpoint_and_exact_reports(persistence_env):
    service, sessions, _, _ = persistence_env
    start(service)
    entry, = history(service, sessions)
    checkpoint = service.checkpoints_dir / entry['filename']
    checkpoint.write_bytes(checkpoint.read_bytes() + b'changed')
    with sessions() as db:
        assert service.set_active_model(entry['id'], db)['success'] is False


@pytest.mark.parametrize('first_score,last_score', [(1.0, -1.0), (-1.0, -2.0)])
def test_cpu_checkpoint_and_final_predictor_use_first_best_not_last(training_env, monkeypatch, first_score, last_score):
    import timm
    import numpy as np
    import wave
    from types import SimpleNamespace
    service, sessions, root, thread = training_env
    register(sessions, 'engine_diagnostics')
    partitions(root, 'engine_diagnostics', classes=('Fixture', 'Other'))
    tone = (np.sin(2 * np.pi * 1500 * np.arange(110250) / 22050) * 10000).astype('<i2')
    for path in (root / 'raw/engine_diagnostics').rglob('*.wav'):
        with wave.open(str(path), 'wb') as out:
            out.setnchannels(1)
            out.setsampwidth(2)
            out.setframerate(22050)
            out.writeframes(tone.tobytes())
    class Classifier(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.score = torch.nn.Parameter(torch.tensor(0.0))
        def forward(self, inputs):
            return torch.stack((self.score, -self.score)).expand(inputs.shape[0], 2)
    monkeypatch.setattr(timm, 'create_model', lambda *a, **k: Classifier())
    monkeypatch.setattr(torch.cuda, 'is_available', lambda: False)
    monkeypatch.setattr(training, 'DataLoader', lambda *a, **k: [(torch.ones(1, 512), torch.zeros(1, dtype=torch.long))])
    restored = []
    predict = training.published_predictor.TrainedModelPredictor.predict
    def observe_predict(predictor, path):
        output = predict(predictor, path)
        restored.append(next(predictor.model.parameters()).item())
        assert not predictor.model.training
        return output
    monkeypatch.setattr(training.published_predictor.TrainedModelPredictor, 'predict', observe_predict)
    scores = iter((first_score, last_score))
    def step(optimizer, closure=None):
        with torch.no_grad():
            optimizer.param_groups[0]['params'][0].fill_(next(scores))
    monkeypatch.setattr(torch.optim.AdamW, 'step', step)
    thread.side_effect = lambda target, args, **k: SimpleNamespace(start=lambda: target(*args))
    service.start_training('engine_diagnostics', architecture='fixture', epochs=2,
        audio_config={'target_sr': 8000, 'duration_seconds': .064, 'n_mels': 32,
                      'n_fft': 256, 'hop_length': 64, 'f_min': 0.0, 'f_max': 4000.0},
        regularization_config={'loss_type': 'cross_entropy'}, early_stopping=False)
    assert service.get_progress()['status'] == 'completed', service.get_progress()['error_message']
    entry, = history(service, sessions)
    payload = torch.load(service.checkpoints_dir / entry['filename'], weights_only=True)
    assert next(iter(payload['state_dict'].values())).item() == first_score
    assert payload['best_val_acc'] == (100.0 if first_score > 0 else 0.0)
    assert [m['val_acc'] for m in service.metrics_history] == ([100.0, 0.0] if first_score > 0 else [0.0, 0.0])
    attempts = evaluations(sessions, entry['id'])
    assert len(attempts) == 2
    expected_matrix = [[1, 0, 0], [1, 0, 0]] if first_score > 0 else [[0, 1, 0], [0, 1, 0]]
    assert all(a['report']['confusion_matrix'] == expected_matrix for a in attempts)
    assert restored == [first_score] * 4  # Two labelled recordings in each final split.


def test_repeated_jobs_never_overwrite_an_existing_checkpoint(persistence_env):
    service, sessions, _, _ = persistence_env
    legacy = service.checkpoints_dir / "engine_diagnostics_fixture_v1.pt"
    legacy.write_bytes(b"pre-existing checkpoint")
    first = start(service)
    assert service.get_progress()["status"] == "completed", service.get_progress()["error_message"]
    first_files = {p.name: p.read_bytes() for p in service.checkpoints_dir.iterdir()}
    second = start(service)
    assert service.get_progress()["status"] == "completed"
    assert legacy.read_bytes() == b"pre-existing checkpoint"
    assert first["job_id"] != second["job_id"]
    for name, content in first_files.items():
        assert (service.checkpoints_dir / name).read_bytes() == content
    entries = history(service, sessions)
    assert len(entries) == 2
    assert len({entry["filename"] for entry in entries}) == 2
    assert all((service.checkpoints_dir / entry["filename"]).is_file() for entry in entries)


def test_commit_failure_is_failed_and_does_not_leave_unregistered_artifacts(persistence_env):
    service, sessions, _, _ = persistence_env
    legacy = service.checkpoints_dir / "existing.pt"
    legacy.write_bytes(b"existing")
    def reject_commit(db):
        raise RuntimeError("Synthetic DB commit failure")
    event.listen(sessions, "before_commit", reject_commit)
    start(service)
    progress = service.get_progress()
    assert progress["status"] == "failed"
    assert "Synthetic DB commit failure" in progress["error_message"]
    assert [p.name for p in service.checkpoints_dir.iterdir()] == ["existing.pt"]
    assert legacy.read_bytes() == b"existing"
    assert history(service, sessions) == []
    assert not any("finalizado" in log["message"] for log in progress["logs"])


@pytest.mark.parametrize("mutation", ["renamed", "deleted"])
def test_dataset_identity_must_still_match_when_registering(persistence_env, monkeypatch, mutation):
    service, sessions, _, dataset_id = persistence_env
    save = torch.save
    def mutate_after_save(payload, output):
        save(payload, output)
        with sessions() as db:
            dataset = db.get(ConjuntoDatos, dataset_id)
            if mutation == "renamed":
                dataset.nombre = "different_source"
            else:
                db.delete(dataset)
            db.commit()
    monkeypatch.setattr(torch, "save", mutate_after_save)
    start(service)
    assert service.get_progress()["status"] == "failed"
    assert "dataset" in service.get_progress()["error_message"].lower()
    assert history(service, sessions) == []
    assert list(service.checkpoints_dir.iterdir()) == []


@pytest.mark.parametrize('f_max', [None, 4000.0])
def test_new_checkpoint_persists_effective_gpu_frontend_contract(persistence_env, f_max):
    service, sessions, _, _ = persistence_env
    start(service, f_max=f_max)
    assert service.get_progress()['status'] == 'completed', service.get_progress()['error_message']
    entry, = history(service, sessions)
    payload = torch.load(service.checkpoints_dir / entry["filename"], weights_only=True)
    contract = {
        "version": 1,
        "implementation": "GPUAudioFrontEnd",
        "sample_rate": 8000,
        "duration_seconds": 0.064,
        "parameters": {
            "n_mels": 32,
            "n_fft": 256,
            "hop_length": 64,
            "f_min": 0.0,
            "f_max": f_max,
            "top_db": 80.0,
            "normalize": True,
            "top_db_scope": "per_sample",
        },
    }

    assert payload["preprocessing_contract"] == contract
    assert payload['audio_config']['f_max'] == f_max
    attempts = evaluations(sessions, entry["id"])
    assert [(attempt['split'], attempt['status']) for attempt in attempts] == [
        ('val', 'completed'), ('test', 'completed')]
    assert all(attempt['preprocessing_config']['frontend_contract'] == contract for attempt in attempts)
    assert all(attempt['preprocessing_config']['f_max'] == f_max for attempt in attempts)


@pytest.mark.parametrize('f_max', [None, 4000.0])
def test_frontend_roundtrip_preserves_optional_nyquist(f_max):
    from copy import deepcopy
    from app.services.standard_evaluation_guard import resolve_training_audio
    from poc.preprocess import build_gpu_audio_frontend_contract, validate_gpu_audio_frontend_contract

    audio = resolve_training_audio('engine_diagnostics', {
        'target_sr': 8000, 'duration_seconds': 0.064, 'n_mels': 32,
        'n_fft': 256, 'hop_length': 64, 'f_min': 0.0, 'f_max': f_max})
    contract = build_gpu_audio_frontend_contract(
        sample_rate=audio['target_sr'], duration_seconds=audio['duration_seconds'],
        **{key: audio[key] for key in ('n_mels', 'n_fft', 'hop_length', 'f_min', 'f_max')})
    before = deepcopy(contract)
    assert validate_gpu_audio_frontend_contract(contract)['parameters']['f_max'] == f_max
    assert contract == before
    for invalid_max, invalid_min in [(5000.0, 0.0), (None, 4000.0)]:
        invalid = deepcopy(contract)
        invalid['parameters'].update(f_max=invalid_max, f_min=invalid_min)
        original = deepcopy(invalid)
        with pytest.raises(ValueError):
            validate_gpu_audio_frontend_contract(invalid)
        assert invalid == original


def test_completed_history_and_checkpoint_expose_verified_provenance(persistence_env):
    service, sessions, root, dataset_id = persistence_env
    accepted = start(service)
    assert service.get_progress()["status"] == "completed"
    entry, = history(service, sessions)
    assert entry["dataset_id"] == dataset_id
    assert entry["dataset_name"] == "engine_diagnostics"
    assert [(m["epoca"], m["precision"], m["perdida"]) for m in entry["metrics"]] == [(1, 100.0, 0.0)]
    checkpoint = service.checkpoints_dir / entry["filename"]
    assert entry["sha256"] == hashlib.sha256(checkpoint.read_bytes()).hexdigest()
    assert entry["file_size_bytes"] == checkpoint.stat().st_size
    payload = torch.load(checkpoint, weights_only=True)
    assert payload["dataset_id"] == dataset_id
    assert payload["dataset_name"] == "engine_diagnostics"
    assert payload["job_id"] == accepted["job_id"]
    assert payload["source_directory"] == str(root / "raw" / "engine_diagnostics")
    assert payload["model_index"] == 1


@pytest.mark.parametrize("failure", ["serialize", "fsync", "publish", "session", "flush", "metric"])
def test_external_save_failures_are_visible_and_clean_only_new_files(persistence_env, monkeypatch, request, failure):
    service, sessions, _, _ = persistence_env
    legacy = service.checkpoints_dir / "existing.pt"
    legacy.write_bytes(b"existing")
    def fail(*args, **kwargs):
        raise RuntimeError(f"Synthetic {failure} failure")
    if failure == "serialize":
        def partial_save(payload, output):
            output.write(b"incomplete")
            fail()
        monkeypatch.setattr(torch, "save", partial_save)
    elif failure in {"fsync", "publish"}:
        monkeypatch.setattr(training.os, "fsync" if failure == "fsync" else "link", fail)
    elif failure == "session":
        save = torch.save
        def lose_connection(payload, output):
            save(payload, output)
            monkeypatch.setattr(training, "SessionLocal", fail)
        monkeypatch.setattr(torch, "save", lose_connection)
    elif failure == "flush":
        event.listen(sessions, "before_flush", fail)
    else:
        from app.models.training import MetricaEntrenamiento
        event.listen(MetricaEntrenamiento, "before_insert", fail)
        request.addfinalizer(lambda: event.remove(MetricaEntrenamiento, "before_insert", fail))
    start(service)
    progress = service.get_progress()
    assert progress["status"] == "failed"
    assert f"Synthetic {failure} failure" in progress["error_message"]
    assert history(service, sessions) == []
    assert [p.name for p in service.checkpoints_dir.iterdir()] == ["existing.pt"]
    assert legacy.read_bytes() == b"existing"
    assert not any("guardados" in log["message"] or "finalizado" in log["message"] for log in progress["logs"])


@pytest.mark.parametrize("collision", ["final", "temporary"])
def test_uuid_collision_never_replaces_existing_files(persistence_env, monkeypatch, collision):
    from types import SimpleNamespace
    service, sessions, _, _ = persistence_env
    monkeypatch.setattr(training.uuid, "uuid4", lambda: SimpleNamespace(hex="collision"))
    name = "fama_collision_best.pt" if collision == "final" else "fama_collision_best.collision.tmp"
    existing = service.checkpoints_dir / name
    existing.write_bytes(b"owned by another job")
    start(service)
    assert service.get_progress()["status"] == "failed"
    assert existing.read_bytes() == b"owned by another job"
    assert [p.name for p in service.checkpoints_dir.iterdir()] == [name]
    assert history(service, sessions) == []


def test_partial_ensemble_failure_keeps_only_the_committed_model(persistence_env):
    service, sessions, _, _ = persistence_env
    commits = []
    def second_commit_fails(db):
        # Reports have their own commits; fail only the second registration.
        if any(isinstance(row, Modelo) and row.estado == 'standard_eval_pending'
               for row in db.identity_map.values()):
            commits.append(True)
            if len(commits) == 2:
                raise RuntimeError("Second model commit failed")
    event.listen(sessions, "before_commit", second_commit_fails)
    start(service, models=[{"architecture": "fixture", "epochs": 1}, {"architecture": "fixture2", "epochs": 1}])
    progress = service.get_progress()
    assert progress["status"] == "failed"
    assert progress["error_message"] == "Second model commit failed"
    entry, = history(service, sessions)
    assert entry["architecture"] == "fixture"
    assert len(entry["metrics"]) == 1
    assert [p.name for p in service.checkpoints_dir.iterdir()] == [entry["filename"]]
    assert not any("Todos los modelos" in log["message"] for log in progress["logs"])


def test_ambiguous_post_commit_error_preserves_registered_checkpoint(persistence_env):
    service, sessions, _, _ = persistence_env
    def lost_acknowledgement(db):
        raise RuntimeError("Commit acknowledgement lost")
    event.listen(sessions, "after_commit", lost_acknowledgement)
    start(service)
    assert service.get_progress()["status"] == "failed"
    assert "Commit acknowledgement lost" in service.get_progress()["error_message"]
    entry, = history(service, sessions)
    assert entry["dataset_name"] == "engine_diagnostics"
    assert len(entry["metrics"]) == 1
    assert (service.checkpoints_dir / entry["filename"]).is_file()


def test_unverifiable_commit_retains_artifact_and_reports_uncertainty(persistence_env, monkeypatch):
    service, sessions, _, _ = persistence_env
    def lost_connection(db):
        def unavailable():
            raise RuntimeError("Registration verification unavailable")
        monkeypatch.setattr(training, "SessionLocal", unavailable)
        raise RuntimeError("Commit outcome unknown")
    event.listen(sessions, "before_commit", lost_connection)
    start(service)
    progress = service.get_progress()
    assert progress["status"] == "failed"
    assert progress["error_message"] == "Commit outcome unknown"
    assert history(service, sessions) == []
    assert len(list(service.checkpoints_dir.glob("*.pt"))) == 1
    assert any("indeterminado" in log["message"] for log in progress["logs"])


def test_job_without_epoch_metrics_cannot_claim_completed(persistence_env):
    service, sessions, _, _ = persistence_env
    start(service, models=[{"architecture": "fixture", "epochs": 0}])
    assert service.get_progress()["status"] == "failed"
    assert "métricas" in service.get_progress()["error_message"]
    assert history(service, sessions) == []
    assert list(service.checkpoints_dir.iterdir()) == []
