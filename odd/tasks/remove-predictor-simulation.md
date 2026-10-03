# Remove predictor simulation

## Intent
Remove fabricated production predictions. No demo mode. Missing/corrupt/incompatible weights raise ModelWeightsError (API 503); unexpected runtime errors remain errors (API 500). Preserve legitimate silence/no-signal outcomes, without masking unavailable required models. Successful response and persistence contracts remain stable.

## Authorization and constraints
Implementation and dedicated branch authorized by user. Branch: fix/remove-predictor-simulation, based on clean dev at c6a81da. User explicitly authorized staging and local work-unit commits through authorize_local_work_unit_commits choice during closure/RDD request. No push/PR/merge authorized. Local commit gate resolved; functional full-suite gate remains open. Single writer. Test first through public predictor.predict and POST /api/predict seams. RDD mode observed on (global). Five final committed source candidates approved and acknowledged independently, with evidence below.

## Scope
Predictor implementations, API inference contract and related existing tests; documentation alongside behavior. GCS upload reordering, auth/security, training behavior changes, downloads and demo mode excluded. User authorized strict inference decoding after explanation: corrupt audio must not become synthetic silence; preserve tolerant training default. Narrow typed malformed-input mapping to API400 is proposed scope; unexpected/internal decode failures stay500. No model deserialization for inventory; tests may load controlled trusted local fixtures only.

## Tasks
- [x] T1: Close production simulation inventory, test runners and checkpoint metadata availability; no source writes. Route: delegated explore, evidence-budget trigger. Check: path/line map, narrow edit surfaces, commands, real-artifact limitations.
- [x] T2 (behavior/checks complete; commit33b8345; final native RDD acknowledged): Remove engine fabricated outcomes with vertical RED/GREEN regressions. Route: delegated worker, multi-file trigger. Check: missing/partial/corrupt/incompatible weights, inference failure and success/silence as applicable through public interface.
- [x] T3 (bundle implemented, committed b5c0787 and native RDD acknowledged): Remove bundle fabricated outcomes and remaining confirmed production simulation. Route: delegated worker. Check: public regressions and supported load compatibility; no silent partial loading presented as valid inference.
- [x] T6 (functional checks green; commit1f6354b plus strict predictor units; renewed native RDD acknowledged): Add opt-in strict decoding to production inference, preserving training default. Route: delegated explore then single worker, multi-file trigger. Check: corrupt existing audio raises explicit error, valid silence preserved, training tolerant default unchanged, unexpected decode errors not mislabeled input failures; HTTP mapping verified in T4.
- [x] T4 (functional checks green; commit78114e4 with README; native RDD acknowledged): Verify API 503/500 and no prediction persistence on failure; preserve success. Route: delegated worker. Check: TestClient public interface, existing response fields and validation.
- [x] T7 (verified tests-only correction; commit4d339c3; native RDD acknowledged): Correct two pre-existing training API mock expectations. User explicitly authorized tests-only correction. Route: delegated worker failed with assistant error and no test-file diff; parent applied small mechanical two-block edit inline after targeted read, verifier delegated. RED already observed in both current and baseline before source edit. Check: adjust expected existing kwargs/serialized model fields, focused module GREEN; no production training changes.
- [ ] T5 (in progress: integral validation resumed; current work-unit RDD already closed): Focused and full backend regression, native RDD for exact work-unit candidate, and real-artifact validation status. Route: delegated verify for suites/external checks. Record unavailable/skipped runtime checks. Do not mark complete if required checks fail.

## Acceptance
No confirmed production path fabricates class/confidence after load/forward errors. Correct exceptions reach API; failed predictions are not persisted. Existing successful inference and domain negative outcomes preserved. Tests and native review evidence recorded truthfully. Real artifacts and runtime availability reported separately; skipped tests are not proof.

## Forecast and rollback
Provisional five work units; authored diff forecast pending T1 (likely several predictor/test files plus main.py). Default delivery strategy ask-on-risk; discuss accumulated >~400 authored lines before delivery. No cosmetic reduction or omitted tests. Rollback must not silently reintroduce fabrication; disable unavailable model instead.

