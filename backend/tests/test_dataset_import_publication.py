"""Confirmed ZIP publication into the shared catalog, through public interfaces only."""
import base64
import hashlib
from types import SimpleNamespace

import pytest
from google.api_core.exceptions import NotFound, PreconditionFailed

from tests.test_dataset_import_api import imports, prepare, confirm, operation
from tests.test_dataset_zip_validation import wav_bytes
from tests.test_training_flow import training_env
from tests.http_security import cookie_headers, cookie_security, COOKIE_ORIGIN

BASE = "/api/ingestion/imports"


@pytest.fixture
def bucket(monkeypatch):
    objects, failures = {}, set()

    class Blob:
        def __init__(self, name):
            self.name = name

        @property
        def md5_hash(self):
            return base64.b64encode(hashlib.md5(objects[self.name], usedforsecurity=False).digest()).decode()

        def reload(self):
            if self.name not in objects:
                raise NotFound("missing")

        def upload_from_string(self, content, **kwargs):
            if self.name in failures:
                raise OSError("synthetic provider failure")
            if kwargs.get("if_generation_match") == 0 and self.name in objects:
                raise PreconditionFailed("exists")
            objects[self.name] = content

    class Client:
        def bucket(self, name):
            return SimpleNamespace(blob=Blob)

    monkeypatch.setattr("google.cloud.storage.Client", Client)
    return SimpleNamespace(objects=objects, failures=failures)


@pytest.fixture
def published(imports, bucket, tmp_path):
    from app.models.user import Usuario
    from app.services.dataset_import_execution import ImportExecution
    from app.services.ingestion import IngestionService
    client, service, app, sessions = imports
    with sessions() as db:
        for identity in (1, 2):
            db.add(Usuario(id=identity, email=f"u{identity}@example.test", password_hash="x", rol="investigador"))
        db.commit()
    publisher = IngestionService(bucket_name="test-bucket", local_base_dir=tmp_path / "raw")
    previous = client.execution
    client.execution = ImportExecution(previous.queue, service, previous.root, publisher=publisher)
    return SimpleNamespace(client=client, sessions=sessions, bucket=bucket, raw=tmp_path / "raw", app=app)


def names_for(sessions, user_id):
    from app.models.user import Usuario
    from app.services.access import ResourceAccess
    with sessions() as db:
        return ResourceAccess(db, db.get(Usuario, user_id)).names


def test_confirm_publishes_objects_rows_local_copy_and_assigns_only_the_importer(published, tmp_path):
    from app.models.dataset import Audio, ConjuntoDatos
    client = published.client
    result = confirm(client, prepare(client, tmp_path, name="Aves"))
    assert result.status_code == 200, result.text
    assert result.json()["status"] == "imported"
    assert result.json()["execution"]["status"] == "succeeded"
    assert published.bucket.objects == {"datasets/Aves/birds/a.wav": wav_bytes()}
    with published.sessions() as db:
        dataset = db.query(ConjuntoDatos).filter_by(nombre="Aves").one()
        audio = db.query(Audio).filter_by(id_conjunto_datos=dataset.id_conjunto_datos).one()
        assert (dataset.cantidad_audios, dataset.id_usuario_carga) == (1, 1)
        assert (audio.clase, audio.nombre_archivo, audio.hash_archivo) == (
            "birds", "a.wav", hashlib.sha256(wav_bytes()).hexdigest())
    assert (published.raw / "Aves" / "birds" / "a.wav").read_bytes() == wav_bytes()
    assert names_for(published.sessions, 1) == {"Aves"}
    assert names_for(published.sessions, 2) == set()


