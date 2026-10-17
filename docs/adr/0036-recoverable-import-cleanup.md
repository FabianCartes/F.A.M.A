# Recoverable staging cleanup independent of publication

Publication prepares only new-member objects in the current attempt directory,
checks their hashes, fsyncs them and retains the existing durable journal before
the fenced rename and membership commit. The validated preview remains available
for recovery; an already renamed destination is verified rather than overwritten.
This temporarily duplicates new WAVs, not existing dataset objects. It does not
remove temporary validation I/O or raise the conservative operating limits.

Cleanup intent lives in the existing normalized import summary as internal
`_cleanup` metadata (`pending`, `deleting`, `done`). Publication and cancellation
schedule it in their transaction under the queue gate. A dedicated execution-job
kind would require changing the constrained queue schema and introducing cleanup
lease semantics; instead, the existing per-import filesystem lock owns deletion
throughout I/O, while a committed `deleting` state blocks new admissions and
receipt mutations. A crashed process releases that lock; another explicit
maintenance invocation reclaims the same intent and repeats deletion safely.
Execution also locks its attempt directory for the entire callback lifetime.
The cleaner nonblockingly locks every selected attempt before claiming deletion;
a timed-out callback still unwinding protects its files even after its queue job
became terminal. Preview rechecks its execution fence after archive hashing and
before creating validation output. `done` is reconciled against actual staging:
a later failed job can leave new attempt files and must be cleaned again.

The cleaner never holds the database gate over recursive deletion, never deletes
published objects, and protects queued/running work (including expired leases)
and committing publication journals. An expired lease must be recovered through
execution, not interpreted as permission to destroy its staging. Receipt
rename-before-finalize recovery remains protected independently of inactivity.
Useful activity is distinct from polling, job heartbeat and audit creation time.

The operator runs the existing one-shot worker with `--cleanup-only` and the same
stable private attempt root. HTTP only schedules cancellation; it does not delete
staging. The write reservation may be released while bytes remain on disk;
admission still checks actual free space. `done` means all selected staging
deletions and parent-directory fsyncs completed, not an exact byte accounting or
a guarantee about unrelated processes. Failed deletion retains `deleting` for
retry without changing a published import or its successful execution result.

This protocol assumes API, workers and cleaner share the physical store and
flock semantics already required by publication. It does not certify distributed
multi-host ownership, real PostgreSQL operation, GCS or deployment. Rolling back
must preserve cleanup metadata and staging and stop cleaners before older code
can admit work; do not erase a deletion fence while a cleaner may still run.