## Evidence
- Initial git status clean; branch dev at c6a81da.
- Created dedicated fix/remove-predictor-simulation branch.
- gentle-ai review mode status: on (global).
- T1 explorer confirmed fabricated engine/bundle results. SuperEnsembleService uses a real AudioCNN fallback: removing real model fallback/partial ensemble policy is outside fabrication scope, so preserve it unless proven fabricated.
- Parent metadata inventory found local weights under backend/checkpoints (including ignored bundles); presence/size is not compatibility or inference proof. Root .venv exists; runner must be checked by worker. No tests or model loads yet.
- Forecast T2: ~120-220 authored lines in engine and tests; later units pending actual inventory. Commit evidence: pending explicit authorization.
- First T2 writer returned partial with no files changed, no RED/GREEN: initial ../.venv/bin/python invocation used repository root instead of backend. Correct backend invocation imported app successfully, but tests were not run.
- User resumed after cancelling to change worker model. Verifier resolved cwd incident: absolute root .venv runner from backend imports app/pytest 9.1.1; engine baseline 8 passed, no skips, 1 PytestCacheWarning (cache permission denied). Existing real-checkpoint test executed. No environment repair.
- Earlier Engram updates failed with session-ended; on this resume mem_save succeeded and full observation1520 readback reconciled with task file. Mirror synchronization restored.

## T2 observed implementation evidence
- Changed engine_ensemble_predictor.py and test_engine_ensemble_predictor.py only: writer reports 188 insertions/79 deletions (including dedentation).
- Public RED/GREEN observed: missing audio 1 failed -> 9 passed; unavailable precedence 9 failed -> 18 passed; load/recovery 6 failed -> 27 passed; forward propagation 3 failed -> 30 passed; incomplete supplied ensemble 2 failed -> 32 passed; final triangulation 33 passed, zero skips. git diff --check passed.
- No fabricated engine fallback; atomic component loading; ModelWeightsError for weights, original runtime error propagation; model availability before silence/noise. Existing local real-weight test ran, synthetic tonal audio only.
- Native review lineage review-aae23813a435b3a8 created for exact engine/test candidate, risk medium, reliability lens. Tracking document excluded from frozen source candidate. One forecast acknowledged.
- Capture blocked before reviewer run: reviewer-config-invalid, no model configured for review-reliability in agent model routing. Fresh bound STATUS reoffers slot; no verdict/acknowledgement produced. Do not replay until configuration resolved.
- ASSESS nativeReviewOutcome unavailable returned unassessable (untracked scope declaration); high-risk fallback requires separate independent verifier. Independent verifier PASS: focused module 33 passed in 6.80s, no skips; git diff --check passed; structural readback found no functional blocker. Known cache permission warning only. Local real-weight path exercised with synthetic tonal audio. RDD remains pending, not approved.

## RDD configuration and closure
- User authorized GPT-6 Luna high for review-reliability. Created /home/kevin/.pi/gentle-ai/models.json with model openai/gpt-6-luna and thinking high; JSON readback valid. Manual agent untouched.
- Fresh bound capture succeeded in this live session after routing edit: native state approved. Exact acknowledgement succeeded for review-aae23813a435b3a8; authority burned, consumed revision sha256:af9bfc247d2235313232b18c03030720772bf74003cf6bab7b4d7268f195c7ed. No source corrections needed. Review not publication/commit authorization.

