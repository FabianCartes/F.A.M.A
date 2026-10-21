"""Durable complete-only ZIP64 exports and native download lifetimes.

No network or hashing runs under the shared admission gate. Attempts own private
directories; callbacks and HTTP streams hold directory locks until I/O stops.
"""
from contextlib import contextmanager
from dataclasses import asdict, dataclass
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import unicodedata
import uuid
import zipfile

from fastapi import HTTPException
from sqlalchemy import func, or_, select

from app.models.dataset_export import DatasetExport, DownloadSession
from app.services.dataset_import_jobs import ImportJobQueue, LeaseLost, _gate, lease_duration
from app.services.dataset_import_manifests import authorized_reference
from app.services.dataset_import_storage import IntegrityConflict, _HashSink
from app.services.dataset_import_worker import ImportJobWorker, _private_root
from app.services.dataset_imports import _durable_directory, digest_file, reject
from app.services.dataset_storage import physical_storage


@dataclass(frozen=True)
class ExportLimits:
    files: int = 50000
    bytes: int = 15 * 1024**3
    manifest_bytes: int = 128 * 1024**2
    session_seconds: int = 900
    artifact_seconds: int = 3600
    retention_seconds: int = 86400

    def __post_init__(self):
        for name, maximum in (("files", 50000), ("bytes", 15 * 1024**3),
                              ("manifest_bytes", 128 * 1024**2), ("session_seconds", 3600),
                              ("artifact_seconds", 86400), ("retention_seconds", 86400)):
            value = getattr(self, name)
            if type(value) is not int or not 1 <= value <= maximum:
                raise ValueError("Invalid export limit")


def _snapshot(row):
    return dict(id=row.id, owner_id=row.owner_id, dataset_id=row.dataset_id, revision=row.revision,
                status=row.status, progress=row.progress, attempt=row.attempt, token=row.token,
                status_url=f"/api/ingestion/imports/exports/{row.id}",
                size_bytes=row.size_bytes, sha256=row.sha256, expires_at=row.expires_at,
                error=row.error, artifact=row.artifact, artifact_identity=row.artifact_identity)


def artifact_identity(info):
    """Detect ordinary replacement/mutation without rehashing 15 GiB per range."""
    return ":".join(str(value) for value in (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns))


def public_export(value):
    return {key: value[key] for key in ("id", "dataset_id", "revision", "status", "progress",
            "status_url", "size_bytes", "sha256", "expires_at", "error")}


