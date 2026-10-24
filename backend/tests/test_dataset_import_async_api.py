"""Admission is not completion; authenticated polling is inert and recoverable."""
from types import SimpleNamespace

from tests.test_dataset_import_api import imports
from tests.test_dataset_zip_validation import archive, wav_bytes

BASE = "/api/ingestion/imports"


def uploaded(client, tmp_path):
    source = client.post(BASE, json={"request_key": "source", "name": "Birds"}).json()
    data = archive(tmp_path / "source.zip", [("birds/a.wav", wav_bytes())]).read_bytes()
    assert client.put(f"{BASE}/{source['id']}/archive", content=data,
                      headers={"Content-Type": "application/zip"}).status_code == 200
    return source["id"]


def test_preview_admission_is_202_durable_idempotent_and_does_no_validation(imports, tmp_path, monkeypatch):
    from app.services import dataset_import_execution as module
    client, service, _, _ = imports
    source = uploaded(client, tmp_path)

    def forbidden(*args, **kwargs):
        raise AssertionError("HTTP must not validate the archive")

    monkeypatch.setattr(module, "validate_zip", forbidden)
    path = f"{BASE}/{source}/preview"
    accepted = client.post(path, json={"request_key": "preview-1", "root": ""})
    assert accepted.status_code == 202, accepted.text
    job = accepted.json()
    assert job["status"] == "queued"
    assert job["stage"] == "queued" and job["progress"] == 0
    assert accepted.headers["location"] == job["status_url"]
    assert client.post(path, json={"request_key": "preview-1", "root": ""}).json() == job
    assert client.post(path, json={"request_key": "preview-1", "root": "different"}).status_code == 409
    assert client.get(job["status_url"]).json() == job
    assert client.get(f"{BASE}/{source}").json()["execution"] == job
    assert not (service.root / "staging" / source / "files").exists()


def test_status_cancel_and_retry_are_owner_scoped_and_polling_does_not_mutate(imports, tmp_path):
    from app.routes.dataset_imports import get_import_user
    client, _, app, sessions = imports
    source = uploaded(client, tmp_path)
    admitted = client.post(f"{BASE}/{source}/preview", json={"request_key": "one", "root": ""})
    assert admitted.status_code == 202
    job = admitted.json()
    with sessions.kw["bind"].connect() as connection:
        before = "\n".join(connection.connection.driver_connection.iterdump())
    for _ in range(3):
        assert client.get(job["status_url"]).json() == job
        assert client.get(f"{BASE}/{source}").json()["execution"] == job
    with sessions.kw["bind"].connect() as connection:
        assert "\n".join(connection.connection.driver_connection.iterdump()) == before
    app.dependency_overrides[get_import_user] = lambda: SimpleNamespace(id=2)
    assert client.get(job["status_url"]).status_code == 404
    assert client.post(job["status_url"] + "/cancel").status_code == 404
    assert client.post(job["status_url"] + "/retry", json={"request_key": "retry"}).status_code == 404
    app.dependency_overrides[get_import_user] = lambda: SimpleNamespace(id=1)
    assert client.post(job["status_url"] + "/cancel").json()["status"] == "cancelled"
    retried = client.post(job["status_url"] + "/retry", json={"request_key": "retry"})
    assert retried.status_code == 202
    assert retried.json()["id"] != job["id"]
