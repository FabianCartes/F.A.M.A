# Enable the agreed large-ZIP import limits

Status: P0 inventory recorded; P1 closed locally; P2 design documented, T1 maintenance foundation functionally checked with independent correction recheck; T1 closure and writer integration pending. P3–P6, operational migration and activation pending.
Baseline: `adecb01` on `dev`; planning branch: `plan/large-zip-limits`.
Scope: 10 GiB received ZIP, 15 GiB expanded import, and preservation of existing dataset quotas.

## Recommendation

Enable the agreed limits through a coordinated, explicitly configured API/worker profile **only after physical-storage accounting, execution budgets and target-runtime acceptance are demonstrated**. Reuse the existing receipt/chunk, queue, ZIP64, contained validator and publication mechanisms. Do not replace them with a whole-body upload or undertake an unrelated architectural rewrite.

The configuration edit is small. The material work is proving that admission, retries, publication and cleanup remain safe at the new sizes. Existing synthetic closures are not evidence of maximum-size operation.

The original request authorized planning only. «Avazemos en la implementación de la etapa 0» authorized P0 diagnostics. «Vamos con la siguiente etapa» and «Procede» authorized P1 with existing Compose variables, conservative defaults and the confirmed public configuration/worker/HTTP test interfaces. After the P2 read-only map, «Autorizo» authorized shared-budget design and its ADR, including migration/recovery planning only if necessary; it did not authorize production implementation or applying migrations. P2–P6 implementation, installation, migration, service restart, real import, large data generation and remote operation remain unexecuted. P1 synthetic test evidence is recorded separately below; no scale benchmark is claimed.

## Request and scope

- User request: «Realiza un plan para aumentar estos limites a los acordados, haz una investigación profunda, delega a varios agentes para esto. Crea una rama para esto o reutiliza la ya existente, aunque esta desactualizada.»
- Agreed limits are recorded in the [original plan, section 2](large-zip-gcs-plan.md) and [active implementation history](large-zip-gcs.md). This follow-up does not rewrite their historical evidence.
- Local Git inspection showed `feat/dataset-zip-import` is an ancestor of `dev`, 28 commits behind it. A fresh branch from current `dev` preserves the integrated work without resetting or merging the older branch. No fetch, push, commit or merge was performed.
- Local-only import acceptance is the primary milestone. Training, model quality, GCS synchronization/export certification and production rollout are not implied by it. Existing export activity must still be included when it competes for local disk.

## 1. Preserve the agreed contract

One GiB is 1,073,741,824 bytes. Exact limits are accepted; values above them are rejected.

| Control | Current code default | Target / disposition |
| --- | --- | --- |
| Received ZIP bytes | 67,108,864 (64 MiB) | **10,737,418,240 (10 GiB)** |
| Expanded bytes per import | 268,435,456 (256 MiB) | **16,106,127,360 (15 GiB)**, including duplicate payloads read from the ZIP |
| Accumulated dataset bytes | 16,106,127,360 | Preserve: unique member bytes, not total owner storage |
| Accumulated dataset members | 50,000 | Preserve: unique members across successive imports |
| Entries per ZIP | 2,000 | Preserve initially; independent of the 50,000-member dataset quota |
| Receipt chunks | 16 MiB by default | Preserve sequential, server-negotiated chunking |
| Concurrent receipts per owner | One | Preserve; several retained datasets remain allowed |
| Global concurrency | Four by default | Determine a safe operational value from shared storage/worker capacity; do not assume four maximum-sized imports are safe |
| WAV size / duration | 32 MiB / 600 seconds | Preserve; increasing aggregate size does not increase per-file allowances |
| WAV content and layout | Original bytes, `class/audio.wav` | Preserve without transcoding, wrapper directory or nested class folders |

**Not part of this request:** allowing 50,000 entries in one ZIP. A dataset may reach 50,000 unique members through multiple imports. If a future requirement raises the per-ZIP count, it needs separate memory, metadata-output and database-scale evidence, rather than being inferred from the dataset quota.

## 2. Research findings and confidence

Three read-only explorers investigated backend capacity, deployment/frontend and verification separately. A fourth, independent verifier challenged the consequential capacity assumptions. Parent readback confirmed publication's additional file copy. Findings refer to the checkout, not inspected running services.

| Finding | Evidence | Planning consequence |
| --- | --- | --- |
| Byte caps are configurable, but still conservative by default | `backend/app/services/dataset_zip.py:19–43`; `backend/app/routes/dataset_imports.py:115–117` | Check effective settings, not merely sample configuration |
| API and worker construct their own limit objects | `backend/app/services/dataset_imports.py:50–53`; `backend/scripts/run_dataset_import_worker.py:44–56` | Propagate and compare the same profile in both processes |
| Receipt reserves declared ZIP bytes plus one expanded allowance | `backend/app/services/dataset_import_receipts.py:59–103` | Reconcile promises against every allocation phase before activation |
| Publication copies new WAVs while validated originals remain | `backend/app/services/dataset_import_execution.py:191–243` | Account for a second expanded copy; rename does not reclaim the originals |
| Promise release and physical cleanup are separate | `dataset_import_execution.py:266–273`; `dataset_import_cleanup.py:62–118`, both under `backend/app/services/` | Test cleanup delay/failure, retry attempts and new admission independently |
| Admission uses actual filesystem free bytes | `backend/app/services/dataset_import_receipts.py:81–92` | Release does not invent free disk; materialized bytes plus full promises can also cause conservative double counting |
| Finalize hashes the complete archive under `validation_seconds` | `backend/app/services/dataset_import_chunks.py:160–227` | Benchmark this phase independently of decoder execution |
| Child resource bounds do not cover all parent I/O | `backend/app/services/dataset_zip_sandbox.py:24–38,120–126,154–182` | Measure parent rehash, publication copy and child execution separately; no global hard-timeout claim |
| Worker timeout defaults to 300 seconds and is cooperative | `backend/app/services/dataset_import_worker.py:25–34,89–104` | A larger decoder deadline alone is not an end-to-end execution policy |
| Per-file metadata is bounded independently of audio bytes | `backend/app/services/dataset_zip_sandbox.py:63–115,171` | Preserve bounded result handling; the ceiling is at most 16 MiB, lower under some configured entry/path limits |
| Some metadata work scales with file/class count | `backend/app/services/dataset_zip.py:285–289`; `dataset_import_execution.py:115–131,252–265` | Measure at the retained 2,000-entry cap before deciding whether optimization is needed |
| Export generation also writes local artifacts | `backend/app/services/dataset_exports.py:206–250,280–361` | Account for simultaneous exports where roots share a filesystem; do not certify cloud operations from this plan |
| Compose does not explicitly propagate these import caps | `docker-compose.yml:45–60`; `backend/scripts/dev_imports.py:33–84` | Cover both container API and external host-worker startup paths |
| Runtime prerequisites differ from ordinary Python dependencies | `backend/app/services/dataset_zip_sandbox.py:154–180`; `backend/Dockerfile:18–24` | Verify `/usr/bin/bwrap`, `/usr/bin/prlimit`, namespaces, seccomp and decoder dependencies in the actual worker runtime |
| Browser uses server limits and receipt-sized slices | `frontend/components/ingestion/DatasetImportPanel.tsx:149–159,236–253`; `frontend/lib/api/datasetImportReceipt.ts:26–71` | Keep aggregate ZIP admission separate from per-request proxy behavior |

