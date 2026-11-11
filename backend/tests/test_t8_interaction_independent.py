"""Receipt-prefix resume through local confirmation and original-byte download."""
import hashlib

from tests.test_dataset_import_api import imports, operation, confirm
from tests.test_dataset_zip_validation import archive, wav_bytes

BASE = "/api/ingestion/imports"


def test_resume_confirm_and_download_without_private_cloud(imports, tmp_path, monkeypatch):
    client, service, app, sessions = imports
    monkeypatch.setenv("FAMA_IMPORT_CHUNK_BYTES", "4096")
    monkeypatch.delenv("FAMA_IMPORT_STORAGE_PROFILE", raising=False)
    expected = {f"birds/{i}.wav": wav_bytes(i + 1) for i in range(61)}
    path = archive(tmp_path / "input.zip", expected.items())
    data = path.read_bytes()
    created = client.post(BASE, json={"request_key": "own-integral", "name": "Independent"})
    assert created.status_code == 200, created.text
    job = created.json()
    url = f"{BASE}/{job['id']}/receipt"
    assert client.post(url, json={"name": "input.zip", "size_bytes": len(data)}).status_code == 200

    def put(index, block):
        return client.put(f"{url}/chunks/{index}", content=block, headers={
            "Content-Type": "application/octet-stream",
            "X-Chunk-Offset": str(index * 4096),
            "X-Chunk-SHA256": hashlib.sha256(block).hexdigest(),
        })

    assert put(0, data[:4096]).status_code == 200
    before = (client.get(url).json(), client.get(url + "/chunks").json())
    assert put(0, b"x" * 4096).status_code == 409
    assert (client.get(url).json(), client.get(url + "/chunks").json()) == before
    prefix = client.get(url + "/chunks").json()["chunks"]
    assert len(prefix) == 1 and prefix[0]["sha256"] == hashlib.sha256(data[:4096]).hexdigest()
    for start in range(4096, len(data), 4096):
        assert put(start // 4096, data[start:start + 4096]).status_code == 200
    assert client.post(url + "/finalize").status_code == 200
    ready = operation(client, job["id"], "preview", {"root": ""})
    assert ready.status_code == 200, ready.text
    assert client.get(BASE + "/datasets").json()["total"] == 0
    result = confirm(client, ready.json())
    assert result.status_code == 200, result.text
    assert result.json()["added_count"] == 61
    assert "sync_status" not in result.json()
    files_url = f"{BASE}/datasets/{result.json()['dataset_id']}/files"
    members = client.get(files_url, params={"limit": 200})
    assert members.status_code == 200, members.text
    files = members.json()["files"]
    assert len(files) == 61
    for member in files:
        download = client.get(files_url + "/" + member["sha256"])
        assert download.status_code == 200, download.text
        assert download.content == expected[member["original_path"]]
    assert client.post(f"{BASE}/{job['id']}/sync", json={"request_key": "retired"}).status_code == 404
