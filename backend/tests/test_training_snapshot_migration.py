"""Explicit additive migration contract on synthetic databases only."""
import pytest
from sqlalchemy import create_engine
from tests.test_dataset_import_api import imports, prepare, confirm


def test_migration_requires_acknowledgement_and_existing_import_schema():
    from scripts.migrate_training_snapshots import migrate_snapshots
    engine = create_engine("sqlite://")
    with pytest.raises(RuntimeError, match="stopped"):
        migrate_snapshots(engine)
    with pytest.raises(RuntimeError, match="schema"):
        migrate_snapshots(engine, writers_stopped=True)
    engine.dispose()


def test_migration_is_idempotent_and_result_is_publicly_usable(imports, tmp_path):
    from scripts.migrate_training_snapshots import migrate_snapshots
    from app.services.training_snapshots import TrainingSnapshots
    client, source, _, sessions = imports
    engine = sessions.kw["bind"]
    job = prepare(client, tmp_path)
    dataset = confirm(client, job).json()["dataset_id"]
    snapshots = TrainingSnapshots(sessions, source, tmp_path / "snapshots")
    # Fixture setup: imports creates all registered models, so explicitly start
    # without the additive targets. Only the public service observes migration.
    from sqlalchemy import inspect
    from sqlalchemy.exc import SQLAlchemyError
    from app.models.training_snapshot import TrainingSnapshot, SnapshotMember
    with engine.begin() as connection:
        SnapshotMember.__table__.drop(connection, checkfirst=True)
        TrainingSnapshot.__table__.drop(connection, checkfirst=True)
    assert not inspect(engine).has_table("training_snapshot")
    assert not inspect(engine).has_table("training_snapshot_member")
    with pytest.raises(SQLAlchemyError):
        snapshots.create(1, dataset)
    migrate_snapshots(engine, writers_stopped=True)
    migrate_snapshots(engine, writers_stopped=True)
    result = snapshots.create(1, dataset)
    assert snapshots.get(1, result["id"])["file_count"] == 1
    from tests.test_dataset_zip_validation import wav_bytes
    assert [(entry["class_name"], chunk) for entry, chunk in snapshots.iter_verified(1, result["id"])] == [("birds", wav_bytes())]


def test_incompatible_existing_schema_is_not_repaired():
    from app.database import Base
    from scripts.migrate_training_snapshots import migrate_snapshots
    engine = create_engine("sqlite://")
    # Fixture-only malformed schema, not a migration against user data.
    for table in Base.metadata.sorted_tables:
        if table.name not in ("training_snapshot", "training_snapshot_member"):
            table.create(engine, checkfirst=True)
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE training_snapshot (id INTEGER PRIMARY KEY)")
    with pytest.raises(RuntimeError, match="Incompatible schema"):
        migrate_snapshots(engine, writers_stopped=True)
    engine.dispose()
