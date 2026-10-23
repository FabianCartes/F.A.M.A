# Supervise one small P5 development case

Implementation only; the retained campaign must remain stopped. Branch: `plan/large-zip-limits`.
Delivery: local files, no commit or campaign execution. Tests: isolated Python CLI tests with synthetic runtime adapters.

## Specs

- **S1:** User authorized «crear ese runner y sus pruebas, **sin ejecutar la campaña**, manteniendo intactos el perfil, los límites y los datos P4» with «Autorizo».
- **S2:** User confirmed «la **CLI del runner**: comprobar su salida, código de retorno, rechazo de condiciones inseguras y parada de procesos propios mediante pruebas aisladas, sin Docker, PostgreSQL ni datos P4 reales» with «Confirmo».
- **S3:** Preserve the original constraint: «No inicies servicios, reinicialices ni reactives almacenamiento, generes fixtures grandes o cambies límites sin autorización específica.» The full-P4 dependency exception covers only the proposed small development case; it does not authorize execution or complete normal-session/non-import acceptance.

## Tasks

- **T1 [S1–S3] — inline, complete:** default plan, fixed retained target, refusal before effects; observed RED (missing script), GREEN (2 tests).
- **T2 [S1–S3] — inline, complete:** bounded supervision, one tiny import, preserved publications and explicit cleanup; observed RED for lifecycle, unrelated cleanup and symlink rejection; GREEN (8 isolated tests).
- **T3 [S1–S3] — inline, complete:** 11 isolated tests passed; independent shutdown recheck and native four-lens review completed with one validated correction. Risk: items 4 and 5. No commit or campaign execution authorized. See L9 for the exact reviewed candidate and passive post-review addendum.

## Usage and evidence boundaries