### Storage: why 25 GiB is insufficient as a complete capacity model

For one no-retry import that contains 15 GiB of new unique WAVs, the current copy-based path can retain approximately:

```text
10 GiB received archive + 15 GiB validated WAVs + 15 GiB prepared/published copy
= 40 GiB of simultaneously present payload
```

This is a derived coexistence scenario, **not a measured requirement or a retry-inclusive upper bound**. Existing objects, filesystem overhead, inodes, exports, logs and retained attempts add to it. Repeated previews can leave earlier attempts until eligible cleanup. Four admitted maximum-size imports must not be justified by multiplying only the current 25 GiB promise.

Map storage roots to physical filesystems first. Where roots differ, enforce capacity on each filesystem; do not pool unrelated free-byte counts. Keep logical dataset quotas distinct from physical allocation promises and actual reclamation.

### Execution: keep the existing safeguards

The child currently has a 768 MiB address-space limit and a CPU limit derived from the validation deadline. Larger total audio does not itself require loading 15 GiB into RAM, because processing is streamed, but the existing memory cap has not been certified at the target workload.

The child wall deadline excludes later parent-side result/file hashing. Finalization, child decoding, parent rehash, publication copying, lease/heartbeat behavior, worker timeout and receipt expiry are separate concerns. Do not extend every deadline blindly, remove containment or call cooperative checks hard termination. Retain bounds and choose any adjustments from measurements.

### Frontend/proxy: aggregate size is not request size

The declared and locally installed Next.js version inspected by the verifier is 16.3.4. `frontend/next.config.ts:3–18` configures a 110 MiB proxy buffer setting and a 300,000 ms proxy timeout. A 10 GiB aggregate upload still travels in negotiated chunks, normally 16 MiB, not one 10 GiB request.

