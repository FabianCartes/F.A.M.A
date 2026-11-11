# Integración MVP — etapa d: entrenamiento de ZIP publicados con `partition_version`
Objetivo: entrenar los datasets publicados por la etapa c con el flujo estándar de particiones (`partition_version`) y retirar la vía paralela de snapshots importados de `feat/local-mvp`. Rama `mvp`, base `d881288`; commits locales en español a nombre de Kevin Cardenas, sin coautoría, sin push ni PR.
Verificación: runner aislado `backend/tests/run_isolated_training_checks.py`, Vitest, tipos, lint y build; suites comparadas contra un worktree de la base. Solución más simple y eficaz.

## Specs
- S1 (plan aceptado 2026-11-10): «Vamos con el camino mas facil, quitemos los snapshots». Un ZIP publicado por c se particiona con `DatasetPartitions` y entrena con `partition_version` (modelo individual y tríada) sin código nuevo de snapshot.
- S2 (prueba pedida en el plan d): «rechazo si el hash local no coincide»: si cambia la copia local en `raw_data_dir`, la versión de partición se rechaza con el mensaje de contenido local.
- S3: se retira la entrada de entrenamientos importados: campos `imported_dataset_id`, `snapshot_id` e `imported_prepared_version` del esquema, rama importada de `start_training`, `include_imported` del catálogo de entrenamiento, rutas `/api/training/imported/snapshots*`, y los servicios que solo la sirven (`training_snapshots.py`, preparación importada, resolución de la fuente importada, creación de tríada importada) con sus pruebas.
- S4: el flujo por `partition_version` no cambia (sus pruebas existentes siguen en verde).
- S5: `TrainingView` deja de ofrecer la fuente importada; los ZIP publicados aparecen en la lista estándar.
- S6 (límite de alcance): las lecturas de modelos importados ya existentes en predicción, historial y feedback (`ImportedModelSource`, `ImportedTriadPredictor`, revisión de pesos) quedan para la etapa e; la etapa f deja de crear las tablas `training_snapshot*`.

## Tasks
- T1 | S1,S2,S4 | inline | done (verde al primer intento: fija comportamiento existente) | Pruebas: ZIP publicado → partición → fuente de entrenamiento; rechazo por hash local; tríada con `partition_version`.
- T2 | S3,S4 | inline + verificador independiente (riesgo 3: contrato) | pending | Retirar entrada y servicios importados del backend.
- T3 | S5 | inline | pending | Retirar panel importado del frontend.
- T4 | S1-S6 | inline | pending | Suites contra base, documentación (manuales de snapshots/preparación importada, KANBAN, README), commits.

## Log
- L1 (2026-11-10, Kevin): «Vamos con el camino mas facil, quitemos los snapshots, apruebo el plan, continua con su ejecucion. Si te quedas sin limite haz un mini cierre para traspasar el trabajo realizado a otra sesion y esta termine el cambio d»
- L2: hallazgo previo (Engram #7431): `partitions.py` del compañero ya congela por sha256, rechaza cambios locales y entrena la tríada; `training_snapshots.py` e `imported_training_source.py` vienen de `feat/local-mvp` y dependen de `DatasetMember`/`owner_id`. Pérdidas aceptadas: procedencia por grabación del ZIP (sin `metadata.csv`) y registros durables de tríada importada.