## T3 observed evidence and scope gate
- Bundle writer changed only bundle_predictor.py and test_bundle_predictor.py: 223 insertions/86 deletions (309 authored diff lines). Engine files preserved.
- RED/GREEN missing audio: 1 failed -> 4 passed/1 skipped; unavailable weights precedence: 18 failed -> 22 passed/1 skipped; forward propagation: 3 failed -> 25 passed/1 skipped; recovery/preprocessing/real fixture triangulation: 32 passed/zero skips; missing legacy BatchNorm buffer with plain dict: 3 failed -> complete-key validation 35 passed.
- Focused final 35 passed; combined engine/bundle 68 passed, zero skips. git diff --check passed. Known pytest cache permission warning. Existing resnet34d bundle now tested after correcting cwd-dependent fixture path; other production bundles unverified.
- Bundle now atomically validates exact state keys and strict tensor compatibility; load errors ModelWeightsError, missing audio FileNotFoundError, forward exceptions unchanged; no .88 mock_fallback.
- Parent spot check confirmed shared training/pipelines/dataset.py load_and_resample catches decode exceptions and returns zeros. Invalid existing audio may appear as legitimate silence. Shared loader also used by training; modifying its default behavior is outside authorized source surfaces. Need user scope decision for strict inference-only decode behavior, preserving training behavior.
- Current accumulated tracked diff 411 insertions/165 deletions = 576 authored lines; delivery slicing decision required before commits/publication. No tests trimmed for size.
- Native inspect ready but current uncommitted projection includes engine plus bundle. No T3 START performed: need reviewable work-unit separation rather than claim bundle-only review of accumulated diff. T2 approved identity remains unchanged.

## T6 observed evidence
- Shared loader now has keyword-only strict=False default and MalformedAudioError. Engine/bundle opt in; training/default/additive mixing retain tolerant zeros. Secondary bundle TTA decode errors propagate rather than reuse waveform.
- Installed sources: librosa1.0.0 directly SoundFile0.14.0, no audioread available. Only LibsndfileError codes1/3/4 (unrecognized/malformed/unsupported encoding) wrap with original cause. Code2/system and permission/runtime/unknown errors unchanged. Alternative dependency versions unverified.
- RED/GREEN public corrupt fixtures: loader missing contract ImportError -> 1 passed; engine and bundle DID NOT RAISE -> each1 passed; secondary TTA swallowed exceptions ->3 passed with identity. Final loader18 passed, combined loader/engine/bundle91 passed, zero skips; diff check passed. Existing trusted local real-weight cases green. Codes3/4 injected, not real codec corpus.
- Tracked accumulated diff565 insertions/169 deletions =734 lines (158 beyond T3). Prior engine approved identity no longer covers changed strict-decode engine file; renewed review required.
- Secondary raw TTA decoder errors remain explicit but not normalized MalformedAudioError: HTTP500 until a separately verified narrow normalization; no claim all decoder paths map400. T4 maps typed error only and verifies no persistence.

## T4 observed evidence
- Changed main.py and test_api_predictions.py only, scoped150 insertions/1 deletion. Typed MalformedAudioError maps safe400 without temp path; existing weights503/runtime500, GCS upload ordering and cleanup unchanged.
- Actual corrupt upload through production strict loader RED expected400/got500 -> minimal typed catch GREEN14 passed. Final API21 passed. Combined loader/engine/bundle/API112 passed, zero skips; diff check passed.
- Regressions prove error responses contain detail only, no DB add/commit/refresh; temp files removed; successful valid decode response/persistence intact. PermissionError/OSError/RuntimeError/ValueError remain500.
- Some malformed RIFF input and secondary raw decoder errors remain500 (unnormalized), not synthetic silence. Generic500 raw error text pre-existing; broad error sanitization not implemented. API strict-loader success uses stub classification after actual decode; existing model/audio tests separately ran.
- Approximate accumulated authored lines885 after T4, verify exact stat before delivery. Work-unit review/commit separation still needed; no publication authorized.

## T5 independent verification (not closed)
- Focused112 passed, known cache warning,14.01s. Full backend361 passed/5 skipped/2 failed,55.14s. Failures tests/test_api_training.py::test_training_lifecycle_triad and ::test_training_lifecycle_dynamic_ensemble: mock expected arguments omit early_stopping=True and per-model learning_rate/batch_size.
- Baseline verifier reproduced the SAME two mock assertions on committed c6a81da5a7f5a9e091b8e2dbcd6a560f16279148 in temporary tracked-file archive:2 failed, as in current worktree. Pre-existing proven; baseline had no local checkpoints, but both reached assertions. Fix would update two expectations for existing early_stopping=True and dynamic learning_rate=None/batch_size=None, no production training changes. User explicitly authorized this tests-only repair on resume.
- Baseline temp /tmp/fama-baseline-c6a81da.0ma1ZR remains because cleanup was blocked; no retry or destructive cleanup performed. Five full-suite skip reasons still not individually identified; do not infer from potential code skips.
- Independent readback supports targeted no-fabrication, strict training compatibility, safe typed400 and failed-prediction persistence prevention. Exact stat8 tracked files715 additions/170 deletions=885 authored lines. Native final content not approved.
- User-facing backend docs still needed; existing backend/README.md locator found. Runtime target container/GPU still unverified; five skip reasons pending baseline verifier.

