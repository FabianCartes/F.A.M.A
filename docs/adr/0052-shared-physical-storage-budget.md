# ADR 0052: Shared physical-storage promises without reinterpreting receipt v1

Status: Design selected for P2; local implementation/checking complete, operational acceptance and cutover pending.

Implementation update: [T1–T4 tracking](../arquitectura/large-zip-storage-budget-implementation.md) records local maintenance, import/export grants and explicit drain-first reconciliation, with functional, independent and acknowledged native review evidence. PostgreSQL and actual mount/quota/floor/metadata/inode qualification remain pending; P2 is not accepted operationally. The design and operational authorization boundary below remain unchanged.

The existing receipt promise covers the declared ZIP plus one expansion, while publication can create another WAV copy, retries retain independent attempts, and exports build local artifacts. We select an additive, versioned physical-budget ledger shared by these writers, with conservative per-filesystem admission and durable grants before growth. The detailed lifecycle, acceptance cases and conditional migration/recovery plan are in [P2 design, section 10](../arquitectura/large-zip-limits-enablement-plan.md#10-p2-shared-physical-budget-design).

## Decision and trade-offs

- Keep receipt-v1 `reserved_bytes`, owner/global receipt budgets and dataset quotas unchanged. The physical ledger is an additional safety gate, not a reinterpretation of a public field or a merger of import/export job-count limits. This extends [ADR 0032](0032-durable-receipt-reservations.md) and [ADR 0038](0038-complete-zip-exports-native-sessions.md) without changing their existing receipt or export contracts.
- Reserve the initial archive and extraction/publication envelope before admitting a new import. Charge each additional attempt before it can create output. Export construction obtains its own bounded grant from the same physical pool when roots share capacity. Unsupported or unverified topology fails closed; separate filesystems never lend capacity to one another.
- Retain the full granted envelope while it can still authorize growth, even when some bytes have materialized. Actual occupied bytes also reduce filesystem free space. Conservative double counting trades utilization for a small, recoverable protocol; no racy subtraction of measured staging sizes is used.
- Release write authority only after the writer is unable to resume under it. Queue lease expiry, a terminal callback result, TTL or cancellation intent alone is insufficient. Retained bytes remain occupied until actual reclamation; preserve the locks, journal, copies and cleanup semantics of [ADR 0036](0036-recoverable-import-cleanup.md).
- Keep short admission transactions separate from filesystem I/O. This ledger coordinates cooperating writers; it is neither filesystem preallocation nor protection against unrelated processes, snapshots or unqualified storage semantics.

## Alternatives not selected

Simply changing the receipt promise to ZIP plus two expansions misses independent retries and exports and changes the meaning of persisted/public v1 values. Relying only on free-space checks cannot coordinate concurrent promises. Deleting old attempts, replacing copy-based publication with moves, or disabling competing exports would alter recovery or product behavior rather than account for it. An exact remaining-byte ledger could improve utilization, but requires atomic accounting across database and filesystem writes; that complexity is not justified for this first bounded design.

## Consequences and authorization boundary

Cross-writer durable grants require additive persisted state in the selected design. Plan and verify its migration separately: never backfill v1 promises by arithmetic, adopt unknown work as covered, or activate mixed old/new writers. Preserve legacy rows, active/recoverable work, published objects and retained exports. Operator-approved quiescence and reconciliation are prerequisites, not operations authorized by this ADR.

The user authorized the design and ADR, including migration/recovery planning only if necessary. No migration script, schema change, runtime limit change, service action, real import or scale acceptance is implemented or authorized here. Exact overhead bounds, topology qualification, migration rehearsal and behavior tests remain implementation gates; this ADR does not close P2.
