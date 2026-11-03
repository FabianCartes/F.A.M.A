"""Offline copy-only relocation of one private, same-mount SQLite laboratory.

All writers must remain stopped until human retirement of one authority copy.
This is not activation, ownership transfer, or an operating-system sandbox.
"""
import argparse
from dataclasses import fields
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import stat
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["PYTHON_DOTENV_DISABLED"] = "1"


def fail(message):
    raise ValueError(message)


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def private(path, *, directory=False):
    info = path.lstat()
    if (path != path.resolve(strict=True) or any(p.is_symlink() for p in (path, *path.parents))
            or info.st_uid != os.getuid() or info.st_mode & 0o077 or not directory and info.st_nlink != 1
            or not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode))):
        fail("private_owned_physical_path_required")
    return info


def read_json(path):
    private(path)
    if path.stat().st_size > 65536:
        fail("configuration_too_large")
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                fail("duplicate_configuration_key")
            result[key] = value
        return result
    return json.loads(path.read_bytes(), object_pairs_hook=unique)


def write_json(path, value):
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as stream:
        json.dump(value, stream, sort_keys=True)
        stream.flush()
        os.fsync(stream.fileno())


def inventory(root, roles):
    """Union traversal: nested roles are copied once; never follow links."""
    result = {}
    directories = set()
    for path in sorted(set(roles), key=lambda p: len(p.parts)):
        if any(path.is_relative_to(parent) for parent in directories):
            continue
        for parent, children, names in os.walk(path, followlinks=False):
            parent = Path(parent)
            for item in [parent, *(parent / name for name in children + names)]:
                info = item.lstat()
                if (info.st_uid != os.getuid() or info.st_dev != root.stat().st_dev
                        or not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode))
                        or stat.S_ISREG(info.st_mode) and info.st_nlink != 1):
                    fail("unsupported_role_entry")
                relative = str(item.relative_to(root))
                result[relative] = ("directory" if item.is_dir() else digest(item),
                                    info.st_size, info.st_ino, info.st_mtime_ns, info.st_ctime_ns)
        directories.add(path)
    return result


def readonly_database(path):
    connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=1)
    connection.execute("PRAGMA query_only=ON")
    if connection.execute("PRAGMA journal_mode").fetchone()[0] != "delete":
        connection.close()
        fail("only_offline_delete_journal_supported")
    return connection


def integrity(connection):
    if connection.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
        fail("sqlite_integrity_failed")
    if connection.execute("PRAGMA foreign_key_check").fetchone():
        fail("sqlite_foreign_key_failed")