def test_failed_publication_keeps_local_import_and_retry_uploads_only_missing(published, tmp_path):
    from app.models.dataset import ConjuntoDatos
    from app.models.dataset_import_job import ImportJob
    client = published.client
    entries = [("birds/a.wav", wav_bytes(1)), ("birds/b.wav", wav_bytes(2))]
    published.bucket.failures.add("datasets/Aves/birds/b.wav")
    failed = confirm(client, prepare(client, tmp_path, name="Aves", entries=entries))
    assert failed.json()["status"] == "failed"
    job = client.get(f"{BASE}/{failed.json()['import_id']}").json()
    assert job["status"] == "imported"
    assert job["added_count"] == 2
    assert set(published.bucket.objects) == {"datasets/Aves/birds/a.wav"}
    with published.sessions() as db:
        assert db.query(ImportJob).filter(ImportJob.status.in_(("queued", "running"))).count() == 0
    published.bucket.failures.clear()
    retried = client.post(f"{BASE}/{job['id']}/jobs/{job['execution']['id']}/retry", json={"request_key": "retry-1"})
    assert retried.status_code == 202, retried.text
    assert client.execution.run_once()
    final = client.get(f"{BASE}/{job['id']}").json()
    assert (final["status"], final["execution"]["status"]) == ("imported", "succeeded")
    assert published.bucket.objects == {f"datasets/Aves/{path}": content for path, content in entries}
    with published.sessions() as db:
        assert db.query(ConjuntoDatos).filter_by(nombre="Aves").one().cantidad_audios == 2


def test_duplicate_global_name_is_rejected_before_upload(published, tmp_path):
    from app.models.dataset import ConjuntoDatos
    client = published.client
    with published.sessions() as db:
        db.add(ConjuntoDatos(nombre="Aves", ruta_gcp="gs://test-bucket/datasets/Aves/", id_usuario_carga=2))
        db.commit()
    response = client.post(BASE, json={"request_key": "dup", "name": "Aves"})
    assert response.status_code == 409
    assert "Aves" not in names_for(published.sessions, 1)
    assert published.bucket.objects == {}


@pytest.mark.parametrize("name", ["a" * 101, "bad/name", "CON", "trailing."])
def test_name_must_be_a_valid_shared_dataset_name(published, name):
    response = published.client.post(BASE, json={"request_key": "invalid", "name": name})
    assert response.status_code == 422


def test_name_taken_after_creation_fails_publication_without_touching_foreign_dataset(published, tmp_path):
    from app.models.dataset import ConjuntoDatos
    client = published.client
    job = prepare(client, tmp_path, name="Aves")
    with published.sessions() as db:
        db.add(ConjuntoDatos(nombre="Aves", ruta_gcp="gs://test-bucket/datasets/Aves/", id_usuario_carga=2))
        db.commit()
    result = confirm(client, job)
    assert result.json()["status"] == "failed"
    assert client.get(f"{BASE}/{job['id']}").json()["status"] == "imported"
    assert published.bucket.objects == {}
    assert names_for(published.sessions, 1) == set()


def test_upload_file_limit_defaults_to_zip_audio_maximum(monkeypatch):
    from app.services.dataset_zip import ImportLimits
    from app.services.ingestion import IngestionService
    monkeypatch.delenv("FAMA_UPLOAD_MAX_FILE_BYTES", raising=False)
    monkeypatch.delenv("FAMA_UPLOAD_MAX_BATCH_BYTES", raising=False)
    assert IngestionService.get_upload_limits() == (ImportLimits().audio_bytes, 256 * 1024 * 1024)


