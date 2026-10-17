"""S8: bounded public collections, explicit publication and inert rejection."""
import hashlib
import json
import pytest
from sqlalchemy import event
from tests.test_dataset_import_api import imports, prepare, confirm
from tests.test_dataset_zip_validation import wav_bytes

BASE = "/api/ingestion/imports"

def state(sessions):
    with sessions.kw["bind"].connect() as conn:
        return hashlib.sha256("\n".join(conn.connection.driver_connection.iterdump()).encode()).hexdigest()

def read(client, engine, url, params=None):
    sql = []
    def capture(*args):
        sql.append(args[2])
    event.listen(engine, "before_cursor_execute", capture)
    try:
        response = client.get(url, params=params)
        assert response.status_code == 200, response.text
        return response.json(), len(sql)
    finally:
        event.remove(engine, "before_cursor_execute", capture)

def test_empty_collections_and_explicit_cursor(imports):
    client, _, _, sessions = imports
    job = client.post(BASE, json={"request_key": "empty", "name": "Empty"}).json()
    for collection in ("files", "classes", "issues"):
        url = f"{BASE}/{job['id']}/{collection}"
        before = state(sessions)
        response = client.get(url)
        assert response.status_code == 200
        assert response.json() == {collection: [], "total": 0, "next_cursor": None, "snapshot": None}
        rejected = client.get(url, params={"cursor": ""})
        assert (rejected.status_code, rejected.json()) == (422, {"detail": "Cursor de página no válido."})
        assert state(sessions) == before
    print("S8_EMPTY empty=3 rejected=3 state=unchanged")

def test_all_collections_bound_queries_and_explicit_publication(imports, tmp_path):
    client, _, _, sessions = imports
    engine = sessions.kw["bind"]
    records = []
    for total in (60, 600):
        job = prepare(client, tmp_path, key=f"own-{total}", name=f"Own-{total}", entries=[
            (f"class{i:04}/a.wav", wav_bytes(i + 1)) for i in range(total)])
        assert job["status"] == "ready"
        assert len(job["issue_sample"]) == 5
        assert job["preview"]["class_count"] == total
        assert job["preview"]["warning_count"] == total
        before = state(sessions)
        queries = {}
        for collection in ("files", "classes", "issues"):
            url = f"{BASE}/{job['id']}/{collection}"
            for limit in (None, 1, 200):
                page, count = read(client, engine, url, None if limit is None else {"limit": limit})
                assert len(page[collection]) == min(total, limit or 50)
                assert page["total"] == total
                assert bool(page["next_cursor"]) == (total > (limit or 50))
                queries[f"{collection}:{limit}"] = count
            cursor, seen = None, []
            while True:
                params = {} if cursor is None else {"cursor": cursor}
                page, _ = read(client, engine, url, params)
                assert len(page[collection]) <= 50
                seen.extend(json.dumps(item, sort_keys=True) for item in page[collection])
                cursor = page["next_cursor"]
                if cursor is None:
                    break
            assert len(seen) == len(set(seen)) == total
            for params, detail in (({"limit": 0}, "El tamaño de página supera el máximo configurado."),
                ({"limit": 201}, "El tamaño de página supera el máximo configurado."),
                ({"cursor": ""}, "Cursor de página no válido."),
                ({"cursor": "malformed"}, "Cursor de página no válido.")):
                response = client.get(url, params=params)
                expected = {"detail": detail}
                if "limit" in params:
                    lower = params["limit"] == 0
                    expected = {"detail": [{"type": "greater_than_equal" if lower else "less_than_equal",
                        "loc": ["query", "limit"], "msg": "Input should be greater than or equal to 1" if lower else "Input should be less than or equal to 200",
                        "input": str(params["limit"]), "ctx": {"ge": 1} if lower else {"le": 200}}]}
                assert (response.status_code, response.json()) == (422, expected)
                assert state(sessions) == before
        assert state(sessions) == before
        assert client.get(BASE + "/datasets").json()["total"] == len(records)
        published = confirm(client, job)
        assert published.status_code == 200, published.text
        assert published.json()["added_count"] == total
        assert published.json()["sync_status"] == "pending"
        dataset = published.json()["dataset_id"]
        member, _ = read(client, engine, f"{BASE}/datasets/{dataset}/files")
        assert member["total"] == total and len(member["files"]) == 50
        summary = next(d for d in client.get(BASE + "/datasets").json()["datasets"] if d["id"] == dataset)
        assert (summary["file_count"], summary["class_count"]) == (total, total)
        records.append(queries)
    assert records[0] == records[1]
    print("S8_BOUNDS " + json.dumps(records, sort_keys=True))