class ExportQueue:
    def __init__(self, sessions, service, *, clock=None, limits=None):
        self.sessions, self.service = sessions, service
        self.jobs = ImportJobQueue(sessions, clock=clock)
        self.limits = limits or ExportLimits()

    def physical(self, db, *, root=None):
        policy = physical_storage(self.service, db)
        if policy is not None and root is not None and Path(root) != policy.roots["exports"]:
            reject(503, "La raíz de exportación no coincide con el presupuesto físico.")
        return policy

    def _reserve(self, db, policy, identity, attempt, token):
        policy.acquire(db, resource=export_resource(identity, attempt, token), phase="export",
            attempt=attempt, token=token, amounts={policy.pools["exports"]: export_envelope(self.limits)},
            policy=hashlib.sha256(json.dumps([policy.configuration_sha256, asdict(self.limits)],
                                           sort_keys=True).encode()).hexdigest())

    def _owned(self, db, owner, identity):
        row = db.query(DatasetExport).filter_by(id=identity, owner_id=owner).first()
        if row is None:
            reject(404, "Exportación no encontrada.")
        self.service.dataset(db, owner, row.dataset_id)
        return row

    def admit(self, owner, dataset_id, revision, request_key):
        if (not isinstance(request_key, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,100}", request_key)
                or type(revision) is not int or revision < 0):
            reject(422, "Solicitud de exportación no válida.")
        with self.sessions() as db, db.begin():
            _gate(db)
            reference = authorized_reference(self.service, db, owner, dataset_id, revision)
            if reference["status"] != "complete":
                reject(409, "La revisión todavía no tiene un manifiesto completo.")
            prior = db.query(DatasetExport).filter_by(owner_id=owner, request_key=request_key).first()
            if prior:
                if (prior.dataset_id, prior.revision) != (dataset_id, revision):
                    reject(409, "La operación ya existe con otros parámetros.")
                return _snapshot(prior)
            physical = self.physical(db)
            active = db.query(DatasetExport).filter(DatasetExport.status.in_(("queued", "running")))
            if (active.count() >= self.jobs.limits.global_active
                    or active.filter_by(owner_id=owner).count() >= self.jobs.limits.owner_active):
                reject(429, "Se alcanzó el límite de trabajos activos.")
            now = self.jobs._now(db)
            row = DatasetExport(id=uuid.uuid4().hex, owner_id=owner, dataset_id=dataset_id,
                revision=revision, request_key=request_key, status="queued", created_at=now,
                expires_at=now + self.limits.artifact_seconds, attempt=0, token=0, progress=0)
            db.add(row)
            db.flush()
            if physical is not None:
                self._reserve(db, physical, row.id, 1, 1)
            return _snapshot(row)

    def get(self, owner, identity):
        with self.sessions() as db:
            return _snapshot(self._owned(db, owner, identity))

    def list(self, owner, dataset_id):
        with self.sessions() as db:
            self.service.dataset(db, owner, dataset_id)
            rows = db.query(DatasetExport).filter_by(owner_id=owner, dataset_id=dataset_id).order_by(
                DatasetExport.created_at.desc(), DatasetExport.id.desc()).limit(20)
            return {"exports": [public_export(_snapshot(row)) for row in rows]}

    def claim(self, *, lease_seconds):
        duration = lease_duration(lease_seconds)
        with self.sessions() as db, db.begin():
            _gate(db)
            now = self.jobs._now(db)
            row = db.scalar(select(DatasetExport).where(or_(DatasetExport.status == "queued",
                (DatasetExport.status == "running") & (DatasetExport.lease_until <= now)))
                .order_by(DatasetExport.created_at, DatasetExport.id).limit(1))
            if row is None:
                return None
            row.attempt += 1
            row.token += 1
            row.status, row.progress, row.error = "running", 0, None
            row.lease_until = now + duration
            return _snapshot(row)

    @contextmanager
    def publication(self, attempt):
        with self.sessions() as db, db.begin():
            _gate(db)
            row = db.get(DatasetExport, attempt["id"])
            if (row is None or row.status != "running" or row.attempt != attempt["attempt"]
                    or row.token != attempt["token"] or row.lease_until <= self.jobs._now(db)):
                raise LeaseLost("Export attempt expired")
            self.service.dataset(db, row.owner_id, row.dataset_id)
            yield db, row
            if row.status == "running" and row.lease_until <= self.jobs._now(db):
                raise LeaseLost("Export attempt expired during publication")

    def heartbeat(self, attempt, *, lease_seconds):
        duration = lease_duration(lease_seconds)
        with self.publication(attempt) as (db, row):
            row.lease_until = max(row.lease_until, self.jobs._now(db) + duration)

    def progress(self, attempt, *, stage, progress):
        if type(progress) is not int or not 0 <= progress <= 99:
            raise ValueError("Invalid export progress")
        with self.publication(attempt) as (_, row):
            row.progress = max(row.progress, progress)

    def finish(self, attempt, *, result=None, error=None):
        # Completion belongs to the fenced artifact publication, not callback return.
        with self.publication(attempt) as (_, row):
            row.status, row.error, row.lease_until = "failed", error or "execution_failed", None

    def issue_session(self, owner, identity):
        with self.sessions() as db, db.begin():
            _gate(db)
            row = self._owned(db, owner, identity)
            now = self.jobs._now(db)
            if row.status != "succeeded" or row.expires_at <= now:
                reject(410, "La exportación no está disponible. Genera una nueva.")
            if db.query(DownloadSession).filter(DownloadSession.export_id == row.id,
                    DownloadSession.expires_at > now).count() >= 8:
                reject(429, "Hay ocho sesiones vigentes. Espera su vencimiento antes de renovar.")
            expires = min(now + self.limits.session_seconds, row.created_at + self.limits.retention_seconds)
            if expires <= now:
                reject(410, "La exportación alcanzó su vigencia máxima.")
            row.expires_at = max(row.expires_at, expires)
            secret, identity = secrets.token_urlsafe(32), uuid.uuid4().hex
            db.add(DownloadSession(id=identity, export_id=row.id, owner_id=owner,
                secret_sha256=hashlib.sha256(secret.encode()).hexdigest(), established=False, expires_at=expires))
            return dict(ticket=identity + "." + secret, expires_at=expires)

    def authorize_download(self, identity, credential, *, bootstrap=False):
        if not isinstance(credential, str) or not re.fullmatch(r"[0-9a-f]{32}\.[A-Za-z0-9_-]{43}", credential):
            reject(401, "Sesión de descarga requerida.")
        session_id, secret = credential.split(".")
        with self.sessions() as db, db.begin():
            # Cookie/range authorization is a read: a later 416 must not commit
            # even an admission-gate counter. Only ticket consumption mutates.
            if bootstrap:
                _gate(db)
            session = db.get(DownloadSession, session_id)
            now = self.jobs._now(db)
            if (session is None or session.export_id != identity or session.expires_at <= now
                    or not secrets.compare_digest(session.secret_sha256, hashlib.sha256(secret.encode()).hexdigest())):
                reject(401, "Sesión de descarga no válida o vencida.")
            if bootstrap and session.established:
                reject(401, "El ticket ya estableció su sesión.")
            if not bootstrap and not session.established:
                reject(401, "Establece primero la sesión de descarga.")
            row = self._owned(db, session.owner_id, identity)
            if row.status != "succeeded" or row.expires_at <= now:
                reject(410, "La exportación venció.")
            if bootstrap:
                session.established = True
            return _snapshot(row), session.expires_at - now

    def cleanup(self, root):
        """Explicit maintenance; exclusive locks never interrupt callbacks or streams."""
        root = _private_root(root)
        result = {"completed": 0, "busy": 0, "failed": 0}
        for path in root.iterdir():
            match = re.fullmatch(r"([0-9a-f]{32})-[1-9][0-9]*-[1-9][0-9]*", path.name)
            if not match or path.is_symlink():
                continue
            fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    result["busy"] += 1
                    continue
                with self.sessions() as db, db.begin():
                    _gate(db)
                    row = db.get(DatasetExport, match[1])
                    if row is None or row.status in ("queued", "running"):
                        continue
                    if row.artifact and row.artifact.split("/")[0] == path.name:
                        if row.status == "succeeded" and row.expires_at > self.jobs._now(db):
                            continue
                        row.status = "deleting"
                    physical = self.physical(db, root=root)
                    if physical is not None:
                        # Exclusive directory ownership proves the callback and
                        # downloads stopped. Claim only advances tokens; it never
                        # resumes this terminal attempt or resurrects its grant.
                        _, number, token = path.name.rsplit("-", 2)
                        physical.retire(db, export_resource(row.id, int(number), int(token)))
                try:
                    shutil.rmtree(path)
                    _durable_directory(root)
                    with self.sessions() as db, db.begin():
                        _gate(db)
                        row = db.get(DatasetExport, match[1])
                        if row.status == "deleting":
                            row.status = "expired"
                    result["completed"] += 1
                except OSError:
                    result["failed"] += 1
            finally:
                os.close(fd)
        # Retry a previous delete whose directory vanished before parent fsync.
        with self.sessions() as db, db.begin():
            _gate(db)
            for row in db.query(DatasetExport).filter_by(status="deleting"):
                if not (root / row.artifact.split("/")[0]).exists():
                    _durable_directory(root)
                    row.status = "expired"
        return result