def test_automatic_import_publication_failure_is_retried_through_its_preview_job(published, tmp_path):
    from tests.test_dataset_zip_validation import archive
    client = published.client
    created = client.post(BASE, json={"request_key": "auto", "name": "Aves", "layout": "class_folders",
                                      "auto_import": True}).json()
    data = archive(tmp_path / "auto.zip", [("birds/a.wav", wav_bytes())]).read_bytes()
    assert client.put(f"{BASE}/{created['id']}/archive", content=data,
                      headers={"Content-Type": "application/zip"}).status_code == 200
    published.bucket.failures.add("datasets/Aves/birds/a.wav")
    failed = operation(client, created["id"], "preview", {"root": ""})
    assert failed.json()["status"] == "failed"
    job = client.get(f"{BASE}/{created['id']}").json()
    assert job["status"] == "imported"
    published.bucket.failures.clear()
    retried = client.post(f"{BASE}/{job['id']}/jobs/{job['execution']['id']}/retry", json={"request_key": "retry-auto"})
    assert retried.status_code == 202, retried.text
    assert client.execution.run_once()
    final = client.get(f"{BASE}/{job['id']}").json()
    assert (final["status"], final["execution"]["status"]) == ("imported", "succeeded")
    assert published.bucket.objects == {"datasets/Aves/birds/a.wav": wav_bytes()}
    assert names_for(published.sessions, 1) == {"Aves"}


def test_foreign_dataset_created_during_publication_receives_no_rows_and_no_grant(published, tmp_path, monkeypatch):
    from app.models.dataset import Audio, ConjuntoDatos
    from app.services import ingestion
    client = published.client
    job = prepare(client, tmp_path, name="Aves")
    original = ingestion.IngestionService.upload_files_to_gcs

    def race(self, files, dataset_name, *args, **kwargs):
        raise AssertionError("upload must not start for a foreign name")

    with published.sessions() as db:
        db.add(ConjuntoDatos(nombre="Aves", ruta_gcp="gs://test-bucket/datasets/Aves/", id_usuario_carga=2))
        db.commit()
    monkeypatch.setattr(ingestion.IngestionService, "upload_files_to_gcs", race)
    assert confirm(client, job).json()["status"] == "failed"
    monkeypatch.setattr(ingestion.IngestionService, "upload_files_to_gcs", original)
    with published.sessions() as db:
        assert db.query(Audio).count() == 0
    assert names_for(published.sessions, 1) == set()
    assert published.bucket.objects == {}


