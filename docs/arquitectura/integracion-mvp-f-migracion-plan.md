# Integración MVP — etapa f: migración Alembic 0005 y tríada estándar combinada
Objetivo: dejar el esquema migrado (0001–0005) en paridad con el ORM vigente después de d/e, retirar los caminos de esquema propios de mvp y publicar la tríada estándar como un modelo combinado con revisión de pesos. Rama `mvp`, base `baf1f01`; delivery strategy `ask-on-risk`.
Verificación: APIs públicas y comprobaciones de esquema con SQLite en memoria y el runner aislado; PostgreSQL real solo si Kevin lo autoriza. Riesgo 1 (esquema persistido), 2 (autorización) y 5 (instalación/entorno). Commits locales en español como Kevin, sin coautorías. **Estado: planificada, no iniciada; se ejecuta en una sesión nueva.**

## Specs
- S1 — Plan original, etapa f: «Del compañero: patrón de esquema congelado (`migrations/schema_000N.py` y `versions/000N_*.py`), sin downgrade.» «Alcance (decisión 11): solo aditiva. No borra las tablas sin uso de la 0004 ni crea `dataset_storage_*`; tampoco agrega `imported_dataset.archived`.»
- S2 — Plan original, etapa f: «Se borra: `backend/scripts/migrate_*.py`, `grant_training_snapshot_updates.sql`, y los caminos `create_all` propios de mvp.» «También se actualiza: `HEAD` en `app/schema.py`, verificación de instalación, `permisos_tablas_pruebas.sql` y `permisos_tablas_oficial.sql`.»
- S3 — Plan original, etapa f: «Tests primero: paridad entre la 0005 y el ORM; subir desde 0004 conserva los datos; el script de permisos cubre las tablas nuevas; el downgrade falla de forma explícita.»
- S4 — Kevin, 2026-11-11: «Guardemoslos para la estapa f». Se incorporan los pendientes de [la tríada estándar](integracion-mvp-triada-estandar-plan.md): predecir con los tres modelos combinados, ajustar los pesos después de entrenar, y no recuperar las tríadas importadas existentes.
- S5 — Kevin: «Haz el plan para la etapa f, se debe realizar el traspaso para realizarla en una nueva sesion».
- S6 — Límites heredados: sin compatibilidad histórica y sin borrar datos ni tablas existentes (decisión 11, etapa e S7). No push, PR, despliegue, Docker ni operaciones con datos reales sin autorización explícita.

## Estado verificado al planificar (`baf1f01`)
- Migraciones: `0001_core`, `0002_access`, `0003_autonomy`, `0004_integration`; `app/schema.py` tiene `HEAD = "0004_integration"`. `0004` crea las tablas nuevas de `schema_0004` y siembra tres tablas de bootstrap; su downgrade lanza `RuntimeError`.
- Comparación ORM frente a `schema_0004` (ORM cargado con todos los `app.models`):
  - Solo en el ORM: `training_snapshot`, `training_snapshot_member` e `imported_model_source`.
  - Solo en `schema_0004`: `dataset_export`, `dataset_export_session`, `imported_dataset_revision` e `imported_dataset_revision_object`, retiradas del código en b; las tablas se conservan por la decisión 11.
  - Columna solo en el ORM: `imported_dataset.archived`.
- Consumidores de las tres tablas exclusivas del ORM: solo los módulos `imported_*`, `training_snapshots.py`, `scripts/migrate_imported_training_source.py`, `scripts/migrate_training_snapshots.py` y `scripts/prepare_zip_manual_database.py`. `main.py`, las rutas, `registry.py` y `training.py` no las usan. `local_prediction_audio.py` solo importa la función `_root_directory` de `training_snapshots.py`.
- **Hallazgo pendiente de confirmar:** `routes/dataset_imports.py` está montada en POSIX (`zip_router`) y usa `ImportedDataset.archived`, tanto en el archivado `DELETE /datasets/{id}` como en el filtro `archived=False` del listado. En una base migrada con 0001–0004 esa columna no existe, y el ORM la incluye en cada consulta de `ImportedDataset`. Hay que confirmarlo con una prueba RED sobre el esquema congelado.
- Consumidores fijos de `0004_integration`: `app/schema.py`, `app/installation.py` (dos usos de `schema_0004`), `app/history_transfer.py`, `scripts/permisos_tablas_oficial.sql`, y las pruebas `test_schema_migrations.py`, `test_installation_wizard.py`, `test_database_backup.py`, `test_official_schema_preparation.py`, `test_permisos_tablas_pruebas.py` y `test_preparacion_roles_pruebas.py`.
- Caminos propios de mvp: 13 `scripts/migrate_*.py`, `scripts/grant_training_snapshot_updates.sql` y `Base.metadata.create_all` en `scripts/prepare_zip_manual_database.py:78`.

