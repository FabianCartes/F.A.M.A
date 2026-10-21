"""Conservative durable write authority; neither preallocation nor reclaimed bytes.

Callers hold their filesystem ownership lock before the queue gate. This module
never acquires a filesystem lock while holding that gate and never commits a
caller's transaction. The floor covers qualified allocation/metadata overhead;
database, WAL and logs require independent operational capacity. Payload grants
are deliberately not reduced by materialized files.
"""
import hashlib
import json
import os
import re
from pathlib import Path
import shutil

from sqlalchemy import CheckConstraint, UniqueConstraint, inspect
from sqlalchemy.exc import SQLAlchemyError

from app.models.dataset_storage import STORAGE_MODELS, StorageGrant, StoragePool, StorageSchema
from app.services.dataset_manifest_stream import MANIFEST_BYTES, BoundedWriter


UNAVAILABLE = "El presupuesto físico requiere un perfil activo y compatible."
INSUFFICIENT = "Espacio físico insuficiente para autorizar la escritura."
MAXIMUM = 2**63 - 1
ROLES = frozenset(("imports", "objects", "attempts", "manifests", "scratch", "exports"))


def _check_sql(sql):
    # Normalize reflected SQL syntax, NEVER quoted literal values. PostgreSQL
    # reflects varchar IN as text = ANY (ARRAY[...]); preserve literal case.
    pieces = re.split(r"('(?:''|[^'])*')", str(sql))
    literals = []
    for index in range(1, len(pieces), 2):
        literals.append(pieces[index])
        pieces[index] = f"@{len(literals) - 1}@"
    syntax = re.sub(r"::(?:character varying|text)(?:\[\])?", "", "".join(pieces).lower())
    syntax = "".join(syntax.split()).replace("(", "").replace(")", "")
    syntax = syntax.replace("=anyarray[", "in").replace("]", "")
    return syntax, tuple(literals)


def _verify_schema(conn):
    # Reuse shape/type/key verification, not the CLI, migration or its lossy
    # CHECK equivalence. Exact checks/uniques/defaults close its permissive gaps.
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


def _reject(message=UNAVAILABLE, code=503):
    from fastapi import HTTPException
    raise HTTPException(code, message)


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _integer(value, *, positive=False):
    if type(value) is not int or not int(positive) <= value <= MAXIMUM:
        raise ValueError("Physical bounds must be nonnegative signed 64-bit integers")
    return value


def _mount(path):
    """Pin an existing private root to its Linux mount view, not merely st_dev."""
    if not path.is_absolute() or path != path.resolve(strict=True):
        raise ValueError("Physical roots must be existing absolute physical paths")
    if any(parent.is_symlink() for parent in (path, *path.parents)):
        raise ValueError("Physical roots must not contain links")
    info = path.stat()
    if not path.is_dir() or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ValueError("Physical roots must be private directories owned by this user")
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
    # Nested subvolumes, project quotas, remote/shared locks and differing quota
    # views need independent qualification; a matching device cannot bless them.
    if filesystem not in ("ext4", "xfs", "tmpfs") or "quota" in options:
        raise ValueError("Storage topology requires separate qualification")
    return (mount, info.st_dev, view.f_fsid, view.f_frsize, filesystem)


