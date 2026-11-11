"""Public HTTP access to existing synthetic imported checkpoints and identities."""
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pathlib import Path
import pytest
from tests.http_security import cookie_headers, cookie_security, COOKIE_ORIGIN
from app.models import web_session, access_quota, security_audit

from tests.test_dataset_import_api import imports
from tests.test_imported_dataset_preparation import cohort
from tests.test_training_flow import training_env
from tests.test_imported_training_evaluation import (
    _complete_imported_cpu_worker, publish_preexisting_imported_checkpoint,
)


def test_imported_http_catalogue_is_opt_in_and_owner_private(cohort, training_env, tmp_path, monkeypatch):
    from tests.test_api_training import main
    from app.database import get_db
    from app.models.user import Usuario
    from app.services import auth
    from app.services.registry import ModelRegistry, get_model_registry
    from tests.test_model_registry import FakeAudioPredictor

    runtime, sessions, model_id, _ = _complete_imported_cpu_worker(
        cohort, training_env, tmp_path, monkeypatch
    )
    monkeypatch.setattr(auth, "SECRET_KEY", "synthetic-t5-model-catalogue-signing-key-2026")
    with sessions() as db:
        for uid in (1, 2):
            db.add(Usuario(id=uid, email=f"model-owner{uid}@example.test", password_hash="unused",
                nombre_completo="Synthetic", rol="administrador", activo=True))
        db.commit()
    registry = ModelRegistry()
    registry.register(FakeAudioPredictor("legacy-public", "Legacy public"), is_default=True)
    monkeypatch.setattr(main, "training_service", runtime)
    app = FastAPI()
    # Rebuild the route around the real endpoint so dependency overrides belong
    # to this isolated app, not the original APIRoute's main.app provider.
    from app.schemas.model_info import ModelListResponse
    app.add_api_route("/api/models", main.list_models, methods=["GET"],
                      response_model=ModelListResponse)
    def database():
        with sessions() as db:
            yield db
    app.dependency_overrides[get_db] = database
    app.dependency_overrides[get_model_registry] = lambda: registry
    headers = lambda uid: cookie_headers(sessions, uid)
    key = f"fama_trained_model_{model_id}"
    # Seed another owner's historical checkpoint and real synthetic evaluation
    # reports without reintroducing the retired training entry.
    from types import SimpleNamespace
    from app.routes.dataset_imports import get_import_user
    from tests.test_dataset_import_api import prepare, confirm
    from tests.test_dataset_zip_validation import wav_bytes
    client_import = cohort[4]
    client_import.import_app.dependency_overrides[get_import_user] = lambda: SimpleNamespace(id=2)
    job = prepare(client_import, tmp_path, key='owner-two', name='Owner B private',
        entries=[(f'{label}/{i}.wav', wav_bytes(10 + n))
                 for n, (label, i) in enumerate((label, i) for label in ('ants', 'zebra') for i in range(3))])
    dataset_b = confirm(client_import, job).json()['dataset_id']
    snapshot_b = cohort[0].create(2, dataset_b)
    mapping_b = [dict(member_id=m['member_id'], recording_id=m['original_path'],
                      group_id=m['original_path'].split('/')[-1])
                 for m, _ in cohort[0].iter_verified(2, snapshot_b['id'])]
    prepared_b = runtime.imported_sources.preparations.create(2, snapshot_b['id'],
        mapping=mapping_b, provenance={'source': 'synthetic owner B'}, seed=42, profile=cohort[3])
    model_b, _ = publish_preexisting_imported_checkpoint(
        runtime, sessions, runtime.imported_sources, owner_id=2,
        dataset_id=dataset_b, snapshot_id=snapshot_b['id'],
        prepared_version=prepared_b['version_id'])
    assert runtime.get_progress()['status'] == 'idle'
    key_b = f"fama_trained_model_{model_b}"
    # A publication collaborator can report unavailable identities. Its foreign
    # diagnostics must not appear even though successful owned rows still do.
    publish = registry.publish_from_db
    def with_foreign_error(*args, **kwargs):
        return publish(*args, **kwargs) + [{'model_id': 'foreign-private-error-id',
            'code': 'foreign-private-name', 'reason': 'checkpoint_invalid'}]
    monkeypatch.setattr(registry, 'publish_from_db', with_foreign_error)
    with TestClient(app, raise_server_exceptions=False, headers={"Origin": COOKIE_ORIGIN}) as client:
        public = client.get("/api/models", headers=headers(1))
        assert public.status_code == 200, public.text
        assert [model["id"] for model in public.json()["models"]] == ["legacy-public"]
        assert key not in public.text
        assert public.json()["default_model_id"] == "legacy-public"
        foreign = client.get("/api/models?include_imported=true", headers=headers(2))
        assert foreign.status_code == 200, foreign.text
        assert key not in foreign.text
        owner = client.get("/api/models?include_imported=true", headers=headers(1))
        assert owner.status_code == 200, owner.text
        models = {model["id"]: model for model in owner.json()["models"]}
        assert key in models
        assert models[key]["classes"] == ["ants", "zebra"]
        assert models[key]["is_default"] is False
        assert owner.json()["default_model_id"] == "legacy-public"
        # Private-only is authenticated independently of include_imported, and
        # never exposes the public default or another owner's catalogue.
        assert client.get('/api/models?private_only=true').status_code == 401
        private = client.get('/api/models?private_only=true', headers=headers(1))
        assert private.status_code == 200, private.text
        assert [m['id'] for m in private.json()['models']] == [key]
        assert private.json()['default_model_id'] == ''
        assert private.json()['publication_errors'] == []
        other = client.get('/api/models?private_only=true&include_imported=false', headers=headers(2))
        assert other.status_code == 200, other.text
        assert [m['id'] for m in other.json()['models']] == [key_b]
        assert other.json()['models'][0]['dataset'] == 'Owner B private'
        assert other.json()['models'][0]['name'].startswith('Owner B private · AudioCNN (v')
        assert other.json()['default_model_id'] == ''
        assert key not in other.text
        assert key_b not in private.text
        for response in (private, other):
            assert 'legacy-public' not in response.text
            assert 'Legacy public' not in response.text
            assert 'foreign-private' not in response.text
            assert response.json()['publication_errors'] == []
        assert 'Owner B private' not in private.text
        assert key_b in client.get('/api/models?include_imported=true', headers=headers(2)).text
        assert 'foreign-private-error-id' in public.text
        # A cached private predictor must not contaminate later public requests.
        again = client.get("/api/models", headers=headers(1))
        assert again.status_code == 200, again.text
        assert key not in again.text
        assert registry.get_default_model_id() == "legacy-public"
        def database_failure(*args, **kwargs):
            return [{'model_id': 'foreign-private-error-id', 'code': 'database_unavailable'}]
        monkeypatch.setattr(registry, 'publish_from_db', database_failure)
        failure = client.get('/api/models?private_only=true', headers=headers(1))
        assert failure.status_code == 503
        assert failure.json()['detail']['errors'] == [{'code': 'database_unavailable'}]
        assert 'foreign-private' not in failure.text


