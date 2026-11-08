# Readable ZIP import history
Objective: latest ten imports labeled by original ZIP filename and creation date, without visible UUIDs. Branch: feat/local-mvp; delivery: feature-branch-chain; forecast ~250 authored lines.
Checks: public HTTP synthetic/in-memory/no-network history tests; frontend Vitest/types/scoped lint/build; preserve unrelated dirty work, no cloud/user-data writes/browser. Runtime API replacement needs explicit maintenance authorization.

## Specs
- S1 (from compacted request): «Cada importación anterior debe identificarse por el nombre del ZIP y la fecha, no por su UUID.»
- S2 (from compacted request): «Solo deben mostrarse las 10 importaciones más recientes.»

## Tasks
- T1 | S1-S2 | inline, one coherent metadata/order/UI change | done | RED/GREEN observed; default API pagination preserved. Commit pending T2.
- T2 | S1-S2 | inline checks and scoped commit | in_progress | checks passed; isolating staged deltas from unrelated dirty work. Commit pending.
- T3 | S1-S2 | parent runtime deployment | blocked | waits for explicit owner maintenance authorization to replace API and apply paired frontend; no DB migration/consumer change/cloud upload.

## Log
- L1 (request available in compaction; original human wording not retained): «Mejorar la sección de importaciones anteriores: mostrar el nombre del archivo ZIP junto con la fecha, en lugar del UUID, y limitar la lista a las últimas 10 importaciones.»
- L2 (exploration): mw792xq7-1z-mj1x + mw7940sw-20-sem2. GET imports uses owner-filtered default ID-ascending cursor pagination, not newest-first. Add opt-in latest mode capped at10 without changing default/cursor contract. Filename source is ImportReceipt.name (one-to-one import_id); created_at already stored. Missing metadata uses neutral labels, never invent ZIPname fromdataset name. UUID retained internally for recover action. No schema migration/newcloudaction, no data edits; frontend previous instructions/record/hover and shared manual edits preserved. Do not claim all historical rows have receipt names or every import originated fromZIP.
- L3 (verification): Backend meaningful RED was wrong ID ordering/count; first fixture attempts hit active-cap429 and unregistered receipt table, corrected synthetic fixture only. Backend job38:29/29 PASS isolated Python3.14/SQLite/no network/protected paths unchanged. Frontend new public UI test RED missing readable bounded history; job36:44 failures in old labels/mock query dispatch, job37:5remaining fixture failures, corrected only synthetic metadata/URL dispatch, no assertion removal; job39:535/535 PASS, types/scoped eslint/webpack build/diff check PASS. S1-S2:ZIP name+local creation date, neutral missingmetadata,10max, no visible UUID in history, recoveryopaqueIDsretained; backend ownerbeforelimit/latestdate/tie stable/defaultcursor preserved. No browser per user instruction, no real cloud/data/runtime checks.
- L4 (review): Native ASSESS unavailable: untracked files require explicit declaration; no reviewDue/START offered, no native approval. Writer-only verification plan; no named high-risk item. Risk: none (optional metadata/order parameter, legacy cursor default and private transfer source history unchanged; no migration/security/writes/worker changes). API+frontend runtime deployment remains blocked on maintenance authorization.