def _path(value, *, segment=False):
    if (not isinstance(value, str) or not value or len(value.encode("utf-8")) > 1024
            or any(ord(c) < 32 or ord(c) == 127 for c in value) or "\\" in value or ":" in value
            or any(part in ("", ".", "..") or part.endswith((" ", ".")) for part in value.split("/"))
            or segment and "/" in value):
        raise IntegrityConflict("Unsafe export path")
    return value


def export_resource(identity, attempt, token):
    return f"export:{identity}:{attempt}:{token}"


def export_envelope(limits):
    # ZIP_STORED: local header 30 + forced ZIP64 extra 20; central
    # header 46 + worst-case ZIP64 extra 32; two UTF-8 names <=2049 each.
    # End records: EOCD 22 + ZIP64 EOCD 56 + locator 20. No comments.
    return limits.manifest_bytes + limits.bytes + limits.files * 4226 + 98


class _ArtifactWriter:
    """Bound seekable ZIP growth, including header rewrites and central records."""

    def __init__(self, destination, maximum, physical):
        self.destination, self.maximum, self.physical = destination, maximum, physical

    def write(self, data):
        if self.tell() + len(data) > self.maximum:
            raise IntegrityConflict("Export exceeds physical envelope")
        pool = self.physical.pools["exports"]
        if shutil.disk_usage(self.physical.roots["exports"]).free < self.physical.free_floors[pool]:
            reject(507, "Espacio físico insuficiente para autorizar la escritura.")
        written = self.destination.write(data)
        if written != len(data):
            raise OSError("Short export write")
        return written

    def tell(self):
        return self.destination.tell()

    def seek(self, *args):
        return self.destination.seek(*args)

    def flush(self):
        return self.destination.flush()


