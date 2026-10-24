# Verified additive import-metadata migration before reader cutover

Status: accepted for the staged implementation; deployment and live migration remain unauthorized.

Legacy import previews and dataset memberships contain complete JSON arrays. Migrate into separate indexed candidate, member, class, issue and summary tables with an explicit offline transaction, retaining the original JSON. Do not activate new runtime readers as a side effect of backfill. This separates recoverable data preparation from the coordinated HTTP/frontend contract change approved by the user.

Stop all legacy writers for backfill and cutover; a database lock additionally excludes writes during the transaction. Compare each persisted normalized row with its source-derived representation, verify global counts, published membership/provenance, sizes, hashes, preview counts/classes and the existing collection fingerprint, then commit a source-digest checkpoint. Replay verifies both source and target again; a checkpoint alone is not evidence of current equivalence. Discrepancies abort without overwriting sources or repairing targets automatically.

Historical `synced` flags lack object generation evidence. Retain them in the untouched original JSON; represent migrated object verification as `unverified` with null key/generation rather than invent cloud proof. `dataset_revision` is the migrated snapshot's revision, not an inferred first-added revision. Files retain original path/root and canonical class-relative path. A canonical-path collision blocks migration; it is not silently renamed. Reconciliation of historical collisions requires an explicit later decision.

Alternatives rejected: destructive JSON removal before verification, partially activated rows, or retaining complete collection responses indefinitely. The trade-off is temporary duplicate metadata and an offline writer window. Legacy JSON loads remain necessary during this one-time migration; it is not a bounded-memory benchmark. This step verifies metadata equivalence, not WAV contents on disk, GCS objects, PostgreSQL deployment behavior or worker recovery.

See [implementation log](../arquitectura/large-zip-gcs.md) and [operator procedure](../manuales/migracion-metadatos-importacion.md).
