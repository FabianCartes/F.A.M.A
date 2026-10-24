# Reserve temporary receipt capacity separately from dataset storage

Receipt admission persists a write promise for the declared ZIP plus the configured
expanded-byte ceiling. An update of the existing execution gate serializes the
owner/global checks and insertion across processes. A per-import filesystem lock
alone would not prevent two unrelated receipts from oversubscribing disk.

One owner may hold one outstanding receipt promise. This is not a limit on the
number or cumulative size of published datasets. Owner/global byte budgets remain
configurable; conservative defaults cover one maximum import per owner and the
existing global concurrent-import count. The admission check also requires all
outstanding promises plus the existing operational margin to fit filesystem free
space. Already written bytes still reduce free space: this deliberately double
counts some capacity rather than claiming a precision the current storage layout
cannot support. It is not filesystem preallocation or protection against unrelated
processes filling the disk.

Cancellation/maintenance retains the import lock, commits its terminal decision,
deletes staging outside the database gate, and releases the promise afterward.
A failed deletion retains the charge; retry is idempotent. A published import has
no remaining receipt/extraction promise; the next admission releases that logical
charge without claiming its retained files were reclaimed. Polling releases
nothing. Retained objects continue to count in real filesystem usage.

The schema is additive and explicitly migrated with writers stopped. Existing
whole-body imports are neither backfilled nor claimed to be reserved. Once a
receipt is reserved, the legacy whole-body endpoint cannot replace it. Chunk
acceptance, browser resume, dataset quotas and coordinated protocol cutover remain
T3b–T3d; runtime space enforcement remains required before that cutover. Keep the
current conservative operational size limits until T4 input containment. This
decision does not certify 10 GiB operation, PostgreSQL or real storage performance.
