# ADR 0037: Durable dataset revisions and immutable reconstruction manifests

Date: 2026-10-17
Status: Accepted for local T6 implementation; verification and delivery status remain in the [implementation log](../arquitectura/large-zip-gcs.md).

## Context

The previous sync persisted object generations but selected only hashes belonging
to the initiating import. Neither that import's success nor insertion revisions
on current members define a complete historical dataset snapshot. Recovery must
survive a remote create before its database checkpoint, without a long network
transaction or repeated rewrites of the entire preview.

## Decision

- Add explicitly migrated revision headers and normalized frozen revision objects.
  Freeze the full current membership with `INSERT SELECT` under the same short
  queue publication gate used by confirmation. Capture owner, name, description,
  totals, paths, classes, provenance, hashes and sizes. Retain existing expected
  object generations, but do not infer fresh verification from them.
- Bind a sync job's existing `expected_revision` on first execution. Reclaim of
  that job uses the same durable snapshot; a newly admitted job may synchronize
  the current revision. Revision membership is not derived from insertion numbers.
- Transfer original WAVs outside database sessions. Batch by count and bytes,
  concurrency one, with three bounded attempts for transient storage failures.
  Fence each transfer's admission and every checkpoint. Keep integrity evidence
  and aggregate verified counts/bytes separate from immutable membership.
- Reverify every object on retry, including an already completed revision. Create
  only with generation-zero preconditions; verify remote original-byte SHA-256
  at the observed generation, and reject changes to a previously recorded one.
  Completed batch results checkpoint together; recoverable successes in a failed
  batch may checkpoint, but unreturned remote creates must be reverified.
- Generate deterministic standard JSON incrementally from frozen rows. Publish
  its digest-derived key with conditional creation and full digest verification.
  Only then atomically persist key/generation/hash/size and mark that revision
  complete under the live execution fence. Replays cannot replace this identity.
- Expose an owner-authorized revision reference and verified manifest recovery.
  A caller cannot supply an arbitrary key or hash. Recover into a private
  temporary file before emitting HTTP bytes; verify the authorized generation,
  size and digest. Stream the response and close its temporary on completion.
  Neither recovery operation needs the original ZIP or local member lists.

## Alternatives and consequences

Keeping only mutable dataset members is smaller but loses coherent historical
membership as imports advance. Keeping one JSON progress document avoids tables
but repeatedly rewrites the collection and couples mutable progress to immutable
publication. Frozen normalized rows cost additional database space per revision;
they make recovery and historical identity explicit without either alternative.

Serial network concurrency is deliberately conservative. Count/byte limits do
not certify throughput or memory performance at the maximum dataset size. The
snapshot insert and its validation are atomic metadata work, not a benchmarked
constant-time operation. No database transaction spans a remote transfer.

A complete historical revision does not mean a newer current revision is complete.
The sync result includes its `dataset_revision`; the initiating import remains
pending if the current dataset advanced during the operation. A stored complete
reference attests publication, not perpetual cloud availability: recovery fails
closed if referenced bytes/generations disappear or change.

No published-object garbage collector is introduced. Existing cleanup continues
to reclaim staging only, never referenced local/remote published objects. A future
collector must respect every published revision before deleting any object.
Export ZIP generation and resumable WAV/ZIP delivery remain T7, not this decision.

## Operational boundary

Migration requires stopped writers and an explicit database target; it creates
and verifies additive tables without promoting historical sync flags. Rollback
requires stopping new sync/recovery consumers and preserving the additive tables,
references, WAVs and journals. Do not drop revision data or reinterpret historical
import-level sync as manifest publication. Real PostgreSQL/GCS, physical power
loss, maximum scale and deployment require separate authorization and proof.
