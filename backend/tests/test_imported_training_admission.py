"""Imported training admission through HTTP with real T1/T2 synthetic sources."""
import pytest
from tests.http_security import cookie_headers, cookie_security

from tests.test_api_training import client
from tests.test_training_flow import training_env, register, partitions
from tests.test_dataset_import_api import imports
from tests.test_imported_dataset_preparation import cohort, create


def test_imported_start_requires_auth_before_admission(client, training_env, cohort, tmp_path):
    runtime, sessions, root, process = training_env
    # A valid legacy decoy proves imported selection cannot silently fall back.
    register(sessions, "AvesChilenas")
    partitions(root, "AvesChilenas")
    from training.imported_dataset_preparation import ImportedDatasetPreparation
    preparations = ImportedDatasetPreparation(cohort[0], tmp_path / "imported-prepared")
    prepared = create(preparations, cohort)
    before = client.get("/api/training/progress").json()
    history = client.get("/api/training/history").json()
    response = client.post("/api/training/start", json={
        "imported_dataset_id": cohort[5], "snapshot_id": cohort[1]["id"],
        "imported_prepared_version": prepared["version_id"],
    })
    assert response.status_code == 401, response.text
    assert response.json() == {"detail": "Sesión requerida o expirada."}
    assert client.get("/api/training/progress").json() == before
    assert client.get("/api/training/history").json() == history
    process.assert_not_called()


@pytest.fixture
def authenticated(training_env, monkeypatch):
    from app.models.user import Usuario
    from app.services import auth
    monkeypatch.setattr(auth, "SECRET_KEY", "synthetic-t3-signing-key-not-a-production-secret-2026")
    with training_env[1]() as db:
        db.add(Usuario(id=1, email="owner@example.test", password_hash="unused",
                       nombre_completo="Owner", rol="investigador", activo=True))
        db.add(Usuario(id=2, email="foreign@example.test", password_hash="unused",
                       nombre_completo="Synthetic", rol="investigador", activo=True))
        db.commit()
    return cookie_headers(training_env[1], 2)


def test_foreign_imported_start_is_non_disclosing(client, training_env, cohort, tmp_path, authenticated):
    from app.services.imported_training_source import ImportedTrainingSource
    from training.imported_dataset_preparation import ImportedDatasetPreparation
    runtime, sessions, root, process = training_env
    register(sessions, "AvesChilenas")
    partitions(root, "AvesChilenas")
    preparations = ImportedDatasetPreparation(cohort[0], tmp_path / "imported-prepared")
    prepared = create(preparations, cohort)
    runtime.imported_sources = ImportedTrainingSource(preparations)
    before = client.get("/api/training/progress").json()
    history = client.get("/api/training/history").json()
    for dataset_id, snapshot_id in ((cohort[5], cohort[1]["id"]), ("0" * 32, "0" * 32)):
        response = client.post("/api/training/start", headers=authenticated, json={
            "imported_dataset_id": dataset_id, "snapshot_id": snapshot_id,
            "imported_prepared_version": prepared["version_id"], "architecture": "AudioCNN",
        })
        assert response.status_code == 404, response.text
        assert response.json() == {"detail": {"code": "source_unavailable", "message": "Fuente importada no disponible."}}
        assert client.get("/api/training/progress").json() == before
        assert client.get("/api/training/history").json() == history
        process.assert_not_called()


def test_imported_progress_stop_and_history_require_owner(client, training_env, cohort, tmp_path, authenticated, monkeypatch):
    import pickle
    from app.services import auth
    from app.services.imported_training_source import ImportedTrainingSource
    from training.imported_dataset_preparation import ImportedDatasetPreparation
    from scripts.migrate_imported_training_source import migrate_imported_sources
    runtime, sessions, _, process = training_env
    from app.services import training
    monkeypatch.setattr(training, "SessionLocal", cohort[0].sessions)
    migrate_imported_sources(cohort[0].sessions.kw["bind"], writers_stopped=True)
    preparations = ImportedDatasetPreparation(cohort[0], tmp_path / "imported-prepared")
    prepared = create(preparations, cohort)
    runtime.imported_sources = ImportedTrainingSource(preparations)
    owner = cookie_headers(training_env[1], 1)
    response = client.post("/api/training/start", headers=owner, json={
        "imported_dataset_id": cohort[5], "snapshot_id": cohort[1]["id"],
        "imported_prepared_version": prepared["version_id"], "architecture": "AudioCNN",
    })
    assert response.status_code == 200, response.text
    config = pickle.loads(pickle.dumps(process.call_args.kwargs["args"][0]))
    assert config["source"]["identity"]["preparation_version"] == prepared["version_id"]
    before = runtime.get_progress()
    for method, path in (("get", "/api/training/progress"), ("post", "/api/training/stop")):
        response = getattr(client, method)(path)
        assert response.status_code == 401, response.text
        response = getattr(client, method)(path, headers=authenticated)
        assert response.status_code == 404, response.text
        assert response.json() == {"detail": "Recurso de entrenamiento no disponible."}
        assert runtime.get_progress() == before
    assert client.get("/api/training/progress", headers=owner).json() == before
    assert client.get("/api/training/history?include_imported=true").status_code == 401
    assert client.get("/api/training/history?include_imported=true", headers=owner).status_code == 200
    assert client.post("/api/training/stop", headers=owner).status_code == 200


