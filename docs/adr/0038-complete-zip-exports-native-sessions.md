# ADR 0038: Complete ZIP64 exports and renewable native download sessions

Date: 2026-10-17
Status: Accepted for local T7 implementation; verification and delivery remain in the [implementation log](../arquitectura/large-zip-gcs.md).

T6 publishes immutable revision manifests, not downloadable ZIPs. Browser-native
navigation cannot attach the application's Bearer header, and the existing Next
`/api/*` rewrite proxies requests with a five-minute timeout. Replacing Blob code
with a same-origin link would preserve that proxy constraint.

## Decision

- Add separate export jobs and download sessions with an explicit additive
  maintenance migration. Do not change existing import-job kind constraints or
  repurpose an import as an export. Reuse the short database gate and trusted
  heartbeat worker, but keep export admission capacity separate from import
  capacity. No worker starts from HTTP and no migration runs at startup.
- Authorize owner, dataset and complete revision before admission and execution.
  Recover the manifest exclusively from its authorized generation/hash/size.
  Parse T6's line-delimited standard JSON incrementally with bounded records,
  schema/count/byte/path/duplicate checks and exact private object keys. Recover
  each original WAV at the specified generation and verify size and SHA-256
  while writing it into a ZIP64 member. No bucket listing or local membership
  fallback exists.
- Build an attempt-private `export.part`. Rename to read-only `export.zip` only
  after all members and totals pass; fsync file and directories before the live
  lease fence publishes the artifact identity. A reclaimed job rebuilds in a new
  attempt; it never adopts a partial ZIP. Keep completed bytes immutable and use
  their SHA-256 as ETag. Persist a stat fingerprint to reject ordinary same-size
  artifact changes without rehashing a maximum-sized ZIP for every byte range.
- The Bearer control plane issues an expiring, random bootstrap ticket. Store
  only its secret hash. A native HTTPS navigation consumes it to establish an
  HttpOnly, Secure, SameSite=Lax, export-path-scoped cookie and redirects to a
  ticket-free URL. That cookie authorizes repeated GET/HEAD/range requests;
  ticket consumption does not consume the download. Recheck current dataset
  ownership and export/session expiry for each new request.
- Renewal issues another session; it does not revoke live older sessions. Bound
  simultaneous sessions to eight and renewal to the artifact's maximum retained
  lifetime. No polling extends any lifetime. An already admitted transfer may
  finish after expiry while its shared directory lock protects its bytes.
- Require a separately configured HTTPS download origin that routes directly to
  the backend, outside Next rewrites. The panel uses a plain external anchor, not
  `fetch`, Blob, object URLs or Next routing for ZIP bytes. Missing configuration
  fails closed. Configuration is an operator assertion, not deployment proof.
- Explicit cleanup nonblockingly obtains exclusive directory locks, then records
  a deleting fence before removal. Keep active/recoverable jobs, valid artifacts,
  callbacks still unwinding and active download streams. Retry deletion and
  stable-root fsync obligations; never delete published T6 WAVs or manifests.

## Trade-offs and limits

Direct signed capability URLs would be smaller but keep authorization secrets in
every range URL. Cookie bootstrap confines them to the initial navigation;
ingress access logs must still redact ticket queries, and links are secrets until
consumed or expired. No CORS or cross-origin Bearer transfer is needed for native
top-level navigation. A shared private artifact filesystem is required; the stat
fingerprint is not a physical-corruption detector or a malicious-host sandbox.

Rebuilding after interruption trades work for a small durable protocol, avoiding
checkpointing partially compressed streams. ZIP_STORED preserves original WAV
bytes without compression CPU; central-directory metadata is bounded by 50,000
members rather than claiming constant memory. Record limit 16 KiB, manifest cap
128 MiB, dataset cap 15 GiB. These do not change import/decoder limits or certify
maximum scale, real PostgreSQL/GCS, process-kill recovery or deployed streaming.

Rollback stops export consumers/cleaners and removes the coordinated T7 routes,
worker and panel; retain additive tables and private artifacts until a separate
authorized retention decision. Import jobs, receipts, T5 journals and T6 immutable
references keep their existing semantics.
