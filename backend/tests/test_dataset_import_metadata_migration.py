"""Explicit migration interface over synthetic legacy rows; no ambient database."""
import hashlib
import json

import pytest
from sqlalchemy import create_engine, select

from tests.test_dataset_import_api import imports


def legacy_database():
    from app.models.dataset_import import DatasetImport, ImportedDataset

    engine = create_engine("sqlite://")
    for model in (DatasetImport, ImportedDataset):
        model.__table__.create(engine)
    job_id, dataset_id = "a" * 32, "b" * 32
    audio = {"original_path": "wrapper/birds/session/a.wav", "class_name": "birds",
             "sha256": hashlib.sha256(b"synthetic original bytes").hexdigest(),
             "size_bytes": 123, "stored_name": "audio.wav", "sample_rate": 8000,
             "duration_seconds": 0.1, "duplicate": False, "existing": False}
    preview = {"root": "wrapper", "files": [audio], "classes": ["birds"],
               "errors": [], "warnings": [{"path": "birds", "code": "small_class"}],
               "new_count": 1, "unique_count": 1, "duplicate_count": 0,
               "fingerprint": "v1:" + hashlib.sha256(json.dumps(
                   ["wav-collection-v1", [["birds", audio["sha256"]]]],
                   ensure_ascii=False, separators=(",", ":")).encode()).hexdigest(),
               "sync_files": {audio["sha256"]: "synced"}}
    with engine.begin() as conn:
        conn.execute(DatasetImport.__table__.insert(), {
            "id": job_id, "owner_id": 1, "request_key": "original",
            "request": {"name": "Birds", "description": "Original"},
            "status": "imported", "sync_status": "synced", "created_at": 1.0,
            "preview": preview, "dataset_id": dataset_id, "added_count": 1})
        conn.execute(ImportedDataset.__table__.insert(), {
            "id": dataset_id, "owner_id": 1, "name": "Birds", "description": "Original",
            "revision": 3, "files": [dict(audio, import_id=job_id)]})
    return engine, job_id, dataset_id, audio, preview


def snapshot(engine):
    from app.models.dataset_import import DatasetImport, ImportedDataset

    with engine.connect() as conn:
        return {model.__tablename__: [dict(row) for row in conn.execute(select(model.__table__)).mappings()]
                for model in (DatasetImport, ImportedDataset)}


def test_backfill_preserves_legacy_data_and_verifies_normalized_membership_on_replay():
    from scripts.migrate_dataset_import_metadata import migrate_metadata
    from app.models.dataset_import_metadata import ImportFile, DatasetMember, ImportIssue, MetadataBackfill

    engine, job_id, dataset_id, audio, _ = legacy_database()
    before = snapshot(engine)
    try:
        result = migrate_metadata(engine, writers_stopped=True)
        assert result == {"datasets": 1, "imports": 1, "members": 1, "files": 1, "issues": 1,
                          "total_size_bytes": 123, "verified": True}
        assert snapshot(engine) == before
        with engine.connect() as conn:
            member = conn.execute(select(DatasetMember.__table__)).mappings().one()
            assert member["dataset_id"] == dataset_id
            assert member["source_import_id"] == job_id
            assert member["dataset_revision"] == 3
            assert member["relative_path"] == "birds/session/a.wav"
            assert member["selected_root"] == "wrapper"
            assert member["sha256"] == audio["sha256"]
            assert member["size_bytes"] == 123
            assert member["legacy_metadata"] == dict(audio, import_id=job_id)
            assert member["object_key"] is None and member["object_generation"] is None
            # Historical sync flags do not establish generation-bound cloud evidence.
            assert member["sync_status"] == "unverified"
            candidate = conn.execute(select(ImportFile.__table__)).mappings().one()
            assert candidate["import_id"] == job_id
            assert candidate["legacy_metadata"] == audio
            assert candidate["id"] != member["id"]
            assert conn.execute(select(ImportIssue.__table__.c.code)).scalar_one() == "small_class"
            assert conn.execute(select(MetadataBackfill.__table__.c.version)).scalar_one() == 1
        assert migrate_metadata(engine, writers_stopped=True) == result
        assert snapshot(engine) == before
    finally:
        engine.dispose()