The canonical scope remains [P4 closure and P5 handoff, sections 36–38](../arquitectura/large-zip-limits-enablement-plan.md#36-authorized-p4-development-only-closure--2026-10-22).
The case-only dependency exception does not alter the historical P4 receipt.
The runner must never invoke root creation, initialization, storage activation,
firewall changes, builds, downloads or cloud synchronization.

### Safe plan (no campaign access)

From the repository root:

```bash
.venv/bin/python -B backend/scripts/run_p5_small_case.py
python -B -m unittest discover -s backend/tests -p test_p5_small_case_runner.py -v
```

The default command prints `plan_only` without inspecting Docker, PostgreSQL or
the retained filesystem. Python 3.14.8 was used for isolated tests; this does not
qualify a Python 3.12 image or the actual decoder/runtime.

### Future execution — not authorized or run here

Only after separate operational, fixture and narrow firewall authorization:

```bash
.venv/bin/python -B backend/scripts/run_p5_small_case.py --execute --firewall-confirmed --cleanup
```

This is not a command to run as part of preparing the runner. The firewall flag
is an operator attestation, not privileged inspection, permission or rule creation.
The CLI uses only the fixed retained campaign and local Docker Unix socket. It
refuses an active frontend/DB, changed profile, wrong SSD, insufficient headroom,
symlinked roots, missing PostgreSQL 16 data and existing `logs/p5-small-01` output.
It starts existing container IDs, never Compose creation or an image build/pull.

On a later authorized run, `ready_for_one_ui_import` gives the private fixture
path. Open the existing UI at `http://127.0.0.1:3002`, choose that ZIP, create a
**new** dataset and complete exactly one import. No second import or recovery
experiment is permitted in this window. The runner never fabricates a development
peer or substitutes a direct service call for the existing UI path.

The fixture has two different PCM16 mono 16 kHz one-second WAVs, 32,044 bytes each,
in `class-a/audio.wav` and `class-b/audio.wav`. The stored ZIP is exactly 64,330
bytes. Expected publication: two members/classes, revision 1 and 64,088 bytes.
Small-class warnings are not model-quality evidence. Existing 64 MiB received /
256 MiB expanded caps and concurrency 1 remain; no target-size claim is made.

The observation window reserves two minutes out of the nominal 900-second budget
for shutdown/checks. Commands have bounded waits; Python scheduling, uninterruptible
OS I/O and external Docker behavior are not a hard real-time guarantee. During
observation it refuses a 20 GiB floor breach, more than 2 GiB global free-space
loss, fewer than 10,000 available inodes, changed profile, exited children or logs
above 16 MiB each. Global free-space loss includes competing writers; it is not
per-case physical accounting. This runner does not measure full per-phase RSS,
CPU or database work and cannot close P5 scale acceptance.

The supervisor compares both historical publications and their file hashes before
and after. It stops frontend and host writers before explicit cleanup, and calls
the existing public cleanup only for a single terminal case with the expected
inventory (one cleanup intent, two live grants, no active/recoverable work).
Failure never automatically cleans/cancels, deletes publications or releases grants.
All case artifacts/logs remain under `logs/p5-small-01`; `result.json` is private
operational evidence, not a native-review approval. Stopping does not remove the
operator's firewall rule; the operator owns its separately authorized removal.

Exit codes: `0` verified and cleaned, `1` failed or unavailable proof, `2` invalid
CLI options, `3` publication verified but cleanup pending. No automatic retry:
preserve the case directory and diagnose before another separately authorized run.

## Log

- **L1:** Original request: «Retoma la preparación de P5 desde la sección 38 de docs/arquitectura/large-zip-limits-enablement-plan.md. Reconcilia en solo lectura el cierre acotado de P4, Git, la campaña retenida y los recursos. Propón el primer caso aislado y presenta la decisión pendiente sobre la dependencia de P4 completo. No inicies servicios, reinicialices ni reactives almacenamiento, generes fixtures grandes o cambies límites sin autorización específica.»
- **L2:** User confirmed the case-only development exception, then authorized runner creation and confirmed the CLI test seam. Service/DB/fixture/firewall execution remains unauthorized.
- **L3:** Existing `p4_host.prepare` rejects populated targets. Reuse `prepare_p4_runtime.check_p4`, `runtime_import_service`, the local-only worker and its explicit cleanup; do not repeat preparation. Prior transient supervisor source is unavailable. Preserve all pre-existing staged/untracked changes.
- **L4:** Route: inline implementation; no parallel independent behavior units or writer trigger. Isolated verifier required for subprocess ordering and retained-service lifecycle. Test scratch stays outside the workspace. No live differential is applicable: this adds a new standalone CLI without changing existing commands.
- **L5:** Isolated suite: `python -B -m unittest discover -s backend/tests -p test_p5_small_case_runner.py -v`: 8 tests passed on Python 3.14.8. Temporary files/processes only; no Docker/DB/campaign start. `git diff --check` passed. Independent verification pending.
- **L6:** Independent verification reproduced two shutdown defects: SIGTERM during frontend stop skipped remaining stops, and one child's final wait timeout skipped escalation of the next group. Both were pinned by failing CLI/process-adapter regressions, corrected in one batch, and independently rechecked successfully. Final isolated suite: 10 tests passed; no live acceptance claimed.
- **L7:** Native assessment returned high risk with `unassessable` because the dirty worktree contains undeclared untracked files. No approval claimed; scoped inventory/consent remains pending. Earlier P4 artifacts and staged files remain unrelated retained work.
- **L8:** Native STATUS requested intended-untracked selection and projected all pre-existing tracked changes as well. No START was invoked: this is not a runner-only candidate. A separately authorized isolated Git review copy is needed to avoid mixing the retained P4 changes. Final read-only Docker inspection: both dedicated containers exited/PID 0. Parent reran the two shutdown regressions successfully and removed the verifier's two external scratch directories. Engram summary retained; full document mirror resynchronization pending.
- **L9 (passive post-review addendum):** User authorized the isolated copy, then selected native candidate review. Review root `/home/kevin/Work/fama-p5-runner-review`, base tree `c0d176e15e5352dbdbbf4935578de5dbaf3176d9`, lineage `review-3b0e950efb7ef570`. Four lenses and one refuter identified `R3-existing-evidence-write`: refusal could create a report in a historical case directory. One correction tracks exclusive directory ownership and adds the observed RED→GREEN regression. Final isolated suite: 11 passed; targeted validator accepted the correction. Exact acknowledgement confirmed `authority: burned` for target `sha256:4a0694dc79bbd49ced04f046a619cdf0cfbaf732861c355f1a82d45bbdb0a94b`. Corrected runner/tests and original four-file snapshot matched byte-for-byte on transfer to the original tree; the one focused regression passed there. This task/status addendum was written afterward and is not part of that reviewed snapshot. Non-blocking follow-up: add credential-safe diagnostic categories (`R2-lost-failure-reason`, `R4-lost-failure-diagnostics`), not raw exception output. Original index remains the two pre-existing files/233 lines; no commit or service start. Final dedicated frontend/DB inspect: exited/PID 0. P5 execution, full P4 acceptance and operational/image/scale proof remain unauthorized or pending.