## T7 and latest full-suite evidence
- Minimal tests-only edit adds early_stopping=True to both expected calls and None learning_rate/batch_size to dynamic model dicts; strict assertions preserved. Independent verifier targeted2 passed/module9 passed; diff check passed. RED previously reproduced current and HEAD. Production training unchanged by this unit; other authorized inference production changes remain present.
- Latest full backend -q -rs:358 passed/5 failed/5 skipped. New failures: two inference labels unexpected in test_api_predict.py; three DB model registry/activation tests PostgreSQL connection refused localhost5432. They passed earlier suite run; no causality assumptions. Read-only incident continuation comparing isolated inference fixtures/registry globals and DB requirements dispatched; no services repaired.
- Exact skips: tests/test_panns_model.py:53 pretrained checkpoint absent; tests/test_trained_predictor.py:42,72,117,129 named fama_efficientnet_b0_1790539191_efficientnet_b0_best.pt absent. No GPU/container proof. Known cache warnings.

## Incident diagnosis
Both inference checks fail isolated: actual power_steering versus bird SPECIES_CLASSES, and no oil_serpentine belt versus Chucao. Test fixture resets default registry every run; no evidence supporting suite-order pollution. Selected predictor model_id was not captured because assertions stop at label. Loaded local ensemble artifacts appear in logs, but no proven regression/artifact causality. Three tests in test_registry_db_sync.py directly use SessionLocal and require live PostgreSQL; refused localhost5432, no DB state known. No environment/expectation repair authorized.

- [x] T8 (structurally verified; included with HTTP commit78114e4; native RDD acknowledged): Document inference fail-closed behavior and verification prerequisites in backend/README.md. Independent verifier confirmed HTTP error mappings, decode modes, persistence/cleanup and GCS nonrollback limit against code; git diff --check clean. Passive documentation: no meaningful RED, no functional tests required for this unit. No commit authorization.

## Final work-unit closure plan
- [x] T9 (five committed candidates approved/acknowledged; final functional113 passed): Commit and perform native RDD on five exact ordered committed ranges, with fresh bindings and acknowledgement per candidate. Loader99 lines; engine284; bundle351; HTTP+README171; training expectations6. Counts from actual git diff --numstat, total911. No accumulated branch review. Existing approved engine lineage does not cover final strict decoder changes. Commit identities, validation and authority burns recorded below after observation.
- Planned commits: fix(inference): add opt-in strict audio decoding; fix(inference): fail closed in engine predictor; fix(inference): fail closed in bundle predictor; fix(api): preserve safe inference failure contracts; test(training): align lifecycle mock expectations.
- Code/tests stay paired; user-visible docs accompany API contract after both predictors. Controlled local functional evidence112 focused plus training9 already observed; checks per candidate will report working-tree vs immutable candidate limitations honestly.