@pytest.mark.parametrize("damage", ["hash", "size", "owner", "membership", "class", "path", "count", "fingerprint", "missing_member", "missing_dataset"])
def test_invalid_legacy_metadata_aborts_all_backfill_rows_without_rewriting_sources(damage):
    from app.models.dataset_import import DatasetImport, ImportedDataset
    from app.models.dataset_import_metadata import BACKFILL_MODELS
    from scripts.migrate_dataset_import_metadata import MetadataMigrationError, migrate_metadata

    engine, job_id, dataset_id, audio, preview = legacy_database()
    try:
        with engine.begin() as conn:
            for model in BACKFILL_MODELS:
                model.__table__.create(conn)
            member = dict(audio, import_id=job_id)
            if damage == "hash":
                member["sha256"] = "c" * 64
            elif damage == "size":
                member["size_bytes"] = 124
            elif damage == "owner":
                conn.execute(DatasetImport.__table__.update().values(owner_id=2))
            elif damage == "membership":
                member["import_id"] = "f" * 32
            elif damage in ("class", "count", "fingerprint"):
                if damage == "class":
                    preview["classes"] = ["wrong-label"]
                elif damage == "count":
                    preview["unique_count"] = 2
                else:
                    preview["fingerprint"] = "v1:" + "0" * 64
                conn.execute(DatasetImport.__table__.update().values(preview=preview))
            elif damage == "path":
                member["original_path"] = "../outside.wav"
            conn.execute(ImportedDataset.__table__.update().where(
                ImportedDataset.id == dataset_id).values(files=[] if damage == "missing_member" else [member]))
            if damage == "missing_dataset":
                conn.execute(ImportedDataset.__table__.delete())
        before = snapshot(engine)
        with pytest.raises(MetadataMigrationError):
            migrate_metadata(engine, writers_stopped=True)
        assert snapshot(engine) == before
        with engine.connect() as conn:
            for model in BACKFILL_MODELS:
                assert conn.execute(select(model.__table__)).all() == []
    finally:
        engine.dispose()


@pytest.mark.parametrize("damage", ["hash", "size", "membership", "count", "legacy_change"])
def test_replay_detects_tampering_instead_of_acknowledging_an_old_checkpoint(damage):
    from app.models.dataset_import import ImportedDataset
    from app.models.dataset_import_metadata import DatasetMember
    from scripts.migrate_dataset_import_metadata import MetadataMigrationError, migrate_metadata

    engine, _, _, _, _ = legacy_database()
    try:
        migrate_metadata(engine, writers_stopped=True)
        with engine.begin() as conn:
            table = DatasetMember.__table__
            if damage == "count":
                conn.execute(table.delete())
            elif damage == "legacy_change":
                conn.execute(ImportedDataset.__table__.update().values(description="Changed after backfill"))
            else:
                field = {"hash": "sha256", "size": "size_bytes", "membership": "source_import_id"}[damage]
                value = 124 if damage == "size" else "f" * (64 if damage == "hash" else 32)
                conn.execute(table.update().values(**{field: value}))
        before = snapshot(engine)
        with pytest.raises(MetadataMigrationError):
            migrate_metadata(engine, writers_stopped=True)
        assert snapshot(engine) == before
    finally:
        engine.dispose()


def test_public_migration_requires_stopped_writers_before_any_schema_or_data_write():
    from sqlalchemy import inspect
    from scripts.migrate_dataset_import_metadata import MetadataMigrationError, migrate_metadata

    engine, _, _, _, _ = legacy_database()
    before = snapshot(engine)
    try:
        with pytest.raises(MetadataMigrationError, match="stop_writers_before_backfill"):
            migrate_metadata(engine)
        assert snapshot(engine) == before
        assert set(inspect(engine).get_table_names()) == {"dataset_import", "imported_dataset"}
    finally:
        engine.dispose()


