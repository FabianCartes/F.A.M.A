"""Private audio browsing through the authenticated HTTP interface."""
from tests.test_dataset_import_api import imports, prepare, confirm
from tests.test_dataset_zip_validation import wav_bytes


def test_feedback_provenance_and_intersection(imports, tmp_path):
    from app.models.dataset_import import DatasetImport
    from app.models.dataset_import_metadata import DatasetMember
    client, _, _, sessions = imports
    first = prepare(client, tmp_path, entries=[("birds/feedback.wav", wav_bytes(1)),
        ("frogs/normal.wav", wav_bytes(2)), ("Retroalimentación/a.wav", wav_bytes(3))])
    target = confirm(client, first).json()["dataset_id"]
    second = prepare(client, tmp_path, key="feedback-source", target_id=target, sample=4)
    confirm(client, second)
    # Seed the two supported persisted origins, never infer from paths or labels.
    with sessions() as db:
        member = db.query(DatasetMember).filter_by(dataset_id=target, class_name="frogs").one()
        member.legacy_metadata = {"origin": {"kind": "feedback"}}
        source = db.get(DatasetImport, second["id"])
        source.request = dict(source.request, origin={"kind": "feedback"})
        db.commit()
    url = f"/api/ingestion/imports/datasets/{target}/files"
    all_rows = client.get(url, params={"browse": True}).json()
    assert all_rows["has_feedback"] is True
    assert all_rows["total"] == 4
    feedback = client.get(url, params={"browse": True, "feedback": True, "limit": 1}).json()
    assert feedback["total"] == 2
    assert feedback["classes"] == ["Retroalimentación", "birds", "frogs"]
    assert feedback["files"][0]["is_feedback"] is True
    both = client.get(url, params={"browse": True, "feedback": True, "class_name": "frogs"}).json()
    assert both["total"] == 1 and both["files"][0]["class_name"] == "frogs"
    ordinary = client.get(url, params={"browse": True, "feedback": False}).json()
    assert ordinary["total"] == 2
    assert {row["class_name"] for row in ordinary["files"]} == {"birds", "Retroalimentación"}
    assert all(row["is_feedback"] is False for row in ordinary["files"])
    assert ordinary["has_feedback"] is True


def test_browse_rejects_other_owner(imports, tmp_path):
    from types import SimpleNamespace
    from app.routes.dataset_imports import get_import_user
    client, _, app, _ = imports
    target = confirm(client, prepare(client, tmp_path)).json()["dataset_id"]
    url = f"/api/ingestion/imports/datasets/{target}/files"
    app.dependency_overrides[get_import_user] = lambda: SimpleNamespace(id=2)
    response = client.get(url, params={"browse": True, "cursor": "invalid"})
    assert response.status_code == 404
    assert response.json()["detail"] == "Dataset no encontrado o no autorizado."


def test_browse_cursor_scope_revision_and_rejected_reads(imports, tmp_path):
    from types import SimpleNamespace
    from app.routes.dataset_imports import get_import_user
    client, _, app, _ = imports
    target = confirm(client, prepare(client, tmp_path, entries=[
        ("birds/a.wav", wav_bytes(1)), ("birds/b.wav", wav_bytes(2))])).json()["dataset_id"]
    url = f"/api/ingestion/imports/datasets/{target}/files"
    baseline = client.get(url, params={"browse": True}).json()
    cursor = client.get(url, params={"browse": True, "limit": 1}).json()["next_cursor"]
    legacy_cursor = client.get(url, params={"limit": 1}).json()["next_cursor"]
    for params in ({"cursor": "invalid"}, {"cursor": cursor, "class_name": "birds"},
                   {"cursor": cursor, "feedback": False}, {"cursor": legacy_cursor}):
        response = client.get(url, params=dict(params, browse=True))
        assert response.status_code == 422, response.text
        assert response.json()["detail"] == "Cursor de página no válido."
    assert client.get(url, params={"browse": True}).json() == baseline
    app.dependency_overrides[get_import_user] = lambda: SimpleNamespace(id=2)
    assert client.get(url, params={"browse": True, "cursor": cursor}).status_code == 404
    app.dependency_overrides[get_import_user] = lambda: SimpleNamespace(id=1)
    other = confirm(client, prepare(client, tmp_path, key="other", name="Other", sample=5)).json()["dataset_id"]
    assert client.get(f"/api/ingestion/imports/datasets/{other}/files",
        params={"browse": True, "cursor": cursor}).status_code == 422
    confirm(client, prepare(client, tmp_path, key="append", target_id=target, sample=3))
    response = client.get(url, params={"browse": True, "cursor": cursor})
    assert response.status_code == 409
    assert response.json()["detail"] == "La revisión cambió. Consulta de nuevo la primera página."
    assert client.get(url, params={"browse": True}).json()["total"] == 3


def test_browse_excludes_unpublished_revision_and_handles_empty(imports, tmp_path):
    from app.models.dataset_import_metadata import DatasetMember
    client, _, _, sessions = imports
    target = confirm(client, prepare(client, tmp_path)).json()["dataset_id"]
    url = f"/api/ingestion/imports/datasets/{target}/files"
    # Simulate journal membership not yet visible in the current revision.
    with sessions() as db:
        member = db.query(DatasetMember).filter_by(dataset_id=target).one()
        member.dataset_revision = 2
        member.legacy_metadata = {"origin": {"kind": "feedback"}}
        db.commit()
    response = client.get(url, params={"browse": True})
    assert response.status_code == 200, response.text
    assert response.json() == {"files": [], "classes": [], "has_feedback": False,
        "total": 0, "next_cursor": None, "snapshot": 1}


def test_browse_facets_and_class_filter_precede_pagination(imports, tmp_path):
    client, _, _, _ = imports
    job = prepare(client, tmp_path, entries=[
        ("birds/a.wav", wav_bytes(1)), ("frogs/b.wav", wav_bytes(2)),
        ("birds/feedback.wav", wav_bytes(3)),
        ("Retroalimentación/c.wav", wav_bytes(4))])
    target = confirm(client, job).json()["dataset_id"]
    url = f"/api/ingestion/imports/datasets/{target}/files"
    legacy = client.get(url).json()
    result = client.get(url, params={"browse": True, "limit": 1, "class_name": "birds"})
    assert result.status_code == 200, result.text
    body = result.json()
    assert body["classes"] == ["Retroalimentación", "birds", "frogs"]
    assert body["total"] == 2
    assert body["has_feedback"] is False
    assert body["files"][0]["is_feedback"] is False
    assert body["next_cursor"]
    following = client.get(url, params={"browse": True, "limit": 1,
        "class_name": "birds", "cursor": body["next_cursor"]}).json()
    assert following["classes"] == body["classes"]
    assert following["total"] == 2
    assert following["next_cursor"] is None
    assert following["files"][0]["id"] != body["files"][0]["id"]
    assert client.get(url).json() == legacy
    assert "is_feedback" not in legacy["files"][0]
    empty = client.get(url, params={"browse": True, "class_name": "missing"}).json()
    assert empty["files"] == [] and empty["total"] == 0
    assert empty["classes"] == body["classes"]
