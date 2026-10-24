# Durable sequential chunks without a second archive copy

## Decision

Keep one append-only `receiving.part` per reserved import, guarded by the existing
per-import filesystem lock. A normalized chunk row records index, offset, length
and SHA-256; its presence in the committed prefix is the durable acceptance state.
Synchronize bytes and staging directories before committing that row and the
receipt's `received_bytes` together. Never acknowledge filesystem-only progress.

The import lock precedes the execution gate. Use the gate only for short checks
and acknowledgement transactions, never streaming, hashing or filesystem sync.
Every operation authorizes the owner; physical names are server-generated. Store
useful activity separately so polling cannot postpone expiration.

## Context and alternatives

The [receipt reservation](0032-durable-receipt-reservations.md) covers one ZIP and
its configured expansion, not two complete compressed archives. Separate chunk
files followed by full assembly would temporarily exceed that promise unless
admission reserved an additional archive. In-place append avoids the second copy
but makes the distinction between durable bytes and acknowledged bytes explicit.

A DB transaction spanning transfer would serialize unrelated imports and block
the execution gate during slow I/O. Releasing the import lock during transfer
would instead permit cancellation, cleanup or another append to race filesystem
changes. Keep that lock across I/O while releasing the DB transaction entirely.

## Recovery protocol

1. Before appending, truncate only bytes beyond the committed prefix. A crash
   after append/fsync but before DB commit leaves a disposable unacknowledged tail.
2. A repeated accepted chunk verifies the request and stored bytes without
   changing counters or useful activity. Different bytes at the same position,
   gaps, overlaps and invalid lengths cannot advance acknowledgement.
3. Finalization checks exact archive size, all chunk hashes and full archive hash
   outside the gate. It fsyncs and renames the same file to `archive.zip`, syncs
   directories, then commits `sealed` and the existing import archive hash.
4. A complete acknowledged prefix plus `archive.zip` while still `receiving` is
   recoverable rename intent, not proof of success. Repeat finalization to recheck
   hashes and restore directory durability. Cleanup preserves that intent even
   after inactivity expiry. Missing or corrupt acknowledged bytes require explicit
   investigation rather than silently resetting progress.
5. Cancellation keeps existing active/recoverable execution and publication
   guards. Release its reservation only after staging deletion and parent
   directory fsync; a failed deletion/sync retains the charge for retry.

The receipt schema stays at version1. New journal/activity tables have their own
explicit additive version1 migration, with stopped-writer acknowledgement and
verified prefix consistency before activation. `create_all()` is insufficient.
Existing whole-body imports remain supported but cannot replace reserved input.

## Consequences and verification limits

Finalization performs a full integrity reread, intentionally preserving the
existing hash/fsync guarantees instead of treating an acknowledged chunk hash as
permanent proof of current disk contents. Hash pages are bounded (default50,
hard maximum200) and cursors bind to the accepted prefix; appending invalidates a
previous traversal. The browser must verify every accepted-prefix chunk before
resume; that coordinated frontend work remains T3c.

Private synthetic process tests exercise pre-fsync interruption, durable append
before commit, rename before commit, fresh-process replay, cleanup exclusion and
an unrelated operation using the gate during paused I/O. They retain the original
guard and protected inputs. They do not simulate physical disk failure or certify
PostgreSQL, multihost filesystem locking, 10GiB operation or throughput. Current
64MiB ZIP/256MiB expansion limits remain unchanged; quotas, decoder containment,
ZIP64 and complete asynchronous reclamation remain later cuts.

Operational steps and rollback are in the
[import work manual](../manuales/trabajos-importacion-datasets.md#t3b-enviar-consultar-y-finalizar-fragmentos).