def test_migration_cli_dry_run_and_missing_apply_prerequisites_never_use_an_ambient_database(monkeypatch, capsys):
    from scripts.migrate_dataset_import_metadata import main

    monkeypatch.delenv("DATABASE_URL", raising=False)
    main([])
    assert "no database opened" in capsys.readouterr().out
    with pytest.raises(SystemExit) as exit_info:
        main(["--apply"])
    assert exit_info.value.code == 2
    assert "explicit DATABASE_URL" in capsys.readouterr().err


def test_backfill_does_not_replace_normalized_runtime_records_after_cutover(imports, tmp_path):
    from sqlalchemy.exc import IntegrityError
    from scripts.migrate_dataset_import_metadata import migrate_metadata
    from tests.test_dataset_import_api import prepare, confirm
    from tests.test_dataset_zip_validation import wav_bytes

    client, _, _, sessions = imports
    first = prepare(client, tmp_path, entries=[("birds/a.wav", wav_bytes()), ("birds/copy.wav", wav_bytes())])
    dataset_id = confirm(client, first).json()["dataset_id"]
    repeated = prepare(client, tmp_path, key="repeat", target_id=dataset_id)
    assert confirm(client, repeated).json()["added_count"] == 0
    extension = prepare(client, tmp_path, key="extension", target_id=dataset_id,
                        entries=[("birds/new.wav", wav_bytes(2))])
    assert confirm(client, extension).json()["added_count"] == 1
    failed = prepare(client, tmp_path, key="invalid", entries=[("birds/third.wav", wav_bytes(3)), ("extra.txt", b"no")])
    assert failed["status"] == "needs_correction"
    engine = sessions.kw["bind"]
    before = persisted_digest(engine)
    # Backfill is an offline legacy operation, never a runtime repair tool.
    with pytest.raises(IntegrityError):
        migrate_metadata(engine, writers_stopped=True)
    assert persisted_digest(engine) == before
    assert client.get(f"/api/ingestion/imports/datasets/{dataset_id}/files").json()["total"] == 2


def persisted_digest(engine):
    """Hash every persisted SQLite row and schema, not just the legacy source tables."""
    raw = engine.raw_connection()
    try:
        return hashlib.sha256("\n".join(raw.driver_connection.iterdump()).encode()).digest()
    finally:
        raw.close()


@pytest.mark.parametrize("sql,replay,error", [
    (None, False, "stop_writers_before_backfill"),
    ("UPDATE imported_dataset SET files='{}'", False, "invalid_dataset_membership"),
    ("UPDATE imported_dataset SET owner_id=2", False, "invalid_member_provenance"),
    ("UPDATE imported_dataset SET description='changed'", True, "legacy_source_changed_since_backfill"),
    ("UPDATE imported_dataset_member SET size_bytes=124", True, "normalized_metadata_mismatch"),
])
def test_every_persisted_row_and_schema_are_unchanged_after_rejected_backfill(sql, replay, error):
    from sqlalchemy import text
    from scripts.migrate_dataset_import_metadata import MetadataMigrationError, migrate_metadata

    engine, *_ = legacy_database()
    try:
        if replay:
            result = migrate_metadata(engine, writers_stopped=True)
            before = persisted_digest(engine)
            assert migrate_metadata(engine, writers_stopped=True) == result
            assert persisted_digest(engine) == before
        if sql:
            with engine.begin() as conn:
                conn.execute(text(sql))
        before = persisted_digest(engine)
        with pytest.raises(MetadataMigrationError, match=error):
            migrate_metadata(engine, writers_stopped=sql is not None)
        assert persisted_digest(engine) == before
    finally:
        engine.dispose()
