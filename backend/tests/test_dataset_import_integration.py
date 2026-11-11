"""Public local ZIP lifecycle: resumable receipt, bounded reads and safe cleanup.

The HTTP fixture uses the synthetic validator; OS containment is checked separately.
"""
import hashlib
import json
import resource

from fastapi.testclient import TestClient
from sqlalchemy import event

from tests.test_dataset_import_api import imports  # noqa: F401
from tests.test_dataset_import_receipts import dump
from tests.test_dataset_zip_validation import archive, wav_bytes

BASE = "/api/ingestion/imports"


def checked(response, code=200):
    assert response.status_code == code, response.text
    return response.json()


def put(client, url, index, data, chunk_bytes):
    return client.put(f"{url}/chunks/{index}", content=data, headers={
        "Content-Type": "application/octet-stream",
        "X-Chunk-Offset": str(index * chunk_bytes),
        "X-Chunk-SHA256": hashlib.sha256(data).hexdigest(),
    })


def execute(client, execution, identity, kind, **payload):
    admission = checked(client.post(f"{BASE}/{identity}/{kind}", json={
        "request_key": f"{kind}-{identity}", **payload}), 202)
    assert admission["status"] == "queued"
    assert execution.run_once()
    assert checked(client.get(admission["status_url"]))["status"] == "succeeded"
    return checked(client.get(f"{BASE}/{identity}"))


def observed_get(client, engine, url, **kwargs):
    statements = []
    def observe(_conn, _cursor, statement, _parameters, _context, _many):
        statements.append(statement)
    event.listen(engine, "before_cursor_execute", observe)
    try:
        response = client.get(url, **kwargs)
        checked(response)
        return response, len(statements)
    finally:
        event.remove(engine, "before_cursor_execute", observe)


def disk_bytes(root):
    return sum(path.stat().st_size for path in root.rglob("*") if path.is_file())


def test_receipt_to_local_download_recovers_and_remains_bounded(imports, tmp_path, monkeypatch):

    original, service, app, sessions = imports
    engine = sessions.kw["bind"]
    chunk_bytes = 4096
    monkeypatch.setenv("FAMA_IMPORT_CHUNK_BYTES", str(chunk_bytes))
    monkeypatch.delenv("FAMA_IMPORT_STORAGE_PROFILE", raising=False)
    measurements = []

    for count in (60, 600):
        expected = {f"birds/{index:04}.wav": wav_bytes(index + 1) for index in range(count)}
        data = archive(tmp_path / f"source-{count}.zip", expected.items()).read_bytes()
        identity = checked(original.post(BASE, json={"request_key": f"integral-{count}",
            "name": f"Synthetic-{count}", "description": "Synthetic local lifecycle"}))["id"]
        url = f"{BASE}/{identity}/receipt"
        checked(original.post(url, json={"name": "one.zip", "size_bytes": len(data)}))
        for index in range(3):
            checked(put(original, url, index, data[index * chunk_bytes:(index + 1) * chunk_bytes], chunk_bytes))
        accepted = checked(original.get(url))["received_bytes"]
        assert accepted == 3 * chunk_bytes

        with TestClient(app, raise_server_exceptions=False) as client:
            prefix = checked(client.get(url + "/chunks"))["chunks"]
            assert len(prefix) == 3
            for chunk in prefix:
                start = chunk["offset_bytes"]
                block = data[start:start + chunk["length_bytes"]]
                assert hashlib.sha256(block).hexdigest() == chunk["sha256"]
            altered = bytearray(data[chunk_bytes:2 * chunk_bytes])
            altered[len(altered) // 2] ^= 1
            before = dump(sessions)
            checked(put(client, url, 1, bytes(altered), chunk_bytes), 409)
            assert dump(sessions) == before
            assert checked(client.get(url))["received_bytes"] == accepted
            for offset in range(accepted, len(data), chunk_bytes):
                checked(put(client, url, offset // chunk_bytes, data[offset:offset + chunk_bytes], chunk_bytes))
            assert checked(client.post(url + "/finalize"))["status"] == "sealed"
            source = execute(client, original.execution, identity, "preview", root="")
            assert source["status"] == "ready" and source["preview"]["new_count"] == count
            assert checked(client.get(BASE + "/datasets"))["total"] == len(measurements)
            assert len(source["issue_sample"]) <= 5

            pages = []
            for limit in (50, 200):
                response, queries = observed_get(client, engine, f"{BASE}/{identity}/files", params={"limit": limit})
                page = response.json()
                assert len(page["files"]) == min(limit, count) and page["total"] == count
                assert (page["next_cursor"] is not None) == (count > limit)
                pages.append({"limit": limit, "bytes": len(response.content), "queries": queries})
            checked(client.get(f"{BASE}/{identity}/files?limit=201"), 422)
            result = execute(client, original.execution, identity, "confirm", preview_token=source["preview_token"])
            assert result["status"] == "imported" and result["added_count"] == count
            assert "sync_status" not in result
            assert checked(client.get(url))["reserved_bytes"] == 0
            assert original.execution.queue.claim(lease_seconds=60) is None
            dataset = result["dataset_id"]
            files_url = f"{BASE}/datasets/{dataset}/files"
            members, cursor = [], None
            while True:
                page = checked(client.get(files_url, params={"limit": 200, **({"cursor": cursor} if cursor else {})}))
                members.extend(page["files"])
                cursor = page["next_cursor"]
                if cursor is None:
                    break
            assert len(members) == count
            assert {m["relative_path"]: m["sha256"] for m in members} == {
                path: hashlib.sha256(value).hexdigest() for path, value in expected.items()}
            for member in members:
                response = client.get(files_url + "/" + member["sha256"])
                assert response.status_code == 200
                assert response.content == expected[member["relative_path"]]
                assert "sync_status" not in member
            observed_peak = disk_bytes(tmp_path)
            with sessions() as db:
                service.cleanup(db, attempt_root=original.execution.root)
            assert not (service.root / "staging" / identity).exists()
            # Cleanup removes transient receipt/attempt files, never published audio.
            assert client.get(files_url + "/" + members[0]["sha256"]).content == expected[members[0]["relative_path"]]
            assert checked(client.get(f"{BASE}/{identity}")) == result
            measurements.append({"files": count, "zip_bytes": len(data), "pages": pages,
                "process_peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                "observed_private_disk_high_water_bytes": observed_peak,
                "private_disk_residual_bytes": disk_bytes(tmp_path)})
    assert [page["queries"] for page in measurements[0]["pages"]] == [page["queries"] for page in measurements[1]["pages"]]
    print("LOCAL_IMPORT_METRICS " + json.dumps(measurements, sort_keys=True))