def _json(line):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise IntegrityConflict("Duplicate manifest key")
            result[key] = value
        return result
    return json.loads(line, object_pairs_hook=unique)


def _line(stream):
    line = stream.readline(16385)
    if len(line) > 16384:
        raise IntegrityConflict("Manifest record exceeds bound")
    return line


def build_zip(storage, reference, staging, limits, report, *, physical=None):
    """Read T6's bounded line-delimited JSON wire format, not local member rows."""
    manifest = reference["manifest"]
    owner, dataset = reference["owner_id"], reference["dataset_id"]
    prefix = f"private-imports/{owner}/{dataset}/"
    expected_manifest = f"{prefix}revisions/{reference['dataset_revision']}/{manifest['sha256']}.json"
    if (manifest["object_key"] != expected_manifest or type(manifest["size_bytes"]) is not int
            or not 0 < manifest["size_bytes"] <= limits.manifest_bytes):
        raise IntegrityConflict("Unauthorized manifest reference")
    manifest_path = staging / "manifest.json"
    with manifest_path.open("xb") as target:
        if physical is not None:
            target = physical.writer(target, manifest["size_bytes"], role="exports")
        storage.read_verified(manifest["object_key"], manifest["object_generation"],
                              manifest["sha256"], manifest["size_bytes"],
                              _HashSink(manifest["size_bytes"], target))
    if manifest_path.stat().st_size != manifest["size_bytes"] or digest_file(manifest_path) != manifest["sha256"]:
        raise IntegrityConflict("Manifest integrity mismatch")
    output = staging / "export.part"
    with manifest_path.open("rb") as stream, output.open("x+b") as destination, zipfile.ZipFile(
            _ArtifactWriter(destination, export_envelope(limits) - limits.manifest_bytes, physical)
            if physical is not None else destination,
            "w", compression=zipfile.ZIP_STORED, allowZip64=True) as archive:
        suffix = b', "files": [\n'
        first = _line(stream)
        if not first.endswith(suffix):
            raise IntegrityConflict("Unsupported manifest framing")
        header = _json(first[:-len(suffix)] + b"}")
        if (set(header) != {"schema_version", "dataset_id", "dataset_revision", "name", "description", "file_count", "total_size_bytes"}
                or type(header["schema_version"]) is not int or header["schema_version"] != 1
                or header["dataset_id"] != dataset or type(header["dataset_revision"]) is not int
                or header["dataset_revision"] != reference["dataset_revision"]
                or any(type(header[k]) is not int or header[k] != reference[k] for k in ("file_count", "total_size_bytes"))
                or not 0 <= header["file_count"] <= limits.files or not 0 <= header["total_size_bytes"] <= limits.bytes):
            raise IntegrityConflict("Manifest header mismatch")
        name = _path(header["name"], segment=True)
        total = count = 0
        paths, hashes = set(), set()
        needs_entry = False
        while True:
            line = _line(stream).strip()
            if line == b"]}":
                if needs_entry or stream.read(1):
                    raise IntegrityConflict("Invalid manifest ending")
                break
            if not line or count >= limits.files:
                raise IntegrityConflict("Invalid manifest entry count")
            if count and not needs_entry:
                raise IntegrityConflict("Missing manifest separator")
            needs_entry = line.endswith(b",")
            entry = _json(line[:-1] if needs_entry else line)
            if not isinstance(entry, dict) or set(entry) != {"class_name", "original_path", "relative_path", "source_import_id", "size_bytes", "sha256", "object_key", "object_generation"}:
                raise IntegrityConflict("Invalid manifest entry schema")
            relative = _path(entry["relative_path"])
            _path(entry["original_path"])
            label = _path(entry["class_name"], segment=True)
            canonical = unicodedata.normalize("NFC", relative).casefold()
            digest, size, generation = entry["sha256"], entry["size_bytes"], entry["object_generation"]
            if (not isinstance(digest, str) or not re.fullmatch("[0-9a-f]{64}", digest)
                    or type(size) is not int or size <= 0 or total + size > limits.bytes
                    or not isinstance(generation, str) or not re.fullmatch(r"[0-9]{1,100}", generation)
                    or not isinstance(entry["source_import_id"], str) or not re.fullmatch("[0-9a-f]{32}", entry["source_import_id"])
                    or entry["object_key"] != prefix + digest + ".wav" or canonical in paths or digest in hashes
                    or not relative.lower().endswith(".wav") or relative.split("/")[0] != label):
                raise IntegrityConflict("Invalid or unauthorized manifest member")
            paths.add(canonical)
            hashes.add(digest)
            report(stage="exporting", progress=min(99, count * 99 // max(1, header["file_count"])))
            with archive.open(name + "/" + relative, "w", force_zip64=True) as member:
                sink = _HashSink(size, member)
                storage.read_verified(entry["object_key"], generation, digest, size, sink)
                if sink.size != size or sink.digest.hexdigest() != digest:
                    raise IntegrityConflict("WAV integrity mismatch")
            count += 1
            total += size
        if count != header["file_count"] or total != header["total_size_bytes"]:
            raise IntegrityConflict("Incomplete export")
    with output.open("rb") as stream:
        os.fsync(stream.fileno())
    final = staging / "export.zip"
    output.rename(final)
    final.chmod(0o400)
    with final.open("rb") as stream:
        os.fsync(stream.fileno())
    _durable_directory(staging)
    _durable_directory(staging.parent)
    return final, digest_file(final)


class ExportExecution:
    def __init__(self, queue, root, *, storage, **options):
        self.queue, self.root, self.storage = queue, _private_root(root), storage
        self.worker = ImportJobWorker(queue, self.root, self.execute, preparation=self.preparation, **options)

    @contextmanager
    def preparation(self, attempt):
        with self.queue.publication(attempt) as (db, row):
            physical = self.queue.physical(db, root=self.root)
            if physical is not None:
                # First authority must have been admitted durably, including
                # after a legacy lease expired. Retry is not implicit adoption.
                from app.models.dataset_storage import StorageGrant
                resource = export_resource(row.id, 1, 1)
                if not db.query(StorageGrant.id).filter_by(resource_id=resource, state="live").first():
                    reject(503, "La exportación requiere conciliación explícita.")
                self.queue._reserve(db, physical, row.id, 1, 1)
                self.queue._reserve(db, physical, row.id, row.attempt, row.token)
        # Commit before creating output. Cleanup skips running jobs, even when
        # their lease expired; the worker owns its new lock before scheduling.
        yield

    def run_once(self):
        return self.worker.run_once()

    def execute(self, attempt, staging, report):
        # ImportJobWorker already owns the directory lock until callback exit.
        # Reopening and flocking the same directory would deadlock against it.
        with self.queue.publication(attempt) as (db, row):
            physical = self.queue.physical(db, root=self.root)
            reference = authorized_reference(self.queue.service, db, row.owner_id, row.dataset_id, row.revision)
            reference["owner_id"] = row.owner_id
            if reference["status"] != "complete":
                raise IntegrityConflict("Incomplete revision")
        path, digest = build_zip(self.storage, reference, staging, self.queue.limits, report, physical=physical)
        with self.queue.publication(attempt) as (db, row):
            now = self.queue.jobs._now(db)
            if row.lease_until <= now:
                raise LeaseLost("Export expired before completion")
            row.artifact = staging.name + "/export.zip"
            row.artifact_identity = artifact_identity(path.stat())
            row.sha256, row.size_bytes = digest, path.stat().st_size
            row.status, row.progress, row.lease_until = "succeeded", 100, None
            row.expires_at = now + self.queue.limits.artifact_seconds
            if physical is not None:
                physical.retire(db, export_resource(row.id, row.attempt, row.token))
        return {}
