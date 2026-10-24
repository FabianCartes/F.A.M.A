# Backfill import metadata before the normalized runtime cutover

The explicit backfill adds normalized metadata and verifies equivalence while retaining `ImportedDataset.files` and `DatasetImport.preview` unchanged. **Running the migration does not activate a new application version or increase ZIP limits.** The T1b working-tree runtime reads/writes normalized records and must be deployed together with its paginated client. Implementation checks and pending acceptance are recorded in the [tracking document](../arquitectura/large-zip-gcs.md); no live migration or deployment is authorized by these instructions.

## Safe inspection

From `backend/`, inspect help or the no-connection dry run:

```bash
python -m scripts.migrate_dataset_import_metadata --help
python -m scripts.migrate_dataset_import_metadata
```

The dry run does not connect to a database or estimate its contents. No `.env` or default database is loaded by this entrypoint. Applying requires an explicitly supplied `DATABASE_URL`, `--apply` and `--writers-stopped`; these flags are acknowledgements, not proof that an operator actually stopped services. The supported dialects are SQLite and PostgreSQL. Do not run the apply command against real data without separate authorization.

## Authorized maintenance procedure

1. Obtain authorization for the exact target database and maintenance operation. Back it up and test restoration using the deployment's established procedure. Do not print credentials or row contents in reports.
2. Stop **every** import writer, including HTTP mutation endpoints and any worker or alternate process. Keep them stopped through verification and the separately implemented cutover. Application `mutation.lock` alone does not cover this migration.
3. Supply the selected database URL explicitly to the process. From `backend/`, run `python -m scripts.migrate_dataset_import_metadata --apply --writers-stopped`. No normal service engine, dotenv fallback or GCS client is used. The original two import tables must already exist; this is not their creation migration.
4. Inspect the bounded count report and `verified` result. The transaction locks source tables against writers, inserts normalized records and summaries, reads every target row back, checks counts/provenance/hash metadata, and records the original-source digest. A failure leaves original rows intact; additive tables may exist after a failed PostgreSQL/SQLite DDL attempt, but no partial backfill is deliberately activated.
5. Rerunning verifies source and target again. If either changed, preserve both versions; do not delete the checkpoint, overwrite targets, or discard JSON to force success. Diagnose with an authorized operator. Missing provenance, inconsistent counts/classes/fingerprints, invalid paths, canonical path collisions and altered normalized data are rejection conditions.
6. Keep writers stopped while installing the coordinated T1b backend and frontend. The new runtime refuses legacy rows without normalized summaries rather than reading full JSON as a fallback. Verify the backfill again immediately before cutover; if legacy writes resumed, an old checkpoint is not current evidence. Run the agreed synthetic/staging acceptance before any separately authorized live reopening. This repository change does not perform that deployment.
7. After normalized runtime writes begin, do not rerun the legacy backfill as a repair operation: retained JSON is a historical snapshot, not a mirror of new memberships or progress. A replay can reject the changed source/target; preserve both. A downgrade to legacy readers would hide new records and requires a separately designed and authorized recovery, not deletion of normalized data.

## Recovery and limits

- Before reader cutover, rollback means continuing with the unchanged legacy application and its original JSON. Do not drop additive tables during normal recovery; preserve them as diagnostic evidence. No destructive recovery command is supplied.
- Physical WAV bytes are not read, rewritten or rehashed here. Hash verification means source/target metadata equivalence and collection-fingerprint verification, not a new integrity check of audio or cloud storage.
- Historical cloud status remains in original JSON. New generation-bound verification is `unverified`, with no invented object key/generation. Snapshot revision does not claim the original revision that added each member.
- One retained legacy row still contains its complete JSON array. The offline backfill is not a benchmark or a promise of bounded memory at 50,000 members. T1b defers those ORM columns with read guards and queries summaries/pages instead; validation still creates a bounded-by-current-limits in-memory result. Large validation and worker isolation belong to later cuts.
- A SQLite synthetic test does not certify production PostgreSQL locking, disk capacity, migrations on real data or deployment.

## Coordinated HTTP and panel contract

All routes below retain the existing import authentication and ownership checks. There is no complete-array compatibility endpoint.

| Route under `/api/ingestion/imports` | Contents |
| --- | --- |
| `GET /{job_id}` | Scalar preview summary, at most five sample issues and detail links; no file/class/issue/progress arrays in `preview` |
| `GET /` | A page of compact job records |
| `GET /datasets` | A page of dataset summaries; `class_count` replaces the full class list |
| `GET /{job_id}/files` | Candidate file page, including stable ID and canonical `relative_path` |
| `GET /{job_id}/classes` | Class page |
| `GET /{job_id}/issues` | Issue page, with severity and action |
| `GET /datasets/{dataset_id}/files` | Published member page |

Collection responses retain their named key (`files`, `classes`, `issues`, `imports` or `datasets`) and add `total`, `next_cursor` and `snapshot`. Follow `next_cursor` through the `cursor` query parameter. Review cursors bind the collection and preview token; dataset cursors bind the dataset and revision. A changed snapshot returns 409; discard its pages and start again. Invalid cursors or sizes return 422. Catalog/history use ID keyset order over the current authorized collection, not an immutable historical snapshot.

`limit` defaults to 50 and cannot exceed 200. `FAMA_IMPORT_PAGE_SIZE` and `FAMA_IMPORT_PAGE_MAX` can lower/configure the defaults within that hard ceiling. These are control values, not scale benchmarks. The panel replaces each visible page rather than appending all members, and keeps confirmation bound to the original preview token/root. Canonical path collisions against published members receive a deterministic hash-based suffix visible in the file page before confirmation; original paths remain recorded.

Sync progress is stored in normalized file/member rows and a scalar continuation, not a full `sync_files` JSON map. The existing explicit sync action and recovery remain; bounded worker batches and complete immutable manifests are still later cuts. A per-object result is not evidence of a complete exported revision.

## Reproduce synthetic checks

Use the validated interpreter and isolated runner described in [training integration](integracion-flujo-entrenamiento.md#reproducir-comprobaciones-aisladas):

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHON_DOTENV_DISABLED=1 DATABASE_URL=sqlite:// \
CUDA_VISIBLE_DEVICES='' PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
../.venv/bin/python tests/run_isolated_training_checks.py \
  tests/test_dataset_import_metadata_migration.py -q
```

Run from `backend/`. Tests use synthetic data and in-memory SQLite only. Results and pending checks are recorded in the implementation log, not inferred from this procedure.