## Final native review evidence
| Unit | Commit | Lines | Lineage | Result |
| --- | --- | --- | --- | --- |
| Strict decoder | 1f6354b481efb9b1ff12800cfaddd0cc9fb34435 | 99 | review-efb173420dafa44e | approved; exact acknowledgement burned authority; consumed f377b90c3c7645ad03bbb976cb106d12dac0d1b4908a9d683861771f64083f0a |
| Engine fail closed | 33b8345caf5afe6e84c90f385c9c6aa3819f97cf | 284 Git / 300 native frozen | review-f8e88cb200955d12 | approved; exact acknowledgement burned authority; consumed 5c262538469bf66c7a0e8b58eda2549678586fcc770c8dc2940acf0f52858d57 |
| Bundle fail closed | b5c07871ca625351de8f22b8248bcd9b0f8e4b17 | 351 Git / 363 native frozen | review-9a932576c0299b05 | approved; exact acknowledgement burned authority; consumed 8f97fd3ed13d650275d28925dbbf6dd3d27071be8877b139c02dbea2c7da1252 |
| HTTP contract and README | 78114e43cba7eac90658bdc2b75d7dc4d26effe5 | 171 | review-9fe2d0e8a20ffe2d | approved; exact acknowledgement burned authority; consumed 6354e80c96ece999a7d907735362ae1224db29975cefbb90afcf7a170fadaf94 |
| Training expectations | 4d339c3a11137bafc6be310b836b5204cecf33ae | 6 | review-bb15b2ea4837c2db | approved; exact acknowledgement burned authority; consumed e21cfaa816b8411473e27fa6396e84fef43d3fc5bf8228a1eeedb90c6067739f |
- Decoder advisory R3-001 reliability WARNING at backend/training/pipelines/dataset.py:34-40 is nonblocking informational; no correction opened and receipt stands. Separate follow-up, not a reason to replay this review.
- Committed-only base c6a81da5a7f5a9e091b8e2dbcd6a560f16279148; source candidate excludes odd tracking file and other unstaged feature units.

## Closure verification and limits
- Final command from backend: /home/kevin/Work/fama/.venv/bin/python -m pytest -q tests/test_generic_audio_dataset.py tests/test_engine_ensemble_predictor.py tests/test_bundle_predictor.py tests/test_api_predictions.py tests/test_api_training.py =>113 passed; cache permission warning unchanged.
- This command excludes tests/test_api_predict.py: verifier collect-only confirmed8 cases. Prior focused112 included that module;112-8+9training=113. No source/test removal or unexplained count loss. Its two failures remain visible in full-suite evidence, not covered by the113-pass claim.
- Final code HEAD4d339c3a11137bafc6be310b836b5204cecf33ae: git diff --check and git diff --exit-code passed; index empty, only odd tracking untracked before archive commit. Five local source units include no weights/environment paths. Immutable candidate review and working-tree functional evidence recorded separately.
- Full suite retained prior observed358 passed/5 failed/5 skipped, not rerun during closure. PostgreSQL unavailable3; isolated inference bird-vs-engine label mismatches2 remain causally unresolved. Five checkpoint skips and container/GPU/representative corpus limitations remain.
- Local RDD/source closure complete; overall integration acceptance NOT complete. No push, PR or merge performed. Separate tracking-only documentation commit archives this ledger and is not part of the five source review candidates.

## Integral validation resume
- Read-only reproduction: API prediction module 6 passed/2 failed; traced both failing responses to `fama_efficientnet_b0_1790642923_efficientnet_b0_best`. Trusted local weights-only metadata contains 13 automotive classes matching observed labels. With PostgreSQL unavailable, newest eligible trained checkpoint becomes default. Registry and affected tests are unchanged against c6a81da; no regression established in those files.
- User explicitly selected separating deterministic HTTP contract tests from real model quality validation; preserve Chucao/confidence requirement separately with explicit artifacts rather than claim it passed through a controlled predictor.
- User explicitly authorized an isolated disposable PostgreSQL container, unique name/port and no persistent volume, explicit DATABASE_URL, cleanup of only that container. Existing fama-db and real data must not be used or changed. One registry test commits model activation, so default database configuration is unsafe.
- [ ] T10 (functional verification and native RDD passed; local commit closure pending): Isolate API predictor selection for deterministic endpoint contract tests; preserve explicit real checkpoint/audio quality validation separately. Allowed source surface: backend/tests/test_api_predict.py only. Verify focused tests and document real-quality limitations; no production behavior changes.
- [ ] T11 (in progress: test-only seeded fixtures authorized; diagnosis complete): Execute three registry DB tests and complete backend suite with disposable PostgreSQL; capture skips and failures, then remove only disposable container.
- [ ] T12 (pending): Obtain explicit acceptance or resolution of missing checkpoint, GPU/container and representative corpus limits; R3-001 remains separate.

