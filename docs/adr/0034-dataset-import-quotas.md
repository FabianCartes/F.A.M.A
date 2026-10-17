# Enforce unique dataset quotas inside fenced publication

Dataset capacity is per dataset, not a retained-storage allowance per owner.
Count published unique WAV bytes and members plus only incoming content that is
neither an internal duplicate nor already a member. Defaults are 15 GiB
(`15 * 1024**3` bytes) and 50,000 files; `FAMA_IMPORT_DATASET_BYTES` and
`FAMA_IMPORT_DATASET_ENTRIES` configure them through `ImportLimits`.
The independent 64 MiB received ZIP, 256 MiB expanded import and 2,000 archive
entry defaults remain unchanged. This decision does not enable large ZIPs or T4.

## Accounting and publication

The bounded preview contains a `quota` object with `current_bytes`,
`current_files`, `new_bytes`, `new_files`, `projected_bytes`, `projected_files`,
`limit_bytes` and `limit_files`. Limits are inclusive. Exceeding either produces
`dataset_size_limit` or `dataset_entry_limit` error issues and a correction
preview, never a ready preview. The panel preserves old previews without this
optional object and renders only the bounded counters when present.

Confirmation checks the reviewed destination revision and recomputes capacity
from normalized records under the existing queue publication gate, both before
committing the journal and before rename/membership publication. Recovery follows
the same checks. Effective limits come from the executing service, not a client
or the stored preview. Already imported replay remains idempotent even if limits
later fall below that dataset's size. Cross-class conflicts remain errors.

Normalized membership aggregates are checked against dataset summary revision,
bytes, files and classes; confirmation also checks import file/byte totals and
the selected new-file count. Discrepancies fail closed without repairing data.
These SQL aggregates have bounded result size, not constant database work.
Hashing, decoding and network operations remain outside the gate. No new lock,
persisted schema, runtime migration or automatic cleanup is introduced.

## Reservation lifecycle and alternatives

Publication fulfills the receipt's temporary write promise in the **same database
transaction** as membership, journal completion and job success, including
zero-new-content publication. The helper assumes the existing gate and neither
reacquires it nor commits separately. A rollback retains the charge and recovery
journal. Replaying an imported job can also release a legacy outstanding promise.
The earlier admission reconciliation remains a compatibility backstop, not the
normal release path. Release does not assert that retained staging was deleted.

Preview errors, failed confirmation and recoverable publication retain promises.
Cancellation still releases only after deletion and directory fsync succeed;
failed cleanup remains charged and retryable. Rejected alternatives were an
owner-wide retained dataset cap (wrong domain), preview-only quota enforcement
(stale admission race), and a separate release transaction (crash gap).

## Verification boundary

Public synthetic HTTP/worker tests cover exact boundaries, deduplication,
configuration changes, competing reviewed confirmations, rollback/recovery and
receipt → chunks → finalize → preview → confirm → original WAV download.
Rendered tests cover capacity display and blocked invalid confirmation without
automatic writes or cloud operations. Existing cancellation/cleanup regressions
remain applicable. This is not PostgreSQL, multihost, scale, Docker Python 3.12,
decoder containment or production certification. Independent verification and
tracking closure remain separate. See the [operator guide](../manuales/trabajos-importacion-datasets.md).
