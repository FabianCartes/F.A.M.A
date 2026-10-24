"""Explicit offline verified backfill. Does not activate readers or erase legacy JSON."""
import argparse
import hashlib
import json
import os
import uuid

from sqlalchemy import func, select


class MetadataMigrationError(ValueError):
    """Sanitized discrepancy: preserve originals and do not activate a partial backfill."""


def _id(kind, parent, position):
    return uuid.uuid5(uuid.NAMESPACE_URL, f"fama:import-metadata:v1:{kind}:{parent}:{position}").hex


def _text(value, maximum, *, empty=False):
    if not isinstance(value, str) or (not value and not empty) or len(value.encode("utf-8")) > maximum:
        raise MetadataMigrationError("invalid_metadata_text")
    return value


def _integer(value):
    if type(value) is not int or not 0 <= value <= 2**63 - 1:
        raise MetadataMigrationError("invalid_metadata_integer")
    return value


def _path(value, *, empty=False):
    import unicodedata

    value = _text(value, 1024, empty=empty)
    if not value and empty:
        return value
    if (any(part in ("", ".", "..") for part in value.split("/")) or "\\" in value or ":" in value
            or any(unicodedata.category(c).startswith("C") for c in value)):
        raise MetadataMigrationError("invalid_metadata_path")
    return value


def _file(file, root, source_id):
    import math
    import unicodedata

    if not isinstance(file, dict):
        raise MetadataMigrationError("invalid_file_metadata")
    original = _path(file.get("original_path"))
    root = _path(root, empty=True)
    prefix = root + "/" if root else ""
    if not original.startswith(prefix):
        raise MetadataMigrationError("file_outside_selected_root")
    relative = original[len(prefix):]
    parts = relative.split("/")
    label = _text(file.get("class_name"), 240)
    if len(parts) < 2 or unicodedata.normalize("NFC", parts[0]) != label:
        raise MetadataMigrationError("file_class_mismatch")
    parts[0] = label
    sha = file.get("sha256")
    if not isinstance(sha, str) or len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha):
        raise MetadataMigrationError("invalid_file_hash")
    stored = _path(file.get("stored_name"))
    if "/" in stored:
        raise MetadataMigrationError("invalid_local_object_reference")
    rate, duration = file.get("sample_rate"), file.get("duration_seconds")
    if rate is not None and (type(rate) is not int or not 0 < rate <= 2**31 - 1):
        raise MetadataMigrationError("invalid_audio_metadata")
    if duration is not None and (type(duration) not in (int, float) or not math.isfinite(duration) or duration <= 0):
        raise MetadataMigrationError("invalid_audio_metadata")
    return dict(source_import_id=source_id, class_name=label, original_path=original,
                selected_root=root, relative_path="/".join(parts), sha256=sha,
                size_bytes=_integer(file.get("size_bytes")), stored_name=stored,
                sample_rate=rate, duration_seconds=duration,
                sync_status="unverified", object_key=None, object_generation=None,
                legacy_metadata=file)


