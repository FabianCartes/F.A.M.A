"""S2/S5/S8 baseline HTTP and original-byte invariants."""
import hashlib
import json
from types import SimpleNamespace

from tests.test_dataset_import_api import imports, prepare, confirm
from tests.test_dataset_zip_validation import wav_bytes


def dump(sessions):
    with sessions.kw["bind"].connect() as conn:
        return hashlib.sha256("\n".join(conn.connection.driver_connection.iterdump()).encode()).hexdigest()


def test_predecessor_public_contract(imports, tmp_path):
    from app.routes.dataset_imports import get_import_user
    client, service, app, sessions = imports
    base = "/api/ingestion/imports"
    source = prepare(client, tmp_path)
    dataset = confirm(client, source).json()["dataset_id"]
    fingerprint = hashlib.sha256(wav_bytes()).hexdigest()
    download = client.get(f"{base}/datasets/{dataset}/files/{fingerprint}")
    assert download.status_code == 200 and download.content == wav_bytes()
    outputs = [("limits", client.get(base + "/limits").json()), ("original", hashlib.sha256(download.content).hexdigest())]
    checks = [
        ("unconfirmed", "post", f"{base}/{source['id']}/preview", {"request_key": "again", "root": ""}),
        ("bad-key", "post", f"{base}/{source['id']}/sync", {"request_key": ""}),
        ("unknown", "get", base + "/unknown", None),
        ("missing-wav", "get", f"{base}/datasets/{dataset}/files/{'a' * 64}", None),
    ]
    for name, method, path, payload in checks:
        before = dump(sessions)
        result = client.request(method, path, json=payload)
        assert result.status_code >= 400
        assert dump(sessions) == before
        outputs.append((name, result.status_code, result.json()))
    app.dependency_overrides[get_import_user] = lambda: SimpleNamespace(id=2)
    for suffix in (f"/{source['id']}", f"/datasets/{dataset}/files"):
        before = dump(sessions)
        result = client.get(base + suffix)
        assert result.status_code == 404 and dump(sessions) == before
        outputs.append(("foreign", result.status_code, result.json()))
    print("COMPAT_OUTPUT " + json.dumps(outputs, sort_keys=True))
