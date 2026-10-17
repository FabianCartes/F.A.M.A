# Serialize import publication with lease recovery

Durable queue fencing alone cannot prevent a replaced callback from renaming files
or committing dataset membership. Real execution therefore prepares immutable,
attempt-private files outside database write transactions, then uses the queue's
existing database gate for short journal, rename/directory-fsync and metadata
transitions. Reclaim takes the same gate; a lease is checked after acquiring it
and again before terminal publication. Membership and successful job completion
commit together. Hashing, file-content fsync, decoding and network calls stay
outside this critical section.

The committed `committing` journal precedes rename. After interruption, a new
authorized attempt verifies hashes at the existing destination and completes the
same journal without duplicating membership. An incompatible publication cannot
pass while that journal needs recovery. Cleanup is explicit maintenance, not an
HTTP side effect, and preserves every active or recoverable job and journal.
Maintenance first acquires the same import-specific exclusion as receipt, skips
busy imports without expiring them, then acquires the queue gate to revalidate
eligibility. It retains receipt exclusion through deletion but releases the DB
gate before recursive filesystem removal. This lock order avoids deleting a
slow active upload merely because its creation-time TTL elapsed.

We reuse the database gate rather than introduce a second dataset-lock table or
rely on a process-local lease check. This intentionally serializes short metadata
publication across datasets as well as admission/reclaim; preparation and remote
I/O remain concurrent. Fine-grained publication locking is deferred until measured
contention justifies the additional lock-order protocol. SQLite evidence does not
certify operational PostgreSQL or multi-host filesystem behavior.

The HTTP contract changes together with its panel: operation POSTs admit durable
jobs with `202`, owner-scoped GETs report bounded state, and confirmation/sync stay
explicit. A worker is never started by a request. See the
[operation manual](../manuales/trabajos-importacion-datasets.md). Python callback
timeouts are not decoder isolation; full asynchronous cleanup and complete remote
manifests remain later cuts.