## T10 implementation evidence (not yet independently closed)
- Single writer changed only backend/tests/test_api_predict.py; controlled registry restoration and no-lifespan HTTP fixtures separate mock contract proof from real Chucao >=0.95 quality validation. Mock telemetry explicitly is_mock=True; successful persistence and 503/no persistence assertions retained.
- Worker focused command from backend, absolute venv, no bytecode/cache provider: 8 passed/1 skipped twice; git diff --check passed. Existing two failures were the observed RED for this test-harness repair, not a new production behavior RED.
- New real-quality diagnostic skipped: FAMA_QUALITY_MODEL_ID, FAMA_QUALITY_CHECKPOINT and FAMA_QUALITY_AUDIO unset. Trusted paths and weights_only=True required; no claim of real model quality. Five prior checkpoint skips remain separate.
- Worker first check exposed import-time default DB create_all before guards; whether any default DB state changed is unknown. Final isolated module guards suppress create_all and telemetry loading; independent verifier must inspect suite collection-order safety.
- Independent verifier mut11sgp-6-7xwy running: confirm disposable PostgreSQL availability/identity before imports; focused API and three registry DB cases then entire backend suite, cleanup only owned container. No default DB tests authorized.

## Independent integral evidence
- Disposable local postgres:16-alpine, localhost:32768/database oddtest, explicit DATABASE_URL for each process; schema created before final checks. Existing fama-db not used by verifier. Owned container removed and absence confirmed; anonymous-volume cleanup proof requested separately.
- API contract module independently 8 passed/1 skipped. Full backend 360 passed/3 failed/6 skipped in 79.91s. Three registry cases fail both focused and full-suite despite reachable schema-created DB: active trained-model resolution, explicit DB registration, activation refreshing registry. Exact assertions/root causes under read-only investigation; no production regression or test correction inferred yet.
- Skips: one new real Chucao quality prerequisite skip; prior PANNs checkpoint skip and four named trained-checkpoint skips. GPU, inference container and representative corpus quality remain unverified; running PostgreSQL in Docker is not inference-container validation.
- New API test unit plus ledger native reviewed exact target 2ae5b5020d19c5749a33ab9a4a1af2b1906bdec3ab6b87aed37335b9a17fb601; medium229 lines reliability lens approved and exact acknowledgement burned review-cea7a416b07ea7b2 consumed a6185e60009a6e9e3ccb963cb5a4710954a497fe7fc86fa84271d84fefdf7c26. Existing source commit RDD not repeated.

## Registry diagnosis and continuation authorization
- All three registry failures stem from tests assuming an active seeded row/model ID 6 while disposable DB had schema only. Expected checkpoint1790539191 vs latest1790642923; explicit DB registration None; activation of absent ID6 reports success but registry remains unchanged. Relevant tests/registry/training paths match c6a81da; no regression established. Production success-without-target remains a separate follow-up, not part of this tests-only correction.
- User authorized fixtures with self-created model rows in backend/tests/test_registry_db_sync.py, strict assertions retained, no production changes; isolated disposable PostgreSQL for focused and full tests.
- User explicitly authorized local work-unit commits for continuation, no push/PR/merge.
- User authorized removing only run-owned anonymous volume54c17c69353b0eeb4752f1ebf512efa327f009a197babf24d086dd37fccd3994 after ownership/noattachments recheck. No prune/othervolume actions; future disposable storage must be explicitly ephemeral.
- Four trained-checkpoint skips need path investigation: filesystem diagnosis confirms expected1790539191 checkpoint exists. Do not label these weights absent conclusively until test locator checked.
- Latest ledger candidate cd206698 native reliability review approved/acknowledged, review-a3d95e137fe9582e consumed3976bb1810f107494907071372f7f0a1387e473a25727e12456dbd25d1ab6a0b.

## Next step
Commit verified T10; implement seeded isolated registry fixtures T11, verify and rerun full suite. Investigate trained checkpoint skip locators read-only, then explicit T12 disposition. T5 remains open. Publication remains a human decision.