@pytest.mark.parametrize("is_tri_model", [False, True])
@pytest.mark.parametrize("changed_local", [False, True])
def test_published_zip_trains_through_a_partition_version_and_rejects_changed_local_copy(
        published, tmp_path, monkeypatch, training_env, cookie_security, is_tri_model, changed_local):
    from app.models.dataset import ConjuntoDatos
    from app.services.partitions import DatasetPartitions, PartitionError
    from app.services import training
    from tests.test_api_training import main
    from training import paths
    runtime, _, _, process = training_env
    monkeypatch.setattr(training, "SessionLocal", published.sessions)
    monkeypatch.setattr(main, "training_service", runtime)
    monkeypatch.setattr(training, "get_raw_data_dir", lambda name=None: published.raw / (name or ""))
    monkeypatch.setattr(paths, "get_raw_data_dir", lambda name=None: published.raw / (name or ""))
    monkeypatch.setattr(paths, "get_processed_data_dir", lambda name=None: tmp_path / "processed" / (name or ""))
    entries = [(f"{label}/{index}.wav", wav_bytes(index + 1)) for index in range(10)
               for label in ["Chucao" if index < 5 else "Canastero"]]
    client = published.client
    assert confirm(client, prepare(client, tmp_path, name="Bosque", entries=entries)).json()["status"] == "imported"

    with published.sessions() as db:
        partitions = DatasetPartitions(db.query(ConjuntoDatos).filter_by(nombre="Bosque").one(), db)
        preview = partitions.preview(validation_percent=20, seed=42, test_percent=20)
        saved = partitions.save(20, 42, preview["version"], True, actor_id=1, test_percent=20)
        source = partitions.training_source(saved["version"])
        assert all(source["recordings"][split] for split in ("train", "val", "test"))
        assert sum(len(source["recordings"][split]) for split in ("train", "val", "test")) == 10
        assert {e["hash_sha256"] for e in saved["entries"]} == {hashlib.sha256(c).hexdigest() for _, c in entries}

    # The same published ZIP reaches the real public start admission, with a
    # deferred process boundary: this does not execute heavy/operational training.
    for path, endpoint, methods in (
            ("/api/training/datasets", main.get_training_datasets, ["GET"]),
            ("/api/training/start", main.start_training_pipeline, ["POST"]),
            ("/api/training/progress", main.get_training_progress, ["GET"]),
            ("/api/training/stop", main.stop_training_pipeline, ["POST"]),
            ("/api/training/history", main.get_training_history, ["GET"])):
        published.app.add_api_route(path, endpoint, methods=methods)
    headers = {**cookie_headers(published.sessions, 1), "Origin": COOKIE_ORIGIN}
    catalog = client.get("/api/training/datasets", headers=headers)
    assert catalog.status_code == 200, catalog.text
    assert [row["id"] for row in catalog.json()["datasets"]] == ["Bosque"]
    body = dict(dataset_name="Bosque", partition_version=saved["version"], is_tri_model=is_tri_model)
    if changed_local:
        (published.raw / "Bosque" / "Chucao" / "0.wav").write_bytes(b"changed")
        with published.sessions() as db:
            partitions = DatasetPartitions(db.query(ConjuntoDatos).filter_by(nombre="Bosque").one(), db)
            with pytest.raises(PartitionError, match="contenido local"):
                partitions.training_source(saved["version"])
        rejected = client.post("/api/training/start", json=body, headers=headers)
        assert rejected.status_code == 400, rejected.text
        assert "contenido local" in rejected.json()["detail"]
        assert client.get("/api/training/progress", headers=headers).json()["status"] == "failed"
        assert client.get("/api/training/history", headers=headers).json() == {"history": []}
        process.assert_not_called()
        return
    admitted = client.post("/api/training/start", json=body, headers=headers)
    assert admitted.status_code == 200, admitted.text
    assert admitted.json()["status"] == "started"
    assert admitted.json()["partition_version"] == saved["version"]
    config = process.call_args.kwargs["args"][0]
    assert config["dataset_name"] == "Bosque"
    assert config["source"]["partition_manifest"]["version"] == saved["version"]
    assert len(config["models"]) == (3 if is_tri_model else 1)
    assert client.get("/api/training/history", headers=headers).json() == {"history": []}
    assert client.post("/api/training/stop", headers=headers).status_code == 200


def test_publication_reports_uploaded_audios_per_batch_until_terminal_result(published, tmp_path, monkeypatch):
    from app.models.dataset_import_job import ImportJob
    from app.services import ingestion
    entries = [("birds/a.wav", wav_bytes(1)), ("birds/b.wav", wav_bytes(2)), ("frogs/c.wav", wav_bytes(3))]
    size = str(max(len(content) for _, content in entries))
    monkeypatch.setenv("FAMA_UPLOAD_MAX_FILE_BYTES", size)
    monkeypatch.setenv("FAMA_UPLOAD_MAX_BATCH_BYTES", size)
    original = ingestion.IngestionService.upload_files_to_gcs
    seen = []

    def observed(self, files, *args, **kwargs):
        with published.sessions() as db:
            row = db.query(ImportJob).filter_by(status="running").one()
            seen.append((row.stage, row.progress, dict(row.result)))
        return original(self, files, *args, **kwargs)

    monkeypatch.setattr(ingestion.IngestionService, "upload_files_to_gcs", observed)
    client = published.client
    result = confirm(client, prepare(client, tmp_path, name="Aves", entries=entries))
    execution = result.json()["execution"]
    assert (result.json()["status"], execution["status"]) == ("imported", "succeeded")
    assert [(stage, counts) for stage, _, counts in seen] == [
        ("publishing", {"uploaded": done, "total": 3}) for done in range(3)]
    progress = [value for _, value, _ in seen]
    assert progress == sorted(progress) and all(1 <= value <= 99 for value in progress)
    assert execution["result"] == {"dataset_id": result.json()["dataset_id"], "added_count": 3}
