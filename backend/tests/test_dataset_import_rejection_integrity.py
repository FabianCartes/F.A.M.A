"""Whole-state rejection invariants promoted from independent HTTP probes."""
import hashlib
from types import SimpleNamespace

from tests.test_dataset_import_api import imports, prepare, confirm


def test_http_rejections_preserve_database_files_and_original_download(imports, tmp_path):
    client, service, app, sessions = imports
    job = prepare(client, tmp_path, key="independent-http")
    published = confirm(client, job).json()
    target = published["dataset_id"]
    base = "/api/ingestion/imports"
    files = client.get(f"{base}/datasets/{target}/files").json()["files"]
    assert len(files) == 1
    audio = client.get(f"{base}/datasets/{target}/files/{files[0]['sha256']}")
    assert audio.status_code == 200
    assert hashlib.sha256(audio.content).hexdigest() == files[0]["sha256"]

    def snapshot():
        connection = sessions.kw["bind"].raw_connection()
        try:
            dump = "\n".join(connection.driver_connection.iterdump()).encode()
        finally:
            connection.close()
        tree = {str(path.relative_to(service.root)): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in service.root.rglob("*") if path.is_file()}
        return hashlib.sha256(dump).hexdigest(), tree

    cases = [
        ("post", base, {"request_key": "independent-http", "name": "Changed"}, 409,
         "La solicitud ya existe con otro destino o contenido."),
        ("get", base + "/" + "0" * 32, None, 404, "Importación no encontrada."),
        ("get", f"{base}/{job['id']}/files?cursor=", None, 422, "Cursor de página no válido."),
    ]
    for method, path, payload, status, detail in cases:
        before = snapshot()
        response = client.request(method, path, json=payload)
        assert response.status_code == status, response.text
        assert response.json() == {"detail": detail}
        assert snapshot() == before

    from app.routes.dataset_imports import get_import_user
    app.dependency_overrides[get_import_user] = lambda: SimpleNamespace(id=2)
    before = snapshot()
    response = client.get(f"{base}/datasets/{target}/files")
    assert response.status_code == 404
    assert response.json() == {"detail": "Dataset no encontrado o no autorizado."}
    assert snapshot() == before
