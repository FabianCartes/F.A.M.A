"""Normalized metadata and snapshot-bound, owner-authorized keyset pages.

Legacy JSON is retained for offline recovery only. Missing summaries fail closed;
this module never backfills or falls back to reading an entire legacy collection.
"""
import base64
import json
import os
import uuid

from fastapi import HTTPException
from sqlalchemy import func

from app.models.dataset_import_metadata import (
    DatasetMember, DatasetSummary, ImportClass, ImportFile, ImportIssue, ImportSummary,
)


def identifier():
    return uuid.uuid4().hex


def required_summary(db, model, key):
    summary = db.get(model, key)
    if summary is None:
        raise HTTPException(503, "Los metadatos requieren migración verificada antes de continuar.")
    return summary


def file_fields(file, root, source):
    prefix = root + "/" if root else ""
    return dict(source_import_id=source, class_name=file["class_name"],
                original_path=file["original_path"], selected_root=root,
                relative_path=file.get("relative_path", file["original_path"][len(prefix):]), sha256=file["sha256"],
                size_bytes=file["size_bytes"], stored_name=file["stored_name"],
                sample_rate=file.get("sample_rate"), duration_seconds=file.get("duration_seconds"),
                sync_status="pending", object_key=None, object_generation=None, legacy_metadata={})


def public_file(file):
    return dict(id=file.id, original_path=file.original_path, relative_path=file.relative_path,
                class_name=file.class_name, sha256=file.sha256, size_bytes=file.size_bytes,
                duplicate=getattr(file, "duplicate", False), existing=getattr(file, "existing", False),
                sync_status=file.sync_status)


def replace_preview(db, row, result):
    for model in (ImportFile, ImportClass, ImportIssue):
        db.query(model).filter_by(import_id=row.id).delete(synchronize_session=False)
    for ordinal, file in enumerate(result["files"]):
        db.add(ImportFile(id=identifier(), import_id=row.id, ordinal=ordinal,
                         duplicate=file["duplicate"], existing=file.get("existing", False),
                         **file_fields(file, result["root"], row.id)))
    for ordinal, label in enumerate(result["classes"]):
        db.add(ImportClass(id=identifier(), import_id=row.id, ordinal=ordinal, class_name=label))
    for severity, key in (("error", "errors"), ("warning", "warnings")):
        for ordinal, issue in enumerate(result[key]):
            db.add(ImportIssue(id=identifier(), import_id=row.id, severity=severity, ordinal=ordinal,
                               path=issue["path"], code=issue["code"], action=issue.get("action"), legacy_metadata={}))
    summary = required_summary(db, ImportSummary, row.id)
    summary.preview = {key: value for key, value in result.items()
                       if key not in ("files", "classes", "errors", "warnings", "sync_files")}
    summary.fingerprint = result.get("fingerprint")
    summary.file_count, summary.class_count = len(result["files"]), len(result["classes"])
    summary.error_count, summary.warning_count = len(result["errors"]), len(result["warnings"])
    summary.total_size_bytes = sum(file["size_bytes"] for file in result["files"])


def page(query, column, *, scope, snapshot, key, serialize, limit=None, cursor=None):
    maximum = min(200, max(1, int(os.environ.get("FAMA_IMPORT_PAGE_MAX", "200"))))
    default = min(maximum, max(1, int(os.environ.get("FAMA_IMPORT_PAGE_SIZE", "50"))))
    limit = default if limit is None else limit
    if not 1 <= limit <= maximum:
        raise HTTPException(422, "El tamaño de página supera el máximo configurado.")
    total = query.with_entities(func.count(column)).scalar()
    if cursor is not None:
        try:
            value = json.loads(base64.urlsafe_b64decode(cursor.encode("ascii")))
            if (not isinstance(value, list) or len(value) != 3 or value[0] != scope
                    or type(value[2]) is not column.type.python_type):
                raise ValueError()
        except (ValueError, TypeError, UnicodeError):
            raise HTTPException(422, "Cursor de página no válido.") from None
        if value[1] != snapshot:
            raise HTTPException(409, "La revisión cambió. Consulta de nuevo la primera página.")
        query = query.filter(column > value[2])
    rows = query.order_by(column).limit(limit + 1).all()
    following = None
    if len(rows) > limit:
        last = getattr(rows[limit - 1], column.key)
        following = base64.urlsafe_b64encode(json.dumps([scope, snapshot, last]).encode()).decode()
    return {key: [serialize(row) for row in rows[:limit]], "total": total,
            "next_cursor": following, "snapshot": snapshot}