def migrate_metadata(engine, *, writers_stopped=False):
    """Backfill and verify in one transaction; reject stale sources or damaged targets.

    Caller must stop every legacy writer for the migration and subsequent cutover.
    The database lock additionally excludes writes for this transaction only.
    No original file is read and no historical cloud flag is upgraded to proof.
    """
    if writers_stopped is not True:
        raise MetadataMigrationError("stop_writers_before_backfill")
    if engine.dialect.name not in ("sqlite", "postgresql"):
        raise MetadataMigrationError("unsupported_migration_database")
    from app.models.dataset_import import DatasetImport, ImportedDataset
    from app.models.dataset_import_metadata import (
        BACKFILL_MODELS, DatasetMember, DatasetSummary, ImportClass,
        ImportFile, ImportIssue, ImportSummary, MetadataBackfill,
    )

    jobs, datasets = DatasetImport.__table__, ImportedDataset.__table__
    counts = {model.__tablename__: 0 for model in BACKFILL_MODELS if model is not MetadataBackfill}
    report = dict(datasets=0, imports=0, members=0, files=0, issues=0, total_size_bytes=0, verified=True)
    digest = hashlib.sha256()
    with engine.begin() as conn:
        if engine.dialect.name == "sqlite":
            conn.exec_driver_sql("BEGIN IMMEDIATE")
        else:
            conn.exec_driver_sql("LOCK TABLE dataset_import, imported_dataset IN SHARE ROW EXCLUSIVE MODE")
        for model in BACKFILL_MODELS:
            model.__table__.create(conn, checkfirst=True)
        if engine.dialect.name == "postgresql":
            names = ", ".join(model.__tablename__ for model in BACKFILL_MODELS)
            conn.exec_driver_sql(f"LOCK TABLE {names} IN SHARE ROW EXCLUSIVE MODE")
        checkpoint = conn.execute(select(MetadataBackfill.__table__)).mappings().first()

        def record(model, values):
            table = model.__table__
            if checkpoint is None:
                conn.execute(table.insert(), values)
            key = next(iter(table.primary_key.columns))
            actual = conn.execute(select(table).where(key == values[key.name])).mappings().first()
            if actual is None or dict(actual) != values:
                raise MetadataMigrationError("normalized_metadata_mismatch")
            counts[table.name] += 1

        def legacy_rows(table):
            for row in conn.execute(select(table).order_by(table.c.id)).mappings():
                digest.update(json.dumps([table.name, dict(row)], sort_keys=True, ensure_ascii=False,
                                         allow_nan=False, separators=(",", ":")).encode("utf-8") + b"\n")
                yield row

        for job in legacy_rows(jobs):
            preview = job["preview"]
            if not isinstance(preview, dict):
                raise MetadataMigrationError("invalid_preview_metadata")
            collections = {name: preview.get(name, []) for name in ("files", "classes", "errors", "warnings")}
            if any(not isinstance(value, list) for value in collections.values()):
                raise MetadataMigrationError("invalid_preview_collection")
            sync = preview.get("sync_files", {})
            if not isinstance(sync, dict) or any(state not in ("synced", "error") for state in sync.values()):
                raise MetadataMigrationError("invalid_legacy_sync_progress")
            total = 0
            for index, file in enumerate(collections["files"]):
                fields = _file(file, preview.get("root", ""), job["id"])
                if type(file.get("duplicate")) is not bool or type(file.get("existing", False)) is not bool:
                    raise MetadataMigrationError("invalid_duplicate_metadata")
                record(ImportFile, dict(fields, id=_id("file", job["id"], index), import_id=job["id"],
                       ordinal=index, duplicate=file["duplicate"], existing=file.get("existing", False)))
                total += fields["size_bytes"]
                report["files"] += 1
            files = collections["files"]
            labels = [_text(label, 240) for label in collections["classes"]]
            if len(labels) != len(set(labels)) or set(labels) != {file["class_name"] for file in files}:
                raise MetadataMigrationError("preview_class_mismatch")
            pairs = sorted({(file["class_name"], file["sha256"]) for file in files})
            fingerprint = "v1:" + hashlib.sha256(json.dumps(
                ["wav-collection-v1", pairs], ensure_ascii=False,
                separators=(",", ":")).encode("utf-8")).hexdigest()
            expected_counts = {
                "unique_count": len({file["sha256"] for file in files}),
                "duplicate_count": sum(file["duplicate"] for file in files),
                "new_count": sum(not file["duplicate"] and not file.get("existing", False) for file in files),
            }
            if any(_integer(preview[key]) != value for key, value in expected_counts.items() if key in preview):
                raise MetadataMigrationError("preview_count_mismatch")
            if "fingerprint" in preview and preview["fingerprint"] != fingerprint:
                raise MetadataMigrationError("preview_fingerprint_mismatch")
            if set(sync) - {file["sha256"] for file in collections["files"]}:
                raise MetadataMigrationError("orphaned_legacy_sync_progress")
            for index, label in enumerate(collections["classes"]):
                record(ImportClass, dict(id=_id("class", job["id"], index), import_id=job["id"],
                       ordinal=index, class_name=_text(label, 240)))
            for severity, key in (("error", "errors"), ("warning", "warnings")):
                for index, issue in enumerate(collections[key]):
                    if not isinstance(issue, dict):
                        raise MetadataMigrationError("invalid_issue_metadata")
                    record(ImportIssue, dict(id=_id(severity, job["id"], index), import_id=job["id"],
                           ordinal=index, severity=severity, path=_text(issue.get("path"), 1024, empty=True),
                           code=_text(issue.get("code"), 100),
                           action=_text(issue["action"], 2000) if "action" in issue else None,
                           legacy_metadata=issue))
                    report["issues"] += 1
            summary = {key: value for key, value in preview.items()
                       if key not in (*collections, "sync_files")}
            if any(isinstance(value, (dict, list)) for value in summary.values()):
                raise MetadataMigrationError("unsupported_preview_summary")
            record(ImportSummary, dict(import_id=job["id"], preview=summary,
                   fingerprint=preview.get("fingerprint"), file_count=len(collections["files"]),
                   class_count=len(collections["classes"]), error_count=len(collections["errors"]),
                   warning_count=len(collections["warnings"]), total_size_bytes=total))
            report["imports"] += 1

        for dataset in legacy_rows(datasets):
            if not isinstance(dataset["files"], list):
                raise MetadataMigrationError("invalid_dataset_membership")
            total, labels, paths = 0, set(), set()
            for file in dataset["files"]:
                if not isinstance(file, dict):
                    raise MetadataMigrationError("invalid_dataset_member")
                source = conn.execute(select(jobs).where(jobs.c.id == file.get("import_id"))).mappings().first()
                if (source is None or source["owner_id"] != dataset["owner_id"]
                        or source["dataset_id"] != dataset["id"] or source["status"] != "imported"):
                    raise MetadataMigrationError("invalid_member_provenance")
                fields = _file(file, source["preview"].get("root", ""), source["id"])
                match = conn.execute(select(ImportFile.__table__).where(
                    ImportFile.import_id == source["id"], ImportFile.sha256 == fields["sha256"],
                    ImportFile.duplicate.is_(False), ImportFile.existing.is_(False))).mappings().first()
                if match is None or any(match[key] != fields[key] for key in (
                        "class_name", "original_path", "relative_path", "sha256", "size_bytes", "stored_name")):
                    raise MetadataMigrationError("member_source_mismatch")
                import unicodedata
                canonical = unicodedata.normalize("NFC", fields["relative_path"]).casefold()
                if canonical in paths:
                    raise MetadataMigrationError("canonical_path_conflict")
                paths.add(canonical)
                record(DatasetMember, dict(fields, id=_id("member", dataset["id"], fields["sha256"]),
                       dataset_id=dataset["id"], dataset_revision=_integer(dataset["revision"])))
                labels.add(fields["class_name"])
                total += fields["size_bytes"]
                report["members"] += 1
            record(DatasetSummary, dict(dataset_id=dataset["id"], revision=_integer(dataset["revision"]),
                   file_count=len(dataset["files"]), class_count=len(labels), total_size_bytes=total))
            report["datasets"] += 1
            report["total_size_bytes"] += total

        for job in conn.execute(select(jobs).where(jobs.c.status == "imported")).mappings():
            member_count = conn.scalar(select(func.count()).select_from(DatasetMember.__table__).where(
                DatasetMember.source_import_id == job["id"]))
            selected_count = conn.scalar(select(func.count()).select_from(ImportFile.__table__).where(
                ImportFile.import_id == job["id"], ImportFile.duplicate.is_(False), ImportFile.existing.is_(False)))
            if member_count != _integer(job["added_count"]) or member_count != selected_count:
                raise MetadataMigrationError("published_membership_count_mismatch")
            if job["dataset_id"] is not None:
                target = conn.execute(select(datasets.c.owner_id).where(
                    datasets.c.id == job["dataset_id"])).first()
                if target is None or target.owner_id != job["owner_id"]:
                    raise MetadataMigrationError("published_dataset_missing_or_foreign")

        for model in BACKFILL_MODELS:
            if model is not MetadataBackfill:
                if conn.scalar(select(func.count()).select_from(model.__table__)) != counts[model.__tablename__]:
                    raise MetadataMigrationError("normalized_count_mismatch")
        values = dict(version=1, source_sha256=digest.hexdigest(), report=report)
        if checkpoint is None:
            conn.execute(MetadataBackfill.__table__.insert(), values)
        elif dict(checkpoint) != values:
            raise MetadataMigrationError("legacy_source_changed_since_backfill")
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Apply verified additive metadata backfill")
    parser.add_argument("--writers-stopped", action="store_true", help="Acknowledge all import writers are stopped")
    args = parser.parse_args(argv)
    if not args.apply:
        print("Dry run: no database opened; backfill retains original JSON and does not activate runtime readers.")
        return
    if not args.writers_stopped or not os.environ.get("DATABASE_URL"):
        parser.error("--apply requires --writers-stopped and an explicit DATABASE_URL; no dotenv/default")
    from sqlalchemy import create_engine
    from app.database import normalize_database_url
    engine = create_engine(normalize_database_url(os.environ["DATABASE_URL"]))
    try:
        report = migrate_metadata(engine, writers_stopped=True)
        print(json.dumps(report, sort_keys=True))
    except Exception:
        # Never print DB errors, credentials, private paths or row contents.
        parser.exit(1, "Metadata backfill failed; preserve originals and inspect with an authorized operator.\n")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
