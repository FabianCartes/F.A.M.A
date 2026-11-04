"""Browser session reaches the existing T3 public source/lifecycle contract."""
from tests.test_api_training import client
from tests.test_training_flow import training_env
from tests.test_dataset_import_api import imports
from tests.test_imported_dataset_preparation import cohort, create
from tests.test_imported_training_admission import authenticated


def test_browser_identity_guards_real_imported_source_and_lifecycle(
        client, training_env, cohort, tmp_path, authenticated, monkeypatch):
    from app.models.user import Usuario
    from app.services import auth, training
    from app.services.imported_training_source import ImportedTrainingSource
    from training.imported_dataset_preparation import ImportedDatasetPreparation
    from scripts.migrate_imported_training_source import migrate_imported_sources
    from tests.test_web_session_integration import login, ORIGIN, PASSWORD
    monkeypatch.setenv("FAMA_WEB_ORIGIN", ORIGIN)
    monkeypatch.setenv("FAMA_ALLOW_INSECURE_LOOPBACK", "1")
    monkeypatch.setenv("FAMA_RATE_LIMIT_KEY", "synthetic-web-training-rate-key-for-isolated-tests")
    # Public progress includes a wall-clock duration; freeze only that boundary.
    monkeypatch.setattr(training.time, "time", lambda: 2000.0)
    runtime, sessions, _, process = training_env
    with sessions() as db:
        for index in (1, 2):
            user = db.get(Usuario, index)
            user.email = f"user{index}@example.test"
            user.password_hash = auth.hash_password(PASSWORD)
        db.get(Usuario, 2).rol = "administrador"
        db.commit()
    monkeypatch.setattr(training, "SessionLocal", cohort[0].sessions)
    migrate_imported_sources(cohort[0].sessions.kw["bind"], writers_stopped=True)
    preparations = ImportedDatasetPreparation(cohort[0], tmp_path / "web-prepared")
    prepared = create(preparations, cohort)
    runtime.imported_sources = ImportedTrainingSource(preparations)
    body = {"imported_dataset_id": cohort[5], "snapshot_id": cohort[1]["id"],
            "imported_prepared_version": prepared["version_id"], "architecture": "AudioCNN"}
    legacy = client.get("/api/training/datasets").json()
    before = client.get("/api/training/progress").json()
    assert login(client, 2).status_code == 200
    assert client.get("/api/training/datasets?include_imported=true").json() == legacy
    denied = client.post("/api/training/start", json=body, headers={"Origin": ORIGIN})
    assert denied.status_code == 404, denied.text
    assert client.get("/api/training/progress").json() == before
    process.assert_not_called()
    assert login(client).status_code == 200
    catalog = client.get("/api/training/datasets?include_imported=true")
    assert catalog.status_code == 200, catalog.text
    assert [row["id"] for row in catalog.json()["datasets"] if row.get("source_type") == "imported"] == [cohort[5]]
    # Invalid Bearer cannot use an otherwise valid browser session.
    rejected = client.post("/api/training/start", json=body,
                           headers={"Origin": ORIGIN, "Authorization": "Bearer invalid"})
    assert rejected.status_code == 401
    assert client.get("/api/training/progress").json() == before
    process.assert_not_called()
    admitted = client.post("/api/training/start", json=body, headers={"Origin": ORIGIN})
    assert admitted.status_code == 200, admitted.text
    state = client.get("/api/training/progress").json()
    assert login(client, 2).status_code == 200
    for method, path in (("get", "/api/training/progress"), ("post", "/api/training/stop")):
        result = getattr(client, method)(path, headers={"Origin": ORIGIN})
        assert result.status_code == 404, result.text
        assert runtime.get_progress() == state
    assert login(client).status_code == 200
    assert client.get("/api/training/progress").json() == state
    assert client.get("/api/training/history?include_imported=true").status_code == 200
    assert client.post("/api/training/stop", headers={"Origin": ORIGIN}).status_code == 200
