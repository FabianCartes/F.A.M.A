# ADR 0027: Private local-first ZIP dataset imports

Status: accepted for local implementation; deployment not authorized.

## Context

The legacy dataset catalog walks local directories and a shared `datasets/` GCS
prefix without dataset ownership. Publishing private user uploads there would
expose their membership. Its filesystem-derived counts also cannot establish
remote content integrity. Existing dataset/audio tables require GCS references,
whereas a successful local import must not depend on GCS availability.

## Decision

Introduce additive `imported_dataset` and `dataset_import` tables. New datasets
belong to the authenticated principal; no administrative override is introduced.
Legacy ownerless datasets remain readable through existing interfaces, but are
not writable destinations in this assistant. Administrative integration is deferred.

For local development only, an explicit `FAMA_ENV=development` plus
`FAMA_IMPORT_DEV_MODE=1` permits direct loopback requests without credentials to use
reserved owner `-1`. This is not a user account or an administrative override:
normal credentials still authenticate and owner filters remain intact. Other
environments reject the opt-in; non-loopback peers are rejected. This mode must
run bound to loopback without proxies, tunnels or trusted proxy-header rewriting.
All local anonymous clients share the development identity. Disabling the mode
does not reassign its objects. No global auth dependency is removed.

Use durable `backend/data/dataset-imports` storage, outside raw-data discovery,
with server-generated import IDs and original-byte SHA-256 filenames. Preserve
original ZIP paths and chosen class labels in the manifest. Catalog membership,
counts and import result publish in one database commit after durable local files.
A committed `committing` journal precedes rename; replay completes publication.
Pending journals reserve their destination. One nonblocking POSIX volume lock
serializes mutations across processes on that volume; previous content remains
visible while an append is incomplete.

Cloud synchronization is an explicit, independently retryable action. Private
keys use `private-imports/{owner}/{dataset}/{sha256}.wav`, not the globally listed
legacy prefix. Conditional creates never overwrite an existing object. Metadata,
size and SHA-256 of generation-bound downloaded bytes verify identity. Persistent
per-file progress survives interruptions; verified progress is not a count-based
claim. Local bytes are retained on cloud failure.

## Alternatives

- Extend the legacy catalog: would require simultaneous permission enforcement
  across all existing consumers and schema references; rejected for this delivery.
- Publish files directly to GCS: fails local-first and makes cloud availability a
  prerequisite; rejected.
- Store only filesystem manifests: cannot atomically publish membership, counters
  and the idempotent result with application persistence; rejected.

## Consequences and limits

- Managed imports appear in a modal opened beside the download action in Gestión
  de audios. It has no embedded login or role selector. The dedicated access view
  is pending; local testing uses the explicit exception above. Imports are not
  registered for training or exposed through legacy scans.
- The storage volume must be persistent, physical and lock-capable POSIX storage;
  multi-host correctness is not asserted for independent local volumes.
- Filesystem and database are not a distributed transaction. Replaying the same
  confirmation recovers a pending publication; operators must not delete journals
  or managed objects to resolve an error.
- Validation budgets are cooperative around native decoding, not OS process
  isolation. Defaults are conservative admission ceilings, not infrastructure
  capacity certification. Consult the [operator guide](../manuales/importacion-datasets-zip.md).
- The explicit additive migration does not relabel, deduplicate or rewrite any
  existing dataset. Deployment and real-cloud acceptance require separate approval.