def test_evaluated_imported_model_cannot_be_globally_activated(cohort, training_env, tmp_path, monkeypatch):
    from tests.test_api_training import main
    from app.database import get_db
    from app.models.user import Usuario
    from app.schemas.model_info import ModelListResponse
    from app.services import auth, registry as registry_module
    from tests.test_model_registry import FakeAudioPredictor

    runtime, sessions, model_id, _ = _complete_imported_cpu_worker(
        cohort, training_env, tmp_path, monkeypatch
    )
    monkeypatch.setattr(auth, "SECRET_KEY", "synthetic-t5-activation-signing-key-2026")
    with sessions() as db:
        for uid in (1, 2):
            db.add(Usuario(id=uid, email=f"activation-owner{uid}@example.test", password_hash="unused",
                nombre_completo="Synthetic", rol="administrador", activo=True))
        db.commit()
    registry = registry_module.ModelRegistry()
    registry.register(FakeAudioPredictor("legacy-public", "Legacy public"), is_default=True)
    monkeypatch.setattr(main, "training_service", runtime)
    # Keep the service's real global-registry synchronization on synthetic
    # objects and the private checkpoint root even if activation wrongly runs.
    monkeypatch.setattr(registry_module, "get_model_registry", lambda: registry)
    monkeypatch.setattr(registry_module, "__file__", str(tmp_path / "app/services/registry.py"))
    app = FastAPI()
    app.add_api_route("/api/models", main.list_models, methods=["GET"], response_model=ModelListResponse)
    app.add_api_route("/api/training/history", main.get_training_history, methods=["GET"])
    app.add_api_route("/api/training/models/{model_id}/activate", main.activate_model, methods=["POST"])
    def database():
        with sessions() as db:
            yield db
    app.dependency_overrides[get_db] = database
    # The catalogue route captured this original dependency at definition time.
    app.dependency_overrides[main.get_model_registry] = lambda: registry
    headers = lambda uid: cookie_headers(sessions, uid)
    with TestClient(app, raise_server_exceptions=False, headers={"Origin": COOKIE_ORIGIN}) as client:
        before = client.get("/api/training/history?include_imported=true", headers=headers(1))
        assert before.status_code == 200, before.text
        from app.models.dataset_import import ImportedDataset
        with sessions() as db:
            owned_dataset = db.query(ImportedDataset).filter_by(owner_id=1).one()
            expected_name = owned_dataset.name
        entry = next(row for row in before.json()['history'] if row['id'] == model_id)
        assert entry['dataset'] == expected_name
        assert entry['dataset_name'] == expected_name
        assert entry['name'].startswith(expected_name + ' · ')
        assert client.get('/api/training/history?include_imported=true').status_code == 401
        foreign_history = client.get('/api/training/history?include_imported=true', headers=headers(2))
        assert foreign_history.status_code == 200
        assert all(row['id'] != model_id for row in foreign_history.json()['history'])
        public_history = client.get('/api/training/history', headers=headers(1)).json()['history']
        assert all(row['id'] != model_id for row in public_history)
        assert any(row['architecture'] == 'existing' for row in public_history)
        active_before = {row["id"]: row["active"] for row in before.json()["history"]}
        assert active_before[model_id] is False
        url = f"/api/training/models/{model_id}/activate"
        assert client.post(url).status_code == 401
        assert client.post(url, headers=headers(2)).status_code == 404
        owner = client.post(url, headers=headers(1))
        assert owner.status_code == 200, owner.text
        assert owner.json() == {"success": False,
            "error": "Los modelos importados no pueden activarse globalmente."}
        after = client.get("/api/training/history?include_imported=true", headers=headers(1))
        assert after.status_code == 200, after.text
        assert {row["id"]: row["active"] for row in after.json()["history"]} == active_before
        public = client.get("/api/models", headers=headers(1))
        assert public.status_code == 200, public.text
        assert public.json()["default_model_id"] == "legacy-public"
        assert [row["id"] for row in public.json()["models"]] == ["legacy-public"]


