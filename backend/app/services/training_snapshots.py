"""Owner-scoped frozen local cohorts. Construction never creates training jobs."""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import tempfile
import uuid

from fastapi import HTTPException
from sqlalchemy import insert, literal, select

from app.models.dataset_import_metadata import DatasetMember
from app.models.training_snapshot import TrainingSnapshot, SnapshotMember
from app.services.dataset_import_jobs import _gate


class SnapshotIntegrityError(RuntimeError):
    """A local snapshot or its source cannot be trusted."""


def _json(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":")) + "\n").encode()


def _parts(value):
    if not isinstance(value, str) or not value or "\\" in value or any(p in ("", ".", "..") for p in value.split("/")) or PurePosixPath(value).is_absolute():
        raise SnapshotIntegrityError("Unsafe local reference")
    return value.split("/")


@contextmanager
def _open(root, relative):
    # Open every component without following links, including the configured root.
    parts = _parts(str(Path(root).absolute()).lstrip("/")) + _parts(relative)
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in parts[:-1]:
            nxt = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = nxt
        file_fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
        with os.fdopen(file_fd, "rb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise SnapshotIntegrityError("Not a regular file")
            yield stream
    finally:
        os.close(fd)


@contextmanager
def _root_directory(path):
    """Create/open a trusted root without following any ancestor symlink."""
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in _parts(str(path).lstrip("/")):
            try:
                try:
                    nxt = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                except FileNotFoundError:
                    try:
                        os.mkdir(part, mode=0o700, dir_fd=fd)
                    except FileExistsError:
                        # Another creator may have won. Reopen without following
                        # links; the final root must still pass the privacy check.
                        pass
                    os.fsync(fd)
                    nxt = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            except OSError as error:
                raise SnapshotIntegrityError("Unsafe snapshot root") from error
            os.close(fd)
            fd = nxt
        if os.fstat(fd).st_mode & 0o077:
            raise SnapshotIntegrityError("Snapshot root must be private")
        yield fd
    finally:
        os.close(fd)


class TrainingSnapshots:
    """Server-configured roots; callers supply only exact owner and opaque IDs.

    get returns a bounded descriptor; iter_verified yields (metadata, <=1MiB
    chunk) pairs. Consumers must exhaust iteration successfully before publishing
    derived artifacts. No deletion/GC interface is deliberately provided.
    """

    def __init__(self, sessions, source, root, *, reserve_bytes=1024 * 1024):
        self.sessions, self.source, self.root = sessions, source, Path(root).absolute()
        if type(reserve_bytes) is not int or reserve_bytes < 0:
            raise ValueError("Invalid free-space reserve")
        self.reserve_bytes = reserve_bytes

    def _row(self, db, owner, snapshot_id):
        row = db.query(TrainingSnapshot).filter_by(id=snapshot_id, owner_id=owner, state="ready").first()
        if row is None:
            raise HTTPException(404, "Snapshot no encontrado.")
        return row

    def _descriptor(self, row):
        return {key: getattr(row, key) for key in ("id", "owner_id", "dataset_id", "dataset_revision", "name", "description", "file_count", "total_size_bytes", "manifest_sha256", "classes")}

    def _batch(self, snapshot_id, cursor=""):
        with self.sessions() as db:
            rows = db.query(SnapshotMember).filter(SnapshotMember.snapshot_id == snapshot_id, SnapshotMember.member_id > cursor).order_by(SnapshotMember.member_id).limit(64).all()
            return [{c.name: getattr(row, c.name) for c in SnapshotMember.__table__.columns if c.name != "snapshot_id"} for row in rows]

    def _members(self, snapshot_id):
        cursor = ""
        while batch := self._batch(snapshot_id, cursor):
            yield from batch
            cursor = batch[-1]["member_id"]

    def create(self, owner, dataset_id):
        snapshot_id = uuid.uuid4().hex
        # Capture exactly one complete cohort using confirm's database gate.
        # The transaction ends before any filesystem copying starts.
        with self.sessions.begin() as db:
            _gate(db)
            dataset = self.source.dataset(db, owner, dataset_id)
            fields = ("source_import_id", "stored_name", "class_name", "original_path", "relative_path", "sha256", "size_bytes")
            db.add(TrainingSnapshot(id=snapshot_id, owner_id=owner, dataset_id=dataset.id,
                dataset_revision=dataset.revision, name=dataset.name, description=dataset.description or "",
                state="building", file_count=0, total_size_bytes=0, classes=[]))
            db.flush()
            db.execute(insert(SnapshotMember).from_select(["snapshot_id", "member_id", *fields],
                select(literal(snapshot_id), DatasetMember.id, *(getattr(DatasetMember, f) for f in fields)).where(DatasetMember.dataset_id == dataset.id)))
        with _root_directory(self.root) as root_fd:
            return self._materialize(owner, dataset_id, snapshot_id, root_fd)

    def _materialize(self, owner, dataset_id, snapshot_id, root_fd):
        staging = ".staging-" + snapshot_id
        published, staging_fd, owned = False, None, False
        try:
            # Include conservative per-entry manifest/filesystem overhead, not
            # just payload bytes. ENOSPC races still fail closed during copying.
            total = 8192 + sum(m["size_bytes"] + 8192 for m in self._members(snapshot_id))
            if total + self.reserve_bytes > shutil.disk_usage(self.root).free:
                raise SnapshotIntegrityError("Insufficient snapshot space")
            os.mkdir(staging, mode=0o700, dir_fd=root_fd)
            owned = True
            staging_fd = os.open(staging, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root_fd)
            count, size, classes = 0, 0, set()
            manifest_fd = os.open("manifest.jsonl", os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o400, dir_fd=staging_fd)
            with os.fdopen(manifest_fd, "wb") as manifest:
                with self.sessions() as db:
                    row = db.get(TrainingSnapshot, snapshot_id)
                    header = dict(schema_version=1, owner_id=owner, dataset_id=dataset_id,
                        dataset_revision=row.dataset_revision, name=row.name, description=row.description)
                manifest.write(_json(header))
                for member in self._members(snapshot_id):
                    _parts(member["original_path"])
                    _parts(member["relative_path"])
                    if len(_parts(member["stored_name"])) != 1 or len(_parts(member["source_import_id"])) != 1:
                        raise SnapshotIntegrityError("Unsafe source reference")
                    if len(_parts(member["member_id"])) != 1:
                        raise SnapshotIntegrityError("Unsafe member identity")
                    digest, length = hashlib.sha256(), 0
                    with _open(self.source.root, "objects/" + member["source_import_id"] + "/" + member["stored_name"]) as src:
                        output_fd = os.open(member["member_id"], os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o400, dir_fd=staging_fd)
                        with os.fdopen(output_fd, "wb") as out:
                            self._copy(src, out, member)
                    count += 1
                    size += member["size_bytes"]
                    classes.add(member["class_name"])
                    manifest.write(_json(member))
                if not count:
                    raise SnapshotIntegrityError("Empty cohort")
                manifest.flush()
                os.fsync(manifest.fileno())
            digest = hashlib.sha256()
            manifest_fd = os.open("manifest.jsonl", os.O_RDONLY | os.O_NOFOLLOW, dir_fd=staging_fd)
            with os.fdopen(manifest_fd, "rb") as stream:
                while chunk := stream.read(1024 * 1024):
                    digest.update(chunk)
            os.fsync(staging_fd)
            os.rename(staging, snapshot_id, src_dir_fd=root_fd, dst_dir_fd=root_fd)
            published = True
            os.fsync(root_fd)
            with self.sessions.begin() as db:
                row = db.get(TrainingSnapshot, snapshot_id)
                row.file_count, row.total_size_bytes = count, size
                row.classes, row.manifest_sha256, row.state = sorted(classes), digest.hexdigest(), "ready"
            return self.get(owner, snapshot_id)
        except Exception:
            if not published and owned:
                shutil.rmtree(staging, dir_fd=root_fd)
            raise
        finally:
            if staging_fd is not None:
                os.close(staging_fd)

    def _copy(self, src, out, member):
        digest, length = hashlib.sha256(), 0
        while chunk := src.read(1024 * 1024):
            length += len(chunk)
            if length > member["size_bytes"]:
                raise SnapshotIntegrityError("Source size mismatch")
            digest.update(chunk)
            out.write(chunk)
        if length != member["size_bytes"] or digest.hexdigest() != member["sha256"]:
            raise SnapshotIntegrityError("Source integrity mismatch")
        out.flush()
        os.fsync(out.fileno())

    def get(self, owner, snapshot_id):
        with self.sessions() as db:
            result = self._descriptor(self._row(db, owner, snapshot_id))
        digest = hashlib.sha256()
        with _open(self.root, snapshot_id + "/manifest.jsonl") as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
        if digest.hexdigest() != result["manifest_sha256"]:
            raise SnapshotIntegrityError("Manifest integrity mismatch")
        return result

    def _manifest_members(self, owner, snapshot_id):
        descriptor = self.get(owner, snapshot_id)
        digest, length = hashlib.sha256(), 0
        with tempfile.SpooledTemporaryFile(max_size=1024 * 1024) as manifest:
            with _open(self.root, snapshot_id + "/manifest.jsonl") as source:
                while chunk := source.read(1024 * 1024):
                    length += len(chunk)
                    if length > 8192 * (descriptor["file_count"] + 1):
                        raise SnapshotIntegrityError("Oversized manifest")
                    digest.update(chunk)
                    manifest.write(chunk)
            if digest.hexdigest() != descriptor["manifest_sha256"]:
                raise SnapshotIntegrityError("Manifest changed during read")
            manifest.seek(0)
            header = json.loads(manifest.readline(8192))
            if any(header[key] != descriptor[key] for key in ("owner_id", "dataset_id", "dataset_revision", "name", "description")):
                raise SnapshotIntegrityError("Manifest identity mismatch")
            count, total, classes = 0, 0, set()
            while line := manifest.readline(8192):
                if not line.endswith(b"\n"):
                    raise SnapshotIntegrityError("Oversized manifest entry")
                member = json.loads(line)
                if len(_parts(member["member_id"])) != 1:
                    raise SnapshotIntegrityError("Unsafe member identity")
                count += 1
                total += member["size_bytes"]
                classes.add(member["class_name"])
                yield member
            if count != descriptor["file_count"] or total != descriptor["total_size_bytes"] or sorted(classes) != descriptor["classes"]:
                raise SnapshotIntegrityError("Manifest summary mismatch")

    def iter_verified(self, owner, snapshot_id):
        for member in self._manifest_members(owner, snapshot_id):
            digest, length = hashlib.sha256(), 0
            # Spill large files to private temporary storage, rather than yield
            # unverified bytes or race a second read of mutable local storage.
            with tempfile.SpooledTemporaryFile(max_size=1024 * 1024) as verified:
                with _open(self.root, snapshot_id + "/" + member["member_id"]) as stream:
                    while chunk := stream.read(1024 * 1024):
                        length += len(chunk)
                        if length > member["size_bytes"]:
                            raise SnapshotIntegrityError("Snapshot size mismatch")
                        digest.update(chunk)
                        verified.write(chunk)
                if length != member["size_bytes"] or digest.hexdigest() != member["sha256"]:
                    raise SnapshotIntegrityError("Snapshot integrity mismatch")
                verified.seek(0)
                while chunk := verified.read(1024 * 1024):
                    yield dict(member), chunk
