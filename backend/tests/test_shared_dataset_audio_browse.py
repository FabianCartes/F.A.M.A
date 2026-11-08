"""Shared browsing through the existing public ingestion service seam."""
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from app.services.ingestion import IngestionService


@pytest.fixture
def inventory(tmp_path):
    root = tmp_path / "raw"
    for relative in ("birds/a.wav", "birds/b.wav", "Retroalimentación/feedback_9.wav"):
        path = root / "Shared" / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"synthetic audio")
    service = IngestionService(bucket_name="test", local_base_dir=root,
                               local_processed_dir=tmp_path / "processed")
    with patch.object(service, "_get_client", side_effect=OSError("offline")):
        yield service, root


def test_filtered_pages_keep_full_facets_and_legacy_inventory(inventory):
    service, root = inventory
    before = service.list_dataset_files("Shared")
    page = service.browse_dataset_files("Shared", class_name="birds", limit=1)
    assert page["classes"] == ["Retroalimentación", "birds"]
    assert page["total"] == 2
    assert page["has_feedback"] is False
    assert page["files"][0]["name"] == "a.wav"
    assert page["files"][0]["is_feedback"] is False
    second = service.browse_dataset_files("Shared", class_name="birds", limit=1,
                                          cursor=page["next_cursor"])
    assert second["files"][0]["name"] == "b.wav"
    assert second["next_cursor"] is None
    assert second["snapshot"] == page["snapshot"]
    assert service.list_dataset_files("Shared") == before
    assert len(list(root.rglob("*.wav"))) == 3


def test_feedback_requires_persisted_canonical_dataset_match(inventory):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from app.models.feedback_sync import FeedbackSync

    service, _ = inventory
    engine = create_engine("sqlite://")
    FeedbackSync.__table__.create(engine)
    with Session(engine) as db:
        for ident, dataset, relative in (
            (1, "Shared", "Shared/birds/a.wav"),
            (2, "Other", "Shared/birds/b.wav"),
        ):
            db.add(FeedbackSync(id_retroalimentacion=ident, dataset_name=dataset,
                               storage_class="birds", class_label="birds",
                               object_key="datasets/" + relative,
                               local_relative_path=relative, sha256="a" * 64,
                               status="pending"))
        db.commit()
        page = service.browse_dataset_files("Shared", db=db, feedback=True)
        assert page["has_feedback"] is True
        assert page["total"] == 1
        assert page["files"][0]["name"] == "a.wav"
        assert page["files"][0]["is_feedback"] is True
        assert page["classes"] == ["Retroalimentación", "birds"]
        assert service.browse_dataset_files("Shared", db=db, feedback=True,
                                            class_name="Retroalimentación")["total"] == 0
        unknown = service.browse_dataset_files("Shared", db=db, feedback=False)
        assert {row["name"] for row in unknown["files"]} == {"b.wav", "feedback_9.wav"}


def test_cursor_rejections_and_drift_do_not_change_inventory(inventory):
    service, root = inventory
    before = service.list_dataset_files("Shared")
    page = service.browse_dataset_files("Shared", limit=1)
    for kwargs in ({"cursor": "not a cursor"},
                   {"cursor": page["next_cursor"], "class_name": "birds"},
                   {"cursor": page["next_cursor"], "feedback": False}):
        with pytest.raises(HTTPException) as error:
            service.browse_dataset_files("Shared", **kwargs)
        assert (error.value.status_code, error.value.detail) == (422, "Invalid browse cursor.")
    with pytest.raises(HTTPException) as error:
        service.browse_dataset_files("Other", cursor=page["next_cursor"])
    assert error.value.status_code == 422
    assert service.list_dataset_files("Shared") == before
    (root / "Shared" / "birds" / "a.wav").write_bytes(b"changed inventory")
    changed = service.list_dataset_files("Shared")
    with pytest.raises(HTTPException) as error:
        service.browse_dataset_files("Shared", cursor=page["next_cursor"])
    assert (error.value.status_code, error.value.detail) == (409, "Dataset inventory changed.")
    assert service.list_dataset_files("Shared") == changed


def test_missing_optional_tables_leave_origin_unknown(inventory):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    service, _ = inventory
    with Session(create_engine("sqlite://")) as db:
        page = service.browse_dataset_files("Shared", db=db)
        assert page["has_feedback"] is False
        assert all(row["is_feedback"] is False for row in page["files"])


def test_route_source_compiles_without_loading_ml_application():
    from pathlib import Path

    source = Path(__file__).parents[1] / "app" / "main.py"
    compile(source.read_text(), str(source), "exec")