def test_imported_catalog_requires_auth_and_preserves_legacy_catalog(client, training_env, cohort, tmp_path, authenticated, monkeypatch):
    from app.services import auth
    from app.services.imported_training_source import ImportedTrainingSource
    from training.imported_dataset_preparation import ImportedDatasetPreparation
    runtime = training_env[0]
    from scripts.migrate_imported_training_source import migrate_imported_sources
    migrate_imported_sources(cohort[0].sessions.kw["bind"], writers_stopped=True)
    preparations = ImportedDatasetPreparation(cohort[0], tmp_path / "imported-prepared")
    prepared = create(preparations, cohort)
    runtime.imported_sources = ImportedTrainingSource(preparations)
    def no_audio_reads(*args, **kwargs):
        pytest.fail("Catalog must not iterate snapshot audio")

    monkeypatch.setattr(cohort[0], "iter_verified", no_audio_reads)
    legacy = client.get("/api/training/datasets").json()
    assert client.get("/api/training/datasets?include_imported=true").status_code == 401
    foreign = client.get("/api/training/datasets?include_imported=true", headers=authenticated)
    assert foreign.status_code == 200, foreign.text
    assert foreign.json() == legacy
    owner = cookie_headers(training_env[1], 1)
    response = client.get("/api/training/datasets?include_imported=true", headers=owner)
    assert response.status_code == 200, response.text
    imported, = [row for row in response.json()["datasets"] if row.get("source_type") == "imported"]
    assert imported["id"] == cohort[5]
    choice, = imported["preparations"]
    assert choice["snapshot_id"] == cohort[1]["id"]
    assert choice["prepared_version"] == prepared["version_id"]
    assert choice["eligible"] is True
    assert choice["reasons"] == []
    assert choice["seed"] == 42
    assert choice["policy"]["name"] == "group-cover-v1"
    assert choice["policy"]["target"] == [0.8, 0.1, 0.1]
    assert choice["provenance"] == {"source": "synthetic annotations v1"}
    assert client.get("/api/training/datasets").json() == legacy


@pytest.mark.parametrize("damage,code,message", [
    ("snapshot", "source_unavailable", "Fuente importada no disponible."),
    ("schema", "source_unavailable", "Fuente importada no disponible."),
    ("version", "source_unavailable", "Fuente importada no disponible."),
    ("incomplete", "source_unavailable", "Fuente importada no disponible."),
    ("hash", "source_unavailable", "Fuente importada no disponible."),
    ("missing", "source_unavailable", "Fuente importada no disponible."),
    ("split", "source_unavailable", "Fuente importada no disponible."),
    ("architecture", "profile_conflict", "La arquitectura no coincide con el perfil preparado."),
    ("audio", "profile_conflict", "El audio solicitado no coincide con el perfil preparado."),
    ("window", "profile_conflict", "Las ventanas no coinciden con el perfil preparado."),
])
def test_owned_invalid_selection_has_no_admission_effects(client, training_env, cohort, tmp_path,
                                                         authenticated, damage, code, message, monkeypatch):
    from app.services import auth
    from app.services.imported_training_source import ImportedTrainingSource
    from training.imported_dataset_preparation import ImportedDatasetPreparation
    runtime, _, _, process = training_env
    preparations = ImportedDatasetPreparation(cohort[0], tmp_path / "imported-prepared")
    prepared = create(preparations, cohort)
    runtime.imported_sources = ImportedTrainingSource(preparations)
    body = {"imported_dataset_id": cohort[5], "snapshot_id": cohort[1]["id"],
            "imported_prepared_version": prepared["version_id"], "architecture": "AudioCNN"}
    if damage == "schema":
        from sqlalchemy import MetaData, Table, Column, Integer
        from app.models.imported_training_source import ImportedModelSource
        from app.services import training
        engine = cohort[0].sessions.kw["bind"]
        ImportedModelSource.__table__.drop(engine, checkfirst=True)
        Table("imported_model_source", MetaData(), Column("model_id", Integer, primary_key=True)).create(engine)
        monkeypatch.setattr(training, "SessionLocal", cohort[0].sessions)
    elif damage == "snapshot":
        body["snapshot_id"] = "0" * 32
    elif damage == "version":
        body["imported_prepared_version"] = "0" * 64
    elif damage == "architecture":
        body["architecture"] = "PANNs-CNN14"
    elif damage == "audio":
        body["audio_config"] = {"target_sr": 16000, "f_max": 8000}
    elif damage == "window":
        body["windowing_config"] = {"hop_seconds": 0.25}
    elif damage == "incomplete":
        from app.models.training_snapshot import TrainingSnapshot
        with cohort[0].sessions() as db:
            db.get(TrainingSnapshot, cohort[1]["id"]).state = "building"
            db.commit()
    elif damage == "split":
        path = preparations.root / prepared["version_id"] / "test.csv"
        path.chmod(0o600)
        path.write_bytes(b"bad partition")
    else:
        member = next(cohort[0].iter_verified(1, cohort[1]["id"]))[0]
        path = cohort[0].root / cohort[1]["id"] / member["member_id"]
        if damage == "missing":
            path.rename(path.with_suffix(".retained"))
        else:
            path.chmod(0o600)
            path.write_bytes(b"modified audio")
    owner = cookie_headers(training_env[1], 1)
    before = runtime.get_progress()
    history = client.get("/api/training/history").json()
    response = client.post("/api/training/start", headers=owner, json=body)
    assert response.status_code == 404, response.text
    assert response.json() == {"detail": {"code": code, "message": message}}
    assert runtime.get_progress() == before
    assert client.get("/api/training/history").json() == history
    process.assert_not_called()


