# Contain ZIP and native audio processing before publication

The import worker delegates ZIP parsing, extraction and WAV decoding to a fresh
Linux bubblewrap process, not another thread. Cooperative deadlines cannot stop
a blocked or compromised native decoder. Publication, heartbeats and authoritative
database state remain outside the sandbox under the existing lease/fencing rules.

## Decision and alternatives

- Use mandatory user/mount/PID/network namespaces, dropped capabilities, disabled
  nested user namespaces and a clean environment. Expose only the read-only archive,
  trusted `/usr` runtime, selected decoder modules and two entrypoint files. Only
  the attempt's staging has a host-writable bind mount; no home, project tree,
  cloud SDK or credential directories are mounted.
- Apply hard address-space, CPU, file-size, descriptor and core limits before
  bubblewrap starts. Before importing the archive engine, seccomp denies sockets,
  process creation, re-execution, namespace changes and process inspection calls.
  A parent deadline kills the process group, and bubblewrap's parent-death/PID
  namespace controls terminate the contained decoder; the parent waits/reaps.
- Bound stdout while reading it, then validate returned paths, types, hashes and
  regular single-link files without following symlinks or blocking on FIFOs.
  The decoder cannot grant a returned path publication authority.
- Validate fixed-size, single-volume classic/ZIP64 EOCD ranges and each actual
  central-directory header before `ZipFile` allocates entries. Independently
  saturated count, size and offset fields are supported. Reject unsupported
  extensible ZIP64 end records, split volumes and prepended/self-extracting layouts
  rather than guessing offsets. Expanded-byte accounting and original WAV bytes
  remain unchanged.

A process with only rlimits would retain host filesystem/network access; Python
audit hooks do not constrain native code. Docker/services or a new containment
dependency installation are not authorized. Consequently missing prerequisites
fail closed, never fall back to in-process decoding. This makes deployment
prerequisites explicit and sacrifices portability; it is not a kernel-exploit or
malware-absence guarantee.

## Consequences

Local constants are 768 MiB address space, CPU seconds equal to half the configured
validation deadline rounded up (minimum one), 64 descriptors, zero core files and
a per-file write cap equal to the larger audio/stdout budget. Stdout is capped at
16 MiB and further bounded by entry/path limits. Four local slots additionally
bound subprocess concurrency; durable queue admission remains authoritative.
These are conservative controls, not capacity benchmarks or total-filesystem quotas.

Existing guarded domain/HTTP fixtures explicitly select the direct synthetic
validator because their unchanged guard forbids subprocesses. They do not prove
containment. A separate private synthetic process procedure exercises the real
default and fault-injected decoders. No schema migration, limit increase, runtime
installation, real data/cloud operation or deployment is included. See the
[operator procedure](../manuales/trabajos-importacion-datasets.md#t4-validacion-zip64-contenida).