Official [Next.js proxy body-size documentation](https://nextjs.org/docs/app/api-reference/config/next-config-js/proxyClientMaxBodySize) and the installed guide at `frontend/node_modules/next/dist/docs/01-app/03-api-reference/05-config/01-next-config-js/proxyClientMaxBodySize.md:69–76,115–117` describe partial buffering and warnings, not automatic HTTP 413 rejection. Context7 also returned upstream canary documentation; the installed guide is the version-matched cross-check.

**Unverified:** applicability of that setting to this rewrite-only path and any external ingress. Test the effective path; do not present a buffer knob as an enforcement gate. Do not raise shared request buffers to 10 GiB or disrupt inference uploads using the same proxy configuration.

## 3. Proposed implementation sequence

P0 inventory is recorded in section 8; P1 implementation/evidence is in section 9. P2 design and additive-state migration planning are in section 10; P2–P6 implementation remains pending. Work units include their relevant regression tests and documentation. Keep source changes small and justified by measured/observable requirements; no framework or dependency replacement is proposed.

| ID | Work and likely edit surfaces | Depends on | Acceptance / stop condition |
| --- | --- | --- | --- |
| P0 | Record runtime topology, effective API/worker limits, storage roots/filesystems, free bytes/inodes, installed containment prerequisites and safe test workspace. Inspect `docker-compose*.yml`, `backend/scripts/dev_imports.py`, worker CLI and the existing operator manuals | None | A concrete local target and resource envelope are identified without exposing secrets. Missing prerequisites are blockers, not grounds for automatic installation |
| P1 | Define one coordinated operational limit profile and preserve configured-small compatibility. Likely surfaces: `backend/app/services/dataset_zip.py`, `docker-compose.yml`, relevant dev startup/config examples and corresponding tests | P0 | API and worker resolve the agreed exact bytes; UI observes server values; existing small-limit overrides still enforce their values. No large live receipt admitted yet |
| P2 | Make physical admission cover publication copies, retained attempts and competing allocations, or establish an equally safe bounded lifecycle with evidence. Inspect `dataset_import_receipts.py`, `dataset_import_execution.py`, `dataset_import_cleanup.py`, and export admission under `backend/app/services/` | P0 | No unbudgeted allocation path under tested retries/concurrency/cleanup failure. Distinguish released promises from recovered bytes. Do not change copy/recovery semantics merely to save disk |
| P3 | Measure and bound finalize, child decode, parent verification and publication; adjust only necessary budgets or proven count-related bottlenecks. Likely surfaces: `dataset_import_chunks.py`, `dataset_zip.py`, `dataset_zip_sandbox.py`, `dataset_import_worker.py` and their focused tests | P0, P2 | Bounded resource behavior and recovery remain valid. Establish measured settings and stop thresholds; no invented throughput, enlarged unbounded output or weakened sandbox |
| P4 | Reconcile transport, effective runtime setup and UI errors with the agreed profile. Likely surfaces: existing Compose/dev worker startup, backend image only if that image owns decoding, receipt client/panel tests and operator documentation | P1, P3 | Chunked requests traverse the actual path; interrupted/lost replies recover; normal authentication and local development identity remain distinct. Existing proxy consumers are preserved |
| P5 | Run staged isolated acceptance: small valid data, the prepared ESC-50 archive if separately authorized, then maximum receipt/expansion and cumulative quota dimensions | P1–P4 | Every claim has current evidence from the intended runtime. Sparse files and mocked deadlines cannot stand in for actual transfer/decoding. A partial result leaves maximum-size enablement pending |
| P6 | Coordinate activation, observation and rollback with active-work policy; update the user/operator manuals and effective-limit display evidence | P5 | New receipts enabled only after proof. Preserve active/recoverable work and storage. Record the runtime profile, tested scope, limitations and rollback procedure |

P1 may prepare configuration and tests before P2/P3 complete, but it must not activate larger live admissions. Candidate edit surfaces above are planning estimates, not permission for a delegated writer to modify whole directories.

### Configuration direction

Use the existing variable names rather than adding a competing source of truth:

- `FAMA_IMPORT_RECEIVED_BYTES`: target 10,737,418,240.
- `FAMA_IMPORT_EXPANDED_BYTES`: target 16,106,127,360.
- `FAMA_IMPORT_DATASET_BYTES`: preserve 16,106,127,360.
- `FAMA_IMPORT_DATASET_ENTRIES`: preserve 50,000.
- `FAMA_IMPORT_ENTRIES`: preserve 2,000 unless separately approved.
- Reconcile existing reservation budgets, global/owner concurrency, `FAMA_IMPORT_VALIDATION_SECONDS`, worker execution timeout, free-space floor and TTL against measured capacity before deciding their operational values.

Prefer explicit coordinated operational configuration for initial rollout rather than silently raising every unconfigured deployment's defaults. Do not expose private roots or environment contents in user-visible diagnostics. Preserve the normal authenticated interface and the existing local-only development exception.

If safe accounting requires a persisted-state change, plan its migration, recovery and ADR separately before implementing it. This proposal assumes no automatic migration and grants no permission to mutate existing reservations.

## 4. Verification and acceptance matrix

Use TDD for behavior changes: observe a deterministic public-interface failure, implement the smallest correction, and retain regression coverage. For each touched existing option/command, preserve its previous documented behavior. Do not fabricate RED for documentation or already-working invariants.

| Layer | Required cases | Evidence required |
| --- | --- | --- |
| Exact byte policy | Received ZIP cap and cap+1; expanded cap and cap+1; dataset unique bytes cap and cap+1; configured-small profile | Correct response/status, no unauthorized publication, expected durable state and unchanged content hashes after rejection |
| Independent counts | Per-ZIP 2,000-entry policy; cumulative dataset 50,000 unique members; duplicates vs conflicting labels; expanded duplicate bytes | No implicit coupling of archive entries to dataset members; validate actual counters, not just displayed values |
| Chunk integrity | Sequential chunks, lost ACK/finalize reply, altered middle chunk with unchanged name/size, reconnect and full-prefix verification | No suffix accepted after invalid prefix; idempotent persisted offsets/hash state and byte-identical result |
| Recovery and capacity | Restart at receipt/finalize/preview/publication; stale attempt; delayed/failed cleanup; export contention where applicable; cancellation and replay | No double publication, live/recoverable work retained, no underbudgeted copy, logical promise release separated from physical reclamation |
| Containment | Valid WAV, malformed ZIP/WAV, deadline exhaustion, resource rejection, denied access/network/process creation, hostile child output | Execute the distinct native OS procedure; unchanged guards and fail-closed behavior |
| Runtime path | Effective API/worker agreement, chunk request via frontend proxy, ownership and normal authentication, bounded UI recovery | Browser/network evidence from the intended runtime; dev-mode success is not normal-mode evidence |
| Scale | Real 10 GiB receipt, real extraction/decoding near the 15 GiB expanded limit, retained entry cap, cumulative 50,000-member dataset through smaller imports | Per-phase wall/CPU time, peak RSS/address-space context, peak physical bytes/inodes, database work, cleanup lag and resulting hashes; no small-test extrapolation |

Test exact arithmetic cheaply using controlled limits and public seams first. Add target-sized physical proof separately; declaring a size or using a sparse ZIP64 fixture does not prove receipt or decoding at that size. Some maximum dimensions need different fixtures; do not demand an artificial archive that reaches every maximum simultaneously.

For actual boundary fixtures, count all ZIP/WAV/container overhead. Generate structurally valid audio privately and deterministically only after resource authorization; do not download, modify or silently transcode user datasets. Include an incompressible/poorly compressible workload so compression cannot hide transfer and storage costs.

### Existing command forms to reuse later — not executed in this research

From `backend/`, after validating the existing interpreter and documented prerequisites:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHON_DOTENV_DISABLED=1 DATABASE_URL=sqlite:// \
CUDA_VISIBLE_DEVICES='' PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
../.venv/bin/python tests/run_isolated_training_checks.py \
  tests/test_dataset_import_api.py tests/test_dataset_import_receipts.py \
  tests/test_dataset_zip_validation.py tests/test_dataset_import_quotas.py \
  tests/test_dataset_import_chunks.py tests/test_dataset_import_cleanup.py -q --tb=short
```

The isolated runner is an application guard, not an OS sandbox. Keep it and its protected inventory unchanged. Run the separate process and containment procedures outside that runner:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHON_DOTENV_DISABLED=1 DATABASE_URL=sqlite:// \
CUDA_VISIBLE_DEVICES='' OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
../.venv/bin/python tests/run_dataset_import_chunk_process_checks.py

PYTHONDONTWRITEBYTECODE=1 PYTHON_DOTENV_DISABLED=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
FAMA_SYNTHETIC_SECRET=synthetic GOOGLE_APPLICATION_CREDENTIALS=/nonexistent/synthetic \
../.venv/bin/python tests/run_dataset_zip_sandbox_checks.py
```

Add the relevant publication/receipt process procedures and frontend tests when their respective paths change; select exact scopes after P0, not an uninspected global suite. Frontend baseline commands are `npm test` and `npm run lint` from `frontend/`; build applicability and installed-version guides must be checked before source changes. Do not install dependencies merely because a check cannot start.

Existing command sources: [worker/receipt/containment manual](../manuales/trabajos-importacion-datasets.md), especially T3/T4, and [integration acceptance manual](../manuales/integracion-importacion-datasets.md). Their historical PASS counts are not new results.

## 5. Resource forecast, rollout and rollback

Before each material test, record its dataset shape, expected disk/inodes, concurrency, runtime ceiling, cleanup ownership and cancellation behavior. Forecasting includes archives, validated and prepared copies, retries, unrelated retained data and export artifacts on each physical filesystem. Obtain authorization before large data generation, Docker build/restart, real database writes or remote/cloud activity. This research did not perform any of them.

1. Keep conservative live admission while preparing the new profile and proof in isolated state.
2. Identify the actual decoder owner: host development worker or container worker. Verify containment there; do not require an unused API image to be the decoder.
3. Establish a policy for active receipts before any change. Recommended first rollout: pause new admissions and drain active/recoverable work, or explicitly cancel only user-approved disposable attempts; keep history and data intact.
4. Apply the same validated profile to API and workers through the intended startup mechanism. Check process restart requirements and effective limits before resuming new receipts.
5. Observe one controlled import first, then the tested concurrency envelope. Do not equate one successful import with four concurrent maximum-sized imports.
6. On failure, stop new large admissions and preserve jobs, archives, journals and artifacts. Lowering current limits can invalidate later validation/confirmation of existing receipts; it does not automatically grandfather them. Drain/reconcile before rollback, or design and test explicit policy compatibility first.

Never use deletion of stored datasets, disabling containment, automatic migration, hidden workers or force-resetting Git as a recovery mechanism. A cleanup failure must not relabel an already published dataset as a failed publication.

## 6. Decisions deferred to evidence

| Uncertainty | Resolution point |
| --- | --- |
| Effective runtime limits and which process owns decoding | P0 observed development API defaults and external-host-worker design; no matching host worker detected, so worker agreement remains unverified |
| Storage root topology, retry/backlog capacity and competing exports | P0/P2: filesystem-level accounting and bounded fault cases |
| Correct execution/CPU/expiry budgets and safe concurrency | P3/P5: measured representative and target-scale runs |
| Whether parent I/O needs additional termination controls | P3: reproduce an unmet bounded-execution requirement before adding machinery |
| Whether code optimization or a persisted migration is actually necessary | P2/P3: public test failure or measured bottleneck, not speculative refactoring |
| Production deployment or GCS-scale acceptance | Separate authorization and target-specific evidence; not implied by local closure |

No unresolved product decision prevents delivering this plan. The recommended scope preserves all agreed quotas and existing entry/per-file policies; operational numeric budgets deliberately remain unset until measured.

## 7. Completion checklist

- [x] Read-only multi-agent research and independent capacity-assumption challenge completed.
- [x] Current baseline and safer planning branch identified; old branch preserved.
- [x] Agreed byte limits distinguished from dataset quota and per-ZIP entry count.
- [x] Proposed stages, test layers, resource prerequisites and rollback recorded.
- [x] P0 local read-only inventory recorded, with explicit missing live-worker and sandbox-operation evidence.
- [x] P1 configuration implemented and functionally verified; three-lens native review approved and exact acknowledgement consumed, without activation.
- [x] P2 shared physical-budget design and ADR 0052 documented; additive migration/recovery planned, not implemented or applied.
- [ ] P2–P6 implemented and verified after separate authorization.
- [ ] Maximum-size/local operational claims supported by new evidence.
- [ ] Production/GCS claims, if requested later, supported separately.

Next step: implement P2 only after separate implementation authorization and resolution of the section 10 gates; P3 can prepare bounded measurements. Do not raise live caps or launch maximum-size tests on the current unbudgeted storage.

Implementation authorization was subsequently given with «Procede a implementarlo» and the public test interfaces confirmed with «Procede, me quedo claro». Current work-unit state and actual checks are in [P2 implementation tracking](large-zip-storage-budget-implementation.md); that authorization does not permit operational migration or activation. The next-step sentence above records the pre-implementation boundary, not a new request to repeat authorization.

## 8. P0 observed local inventory

Authorization: «Avazemos en la implementación de la etapa 0». The [P0 receipt](../receipts/large-zip-limits-p0.json) retains exact observations and collection limitations. The parent storage spot check was recorded at `2026-10-21T01:22:03Z`; capacity is a snapshot, not reserved space.

| Area | Observed result | Consequence |
| --- | --- | --- |
| Local stack | Frontend, backend and database running and healthy; only frontend published at `127.0.0.1:3000` in the inspected bindings | Concrete target is the existing development stack; no restart performed |
| Effective API caps | Loopback frontend GET `/api/ingestion/imports/limits` returned HTTP200: 64 MiB received, 256 MiB expanded, 2,000 entries, 60 seconds; dataset 15 GiB / 50,000 unique members | Conservative caps are confirmed in the running API, not just source defaults |
| Worker | No recognized same-user host worker with cwd inside this repository was detected | No worker started; API/worker effective agreement and job readiness remain unproved |
| Storage roots | `backend/data-dev/dataset-imports` and `backend/data-dev/dataset-import-attempts` exist, are invoking-user owned, mode0700 and writable; both on the same Btrfs `/home` filesystem | Matches the source requirement for host-worker publication; roots were not modified or recursively inventoried |
| Data capacity | Parent spot check: 45,391,306,752 available bytes, approximately **42.274 GiB**; Btrfs does not report a fixed inode pool through this statvfs query | Shared free space must not be added twice; absence of a fixed inode count is not zero free inodes |
| Maximum-size margin | Approximately **2.274 GiB** after the hypothetical 40 GiB no-retry coexistence scenario | Insufficiently characterized margin for clearance: overhead, stale attempts, exports and concurrency remain unbudgeted |
| Small scratch | `/tmp/opencode` resides on tmpfs, with 8,159,956,992 available bytes at collection | Suitable only for bounded small private checks, not a 10 GiB archive or a maximum-size import |
| Large scratch candidate | `backend/data-dev/large-zip-checks/<private-run>` on the data filesystem; parent does not yet exist | Keep separate from live roots, create mode0700 only when authorized/budgeted; no large-test workspace provisioned |
| Host prerequisites | Executable bubblewrap0.13.1 and prlimit/util-linux2.42.4; libseccomp.so.2 lookup succeeds; unprivileged user namespaces enabled | Presence is established, but sandbox launch/resource-denial behavior was not tested |
| Interpreter | Project `.venv/bin/python` is Python3.14.8; module specs found for SoundFile, `_soundfile`, NumPy, CFFI, SQLAlchemy, psycopg2 and typing_extensions | Candidate for later runner/prerequisite validation; not qualification of Python3.12/container execution or native module initialization |
| Host envelope | 12 logical CPUs; approximately16.46GB total RAM and7.76GB available at collection | Snapshot only; not a decoder-memory allowance or evidence for four simultaneous large imports |

The system Python is also3.14.8 but lacks the inspected application module specs except typing_extensions; do not switch to it or install packages to manufacture a green check. No application/database module was imported by the diagnostic.

The running backend has no explicit received/expanded overrides in the inspected import environment. The development wrapper is designed to obtain settings from the API-side configuration before constructing its host worker; because no matching worker was observed, P0 does not claim to have compared running process policies. Existing export roots/backlogs and active import/reservation state were deliberately not queried and remain P2/P6 inputs.

### Collection limits and P0 closure

The two explorers completed static mapping but lacked command execution. A command runner then executed one filtered read-only collector. All observation sections were received, including successful internal Docker listing, HTTP200, executable-version and interpreter probes; **the runner did not expose the overall collector exit code**. No full retry or synthetic global PASS is claimed. The parent separately spot-checked the data filesystem and proposed workspace absence with an explicit successful observation.

P0 is closed as an **inventory with limitations**, not functional readiness or maximum-size acceptance. It identifies the concrete development target, roots, present prerequisites and storage constraints needed to prepare P1/P2. Live worker agreement, actual containment, authenticated normal mode and adequate maximum-test capacity remain explicit later gates. No test suite, sandbox smoke, dataset import, DB/schema change, service lifecycle action, installation, cleanup or commit was performed.

## 9. P1 coordinated configuration

Authorization: «Vamos con la siguiente etapa», then «Procede» after confirming the existing-variable approach and public Compose-resolution, host-launcher and `/limits` test interfaces. Route: inline implementation; independent verification required for shared operational configuration. No worker or service activation is part of P1.

### Active P1 acceptance criteria

- P1.A1: Compose resolves the five existing received/expanded/dataset-byte/dataset-member/archive-entry variables. Unconfigured normal and development modes retain 64 MiB / 256 MiB, 15 GiB / 50,000 dataset quotas and 2,000 ZIP entries.
- P1.A2: Explicit 10 GiB / 15 GiB values and configured-small values reach backend configuration without silently changing dataset or archive-entry policies. Existing authentication, ports and separate direct-upload limits remain unchanged.
- P1.A3: The development host launcher forwards the backend-selected profile instead of stale inherited limits. Its foreground/local-only behavior and sanitized output remain intact.
- P1.A4: The public HTTP limits response exposes the selected conservative/large/small profile in synthetic state, retaining dataset and entry quotas and without creating datasets.
- P1.A5: No running limits, services, data or schema change; documentation distinguishes configuration support from activation and scale acceptance.

### Implementation and checks

`docker-compose.yml` adds only the five existing variable substitutions and conservative fallbacks. No loader, API, worker, proxy or persisted-format implementation was changed. The existing verified development configuration transfer remains in use; no new profile flag or overlay was added. Operator semantics and activation restrictions are documented in [the import manual](../manuales/importacion-datasets-zip.md#límites-coordinados-de-importación-en-compose).

Own observed RED: the new public Compose-resolution test failed in all six cases because every import variable was absent. GREEN after the six-line Compose change: six passed. Both focused runs explicitly deselected seven unrelated cases; those were subsequently included in the complete three-module configuration suite.

Own closure checks:

- Root configuration/launcher suite: `PYTHONDONTWRITEBYTECODE=1 PYTHON_DOTENV_DISABLED=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -B -m pytest -p no:cacheprovider --basetemp /tmp/opencode/p1-config-suite tests/test_container_configuration.py tests/test_compose_import_dev.py tests/test_dev_imports.py -q --tb=short`: **20 passed, six subtests passed**, no deselections. Docker client output was resolved with synthetic inputs; existing context-build tests use a loopback simulated engine, not a real image build or daemon.
- From `backend/`: `PYTHONDONTWRITEBYTECODE=1 PYTHON_DOTENV_DISABLED=1 DATABASE_URL=sqlite:// CUDA_VISIBLE_DEVICES='' PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 ../.venv/bin/python tests/run_isolated_training_checks.py tests/test_dataset_import_quotas.py -q --tb=short`: **16 passed**, process/pytest exit0, no deselections; synthetic memory SQLite, network/live-DB denial, 30 protected paths unchanged and private scratch cleanup reported. Python emitted two interpreter-prefix warnings; the check completed successfully.

The worker-transfer and HTTP-profile additions are preservation evidence for already-working behavior, not separate fabricated RED cycles. No frontend source changed, so no frontend suite/build or browser claim is made. Independent verification and native review are complete within the scope below; no commit has been created.

Independent verification: nine public probes passed in a fresh private copy, exit0. Normal/development unset, empty, target and custom-small Compose models match baseline `adecb01` after removing exactly the five new keys and normalizing checkout paths; launcher forwarding, clearing omitted stale values, baseline rejection output and sentinel hashes were preserved. The verifier reported 445 workspace hashes and status unchanged.

Historical independent P1.A4 preparation failures: the curated scratch copy first lacked three protected tracked sources, then collection failed with `ModuleNotFoundError: No module named 'ml_core'`, exit4, zero SQLite connections and no test-call reports. The verifier stopped after two non-progress attempts. These remain scratch-prerequisite failures, not product RED or failed application assertions.

Authorized recovery: the user replied «Autorizo» to scratch-only completion and one HTTP execution per snapshot. The same verifier completed 44 missing tracked Python sources in each copy and statically inventoried 76 reachable local modules with no unresolved local import before launch. The unchanged prepared probe then passed **once in candidate and once at baseline**, process/pytest exit0, one test call and one memory SQLite connection each, no deselections, 30 protected paths unchanged, network/live-DB denial and private cleanup intact. It exercised the actual service factory, full conservative/target/small responses, unchanged empty catalogue and identical invalid-configuration rejection with sentinel hashes preserved. All P1.A1–A5 are met within this synthetic scope.

The recovery left 492 workspace hashes and Git status unchanged, did not alter probes/guards and did not repeat approved suites. The parent read back the result and repeated structural Git checks rather than exceed the authorized once-per-snapshot functional limit. No production correction or test-source modification was needed. Evidence: [P1 receipt](../receipts/large-zip-limits-p1.json). No operational limit has been raised.

Native closure: after explicit selection of «Revisar este cambio», the high-risk candidate was inspected by risk, readability and reliability lenses. All three completed without findings; no correction was opened. The exact acknowledgement returned `gentle-ai.review-acknowledged/v1`, `action=acknowledged`, `authority=burned`, lineage `review-dfe0247bbcb56871`, target `sha256:b0aa4b1e3ace6f50f175703f8b24c3caef42951cb1844aebf21fc9a5476ccb6d` and consumed revision `sha256:753df48a644492ad35d9d4d9d3141d3b5470ae14d4b7b62ffbb02a199087c2f9`. Review covered ten paths / 622 changed lines, including earlier passive planning and P0 evidence; the only production change remains six Compose lines.

P1 is closed locally within its synthetic configuration scope. These status/evidence updates are passive post-review closure notes, not changes to the reviewed executable bytes. The reviewed snapshot is `f6c3fbf7566d98194a98c866096e8cb06d917323`; no trailing review lifecycle operation, commit, delivery or operational activation is authorized by its outcome. P2–P6, maximum-size proof and running worker agreement remain pending.

Risk: items 3 (shared Compose consumers) and 5 (operational configuration); no live activation or capacity certification.

## 10. P2 shared physical-budget design

Scope: design only, on `plan/large-zip-limits` / `adecb01`. The user answered «Autorizo» to: «¿Autorizas avanzar con ese diseño y su ADR, incluyendo el plan de migración y recuperación **solo si resulta necesario**, sin aplicar migraciones ni cambiar los límites activos?» This authorizes this section and [ADR 0052](../adr/0052-shared-physical-storage-budget.md), not production code, migration execution, live inventory of jobs or operational cutover.

### Decision and current evidence

Use one internal physical-budget module with durable grants shared by import and export writers. Preserve receipt-v1 values and owner/global receipt budgets as separate controls. Preserve the 10 GiB / 15 GiB target, dataset 15 GiB / 50,000 unique-member quotas, 2,000 ZIP-entry policy, conservative active limits, journal and copy-based publication.

| Current behavior | Evidence in the checkout | Required design coverage |
| --- | --- | --- |
| Receipt promise is declared ZIP plus one expansion; free bytes come from the import root | `backend/app/services/dataset_import_receipts.py:38–47,59–103` | Add physical accounting; do not silently change `reserved_bytes` or its budgets |
| Receipt v1 persists and exposes `reserved_bytes` | `backend/app/models/dataset_import_receipt.py:14–30`; `frontend/lib/api/datasetImportReceipt.ts:5–11`; ADR 0032 | Keep old values readable and preserve replay responses |
| Finalize hashes and renames the uploaded file, rather than assembling a second archive | `backend/app/services/dataset_import_chunks.py:160–227` | One archive envelope, not two full ZIP copies |
| Each worker attempt has independent staging; publication copies validated WAVs | `backend/app/services/dataset_import_worker.py:38–77`; `dataset_import_execution.py:70–104,209–244` in the same services directory | Cover extraction and publication growth, including replacement attempts |
| Gate transactions are short; callbacks retain attempt locks beyond lease expiry | `backend/app/services/dataset_import_jobs.py:69–82`; ADR 0030 and ADR 0036 | Serialize grant decisions, not long I/O; do not refund an expired writer blindly |
| Logical release does not claim staging deletion | `backend/app/services/dataset_import_receipts.py:125–136`; ADR 0036 | Separate future write authority from retained occupied bytes |
| Export attempts write manifest and ZIP_STORED artifacts, with job-count admission only | `backend/app/services/dataset_exports.py:80–104,280–361`; ADR 0038 | Include manifest, ZIP metadata, retries and retained artifacts on their actual pool |

Read-only mapping used CodeGraph and the existing ADRs. A parent spot check directly read receipt admission after a targeted CodeGraph query returned unrelated source. No new test results, free-space measurements, active-work inventory or deployed agreement are claimed.

### Physical pools and admission invariant

A **physical storage pool** is capacity shared by writers, not a sum of path-level free-space readings. Deployment configuration must explicitly map import, attempt, object, manifest, export and relevant scratch roots to validated pools. Distinct path strings, bind mounts or different container paths do not establish distinct capacity. A device number alone does not establish equivalent mounts, quota scopes or working lock semantics.

Initial supported topology must retain the same-filesystem rename and shared-lock assumptions of publication. Do not introduce cross-filesystem copy/recovery fallback or distributed-lock claims. Separate export capacity can use a separate pool only after the mapping is verified. Unknown, missing or conflicting mappings fail closed for new growth without deleting or hiding retained data. Multi-host or differing quota views require separate qualification. Do not pool independent free-byte counts or overlook quota/subvolume constraints on a shared device.

For every affected pool `p`, admit a new grant only when, under the shared database gate:

```text
sum(full live physical grants on p) + requested new growth envelope on p
    + operational free-space floor on p <= current available bytes on p
```

All quantities are nonnegative, bounded integers. Check every pool atomically; do not leave partial grants if one pool refuses. Sample availability through the validated pool view during the serialized decision, not from the historical P0 snapshot. Existing receipt-v1 budgets remain independently enforced; their byte values are not added again as physical grants.

Already materialized bytes reduce actual available space AND their full growth envelope remains charged while it can authorize writes. This is intentionally conservative. Do not subtract directory sizes or decrement grants per write: database commits and filesystem allocation are not one atomic transaction. Keep new-grant admission distinct from use of an existing grant; a phase transition that stays inside its grant must not demand the same full envelope a second time.

This controls cooperating application writers, not unrelated host activity or filesystem preallocation. Each bounded write still observes free-space/error handling and preserves recoverable state on exhaustion. Filesystem metadata, block rounding, CoW, quotas and inode behavior must be included in qualification and the operational floor. On Btrfs, no fixed inode pool is not a report of zero free inodes; bound file creation and qualify metadata capacity rather than inventing an inode measurement. No finite floor or sparse fixture proves hard capacity under arbitrary external allocation.

### Growth envelopes and lifecycle

The module owns grant acquisition, idempotent lookup, attempt binding and safe retirement. Callers supply explicit resource/attempt identity, pool, versioned limits and bounded growth; they do not edit ledger counters or infer reclamation. Reuse the short DB gate for grant changes and existing filesystem locks for actual I/O; specify one lock order before implementation and never hold the gate over decoding, hashing, copying, streaming or recursive deletion.

| Writer / phase | Required authority before growth | Retirement / retained bytes |
| --- | --- | --- |
| New receipt or compatible whole-body upload | Archive envelope plus an initial extraction/publication envelope, acquired atomically before upload admission | Upload replay reuses the same grant; finalize rename does not refund archive capacity or allocate a duplicate archive envelope |
| Initial validation and publication | Initial attempt envelope covers up to one expanded allowance of validated files plus one expanded allowance of prepared new-member copies | Transfer initial envelope ownership to the exact attempt atomically; no temporary gap or second charge for the same attempt |
| Revalidation or replacement attempt | New extraction/publication envelope before creating attempt output, unless safely reusing an unconsumed initial envelope | An old attempt retains its authority until proven unable to grow; a new lease does not revoke old filesystem writes |
| Export construction or retry | Manifest bound + member payload bound + ZIP64 headers/central directory/names + other bounded temporary growth on the export pool | No adoption of a previous partial ZIP; a new attempt needs its own grant while an old writer can still write |
| Published objects and retained artifacts | Covered while being constructed; after completion they remain in actual filesystem usage | Do not keep granting growth from a retired token; downloading existing bytes is not a new full-artifact allocation |
| Cleanup | Deletion does not create a negative grant; any material auxiliary output needs a bound | Failed deletion leaves retained bytes and recovery fences; success is not a guessed-byte refund |

Let `Z` be declared archive bytes, `E` the selected expanded-byte ceiling, and `O` the separately bounded auxiliary growth. The initial import payload envelope is `Z + 2E`, with `O` added on the appropriate pools. At the eventual limits this is 40 GiB of payload, not a universal physical ceiling. A further attempt needs up to `2E + O_attempt` in new authority while earlier writers remain capable of growth. Existing files already consume capacity; retries are not unlimited promises made by the initial receipt. If no new envelope fits, refuse or defer new growth without corrupting accepted data or silently reporting success.

Whole-body compatibility needs an ingress-specific check: without a validated declared archive size, reserve the configured received-byte ceiling, not an optimistic content-length estimate. Trace framework/multipart temporary spooling before the route handler as well as the eventual archive write. A grant obtained after spooling is too late. Any disk-backed ingress copy needs its own bounded envelope on its actual pool, or a separately reviewed transport path that proves it does not allocate there. Until this is demonstrated, whole-body coverage remains an implementation gate; do not claim it is covered by the chunked receipt design or silently remove that existing interface. The 40 GiB payload example does not cover additional ingress copies.

Derive `O` from actual writers before coding admission arithmetic: file/name counts, chunk/hash metadata, validation output, manifests, journals and any local synchronization scratch that competes with these pools. Database/WAL/log growth must be explicitly assigned an operational allowance or an independent capacity boundary; do not claim its safety from audio bytes. Do not assume that ZIP_STORED has zero overhead or that an export contains only the current import's 2,000 entries; it can contain a complete 50,000-member revision. Unbounded or unclassified writers block coverage rather than receive a zero estimate. Exact formulas and conservative numeric floors remain implementation/measurement gates, not invented constants in this design.

For each grant, persist a unique idempotency binding, pool and policy version, owning resource, phase/attempt identity and fencing generation, maximum authorized growth and retirement state. Bind the grant durably before output creation. A crash after grant commit but before writing can leak authority conservatively; recovery reconciles it under locks. Never create an output and hope to charge it afterward. Durable limits belong to the grant; a later configuration change must not silently enlarge, shrink or reinterpret outstanding authority.

A grant can retire only after exclusive ownership proves all writers using it have stopped, combined with a durable fence preventing resumption. An expired queue lease, cancellation request, callback timeout or terminal status alone is insufficient. For a preview awaiting confirmation, keep future publication authority or require an explicit new grant before resuming; the initial-envelope design retains it. If ownership or writer termination cannot be proved, keep the charge and require reconciliation. A later retry must acquire fresh authority rather than revive a retired token.

Retirement removes only a future-write promise. Published files, archives, failed attempts and active-download artifacts remain reflected in filesystem usage until actually removed. Preserve existing cleanup eligibility and locks; do not delay a successful publication result merely because subsequent cleanup fails. Do not reinterpret receipt-v1 release timing as proof that a physical grant is retired.

### Additive migration and recovery plan — not an executable procedure

The selected cross-writer design needs durable state beyond receipt v1: exports, multiple attempts and pool bindings cannot be represented by one receipt's original promise. Plan a separate ledger schema/version marker; preserve existing tables and v1 receipt values. Exact DDL, migration CLI and implementation paths are intentionally not introduced here.

1. **Prepare offline:** implement and test the additive schema, dry-run inventory, version checks, idempotency and grants against isolated SQLite and the intended PostgreSQL behavior. Review lock ordering and old/new writer compatibility. No startup or HTTP migration; no ambient database fallback.
2. **Plan operator-approved quiescence:** identify all API, import, export, synchronization and cleanup writers sharing the pools. Stop new admissions and drain work or supervise writer shutdown under a separately authorized maintenance plan. Stopping jobs or services is not authorized by this document. Lease expiry alone is not quiescence; open downloads can retain deletion locks.
3. **Back up and inventory:** with explicit database/filesystem authorization, capture recoverable DB state, pool mappings, policy versions, receipts, attempts, journals and artifacts without publishing private paths. Verify backup restoration separately. Dry-run does not alter data, grants, jobs or receipt counters.
4. **Classify existing work:** completed/retained data consumes measured free capacity without automatic new growth authority. Active, partial, legacy whole-body or recoverable work is not automatically covered by v1 promises. For future growth, explicitly create conservative grants based on verified state and ceilings; ambiguous work stays blocked for reconciliation, never assumed to use zero bytes. Do not parse an old `reserved_bytes` value as a new physical grant or cancel/delete work to make the totals fit.
5. **Apply and reconcile explicitly:** additive migration must verify shape/version and be repeatable without duplicating grants. Obtain all required pool authority or report insufficient capacity with work preserved. Failures leave a maintenance fence; do not resume old unbudgeted writers or partially enable new ones. Prepared grants are not permission to start workers.
6. **Cut over together:** only compatible API/workers/cleaners may write under the new ledger. Check policy version, DB identity and pool mapping before admitting growth. Old binaries must be kept out by the coordinated deployment/maintenance boundary; an additive marker cannot magically constrain code that never reads it. No mixed-writer rollout. Keep conservative limits until later P3–P6 proof.
7. **Recover without destructive rollback:** stop new growth, preserve ledger rows and publication/cleanup journals, and reconcile uncertain attempts under their locks. A leaked grant is safer than an unjustified refund. Retain additive tables and data on binary rollback; do not allow older writers to bypass the ledger until a separately reviewed safe compatibility/drain plan exists. Never drop the ledger, erase a fence or reset receipts merely to restore availability.

### Implementation acceptance and remaining gates

P2 is not closed by this design. Later implementation must use public-interface RED → GREEN tests with small synthetic state; no maximum-sized fixtures are required for arithmetic tests. Preserve prior command/option responses and v1 receipt replay, limits, dataset membership, content hashes and publication recovery.

| Case | Required observable evidence |
| --- | --- |
| Physical boundary and shared pools | Exact envelope fits; one byte above refuses without grants, artifacts or data changes; shared aliases count capacity once; separate pools cannot subsidize one another |
| Concurrent import/export/whole-body writers | Atomic grant admission prevents overcommit across all participating paths; independent job and receipt budgets still apply; retry/replay never duplicates grants |
| Initial attempt and repeated preview | Initial envelope transfers without a gap; each additional attempt is charged before output; a late callback after lease loss cannot cause an early refund |
| Crash and recovery | Kill points before/after grant commit, output creation, rename, DB publication and retirement preserve data and fences; replay does not republish or resurrect retired authority |
| Cleanup and downloads | Failed/delayed cleanup retains physical usage; downloads retain artifact protection; retirement is never presented as reclaimed bytes; publication success remains success |
| Existing state and migration | Dry-run unchanged hashes/rows, no implicit upgrade, explicit additive/idempotent rehearsal, incompatible/mixed policy refusal, recoverable v1/whole-body work retained |
| Auxiliary bounds and topology | ZIP64/manifest/file-count arithmetic, allocation/error handling, metadata/inode policy and supported root/lock mappings have explicit bounded evidence; unknown coverage fails closed |

Candidate code surfaces remain the receipt, chunk, whole-body route, execution, worker, cleanup and export modules already mapped, plus narrowly scoped new ledger/model/migration files derived before implementation. No blanket directory authorization is granted. Existing relevant regression modules and process runners must be inspected before fixing exact check commands; their historical results are not new evidence. Implementation of the shared persisted/concurrent contract will require independent verification; this passive design update received structural checks only, not a native approval or functional PASS.

Completed here: current-contract mapping, selected accounting model, ADR and migration/recovery plan. Pending: production implementation authorization, exact growth/overhead bounds and lock ordering, synthetic behavior/process tests, current pool/runtime qualification, operator-approved reconciliation, migration/cutover, and all P3–P6 operational evidence. No source changes, tests, migrations, services, imports, large fixtures or commits were performed for this design.
