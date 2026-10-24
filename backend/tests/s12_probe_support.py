import hashlib, json, uuid
from tests.test_dataset_zip_validation import archive, wav_bytes
B = "/api/ingestion/imports"
def digest(engine):
    with engine.connect() as db:
        return hashlib.sha256("\n".join(db.connection.driver_connection.iterdump()).encode()).hexdigest()
def new(request, tmp_path, *, auto=None, entries=None, layout="class_folders", name="Probe"):
    body = dict(request_key=uuid.uuid4().hex, name=name, target_id=None)
    if auto is not None: body["auto_import"] = auto
    if layout is not None: body["layout"] = layout
    result = request("POST", B, body=body)
    assert result.status_code == 200, result.content
    source = result.json()["id"]
    data = archive(tmp_path / (source + ".zip"), entries if entries is not None else [("bird/a.wav", wav_bytes())]).read_bytes()
    assert request("PUT", f"{B}/{source}/archive", content=data).status_code == 200
    return source, body
def admit(request, source, kind="preview", **params):
    body = {"request_key": uuid.uuid4().hex, **({"root": ""} if kind == "preview" else {}), **params}
    result = request("POST", f"{B}/{source}/{kind}", body=body)
    assert result.status_code == 202, result.content
    return result.json(), body
def state(request, source): return request("GET", f"{B}/{source}").json()
def reject_unchanged(engine, callback, status, detail):
    before = digest(engine)
    response = callback()
    assert (response.status_code, response.json()) == (status, {"detail": detail})
    assert digest(engine) == before