def test_invalid_credentials_cannot_fall_back_from_imported_selection(client, training_env, authenticated):
    _, sessions, root, process = training_env
    register(sessions, "AvesChilenas")
    partitions(root, "AvesChilenas")
    before = training_env[0].get_progress()
    response = client.post("/api/training/start", headers={"Authorization": "Bearer invalid"},
                           json={"imported_dataset_id": "a" * 32, "snapshot_id": "b" * 32,
                                 "imported_prepared_version": "c" * 64, "architecture": "AudioCNN"})
    assert response.status_code == 401, response.text
    assert response.json() == {"detail": "Sesión requerida o expirada."}
    assert training_env[0].get_progress() == before
    process.assert_not_called()


@pytest.mark.parametrize("path", ["datasets", "history", "progress"])
def test_legacy_queries_preserve_access_without_using_supplied_credentials(client, training_env, path):
    expected = client.get("/api/training/" + path)
    response = client.get("/api/training/" + path, headers={"Authorization": "Bearer invalid"})
    assert response.status_code == expected.status_code == 200
    assert response.json() == expected.json()


@pytest.mark.parametrize("body", [
    {"snapshot_id": "a" * 32}, {"imported_dataset_id": "b" * 32},
    {"imported_dataset_id": "b" * 32, "snapshot_id": "a" * 32, "imported_prepared_version": "c" * 64,
     "dataset_name": "AvesChilenas"},
    {"imported_dataset_id": "b" * 32, "snapshot_id": "a" * 32, "imported_prepared_version": "c" * 64,
     "allow_historical_preparation": True},
    {"imported_dataset_id": "b" * 32, "snapshot_id": "a" * 32, "imported_prepared_version": "c" * 64,
     "owner_id": 1},
])
def test_imported_selection_is_complete_and_exclusive(client, training_env, body):
    before = training_env[0].get_progress()
    response = client.post("/api/training/start", json=body)
    assert response.status_code == 422, response.text
    assert training_env[0].get_progress() == before
    training_env[3].assert_not_called()


@pytest.mark.parametrize("subject", ["-1", "3", "1"])
def test_imported_resources_require_real_existing_active_user(
    client, training_env, authenticated, subject,
):
    from app.services import auth
    from app.models.user import Usuario
    if subject == "1":
        with training_env[1]() as db:
            db.get(Usuario, 1).activo = False
            db.commit()
    headers = cookie_headers(training_env[1], subject)
    message = "Sesión requerida o expirada."
    before = training_env[0].get_progress()
    for path in ("datasets", "history"):
        response = client.get("/api/training/" + path + "?include_imported=true", headers=headers)
        assert response.status_code == 401, response.text
        assert response.json() == {"detail": message}
    response = client.post("/api/training/start", headers=headers, json={
        "imported_dataset_id": "a" * 32, "snapshot_id": "b" * 32,
        "imported_prepared_version": "c" * 64, "architecture": "AudioCNN",
    })
    assert response.status_code == 401, response.text
    assert response.json() == {"detail": message}
    assert training_env[0].get_progress() == before
    training_env[3].assert_not_called()