def test_public_legacy_activation_preserves_real_weight_loading(training_env, tmp_path, monkeypatch):
    import hashlib
    import torch
    from tests.test_api_training import main
    from tests.test_imported_training_evaluation import checkpoint_payload
    from poc.train import AudioCNN
    from app.database import get_db
    from app.models.training import Modelo
    from app.services import registry as registry_module

    runtime, sessions, _, _ = training_env
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    payload = checkpoint_payload()
    payload.pop("imported_source")
    payload.pop("job_id")
    payload.update(dataset_name="Historical", dataset_id=None,
                   state_dict=AudioCNN(num_classes=2).state_dict())
    checkpoint = runtime.checkpoints_dir / "legacy-activation.pt"
    checkpoint.parent.mkdir(parents=True, exist_ok=True)
    torch.save(payload, checkpoint)
    digest = hashlib.sha256(checkpoint.read_bytes()).hexdigest()
    with sessions() as db:
        row = Modelo(arquitectura="AudioCNN", clase_objetivo="Historical",
            ruta_binario_gcp=checkpoint.as_uri(), hash_binario=digest,
            epocas=1, tasa_aprendizaje=0.001, tamano_lote=1, activo=False, estado="legacy")
        db.add(row)
        db.commit()
        model_id = row.id_modelo
    registry = registry_module.ModelRegistry()
    monkeypatch.setattr(main, "training_service", runtime)
    monkeypatch.setattr(registry_module, "get_checkpoints_dir", lambda: runtime.checkpoints_dir)
    monkeypatch.setattr(registry_module, "get_model_registry", lambda: registry)
    monkeypatch.setattr(registry_module, "__file__", str(tmp_path / "app/services/registry.py"))
    app = FastAPI()
    app.add_api_route("/api/training/history", main.get_training_history, methods=["GET"])
    app.add_api_route("/api/training/models/{model_id}/activate", main.activate_model, methods=["POST"])
    def database():
        with sessions() as db:
            yield db
    app.dependency_overrides[get_db] = database
    from app.services.auth import create_user
    with sessions() as db:
        create_user(db, "legacy-admin@example.test", "SyntheticPassword2026!", "Synthetic", "administrador")
    with TestClient(app, raise_server_exceptions=False, headers=cookie_headers(sessions, 1)) as client:
        before = client.get("/api/training/history")
        assert before.status_code == 200, before.text
        assert before.json()["history"][0]["active"] is False
        activated = client.post(f"/api/training/models/{model_id}/activate")
        assert activated.status_code == 200, activated.text
        assert activated.json()["success"] is True
        after = client.get("/api/training/history")
        assert after.status_code == 200, after.text
        assert after.json()["history"][0]["active"] is True
        predictor = registry.get()
        assert predictor.model is not None
        assert predictor.metadata.loaded_checkpoint_sha256 == digest
        assert registry.get_default_model_id() == f"fama_trained_model_{model_id}"