## Decisiones abiertas (resolver al iniciar f, una pregunta a la vez)
1. **Tablas de snapshots e importación de modelos.** El plan original pedía crearlas en 0005, pero d y e dejaron el flujo activo sin consumidores. Recomendado: no crearlas en 0005 y retirar del código sus modelos ORM y los servicios `imported_*`/`training_snapshots` que quedaron sin uso (código, no datos), moviendo antes `_root_directory` a un módulo neutral. Alternativa: crearlas en 0005 para conservar paridad con un ORM que nadie usa.
2. **`imported_dataset.archived`.** Recomendado: confirmar el hallazgo con RED y retirar del ORM la columna y su uso (archivado y filtro del listado privado), coherente con «tampoco agrega `imported_dataset.archived`». Alternativa: agregar la columna en 0005, lo que contradice la decisión 11 tal como está escrita.
3. **Persistencia de la composición de la tríada.** Recomendado: tabla nueva en 0005 (composición versionada: dataset, `partition_version`, `job_id`, tres `id_modelo` ordenados, pesos, autor, fecha y versión anterior) y ADR `0077` o el siguiente número libre. Alternativa: derivarla solo de los checkpoints, sin revisiones persistentes. Ver [plan de la tríada](integracion-mvp-triada-estandar-plan.md).
4. **Alcance de la verificación real.** Recomendado: SQLite en memoria y el runner aislado para la paridad y las pruebas, y PostgreSQL 16 en Docker (`fama_pruebas`) solo con autorización de Kevin, para comprobar el upgrade 0004→0005 y los permisos.

## Tasks (propuestas; rutas y forma se confirman tras las decisiones)
- T1 | S1,S3,S6 | inline | pending | RED de paridad: `schema_0005` congelado frente al ORM final, upgrade 0004→0005 que conserva filas sintéticas y downgrade que falla de forma explícita. Incluye la RED del hallazgo de `archived`.
- T2 | S1,S2,S6 | inline | pending | Esquema: `migrations/schema_0005.py` y `versions/0005_*.py` aditivos, `HEAD` en `app/schema.py`, `installation.py`, `history_transfer.py` y los consumidores de pruebas fijados a 0004. Risk: item 1.
- T3 | S2 | inline | pending | Retirar los `scripts/migrate_*.py`, `grant_training_snapshot_updates.sql` y el `create_all` de `prepare_zip_manual_database.py`, junto con sus pruebas exclusivas (sin borrar datos). Actualizar `permisos_tablas_pruebas.sql` y `permisos_tablas_oficial.sql` y sus pruebas. Risk: item 5.
- T4 | S4 | delegated si hay un motivo de escritor | pending | Tríada estándar: composición, predictor combinado, publicación `metadata_only` autorizada por asignación, revisión de pesos versionada, historial y feedback. Seguir el [plan de la tríada](integracion-mvp-triada-estandar-plan.md). Risk: items 1 y 2.
- T5 | S4 | inline | pending | Frontend: tríada combinada visible como un modelo en `PredictionView` y revisión de pesos con `TriadComponentsEditor`. Vitest, tipos, lint y build.
- T6 | S1-S6 | independent verify | pending | Verificador independiente (items 1, 2 y 5) y RDD por commit de unidad de riesgo.
- T7 | S5,S6 | inline | pending | ADR, manual de migración/instalación, recibo `docs/receipts/integracion-mvp-f.json`, KANBAN y README; commits locales.

## Estrategia de revisión
- Durante f: revisar por separado con RDD cada commit de alto riesgo (la migración 0005 y la autorización de la tríada combinada), cuando quepa en el presupuesto de contexto; el verificador independiente (T6) se mantiene igual.
- La revisión de la rama completa `mvp` frente a `main` se hace al terminar, dividida en PRs encadenados por etapa. Toda la rama (1427 archivos, ~135 000 líneas) excede el presupuesto (`lens_context_budget_exceeded`, 2026-11-11), así que no puede revisarse de una vez. Mientras tanto se puede omitir en cada cierre.

## Comprobaciones
- Runner: desde `backend/`, `PYTHONDONTWRITEBYTECODE=1 PYTHON_DOTENV_DISABLED=1 DATABASE_URL=sqlite:// CUDA_VISIBLE_DEVICES='' PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 ../.venv/bin/python tests/run_isolated_training_checks.py <selectores> --maxfail=100000`. El runner fija `-x`; `--maxfail` lo anula. Prohíbe SQLite en archivo y subprocesos, así que las pruebas de esquema que dependan de ellos deben adaptarse o declararse como exclusión explícita.
- Comparar siempre el candidato contra la base `baf1f01` (copia `git archive` en un directorio temporal) por nodeid y fase; no contar como aprobados los fallos de la base.
- Frontend: `npx vitest run`, `npx tsc --noEmit -p .`, `npm run lint` (la base tiene 2 errores previos) y `npm run build`.

## Log
- L1 — Kevin: «Haz el plan para la etapa f, se debe realizar el traspaso para realizarla en una nueva sesion».
- L2 — Kevin: «Guardemoslos para la estapa f» (tríada estándar combinada, ajuste de pesos y tríadas importadas existentes).
- L3 — Planificación sobre `baf1f01`, árbol limpio: diferencias entre el ORM y `schema_0004`, consumidores y hallazgo de `archived` obtenidos por inspección del código; nada se ejecutó contra una base real. La etapa e está cerrada (`2f67a26`, `3c7dfa1`, `f2c64b7`). Kevin omitió la revisión nativa del rango de e y de la rama completa frente a `main`; la revisión de la rama sigue pendiente y se recomienda hacerla en PRs por etapa al entregar.
- L4 — Kevin aceptó revisar la rama completa al terminar: «Puede que la revision sea lo ideal al terminar, debido a que como faltan partes por implementar parte del codigo estara mal». El intento con toda la rama falló por `lens_context_budget_exceeded`, sin crear autoridad. Estrategia registrada arriba.
- L5 — Kevin: «Vamos por f, haz el plan y el traspaso». La sesión nueva empieza por las decisiones abiertas 1–4.