class PhysicalStorage:
    """Explicit pool/root policy. Construction does not prepare or activate state.

    Supported scope is a single Linux host/mount namespace, private same-user
    roots and local flock/rename semantics. Distinct mounts cannot be declared
    aliases; distinct pool IDs on one mount are refused rather than counted twice.
    All six writer roles must be mapped, including future export integration.
    """

    def __init__(self, *, roots, pools, free_floors, manifest_bytes=MANIFEST_BYTES):
        if type(manifest_bytes) is not int or not 1 <= manifest_bytes <= MANIFEST_BYTES:
            raise ValueError("Manifest ceiling must be in [1, 128 MiB]")
        self.manifest_bytes = manifest_bytes
        if set(roots) != ROLES or set(pools) != ROLES or set(free_floors) != set(pools.values()):
            raise ValueError("Every writer root requires an explicit physical pool")
        if any(not isinstance(pool, str) or not 1 <= len(pool) <= 64 for pool in pools.values()):
            raise ValueError("Invalid physical pool identity")
        self.roots = {role: Path(path) for role, path in roots.items()}
        self.pools = dict(pools)
        self.free_floors = {pool: _integer(value, positive=True) for pool, value in free_floors.items()}
        self.mounts = {role: _mount(path) for role, path in self.roots.items()}
        for left in ROLES:
            for right in ROLES:
                if (pools[left] == pools[right]) != (self.mounts[left] == self.mounts[right]):
                    raise ValueError("Pool aliases require the identical qualified mount view")
                if pools[left] != pools[right] and self.mounts[left][1:3] == self.mounts[right][1:3]:
                    raise ValueError("Distinct mounts may still share physical capacity")
        if len({pools[role] for role in ("imports", "objects", "attempts", "manifests")}) != 1:
            raise ValueError("Import publication requires one rename-capable physical pool")
        if self.roots["objects"] != self.roots["imports"] / "objects":
            raise ValueError("Object root does not match import publication")
        if self.roots["manifests"] != self.roots["attempts"]:
            raise ValueError("Manifest output must use the attempt root")
        self.configuration_sha256 = _hash({
            "version": 1, "roots": {role: str(path) for role, path in self.roots.items()},
            "pools": self.pools, "floors": self.free_floors, "mounts": self.mounts,
            "manifest_bytes": self.manifest_bytes,
        })

    def verify(self, db, service):
        try:
            _verify_schema(db.connection())
            marker = db.get(StorageSchema, 1)
            if marker is None or marker.version != 1 or marker.state != "active":
                _reject()
            if Path(service.root) != self.roots["imports"]:
                _reject()
            if hasattr(service, "attempt_root") and Path(service.attempt_root) != self.roots["attempts"]:
                _reject()
            for role, path in self.roots.items():
                if _mount(path) != self.mounts[role]:
                    _reject()
            for identity, floor in self.free_floors.items():
                row = db.get(StoragePool, identity)
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
        """Caller owns the queue gate; all pools succeed or the transaction rolls back."""
        expected = []
        for pool, amount in sorted(amounts.items()):
            _integer(amount, positive=True)
            identity = _hash([resource, phase, attempt, token, pool])
            row = db.get(StorageGrant, identity)
            if row is not None:
                if (row.state != "live" or row.pool_id != pool or row.resource_id != resource
                        or row.phase != phase or row.attempt != attempt or row.token != token
                        or row.policy_sha256 != policy or row.envelope_bytes != amount):
                    _reject()
                continue
            expected.append((identity, pool, amount))
        for _, pool, amount in expected:
            if pool not in self.free_floors:
                _reject()
            # Python sums avoid SQL BIGINT overflow across many conservative grants.
            used = sum(value for (value,) in db.query(StorageGrant.envelope_bytes).filter_by(pool_id=pool, state="live"))
            root = next(self.roots[role] for role in ROLES if self.pools[role] == pool)
            if used + amount + self.free_floors[pool] > shutil.disk_usage(root).free:
                _reject(INSUFFICIENT, 507)
        for identity, pool, amount in expected:
            db.add(StorageGrant(id=identity, pool_id=pool, resource_id=resource, phase=phase,
                attempt=attempt, token=token, policy_sha256=policy, envelope_bytes=amount, state="live"))
        db.flush()

    def initial(self, db, service, identity, archive_bytes):
        pool = self.pools["imports"]
        policy = self.policy_hash(service.limits)
        self.acquire(db, resource=identity, phase="archive", attempt=0, token=0,
                     amounts={pool: archive_bytes}, policy=policy)
        self.acquire(db, resource=identity, phase="initial", attempt=0, token=0,
                     amounts={pool: 2 * service.limits.expanded_bytes}, policy=policy)

    def require(self, db, service, identity, phase, amount, *, attempt=0, token=0, role="imports"):
        pool = self.pools[role]
        row = db.get(StorageGrant, _hash([identity, phase, attempt, token, pool]))
        if (row is None or row.state != "live" or row.pool_id != pool or row.resource_id != identity
                or row.phase != phase or row.attempt != attempt or row.token != token
                or row.envelope_bytes != amount or row.policy_sha256 != self.policy_hash(service.limits)):
            _reject()
        return row

    def retire(self, db, resource, *, phase=None):
        """Only under exclusive filesystem ownership AFTER a durable stop fence.

        Callers must prove every writer has stopped, not infer it from a lease.
        Retired rows persist and acquire/require can never resurrect their token.
        """
        query = db.query(StorageGrant).filter_by(resource_id=resource, state="live")
        if phase is not None:
            query = query.filter_by(phase=phase)
        for row in query:
            row.state = "retired"

    def attempt(self, db, service, attempt, *, reviewed=None):
        if attempt["kind"] == "sync":
            self.acquire(db, resource=f"{attempt['import_id']}:{attempt['id']}", phase="sync",
                attempt=attempt["attempt"], token=attempt["token"],
                amounts={self.pools["manifests"]: self.manifest_bytes}, policy=self.policy_hash(service.limits))
            return
        resource = f"{attempt['import_id']}:{attempt['id']}"
        pool = self.pools["attempts"]
        amount = service.limits.expanded_bytes * (1 if attempt["kind"] == "confirm" else 2)
        from app.models.dataset_import import DatasetImport
        source = db.get(DatasetImport, attempt["import_id"])
        if attempt["kind"] == "confirm" and source.status == "imported":
            return  # Idempotent publication recovery creates no payload copy.
        archive = db.get(StorageGrant, _hash([source.id, "archive", 0, 0, self.pools["imports"]]))
        if archive is None or archive.state != "live" or archive.policy_sha256 != self.policy_hash(service.limits):
            _reject()  # Never adopt unaccounted legacy work at runtime.
        phase = "preview" if attempt["kind"] == "preview" and not source.request.get("auto_import") else "attempt"
        policy = self.policy_hash(service.limits)
        identity = _hash([resource, phase, attempt["attempt"], attempt["token"], pool])
        initial = db.get(StorageGrant, _hash([attempt["import_id"], "initial", 0, 0, pool]))
        transfer = None
        if reviewed is not None:
            old_resource, number, token = reviewed
            transfer = self.require(db, service, old_resource, "preview", 2 * service.limits.expanded_bytes,
                                    attempt=number, token=token, role="attempts")
        elif attempt["kind"] == "preview" and initial is not None and initial.state == "live":
            self.require(db, service, attempt["import_id"], "initial", amount)
            transfer = initial
        if transfer is not None:
            # Transfer the unconsumed promise and exact fencing identity in ONE
            # transaction; never commit a gap or reserve this envelope again.
            transfer.state = "retired"
            db.add(StorageGrant(id=identity, pool_id=pool, resource_id=resource, phase=phase,
                attempt=attempt["attempt"], token=attempt["token"], policy_sha256=policy,
                envelope_bytes=amount, state="live"))
            db.flush()
        else:
            self.acquire(db, resource=resource, phase=phase, attempt=attempt["attempt"], token=attempt["token"],
                         amounts={pool: amount}, policy=policy)

    def retire_import(self, db, identity):
        """Caller holds import AND all attempt locks plus a durable deletion fence."""
        for row in db.query(StorageGrant).filter(StorageGrant.state == "live").filter(
                (StorageGrant.resource_id == identity) | StorageGrant.resource_id.startswith(identity + ":")):
            row.state = "retired"

    def writer(self, destination, maximum, *, role):
        def check():
            if shutil.disk_usage(self.roots[role]).free < self.free_floors[self.pools[role]]:
                _reject(INSUFFICIENT, 507)
        return BoundedWriter(destination, maximum, check=check)


def physical_storage(service, db):
    """Prepared/auto-created tables never opt an unconfigured writer in."""
    policy = getattr(service, "storage_policy", None)
    if policy is None:
        try:
            if inspect(db.connection()).has_table(StorageSchema.__tablename__):
                marker = db.get(StorageSchema, 1)
                if marker is not None:
                    if marker.version != 1 or marker.state != "prepared":
                        _reject()
        except SQLAlchemyError:
            _reject()
        return None
    policy.verify(db, service)
    return policy
