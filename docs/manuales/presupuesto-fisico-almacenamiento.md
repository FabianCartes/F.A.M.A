# Inspect and prepare physical-budget metadata without activating it

Status: P2 maintenance foundation and **inactive import-side integration**, including bounded manifest sync/download, closed locally within synthetic verification and acknowledged native review ([T2 receipt](../receipts/large-zip-limits-p2-t2.json)). Do not activate it: operational topology/floor qualification, export integration and coordinated reconciliation remain open. This command does not enable larger imports, reconcile existing work or establish disk capacity. Follow [P2 implementation tracking](../arquitectura/large-zip-storage-budget-implementation.md) and [ADR 0052](../adr/0052-shared-physical-storage-budget.md).

## Read-only inspection

From `backend/`, using the existing validated interpreter:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHON_DOTENV_DISABLED=1 \
  ../.venv/bin/python -m scripts.migrate_dataset_storage \
  --database-url '<explicit-database-url>'
```

Replace the placeholder only for a separately authorized target. The database URL is required; the command does not read dotenv or fall back to ambient credentials. Avoid exposing credentials through command history or process arguments; follow the target's credential-handling policy. No actual target inspection is authorized by this example.

Default inspection does not create tables, insert markers, backfill receipts or modify grants. SQLite file targets must already exist; inspection opens them read-only and refuses SQLite URI query options. SQLite memory URLs are suitable for isolated checks. PostgreSQL is supported by the migration dialect/shape checks, but real PostgreSQL operation has not been certified by the SQLite tests.

Output is bounded JSON with `action`, `version`, `state`, `schema_verified`, `pools` and `live_grants`. Pool names, resource identities, paths and connection secrets are omitted.

| State | Meaning |
| --- | --- |
| `absent` | All three physical-budget tables are absent; no schema is prepared |
| `uninitialized` | All three table shapes are compatible and empty, but explicit preparation has not written its marker |
| `prepared` | The additive marker is verified; this does not establish coverage or authorize writers |
| `active` | Existing metadata records an active state; inspection does not validate runtime agreement or change that state |

Partial or incompatible tables, missing markers with existing pool/grant data, and incompatible versions fail with exit 1 and a sanitized diagnostic. They are not automatically repaired. Inspection exits 0 for recognized states; this is successful inspection, not a readiness or capacity approval.

## Explicit preparation — separate maintenance authorization required

The modifying form requires **both** `--apply` and `--writers-stopped`. Supplying only one fails with exit 2 before connecting. A verified existing import-job gate is required; this migration does not create or repair that queue.

```text
python -m scripts.migrate_dataset_storage --database-url <explicit-database-url> --apply --writers-stopped
```

Do not run this against the application database as routine validation. First obtain authorization for the target and maintenance, back up and verify restoration, and stop all participating writers under the [P2 migration/recovery plan](../arquitectura/large-zip-limits-enablement-plan.md#10-p2-shared-physical-budget-design). The acknowledgement is an operator assertion, not process discovery or proof that writers stopped.

Preparation creates only `dataset_storage_schema`, `dataset_storage_pool` and `dataset_storage_grant`, and writes an initial `prepared` marker. It registers no pool, adopts no existing import/export and activates no profile. Existing compatible metadata is preserved on replay. Existing receipt-v1 values and HTTP responses keep their meaning. The command never deletes legacy data or drops tables on failure.

If preparation fails, keep writers stopped and preserve database/filesystem state for diagnosis. Do not delete partially present tables, erase markers or downgrade binaries to bypass a refusal. The command does not implement operational reconciliation or a rollback that makes older writers safe.

## Local-import prototype — not an activation procedure

`app.services.dataset_storage.PhysicalStorage` accepts explicit `roots`, `pools` and `free_floors` mappings. Every role must be present: `imports`, `objects`, `attempts`, `manifests`, `scratch`, `exports`. Roots must already exist as private, same-user, physical absolute directories. `objects` must equal `imports / "objects"`; `manifests` must equal `attempts`. Publication roots must share the identical Linux mount view and pool. Different pool IDs cannot split one observed filesystem's capacity; distinct mounts on the same observed filesystem are also refused. Device equality alone never registers an alias.

These are preliminary fail-closed checks, **not operational topology qualification**. Btrfs, overlay, remote filesystems and mounts advertising quotas are refused. The host's Btrfs storage has not been qualified; the accounting tests explicitly substitute a synthetic local mount observation, not a real filesystem certification. Cross-process locks, mount/quota aliases, metadata capacity and external allocation still need independent evidence.

Configuration is programmatic only:

```python
policy = PhysicalStorage(roots=writer_roots, pools=role_to_pool,
                         free_floors=qualified_pool_floors,
                         manifest_bytes=128 * 1024**2)