def validate(connection, policy, limits):
    """Use existing public authority checks, with a read-only SQLite handle."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from app.models.dataset_storage import StorageGrant, StoragePool
    from app.services.dataset_imports import DatasetImports
    if connection.execute("SELECT 1 FROM dataset_import_job WHERE status IN ('queued','running') LIMIT 1").fetchone():
        fail('active_job')
    engine = create_engine("sqlite://", creator=lambda: connection)
    service = DatasetImports(policy.roots["imports"], limits=limits, storage_policy=policy)
    with Session(engine) as db:
        policy.verify(db, service)
        if {row.id for row in db.query(StoragePool)} != set(policy.free_floors):
            fail('unknown_pool_binding')
        grants = db.query(StorageGrant).all()
        from app.models.dataset_import import DatasetImport
        from app.models.dataset_import_job import ImportJob
        from app.models.dataset_import_receipt import ImportReceipt
        for row in grants:
            resource = row.resource_id.split(':')
            source = db.get(DatasetImport, resource[0])
            if source is None or source.status != 'imported':
                fail('unknown_grant_resource')
            if row.phase in ('archive', 'initial', 'published'):
                receipt = db.get(ImportReceipt, source.id)
                expected = (receipt.size_bytes if receipt else None) if row.phase == 'archive' else (
                    2 * limits.expanded_bytes if row.phase == 'initial' else sum(size for (size,) in
                    connection.execute('SELECT size_bytes FROM imported_dataset_member WHERE source_import_id=?', (source.id,))))
                if len(resource) != 1 or row.attempt != 0 or row.token != 0 or row.envelope_bytes != expected:
                    fail('invalid_import_grant')
                if row.state == 'live' and row.phase == 'archive':
                    archive = policy.roots['imports'] / 'staging' / source.id / 'archive.zip'
                    if not archive.is_file() or archive.stat().st_size != expected or digest(archive) != source.archive_sha256:
                        fail('archive_integrity_failed')
            elif row.phase in ('attempt', 'preview', 'retained', 'sync'):
                job = db.get(ImportJob, resource[1]) if len(resource) == 2 else None
                if (job is None or job.import_id != source.id or job.owner_id != source.owner_id
                        or job.status != 'succeeded' or job.attempt != row.attempt or job.token != row.token
                        or job.kind not in ({'sync'} if row.phase == 'sync' else
                            {'preview'} if row.phase in ('preview', 'retained') else {'preview', 'confirm'})):
                    fail('invalid_attempt_binding')
                expected = policy.manifest_bytes if row.phase == 'sync' else limits.expanded_bytes * (
                    2 if row.phase == 'preview' or row.phase == 'attempt' and job.kind == 'preview' else 1)
                if row.envelope_bytes != expected:
                    fail('invalid_attempt_envelope')
                if row.state == 'live' and not (policy.roots['attempts'] / f'{job.id}-{job.attempt}-{job.token}').is_dir():
                    fail('missing_live_attempt')
            else:
                fail('unknown_grant_phase')
            if row.policy_sha256 != policy.policy_hash(limits) or row.pool_id not in policy.free_floors:
                fail("unknown_grant_binding")
            if row.state == "live":
                role = next(role for role in policy.pools if policy.pools[role] == row.pool_id)
                policy.require(db, service, row.resource_id, row.phase, row.envelope_bytes,
                               attempt=row.attempt, token=row.token, role=role)
        required_authority(db, policy, service, grants)
        authority = sum(row.envelope_bytes for row in grants if row.state == "live")
    # Do not dispose: caller retains the read-only connection for backup.
    return authority, len(grants)


def required_authority(db, policy, service, grants):
    """Derive the supported publication chain, not merely the surviving ledger.

    Preview's durable manifest is ImportSummary + ImportFile, NOT a guessed
    filesystem manifest.json (that filename belongs to remote sync revisions).
    """
    from app.models.dataset_import import DatasetImport
    from app.models.dataset_import_job import ImportJob
    from app.models.dataset_import_metadata import ImportSummary, ImportFile, DatasetMember
    from app.models.dataset_import_receipt import ImportReceipt
    from app.models.dataset_import_chunk import ImportChunk
    from app.services.dataset_zip import fingerprint
    limits = service.limits
    expected = set()
    by_key = {(g.resource_id, g.phase, g.attempt, g.token): g for g in grants}
    def require(resource, phase, amount, attempt=0, token=0):
        expected.add((resource, phase, attempt, token))
        row = by_key.get((resource, phase, attempt, token))
        if row is None or row.state != 'live' or row.envelope_bytes != amount:
            fail('required_live_authority')
        policy.require(db, service, resource, phase, amount, attempt=attempt, token=token)
    for source in db.query(DatasetImport):
        summary = db.get(ImportSummary, source.id)
        receipt = db.get(ImportReceipt, source.id)
        if (source.status != 'imported' or summary is None or receipt is None
                or receipt.status != 'sealed' or receipt.received_bytes != receipt.size_bytes
                or receipt.reservation_active):
            fail('unsupported_publication_state')
        cleanup = summary.preview.get('_cleanup', {}).get('state')
        if cleanup == 'done':
            size = sum(size for (size,) in db.connection().exec_driver_sql(
                'SELECT size_bytes FROM imported_dataset_member WHERE source_import_id=?', (source.id,)))
            if size:
                require(source.id, 'published', size)
            continue
        if cleanup != 'pending' or source.sync_status != 'pending':
            fail('unsupported_publication_state')
        require(source.id, 'archive', receipt.size_bytes)
        initial = by_key.get((source.id, 'initial', 0, 0))
        if initial is None or initial.state != 'retired':
            fail('required_initial_transfer')
        jobs = db.query(ImportJob).filter_by(import_id=source.id).all()
        previews = [job for job in jobs if job.kind == 'preview']
        confirmations = [job for job in jobs if job.kind == 'confirm']
        if (len(previews) != 1 or any(job.status != 'succeeded' for job in jobs)
                or any(job.kind == 'sync' for job in jobs)):
            fail('unsupported_publication_chain')
        preview = previews[0]
        name = f'{preview.id}-{preview.attempt}-{preview.token}'
        if summary.preview.get('staging_attempt') != name:
            fail('invalid_preview_manifest_binding')
        resource = f'{source.id}:{preview.id}'
        if source.request.get('auto_import') is True:
            if confirmations or summary.preview.get('execution_id') != preview.id:
                fail('unsupported_publication_chain')
            require(resource, 'attempt', 2 * limits.expanded_bytes, preview.attempt, preview.token)
        else:
            if len(confirmations) != 1 or summary.preview.get('execution_id') != confirmations[0].id:
                fail('unsupported_publication_chain')
            old = by_key.get((resource, 'preview', preview.attempt, preview.token))
            if old is None:
                fail('required_live_authority')
            if old.state == 'retired':
                require(resource, 'retained', limits.expanded_bytes, preview.attempt, preview.token)
            else:
                require(resource, 'preview', 2 * limits.expanded_bytes, preview.attempt, preview.token)
            confirm = confirmations[0]
            require(f'{source.id}:{confirm.id}', 'attempt', limits.expanded_bytes, confirm.attempt, confirm.token)
        records = db.query(ImportFile).filter_by(import_id=source.id).limit(limits.entries + 1).all()
        if (not 0 < len(records) == summary.file_count <= limits.entries or summary.error_count
                or len(json.dumps(summary.preview).encode()) > policy.manifest_bytes
                or fingerprint([{'class_name': f.class_name, 'sha256': f.sha256} for f in records]) != summary.fingerprint
                or len({f.class_name for f in records}) != summary.class_count
                or sum(f.size_bytes for f in records) != summary.total_size_bytes):
            fail('retained_payload_manifest')
        selected = {(f.stored_name, f.sha256, f.size_bytes) for f in records if not f.duplicate and not f.existing}
        members = db.query(DatasetMember).filter_by(source_import_id=source.id).all()
        if (len(selected) != source.added_count or selected !=
                {(f.stored_name, f.sha256, f.size_bytes) for f in members}
                or any(f.dataset_id != source.dataset_id for f in members)):
            fail('retained_payload_publication_manifest')
        directory = policy.roots['attempts'] / name / 'files'
        names = {f.stored_name for f in records}
        if not directory.is_dir() or {p.name for p in directory.iterdir()} != names:
            fail('retained_payload_missing')
        for file in records:
            if file.stored_name != file.sha256 + '.wav':
                fail('retained_payload_manifest')
            path = directory / file.stored_name
            if not path.is_file() or path.stat().st_size != file.size_bytes or digest(path) != file.sha256:
                fail('retained_payload_checksum')
        chunks = db.query(ImportChunk).filter_by(import_id=source.id).order_by(ImportChunk.chunk_index).yield_per(128)
        archive = policy.roots['imports'] / 'staging' / source.id / 'archive.zip'
        offset = 0
        with archive.open('rb') as stream:
            for index, chunk in enumerate(chunks):
                length = min(receipt.chunk_bytes, receipt.size_bytes - offset)
                hashed, remaining = hashlib.sha256(), length
                while remaining > 0:
                    block = stream.read(min(1024**2, remaining))
                    if not block:
                        fail('retained_chunk_manifest')
                    hashed.update(block)
                    remaining -= len(block)
                if (chunk.chunk_index != index or chunk.offset_bytes != offset or chunk.length_bytes != length
                        or hashed.hexdigest() != chunk.sha256):
                    fail('retained_chunk_manifest')
                offset += length
        if offset != receipt.size_bytes:
            fail('retained_chunk_manifest')
    if expected != {(g.resource_id, g.phase, g.attempt, g.token) for g in grants if g.state == 'live'}:
        fail('required_live_authority_bijection')


def persisted(connection, policy):
    """Validate supported terminal states and DB-backed original-byte objects."""
    if connection.execute("SELECT 1 FROM dataset_import_job WHERE status IN ('queued','running') LIMIT 1").fetchone():
        fail("active_job")
    if connection.execute("SELECT 1 FROM dataset_import WHERE status != 'imported' LIMIT 1").fetchone():
        fail("only_published_imports_supported")
    if connection.execute("SELECT 1 FROM dataset_import_receipt WHERE status = 'receiving' LIMIT 1").fetchone():
        fail("receiving_record")
    count = total = 0
    for source, name, sha, size in connection.execute(
            "SELECT source_import_id, stored_name, sha256, size_bytes FROM imported_dataset_member"):
        if any(not isinstance(v, str) or Path(v).name != v or v in ('', '.', '..') for v in (source, name)):
            fail("invalid_published_binding")
        path = policy.roots["objects"] / source / name
        if path.is_symlink() or not path.is_file() or path.stat().st_size != size or digest(path) != sha:
            fail("published_content_mismatch")
        count += 1
        total += size
    # Persisted runtime paths are relative in this schema. Refuse unknown absolute
    # strings instead of guessing or rewriting arbitrary user/JSON data.
    def absolute(value):
        if isinstance(value, str):
            if value.startswith('/'):
                fail("unrecognized_absolute_persisted_path")
            if value.startswith(('{', '[')):
                try:
                    absolute(json.loads(value))
                except json.JSONDecodeError:
                    pass
        elif isinstance(value, dict):
            for item in value.values():
                absolute(item)
        elif isinstance(value, list):
            for item in value:
                absolute(item)
    for (table,) in connection.execute("SELECT name FROM sqlite_master WHERE type='table'"):
        if not table.replace('_', '').isalnum():
            fail("unsupported_table_name")
        for row in connection.execute(f'SELECT * FROM "{table}"'):
            for value in row:
                absolute(value)
    return count, total


def schema_inventory(connection):
    """Preserve all ordinary tables/indexes; never execute unsupported objects."""
    objects = connection.execute(
        'SELECT type, name, tbl_name, sql FROM sqlite_master ORDER BY type, name').fetchall()
    if (any(kind not in ('table', 'index') for kind, *_ in objects)
            or any(row[2] in ('virtual', 'shadow', 'view') for row in connection.execute('PRAGMA table_list'))):
        fail('unsupported_schema_object')
    return objects


def database_inventory(connection, *, policy_mapping=None):
    """Receipt of every persisted cell; only two authorized bindings may differ."""
    result = {}
    for table, sql in connection.execute("SELECT name, sql FROM sqlite_master WHERE type='table' ORDER BY name"):
        cursor = connection.execute(f'SELECT * FROM "{table}"')
        columns = [column[0] for column in cursor.description]
        rows = []
        for row in cursor:
            values = list(row)
            column = {'dataset_storage_pool': 'configuration_sha256',
                      'dataset_storage_grant': 'policy_sha256'}.get(table)
            if policy_mapping and column:
                index = columns.index(column)
                values[index] = policy_mapping.get(values[index], values[index])
            rows.append(repr(values))
        result[table] = (sql, sorted(rows))
    return hashlib.sha256(repr((schema_inventory(connection), result)).encode()).hexdigest()


def relocate(source_root, destination_root, *, writers_stopped=False):
    if writers_stopped is not True:
        fail("writers_stopped_required")
    from app.services.dataset_storage import PhysicalStorage, _mount
    from app.services.dataset_zip import ImportLimits
    source, destination = Path(source_root), Path(destination_root)
    private(source, directory=True)
    if not destination.is_absolute() or destination.exists() or destination.is_symlink():
        fail("fresh_absolute_destination_required")
    private(destination.parent, directory=True)
    if (destination != destination.resolve() or destination.is_relative_to(source)
            or source.is_relative_to(destination)):
        fail("disjoint_destination_required")
    config = read_json(source / "profile.json")
    old = PhysicalStorage(**config)
    if len(old.free_floors) != 1 or any(not p.is_relative_to(source) for p in old.roots.values()):
        fail("one_confined_pool_required")
    if _mount(source) != _mount(destination.parent) or any(m != _mount(source) for m in old.mounts.values()):
        fail("same_mount_required")
    environment = read_json(source / "environment.json")
    if not isinstance(environment, dict):
        fail("environment_mapping_required")
    numeric = {}
    for field in fields(ImportLimits):
        key = "FAMA_IMPORT_" + field.name.upper()
        if key in environment:
            value = environment[key]
            if type(value) not in (str, int) or not str(value).isascii() or not str(value).isdigit() or int(value) <= 0:
                fail("invalid_numeric_limit")
            numeric[key] = str(value)
    limits = ImportLimits(**{key.removeprefix("FAMA_IMPORT_").lower(): int(value) for key, value in numeric.items()})
    from app.services.dataset_import_receipts import CHUNK_BYTES
    receipt_defaults = {'FAMA_IMPORT_CHUNK_BYTES': CHUNK_BYTES,
        'FAMA_IMPORT_RESERVED_BYTES_PER_OWNER': limits.received_bytes + limits.expanded_bytes,
        'FAMA_IMPORT_RESERVED_BYTES_GLOBAL': (limits.received_bytes + limits.expanded_bytes) * limits.concurrent_imports}
    for key, default in receipt_defaults.items():
        value = environment.get(key, default)
        if type(value) not in (str, int):
            fail('invalid_receipt_limit')
        value = int(value)
        if not 0 < value <= (2**31 - 1 if key == 'FAMA_IMPORT_CHUNK_BYTES' else 2**63 - 1):
            fail('invalid_receipt_limit')
        numeric[key] = str(value)
    database = source / "manual.sqlite3"
    private(database)
    if any((source / ("manual.sqlite3" + suffix)).exists() for suffix in ('-wal', '-shm', '-journal')):
        fail("sqlite_sidecar_requires_offline_recovery")
    def controls():
        result = {}
        for name in ('manual.sqlite3', 'profile.json', 'environment.json'):
            sha, info = digest(source / name), (source / name).stat()
            result[name] = (sha, info.st_ino, info.st_size, info.st_mtime_ns,
                            info.st_ctime_ns, info.st_mode, info.st_uid, info.st_gid)
        return result
    control = controls()
    before = inventory(source, old.roots.values())
    connection = readonly_database(database)
    try:
        original_schema = schema_inventory(connection)
        integrity(connection)
        authority, grants = validate(connection, old, limits)
        count, published_bytes = persisted(connection, old)
        original_inventory = database_inventory(connection)
        required = sum(v[1] for v in before.values() if v[0] != 'directory') + database.stat().st_size + 131072
        floor = next(iter(old.free_floors.values()))
        # Both retained ledgers are charged conservatively, not treated as two
        # independent capacities. Offline exclusivity remains mandatory.
        if shutil.disk_usage(source).free < required + 2 * authority + floor:
            fail("insufficient_copy_and_authority_headroom")
        destination.mkdir(mode=0o700)
        for relative, data in sorted(before.items(), key=lambda pair: len(Path(pair[0]).parts)):
            target = destination / relative
            if data[0] == 'directory':
                for parent in reversed((target, *target.parents)):
                    if parent.is_relative_to(destination):
                        parent.mkdir(mode=0o700, exist_ok=True)
            else:
                with (source / relative).open('rb') as original, os.fdopen(
                        os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'wb') as copy:
                    shutil.copyfileobj(original, copy, 1024 * 1024)
                    copy.flush()
                    os.fsync(copy.fileno())
                if digest(target) != data[0] or target.stat().st_size != data[1]:
                    fail("copy_integrity_failed")
        copied_database = destination / 'manual.sqlite3'
        os.close(os.open(copied_database, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600))
        with sqlite3.connect(copied_database) as copied:
            connection.backup(copied)
            if schema_inventory(copied) != original_schema:
                fail('copied_schema_mismatch')
            integrity(copied)
            new_config = dict(config, roots={role: str(destination / path.relative_to(source))
                                            for role, path in old.roots.items()})
            new = PhysicalStorage(**new_config)
            copied.execute('UPDATE dataset_storage_pool SET configuration_sha256=? WHERE configuration_sha256=?',
                           (new.configuration_sha256, old.configuration_sha256))
            copied.execute('UPDATE dataset_storage_grant SET policy_sha256=? WHERE policy_sha256=?',
                           (new.policy_hash(limits), old.policy_hash(limits)))
            copied.commit()
            integrity(copied)
            if database_inventory(copied, policy_mapping={
                    new.configuration_sha256: old.configuration_sha256,
                    new.policy_hash(limits): old.policy_hash(limits)}) != original_inventory:
                fail('unexpected_persisted_change')
        write_json(destination / 'profile.json', new_config)
        write_json(destination / 'environment.json', numeric)
        with readonly_database(copied_database) as copied:
            validate(copied, new, limits)
            if persisted(copied, new) != (count, published_bytes):
                fail("copied_catalog_mismatch")
        validate(connection, old, limits)
        if (inventory(source, old.roots.values()) != before
                or controls() != control):
            fail("source_changed_during_relocation")
        report = dict(status='complete', source=str(source), destination=str(destination),
                      source_configuration_sha256=old.configuration_sha256,
                      destination_configuration_sha256=new.configuration_sha256,
                      files=sum(v[0] != 'directory' for v in before.values()),
                      published_members=count, published_bytes=published_bytes, grants=grants,
                      live_envelope_bytes=authority, copied_bytes=required - database.stat().st_size - 131072,
                      role_inventory_sha256=hashlib.sha256(json.dumps(before, sort_keys=True).encode()).hexdigest(),
                      preserved_database_inventory_sha256=original_inventory,
                      source_database_sha256=control['manual.sqlite3'][0],
                      destination_database_sha256=digest(copied_database),
                      lifecycle='preserved; offline backup, never concurrent')
        write_json(destination / 'relocation-complete.json', report)
        return report
    finally:
        connection.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', required=True)
    parser.add_argument('--destination-root', required=True)
    parser.add_argument('--writers-stopped', required=True, action='store_true')
    args = parser.parse_args()
    try:
        report = relocate(args.source_root, args.destination_root, writers_stopped=args.writers_stopped)
    except Exception as error:
        print(f'relocation refused: {type(error).__name__}: {error}; any partial destination is NOT usable', file=sys.stderr)
        return 1
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
