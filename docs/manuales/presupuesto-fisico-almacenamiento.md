# Inspect and prepare physical-budget metadata without activating it

Status: P2 maintenance foundation only. Import/export writers do not yet use the new ledger. This command does not enable larger imports, reconcile existing work or establish disk capacity. Follow [P2 implementation tracking](../arquitectura/large-zip-storage-budget-implementation.md) and [ADR 0052](../adr/0052-shared-physical-storage-budget.md).

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

## Verification boundary

The automated CLI tests use an in-process SQLite-memory adapter, private synthetic state and the unchanged isolated backend runner. They test default non-mutation, explicit/repeatable preparation, refusals and public receipt compatibility. They do not demonstrate cross-process file locking, PostgreSQL, disk admission, grant retirement, deployment or maximum-size imports. Later P2 cuts must implement and verify those applicable contracts before operational cutover.
