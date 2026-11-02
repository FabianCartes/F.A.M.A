"""Explicit opt-in physical budget policy, adapted from the preserved reference.

Promises include materialized bytes: this is conservative authority, not disk
preallocation. Caller holds filesystem ownership locks BEFORE the queue gate,
serializes every request under that gate, and owns commit/rollback. Constructors
and verification never create directories or tables. Runtime activation is external.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil

from fastapi import HTTPException
from sqlalchemy import CheckConstraint, UniqueConstraint, inspect
from sqlalchemy.exc import SQLAlchemyError

from app.models.dataset_storage import STORAGE_MODELS, StorageGrant, StoragePool, StorageSchema

MAXIMUM = 2**63 - 1
ROLES = frozenset(("imports", "objects", "attempts", "manifests", "scratch", "exports"))
UNAVAILABLE = "El presupuesto físico requiere un perfil activo y compatible."


def _reject(code=503):
    raise HTTPException(code, UNAVAILABLE if code == 503 else "Espacio físico insuficiente.")


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _integer(value, *, positive=False):
    if type(value) is not int or not int(positive) <= value <= MAXIMUM:
        raise ValueError("Physical bounds require signed 64-bit integers")
    return value


def _check_sql(sql):
    # Preserve quoted literal case, unlike the migration's permissive normalizer.
    pieces = re.split(r"('(?:''|[^'])*')", str(sql))
    literals = []
    for index in range(1, len(pieces), 2):
        literals.append(pieces[index])
        pieces[index] = f"@{len(literals) - 1}@"
    syntax = re.sub(r"::(?:character varying|text)(?:\[\])?", "", "".join(pieces).lower())
    syntax = "".join(syntax.split()).replace("(", "").replace(")", "")
    return syntax.replace("=anyarray[", "in").replace("]", ""), tuple(literals)


def _verify_schema(conn):
    from scripts.migrate_dataset_import_jobs import _verify_table
    inspector = inspect(conn)
    for model in STORAGE_MODELS:
        table = model.__table__
        _verify_table(conn, table)
        columns = {item["name"]: item for item in inspector.get_columns(table.name)}
        for column in table.columns:
            actual = columns[column.name]
            if (actual["type"].compile(dialect=conn.dialect) != column.type.compile(dialect=conn.dialect)
                    or getattr(actual["type"], "length", None) != getattr(column.type, "length", None)
                    or actual.get("default") is not None):
                raise ValueError("incompatible_storage_column")
        checks = {_check_sql(item["sqltext"]) for item in inspector.get_check_constraints(table.name)}
        expected = {_check_sql(item.sqltext) for item in table.constraints if isinstance(item, CheckConstraint)}
        unique = {tuple(item["column_names"]) for item in inspector.get_unique_constraints(table.name)}
        if (checks != expected or unique != {tuple(c.name for c in item.columns) for item in table.constraints
                                             if isinstance(item, UniqueConstraint)}
                or any(item.get("unique") for item in inspector.get_indexes(table.name))
                or any(item.get("referred_schema") is not None or item.get("options")
                       for item in inspector.get_foreign_keys(table.name))):
            raise ValueError("incompatible_storage_constraints")


def _write_transaction(db):
    # SQLite legacy transaction control does not BEGIN for SELECT/SAVEPOINT.
    # Releasing the outermost savepoint would otherwise commit caller-owned work.
    conn = db.connection()
    if conn.dialect.name == "sqlite" and not conn.connection.driver_connection.in_transaction:
        conn.exec_driver_sql("BEGIN")


def _mount(path):
    if not path.is_absolute() or path != path.resolve(strict=True):
        raise ValueError("Roots must be existing absolute physical paths")
    if any(parent.is_symlink() for parent in (path, *path.parents)):
        raise ValueError("Roots must not contain links")
    info = path.stat()
    if not path.is_dir() or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ValueError("Roots must be private directories owned by this user")
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        with open(f"/proc/self/fdinfo/{fd}") as stream:
            mount = next(line.split()[1] for line in stream if line.startswith("mnt_id:"))
        view = os.fstatvfs(fd)
    finally:
        os.close(fd)
    with open("/proc/self/mountinfo") as stream:
        record = next(line.split() for line in stream if line.split()[0] == mount)
    separator = record.index("-")
    filesystem = record[separator + 1]
    options = ",".join((record[5], record[separator + 3]))
    if filesystem not in ("ext4", "xfs", "tmpfs") or "quota" in options:
        raise ValueError("Storage topology requires separate qualification")
    return mount, info.st_dev, view.f_fsid, view.f_frsize, filesystem


class PhysicalStorage:
    """Single Linux host/mount namespace; private same-user local roots only."""

    def __init__(self, *, roots, pools, free_floors, manifest_bytes=64 * 1024**2):
        if set(roots) != ROLES or set(pools) != ROLES or set(free_floors) != set(pools.values()):
            raise ValueError("Every writer role requires an explicit physical pool")
        if any(not isinstance(pool, str) or not 1 <= len(pool) <= 64 for pool in pools.values()):
            raise ValueError("Invalid physical pool identity")
        self.manifest_bytes = _integer(manifest_bytes, positive=True)
        self.roots = {role: Path(path) for role, path in roots.items()}
        self.pools = dict(pools)
        self.free_floors = {pool: _integer(value, positive=True) for pool, value in free_floors.items()}
        self.mounts = {role: _mount(path) for role, path in self.roots.items()}
        for left in ROLES:
            for right in ROLES:
                if (pools[left] == pools[right]) != (self.mounts[left] == self.mounts[right]):
                    raise ValueError("Pool aliases require identical mount views")
                if pools[left] != pools[right] and self.mounts[left][1:3] == self.mounts[right][1:3]:
                    raise ValueError("Distinct mounts may share capacity")
        if len({pools[role] for role in ("imports", "objects", "attempts", "manifests")}) != 1:
            raise ValueError("Publication requires one rename-capable pool")
        if self.roots["objects"] != self.roots["imports"] / "objects":
            raise ValueError("Object root does not match publication")
        if self.roots["manifests"] != self.roots["attempts"]:
            raise ValueError("Manifests must use the attempt root")
        self.configuration_sha256 = _hash({
            "version": 1, "roots": {role: str(path) for role, path in self.roots.items()},
            "pools": self.pools, "floors": self.free_floors, "mounts": self.mounts,
            "manifest_bytes": self.manifest_bytes,
        })

    def verify(self, db, service=None):
        try:
            _verify_schema(db.connection())
            marker = db.get(StorageSchema, 1, populate_existing=True)
            if marker is None or marker.version != 1 or marker.state != "active":
                _reject()
            if service is not None:
                if Path(service.root) != self.roots["imports"]:
                    _reject()
                if getattr(service, "attempt_root", None) is None or Path(service.attempt_root) != self.roots["attempts"]:
                    _reject()
            for role, path in self.roots.items():
                if _mount(path) != self.mounts[role]:
                    _reject()
            for identity, floor in self.free_floors.items():
                row = db.get(StoragePool, identity, populate_existing=True)
                if row is None or row.configuration_sha256 != self.configuration_sha256 or row.free_floor_bytes != floor:
                    _reject()
        except (SQLAlchemyError, OSError, ValueError, StopIteration):
            _reject()

    def policy_hash(self, limits):
        try:
            for value in limits.public().values():
                _integer(value, positive=True)
            _integer(2 * limits.expanded_bytes, positive=True)
        except ValueError:
            _reject()
        return _hash([self.configuration_sha256, limits.public()])

    def acquire(self, db, *, resource, phase, attempt, token, amounts, policy):
        """All requested pools or none; caller must serialize under queue gate."""
        _write_transaction(db)
        self.verify(db)
        _integer(attempt)
        _integer(token)
        if (not isinstance(resource, str) or not 1 <= len(resource) <= 128
                or not isinstance(phase, str) or not 1 <= len(phase) <= 24
                or not isinstance(policy, str) or re.fullmatch(r"[0-9a-f]{64}", policy) is None
                or not amounts):
            raise ValueError("Invalid grant identity")
        expected = []
        for pool, amount in sorted(amounts.items()):
            _integer(amount, positive=True)
            if pool not in self.free_floors:
                _reject()
            identity = _hash([resource, phase, attempt, token, pool])
            row = db.get(StorageGrant, identity, populate_existing=True)
            if row is not None:
                if (row.state != "live" or row.pool_id != pool or row.resource_id != resource
                        or row.phase != phase or row.attempt != attempt or row.token != token
                        or row.policy_sha256 != policy or row.envelope_bytes != amount):
                    _reject()
            else:
                expected.append((identity, pool, amount))
        # Autoflush is required even with caller sessions configured autoflush=False:
        # earlier requests in the SAME transaction must remain additive.
        db.flush()
        for _, pool, amount in expected:
            used = sum(value for (value,) in db.query(StorageGrant.envelope_bytes).filter_by(pool_id=pool, state="live"))
            root = next(self.roots[role] for role in ROLES if self.pools[role] == pool)
            if used + amount + self.free_floors[pool] > shutil.disk_usage(root).free:
                _reject(507)
        with db.begin_nested():
            for identity, pool, amount in expected:
                db.add(StorageGrant(id=identity, pool_id=pool, resource_id=resource, phase=phase,
                    attempt=attempt, token=token, policy_sha256=policy, envelope_bytes=amount, state="live"))
            db.flush()

    def initial(self, db, service, identity, archive_bytes):
        _write_transaction(db)
        self.verify(db, service)
        _integer(archive_bytes, positive=True)
        policy = self.policy_hash(service.limits)
        # Savepoint prevents a rejected second phase from retaining the archive.
        with db.begin_nested():
            self.acquire(db, resource=identity, phase="archive", attempt=0, token=0,
                         amounts={self.pools["imports"]: archive_bytes}, policy=policy)
            self.acquire(db, resource=identity, phase="initial", attempt=0, token=0,
                         amounts={self.pools["imports"]: 2 * service.limits.expanded_bytes}, policy=policy)

    def require(self, db, service, identity, phase, amount, *, attempt=0, token=0, role="imports"):
        """Validate exact live authority, never substitute a different phase/token."""
        self.verify(db, service)
        pool = self.pools[role]
        row = db.get(StorageGrant, _hash([identity, phase, attempt, token, pool]), populate_existing=True)
        if (row is None or row.state != "live" or row.pool_id != pool or row.resource_id != identity
                or row.phase != phase or row.attempt != attempt or row.token != token
                or row.envelope_bytes != amount or row.policy_sha256 != self.policy_hash(service.limits)):
            _reject()
        return row

    def attempt(self, db, service, attempt, *, reviewed=None):
        """Caller owns current attempt/import locks and a validated queue fence.

        An initial envelope has no writer. Its transfer commits with the exact
        running token before extraction. Old attempts otherwise remain charged.
        """
        from app.models.dataset_import import DatasetImport
        source = db.get(DatasetImport, attempt["import_id"])
        if attempt["kind"] == "confirm" and source.status == "imported":
            return  # Replay cannot create payload and may follow completed cleanup.
        if attempt["kind"] == "sync":
            self.acquire(db, resource=f"{attempt['import_id']}:{attempt['id']}", phase="sync",
                         attempt=attempt["attempt"], token=attempt["token"],
                         amounts={self.pools["manifests"]: self.manifest_bytes}, policy=self.policy_hash(service.limits))
            return
        from app.models.dataset_import_receipt import ImportReceipt
        receipt = db.get(ImportReceipt, attempt["import_id"])
        if receipt is None:
            _reject()
        self.require(db, service, attempt["import_id"], "archive", receipt.size_bytes)
        amount = service.limits.expanded_bytes * (1 if attempt["kind"] == "confirm" else 2)
        phase = "preview" if attempt["kind"] == "preview" and not source.request.get("auto_import") else "attempt"
        pool = self.pools["attempts"]
        resource = f"{attempt['import_id']}:{attempt['id']}"
        initial = db.get(StorageGrant, _hash([attempt["import_id"], "initial", 0, 0, pool]),
                         populate_existing=True)
        with db.begin_nested():
            if attempt["kind"] == "preview" and initial is not None and initial.state == "live":
                self.require(db, service, attempt["import_id"], "initial", amount)
                initial.state = "retired"
                db.flush()
            elif reviewed is not None:
                old_resource, number, token = reviewed
                old = db.get(StorageGrant, _hash([old_resource, "preview", number, token, pool]),
                             populate_existing=True)
                if old is not None and old.state == "live":
                    self.require(db, service, old_resource, "preview", 2 * amount,
                                 attempt=number, token=token, role="attempts")
                    # Succeeded is a durable token fence AND caller owns its
                    # flock. Retain extraction's half; transfer only output.
                    old.state = "retired"
                    db.flush()
                    self.acquire(db, resource=old_resource, phase="retained", attempt=number, token=token,
                                 amounts={pool: amount}, policy=self.policy_hash(service.limits))
            self.acquire(db, resource=resource, phase=phase, attempt=attempt["attempt"],
                         token=attempt["token"], amounts={pool: amount}, policy=self.policy_hash(service.limits))

    def reclaim(self, db, service, identity, retained_bytes):
        """After durable deletion, with import AND every attempt flock held.

        Cleanup's committed deleting fence rejects future callbacks. Remaining
        object bytes are transferred, not forgiven because status is imported.
        """
        self.verify(db, service)
        _integer(retained_bytes)
        rows = db.query(StorageGrant).filter(StorageGrant.state == "live").filter(
            (StorageGrant.resource_id == identity) | StorageGrant.resource_id.startswith(identity + ":")).all()
        if retained_bytes > sum(row.envelope_bytes for row in rows):
            _reject()
        for row in rows:
            if row.phase != "published" or not retained_bytes:
                row.state = "retired"
        db.flush()
        if retained_bytes:
            self.acquire(db, resource=identity, phase="published", attempt=0, token=0,
                         amounts={self.pools["objects"]: retained_bytes}, policy=self.policy_hash(service.limits))

    def check_free(self, role, amount=0):
        if shutil.disk_usage(self.roots[role]).free - amount < self.free_floors[self.pools[role]]:
            _reject(507)

    def writer(self, destination, maximum, *, role):
        from app.services.dataset_manifest_stream import BoundedWriter
        return BoundedWriter(destination, maximum, check=lambda amount=0: self.check_free(role, amount))

    def retire(self, db, resource, *, durable_stop=False, phase=None):
        """Caller attests a DURABLE stop fence under exclusive filesystem locks.

        A lease expiry is not a stop fence. This flag cannot prove process death;
        lifecycle integration must establish that fact before invoking retirement.
        Tombstones persist so identical authority can never be resurrected.
        """
        self.verify(db)
        if durable_stop is not True:
            _reject()
        query = db.query(StorageGrant).filter_by(resource_id=resource, state="live")
        if phase is not None:
            query = query.filter_by(phase=phase)
        for row in query:
            row.state = "retired"
        db.flush()


def physical_storage(service, db):
    """Only explicit configuration plus an active marker authorizes physical I/O."""
    policy = getattr(service, "storage_policy", None)
    if policy is not None:
        policy.verify(db, service)
        return policy
    try:
        if inspect(db.connection()).has_table(StorageSchema.__tablename__):
            marker = db.get(StorageSchema, 1, populate_existing=True)
            if marker is not None and (marker.version != 1 or marker.state != "prepared"):
                _reject()
    except SQLAlchemyError:
        _reject()
    return None