service = DatasetImports(import_root, limits=limits, storage_policy=policy)
execution = ImportExecution(queue, service, attempt_root)
```

The API can receive that service through its existing `get_import_service` dependency override. There is no new environment toggle, worker CLI activation option, startup migration, pool registration or production cutover function. Construction does not modify the database. A configured writer requires a compatible **already active** marker and pre-existing matching pool metadata; the preparation CLI still writes only `prepared`. Active metadata without a supplied policy refuses new payload growth. Tests alone create synthetic active state after explicitly invoking the existing migration.

Runtime verification checks all three ledger tables' column types/lengths/nullability, primary and foreign keys, exact CHECK/uniqueness constraints and absent server defaults. Quoted CHECK literals retain their case during comparison: `'LIVE'` is not accepted as `'live'`. It reuses read-only queue migration shape verification, never executes migration or calls the maintenance CLI. Incompatible state is refused with 503 and no new grants or payload changes; no automatic repair or policy adoption occurs.

### Payload promises and ownership

| Path | Prototype behavior |
| --- | --- |
| Receipt | Acquire archive `Z` and initial extraction/publication `2E` in the same gated transaction before upload. Receipt-v1 `reserved_bytes` remains `Z + E`; owner/global v1 budgets remain separate. |
| Chunks / finalize | Require the original archive authority; appends stay within it. Finalize hashes and renames the same inode without another archive grant. |
| Raw ZIP | Reserve the configured received-byte ceiling, not Content-Length. Replay additionally reserves that ceiling while the retained archive and incoming part coexist. Synchronous ingress retirement occurs under the import lock after streaming/output has stopped. |
| Preview | Transfer the unconsumed initial envelope to the exact job/attempt/token atomically. Later validation attempts need a fresh `2E` before creating their directory. |
| Confirmation | A stopped, successful manual preview can transfer its unused publication authority under its directory lock and a durable retired-token fence. Otherwise a fresh copy allowance `E` is required. Original validated WAVs, copy publication, fsync and the recovery journal remain. |
| Sync | Acquire a fresh manifest-ceiling grant `M` for every attempt before creating output. The attempt's directory lock protects authority even after callback timeout. Failures/retries keep earlier grants until fenced cleanup; no partial manifest is marked complete. |
| Manifest download | Acquire declared bytes `D`, with `0 < D <= M`, before creating `TemporaryFile` in the configured `scratch` root. Check actual bytes and SHA-256 independently of the adapter. Retire the unique token only after the synchronous writer stops; streaming existing bytes is read-only growth-wise. |
| Cleanup | Retire only while owning import and all discovered attempt locks, atomically with the durable deletion fence. Failure may retain every file after authority retirement; this is not reclaimed space or a failed publication result. |

Admission sums **all full live physical grants** on the validated pool, adds new authority and its floor, and compares with current free bytes under the existing queue gate. Materialized bytes also reduce free space: double counting is deliberate. It never subtracts staging sizes or adds receipt-v1 promises again.

Lock order is import flock, existing attempt flocks when needed, then the queue gate. An initial eligibility transaction is released before cleanup takes attempt locks, then eligibility is rechecked under the gate. For worker creation, authority commits under import ownership before directory creation; the worker takes the new directory flock before releasing import ownership or scheduling its callback. That flock stays with the callback until its actual exit, including after timeout. No gate spans streaming, decoding, hashing, copying or recursive deletion.

### Auxiliary bounds and remaining qualification

The local validator writes original WAV payload plus `decoding.part` within its expanded-byte counter; result JSON uses a pipe, not a disk spool. Chunk hashes, preview metadata and recovery intent are database rows. Database/WAL/log capacity must be an independently provisioned operational boundary; directory entries, allocation rounding, CoW and bounded file creation require a **positive qualified floor**, not an assumption that five synthetic bytes are sufficient. Constructor validation of positivity is not certification of that floor.

Synchronization writes a full-revision `manifest.json`, potentially covering 50,000 members rather than one ZIP's 2,000 entries. Its existing export reader defines a 128 MiB total ceiling and 16 KiB per line. Import serialization now enforces those same wire limits, including the header, escaped Unicode, comma/newline framing and member count. `manifest_bytes` can only lower the total ceiling; it is included in the persisted policy fingerprint. Each write measures bytes **before** forwarding to the file and checks the pool's free-space floor. This is a hard serialized-byte ceiling, not an estimate of 50,000 rows times average path length, and it is independent of audio `E`.

Let `L` be full live grants on the pool and `F` its qualified floor. A new sync requires `L + M + F <= free`; a manifest download requires `L + D + F <= free`. Independent pools cannot subsidize these decisions. Download overrun/truncation/digest failures return the existing integrity-conflict 409 without exposing partial bytes; a declared size above `M` returns 413 with `El manifiesto supera el límite físico permitido.` before any scratch creation or remote call. Ordinary unconfigured sync and downloads retain their public behavior. The serializer's reader-compatible limits also reject malformed/oversized metadata without publishing a complete revision.

The supported synchronous GCS adapter was inspected: `ensure`/`ensure_manifest` call `upload_from_filename` on an existing read-only source and verify downloads into a hash-only sink; `read_verified` forwards to the caller's bounded destination. Installed Python Storage upload paths read that source into in-memory multipart/resumable buffers; raw download paths write to the supplied stream. No additional local media spool is created by those inspected paths. This is not certification of arbitrary injected clients, custom storage adapters, auth hooks, logging handlers or future SDK changes. Such integrations must preserve synchronous completion and introduce no unaccounted filesystem writes. Authentication, database/WAL and logs remain separately provisioned operational dependencies. No cloud call or ambient credential inspection was used for verification.

Download creation is outside the gate only after its grant commits. Its exclusive anonymous temporary file is not an import-cleanup target. After the adapter returns or unwinds, the route persists retirement of a unique, never-reused token before returning the read stream; actual file bytes continue reducing free space until it closes. A crash can conservatively leak a grant for later quiescent reconciliation. No timeout/lease alone retires sync authority, and no directory-size subtraction or guessed-byte refund is used.

Do not activate a profile until independent import-side verification, Btrfs or the selected deployment topology/floor qualification, export writers (T3), and coordinated migration/reconciliation (T4) are complete. Existing active limits remain unchanged.

## Verification boundary

The automated CLI tests use an in-process SQLite-memory adapter, private synthetic state and the unchanged isolated backend runner. They test default non-mutation, explicit/repeatable preparation, refusals and public receipt compatibility. Import tests additionally exercise HTTP/worker/cleanup/sync/download behavior with synthetic free-space and private-root mount observations, small WAVs, incompatible DDL, full-revision metadata, failed writes and delayed callbacks. They do not demonstrate real disk capacity, cross-process file locking, PostgreSQL, operational floor sufficiency, deployment or maximum-size imports. Independent verification and later P2 cuts must establish those applicable contracts before operational cutover.