@pytest.mark.parametrize("selection", ["canonical", "numeric", "filename", "stem"])
def test_imported_http_predict_is_private_and_persists_locally_without_gcs(cohort, training_env, tmp_path, monkeypatch, selection):
    import io
    import wave
    import numpy as np
    from tests.test_api_training import main
    from app.database import get_db
    from app.models.user import Usuario
    from app.services import auth
    from app.services.registry import ModelRegistry, get_model_registry
    from app.services.predictors.trained_predictor import TrainedModelPredictor
    from app.schemas.model_info import ModelListResponse
    from tests.test_model_registry import FakeAudioPredictor

    runtime, sessions, model_id, association = _complete_imported_cpu_worker(
        cohort, training_env, tmp_path, monkeypatch
    )
    monkeypatch.setattr(auth, "SECRET_KEY", "synthetic-t5-predict-signing-key-2026")
    with sessions() as db:
        for uid in (1, 2):
            db.add(Usuario(id=uid, email=f"predict-owner{uid}@example.test", password_hash="unused",
                nombre_completo="Synthetic", rol="administrador", activo=True))
        db.commit()
        before = {row["id"]: row["active"] for row in runtime.get_history(db, owner_id=1)}
        entry = next(row for row in runtime.get_history(db, owner_id=1) if row["id"] == model_id)
        digest, filename = entry["sha256"], entry["filename"]
    registry = ModelRegistry()
    registry.register(FakeAudioPredictor("legacy-public", "Legacy public"), is_default=True)
    monkeypatch.setattr(main, "training_service", runtime)
    local_root = cohort[0].source.root
    from app.services.feedback import FeedbackService
    monkeypatch.setattr(main, "feedback_service", FeedbackService(tmp_path / "reviewed-raw", import_root=local_root))
    monkeypatch.setenv("FAMA_IMPORT_ROOT", str(local_root))
    effects, confirm_upload = [], [True]
    async def upload(audio_bytes, **kwargs):
        effects.append("upload")
        raise AssertionError("Imported inference must never attempt cloud storage")
    real_predict = TrainedModelPredictor.predict
    def observed_predict(predictor, path):
        effects.append("predict")
        return real_predict(predictor, path)
    monkeypatch.setattr(main, "upload_audio_to_gcp", upload)
    monkeypatch.setattr(TrainedModelPredictor, "predict", observed_predict)
    app = FastAPI()
    app.add_api_route("/api/predict", main.predict_audio, methods=["POST"])
    app.add_api_route("/api/feedback", main.record_feedback, methods=["POST"], status_code=201)
    app.add_api_route("/api/feedback/pending", main.get_pending_feedback, methods=["GET"])
    app.add_api_route("/api/feedback/{id_retroalimentacion}/approve", main.approve_feedback, methods=["POST"])
    app.add_api_route("/api/models", main.list_models, methods=["GET"], response_model=ModelListResponse)
    def database():
        with sessions() as db:
            yield db
    app.dependency_overrides[get_db] = database
    app.dependency_overrides[get_model_registry] = lambda: registry
    headers = lambda uid: cookie_headers(sessions, uid)
    stream = io.BytesIO()
    with wave.open(stream, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(8000)
        audio.writeframes((np.sin(2 * np.pi * 440 * np.arange(8000) / 8000) * 12000).astype("<i2").tobytes())
    files = {"file": ("synthetic.wav", stream.getvalue(), "audio/wav")}
    key = f"fama_trained_model_{model_id}"
    requested = {"canonical": key, "numeric": str(model_id), "filename": filename,
                 "stem": Path(filename).stem}[selection]
    with TestClient(app, raise_server_exceptions=False, headers={"Origin": COOKIE_ORIGIN}) as client:
        # No catalogue call or owner publication precedes this cold selection.
        owner = client.post(f"/api/predict?model_id={requested}", files=files, headers=headers(1))
        assert owner.status_code == 200, owner.text
        result = owner.json()
        assert result["modelo_id"] == key
        assert result["gcp_upload"] is False
        assert result["local_audio_saved"] is True
        assert result["cloud_status"] == "deferred"
        assert result["clase"] in ["ants", "zebra"]
        assert result["detalles"]["loaded_checkpoint_sha256"] == digest
        assert result["detalles"]["preprocessing_mode"] == "gpu_mel_zscore"
        assert result["detalles"]["mel_bands"] == association["profile"]["audio"]["n_mels"]
        assert effects == ["predict"]
        from app.models.prediction import Prediccion
        from app.services.local_prediction_audio import LocalPredictionAudio
        with sessions() as db:
            saved = db.get(Prediccion, result["db_id"])
            assert LocalPredictionAudio(local_root).read(1, saved.ruta_audio_prueba) == stream.getvalue()
        for credentials, expected in (({}, 401), (headers(2), 404)):
            effects.clear()
            denied = client.post(f"/api/predict?model_id={requested}", files=files, headers=credentials)
            assert denied.status_code == expected, denied.text
            assert key not in denied.text
            assert effects == []
        effects.clear()
        confirm_upload[0] = False
        failed = client.post(f"/api/predict?model_id={requested}", files=files, headers=headers(1))
        assert failed.status_code == 200, failed.text
        assert failed.json()["gcp_upload"] is False
        assert failed.json()["local_audio_saved"] is True
        assert effects == ["predict"]
        if selection == "canonical":
            review = client.post('/api/feedback', headers=headers(1), json={
                'id_prediccion': result['db_id'], 'fue_correcta': True})
            assert review.status_code == 201, review.text
            feedback_id = review.json()['id_retroalimentacion']
            pending = client.get('/api/feedback/pending', headers=headers(1))
            assert pending.status_code == 200, pending.text
            assert [row['id_retroalimentacion'] for row in pending.json()] == [feedback_id]
            for denied_headers, expected_status in (({}, 401), (headers(2), 404)):
                denied = client.post(f'/api/feedback/{feedback_id}/approve', headers=denied_headers)
                assert denied.status_code == expected_status, denied.text
            approved = client.post(f'/api/feedback/{feedback_id}/approve', headers=headers(1))
            assert approved.status_code == 200, approved.text
            assert approved.json()['local_status'] == 'incorporated'
            assert approved.json()['sync_status'] == 'pending'
            assert effects == ['predict']
            assert client.get('/api/feedback/pending', headers=headers(1)).json() == []
            before_files = {p: p.read_bytes() for p in (local_root / 'local_predictions').rglob('*.wav')}
            from app.services.predictors.base import ModelWeightsError
            def broken_predict(predictor, path):
                raise ModelWeightsError('synthetic inference failure')
            with monkeypatch.context() as failures:
                failures.setattr(TrainedModelPredictor, 'predict', broken_predict)
                inference_failed = client.post(f'/api/predict?model_id={requested}', files=files, headers=headers(1))
                assert inference_failed.status_code == 503, inference_failed.text
            assert {p: p.read_bytes() for p in (local_root / 'local_predictions').rglob('*.wav')} == before_files
            original_commit = sessions.class_.commit
            def broken_commit(db):
                if any(isinstance(row, Prediccion) for row in (*db.new, *db.identity_map.values())):
                    raise RuntimeError('synthetic prediction commit failure')
                return original_commit(db)
            with monkeypatch.context() as failures:
                failures.setattr(sessions.class_, 'commit', broken_commit)
                commit_failed = client.post(f'/api/predict?model_id={requested}', files=files, headers=headers(1))
                assert commit_failed.status_code == 500, commit_failed.text
                assert 'synthetic prediction commit failure' not in commit_failed.text
            assert {p: p.read_bytes() for p in (local_root / 'local_predictions').rglob('*.wav')} == before_files
            assert client.get('/api/feedback/pending', headers=headers(1)).json() == []
            # A committed row must retain its source even if the commit reply
            # or the subsequent refresh fails. No successful HTTP is fabricated.
            for ambiguous_stage in ('commit-reply', 'refresh'):
                with sessions() as db:
                    before_ids = {row.id_prediccion for row in db.query(Prediccion).all()}
                def ambiguous_commit(db):
                    prediction_pending = any(isinstance(row, Prediccion) for row in (*db.new, *db.identity_map.values()))
                    original_commit(db)
                    if prediction_pending:
                        raise RuntimeError('synthetic commit acknowledgement lost')
                original_refresh = sessions.class_.refresh
                def broken_refresh(db, instance, *args, **kwargs):
                    if isinstance(instance, Prediccion):
                        raise RuntimeError('synthetic committed prediction refresh failure')
                    return original_refresh(db, instance, *args, **kwargs)
                with monkeypatch.context() as failures:
                    failures.setattr(sessions.class_, 'commit' if ambiguous_stage == 'commit-reply' else 'refresh',
                                     ambiguous_commit if ambiguous_stage == 'commit-reply' else broken_refresh)
                    uncertain = client.post(f'/api/predict?model_id={requested}', files=files, headers=headers(1))
                    assert uncertain.status_code == 500, uncertain.text
                    assert uncertain.json() == {'detail': 'No fue posible registrar la predicción local.'}
                with sessions() as db:
                    created = [row for row in db.query(Prediccion).all() if row.id_prediccion not in before_ids]
                    assert len(created) == 1
                    assert LocalPredictionAudio(local_root).read(1, created[0].ruta_audio_prueba) == stream.getvalue()
                assert client.get('/api/feedback/pending', headers=headers(1)).json() == []
            # If both commit and the reference check are uncertain, preserve
            # only this private source; never invent a DB row or auto-incorporate.
            with sessions() as db:
                before_count = db.query(Prediccion).count()
            before_keys = {str(p.relative_to(local_root)) for p in (local_root / 'local_predictions').rglob('*.wav')}
            original_query = sessions.class_.query
            lost_commit = [False]
            def unknown_commit(db):
                if any(isinstance(row, Prediccion) for row in (*db.new, *db.identity_map.values())):
                    lost_commit[0] = True
                    raise RuntimeError('synthetic unavailable commit')
                return original_commit(db)
            def unknown_reference(db, *entities, **kwargs):
                if lost_commit[0] and entities == (Prediccion,):
                    raise RuntimeError('synthetic unavailable reference query')
                return original_query(db, *entities, **kwargs)
            with monkeypatch.context() as failures:
                failures.setattr(sessions.class_, 'commit', unknown_commit)
                failures.setattr(sessions.class_, 'query', unknown_reference)
                uncertain = client.post(f'/api/predict?model_id={requested}', files=files, headers=headers(1))
                assert uncertain.status_code == 500, uncertain.text
                assert uncertain.json() == {'detail': 'No fue posible registrar la predicción local.'}
            with sessions() as db:
                assert db.query(Prediccion).count() == before_count
            after_keys = {str(p.relative_to(local_root)) for p in (local_root / 'local_predictions').rglob('*.wav')}
            assert len(after_keys - before_keys) == 1
            retained_key = (after_keys - before_keys).pop()
            assert LocalPredictionAudio(local_root).read(1, retained_key) == stream.getvalue()
            # Cancellation at the durable-write boundary has no confirmed key
            # or DB result. Retain bytes rather than guess that deletion is safe.
            import asyncio
            from concurrent.futures import CancelledError as FutureCancelledError
            original_save = LocalPredictionAudio.save
            def cancelled_after_write(store, owner, audio):
                original_save(store, owner, audio)
                raise asyncio.CancelledError()
            before_keys = after_keys
            with monkeypatch.context() as failures:
                failures.setattr(LocalPredictionAudio, 'save', cancelled_after_write)
                try:
                    cancelled = client.post(f'/api/predict?model_id={requested}', files=files, headers=headers(1))
                except FutureCancelledError:
                    cancelled = None
                if cancelled is not None:
                    assert cancelled.status_code == 500, cancelled.text
                    assert 'local_audio_saved' not in cancelled.text
            with sessions() as db:
                assert db.query(Prediccion).count() == before_count
            after_keys = {str(p.relative_to(local_root)) for p in (local_root / 'local_predictions').rglob('*.wav')}
            assert len(after_keys - before_keys) == 1
            assert LocalPredictionAudio(local_root).read(1, (after_keys - before_keys).pop()) == stream.getvalue()
            assert client.get('/api/feedback/pending', headers=headers(1)).json() == []
            recovered = client.post(f'/api/predict?model_id={requested}', files=files, headers=headers(1))
            assert recovered.status_code == 200, recovered.text
            assert recovered.json()['local_audio_saved'] is True
            assert 'upload' not in effects
        public = client.get("/api/models", headers=headers(1))
        assert public.status_code == 200, public.text
        assert key not in public.text
        assert public.json()["default_model_id"] == "legacy-public"
        assert registry.get_default_model_id() == "legacy-public"
    with sessions() as db:
        assert {row["id"]: row["active"] for row in runtime.get_history(db, owner_id=1)} == before


def test_cached_public_legacy_keeps_db_failure_after_real_inference(training_env, tmp_path, monkeypatch):
    import hashlib
    import io
    import wave
    import numpy as np
    import torch
    from sqlalchemy.exc import SQLAlchemyError
    from sqlalchemy.orm import Session
    from tests.test_api_training import main
    from tests.test_imported_training_evaluation import checkpoint_payload
    from poc.train import AudioCNN
    from app.database import get_db
    from app.services.registry import ModelRegistry, get_model_registry
    from app.services.predictors.trained_predictor import TrainedModelPredictor

    runtime, sessions, _, _ = training_env
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    payload = checkpoint_payload()
    payload.pop("imported_source")
    payload.pop("job_id")
    payload.update(dataset_name="Historical", dataset_id=None,
                   state_dict=AudioCNN(num_classes=2).state_dict())
    checkpoint = runtime.checkpoints_dir / "cached-public.pt"
    checkpoint.parent.mkdir(parents=True, exist_ok=True)
    torch.save(payload, checkpoint)
    predictor = TrainedModelPredictor(checkpoint, model_id="legacy-public", lazy_load=False,
        expected_checkpoint_sha256=hashlib.sha256(checkpoint.read_bytes()).hexdigest())
    registry = ModelRegistry()
    registry.register(predictor, is_default=True)
    effects = []
    class UnavailableBindSession(Session):
        # Inject only SQL bind resolution failure after delivering a real Session.
        # This is not a live database outage or a failure of session construction.
        def get_bind(self, *args, **kwargs):
            from app.models.prediction import Prediccion
            if any(isinstance(row, Prediccion) for row in self.new):
                effects.append("database")
                raise SQLAlchemyError("synthetic-db-unavailable")
            return super().get_bind(*args, **kwargs)
    def database():
        with UnavailableBindSession(bind=sessions.kw["bind"]) as db:
            yield db
    async def upload(audio_bytes, **kwargs):
        effects.append("upload")
        return True
    real_predict = TrainedModelPredictor.predict
    def observed_predict(selected, path):
        effects.append("predict")
        return real_predict(selected, path)
    monkeypatch.setattr(main, "upload_audio_to_gcp", upload)
    monkeypatch.setattr(TrainedModelPredictor, "predict", observed_predict)
    app = FastAPI()
    app.add_api_route("/api/predict", main.predict_audio, methods=["POST"])
    app.dependency_overrides[get_db] = database
    app.dependency_overrides[get_model_registry] = lambda: registry
    from app.services.auth import create_user
    with sessions() as db:
        create_user(db, "legacy-admin@example.test", "SyntheticPassword2026!", "Synthetic", "administrador")
    stream = io.BytesIO()
    with wave.open(stream, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(8000)
        audio.writeframes((np.sin(2 * np.pi * 440 * np.arange(8000) / 8000) * 12000).astype("<i2").tobytes())
    with TestClient(app, raise_server_exceptions=False, headers=cookie_headers(sessions, 1)) as client:
        response = client.post("/api/predict?model_id=legacy-public",
            files={"file": ("synthetic.wav", stream.getvalue(), "audio/wav")})
    assert response.status_code == 500, response.text
    assert response.json() == {"detail":
        "Fallo al registrar la predicción en PostgreSQL: synthetic-db-unavailable"}
    assert effects == ["upload", "predict", "database"]


def test_imported_predict_cookie_credentials_and_origin(cohort, training_env, tmp_path, monkeypatch):
    from tests.test_api_training import main
    from tests.test_web_session_integration import login, ORIGIN, PASSWORD
    from tests.test_prediction_audio_metadata import synthetic_wav
    from app.database import get_db
    from app.models.user import Usuario
    from app.routes.auth import router as auth_router
    from app.services import auth
    from app.services.registry import ModelRegistry, get_model_registry
    from app.services.predictors.trained_predictor import TrainedModelPredictor

    runtime, sessions, model_id, _ = _complete_imported_cpu_worker(
        cohort, training_env, tmp_path, monkeypatch
    )
    monkeypatch.setenv("FAMA_WEB_ORIGIN", ORIGIN)
    monkeypatch.setenv("FAMA_ALLOW_INSECURE_LOOPBACK", "1")
    monkeypatch.setenv("FAMA_IMPORT_ROOT", str(cohort[0].source.root))
    monkeypatch.setenv("FAMA_RATE_LIMIT_KEY", "synthetic-model-cookie-rate-key-for-isolated-tests")
    monkeypatch.setattr(auth, "SECRET_KEY", "synthetic-model-cookie-bearer-key-2026")
    with sessions() as db:
        for uid in (1, 2):
            db.add(Usuario(id=uid, email=f"user{uid}@example.test",
                password_hash=auth.hash_password(PASSWORD), nombre_completo="Synthetic",
                rol="administrador", activo=True))
        db.commit()
    registry, effects = ModelRegistry(), []
    monkeypatch.setattr(main, "training_service", runtime)
    async def upload(audio_bytes, **kwargs):
        effects.append("upload")
        return True
    real_predict = TrainedModelPredictor.predict
    def observed_predict(predictor, path):
        effects.append("predict")
        return real_predict(predictor, path)
    monkeypatch.setattr(main, "upload_audio_to_gcp", upload)
    monkeypatch.setattr(TrainedModelPredictor, "predict", observed_predict)
    app = FastAPI()
    app.include_router(auth_router)
    app.add_api_route("/api/predict", main.predict_audio, methods=["POST"])
    def database():
        with sessions() as db:
            yield db
    app.dependency_overrides[get_db] = database
    app.dependency_overrides[get_model_registry] = lambda: registry
    from tests.test_cookie_identity import legacy_bearer
    token = lambda uid: "Bearer " + legacy_bearer(uid)
    key = f"fama_trained_model_{model_id}"
    files = {"file": ("synthetic.wav", synthetic_wav(frames=8000, rate=8000), "audio/wav")}
    with TestClient(app, raise_server_exceptions=False) as client:
        authenticated = login(client)
        assert authenticated.status_code == 200, authenticated.text
        for headers in ({"Origin": ORIGIN}, {"Origin": ORIGIN, "Authorization": token(1)},
                        {"Origin": ORIGIN, "Authorization": "Bearer invalid"},
                        {"Origin": ORIGIN, "Authorization": token(2)}):
            effects.clear()
            accepted = client.post(f"/api/predict?model_id={key}", files=files, headers=headers)
            assert accepted.status_code == 200, accepted.text
            assert accepted.json()["modelo_id"] == key
            assert accepted.json()["local_audio_saved"] is True
            assert accepted.json()["gcp_upload"] is False
            assert effects == ["predict"]
        for headers, expected in (
                ({}, 403), ({"Origin": "https://foreign.example.test"}, 403)):
            effects.clear()
            denied = client.post(f"/api/predict?model_id={key}", files=files, headers=headers)
            assert denied.status_code == expected, denied.text
            assert key not in denied.text
            assert effects == []
        foreign = login(client, 2)
        assert foreign.status_code == 200, foreign.text
        effects.clear()
        denied = client.post(f"/api/predict?model_id={key}", files=files, headers={"Origin": ORIGIN})
        assert denied.status_code == 404, denied.text
        assert key not in denied.text
        assert effects == []
