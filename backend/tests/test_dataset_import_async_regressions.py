"""Independent HTTP probes promoted as durable public-interface regressions."""
import hashlib
from types import SimpleNamespace

from tests.test_dataset_import_api import imports
from tests.test_dataset_zip_validation import archive, wav_bytes

BASE = "/api/ingestion/imports"


def dump(sessions):
    with sessions.kw["bind"].connect() as connection:
        return hashlib.sha256("\n".join(connection.connection.driver_connection.iterdump()).encode()).hexdigest()


def test_existing_public_errors_preserve_response_bytes_and_persisted_state(imports):
    client, _, _, sessions = imports
    before = dump(sessions)
    cases = [
        ("get", BASE + "/" + "0" * 32, 404, "Importación no encontrada."),
        ("get", BASE + "/datasets/" + "0" * 32 + "/files", 404, "Dataset no encontrado o no autorizado."),
        ("put", BASE + "/" + "0" * 32 + "/archive", 415, "Selecciona un ZIP y envíalo como application/zip."),
    ]
    for method, path, status, message in cases:
        response = getattr(client, method)(path)
        assert (response.status_code, response.text) == (status, '{"detail":"' + message + '"}')
        assert dump(sessions) == before


def test_rejected_admission_and_foreign_status_are_atomic_and_polling_is_inert(imports, tmp_path):
    from app.routes.dataset_imports import get_import_user
    client, _, app, sessions = imports
    source = client.post(BASE, json={"request_key": "own", "name": "Own"}).json()["id"]
    data = archive(tmp_path / "own.zip", [("birds/a.wav", wav_bytes())]).read_bytes()
    assert client.put(f"{BASE}/{source}/archive", content=data,
                      headers={"Content-Type": "application/zip"}).status_code == 200
    before = dump(sessions)
    for payload in ({}, {"request_key": ""}, {"request_key": "x" * 101},
                    {"request_key": "é"}, {"request_key": "x", "ignored": True}):
        assert client.post(f"{BASE}/{source}/preview", json=payload).status_code == 422
        assert dump(sessions) == before
    accepted = client.post(f"{BASE}/{source}/preview", json={"request_key": "x", "root": ""})
    assert accepted.status_code == 202
    job = accepted.json()
    assert accepted.headers["location"] == job["status_url"] == f"{BASE}/{source}/jobs/{job['id']}"
    assert set(job) == {"id", "import_id", "kind", "status", "stage", "progress", "result", "error", "status_url"}
    before = dump(sessions)
    for _ in range(2):
        assert client.get(job["status_url"]).json() == job
        assert dump(sessions) == before
    response = client.get(f"{BASE}/{'0' * 32}/jobs/{job['id']}")
    assert (response.status_code, response.text) == (404, '{"detail":"Trabajo no encontrado."}')
    assert dump(sessions) == before
    app.dependency_overrides[get_import_user] = lambda: SimpleNamespace(id=2)
    for method, suffix, body in (("get", "", None), ("post", "/cancel", {}),
                                 ("post", "/retry", {"request_key": "r"})):
        response = getattr(client, method)(job["status_url"] + suffix,
                                           **({"json": body} if body is not None else {}))
        assert response.status_code == 404
        assert dump(sessions) == before
