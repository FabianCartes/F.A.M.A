# Snapshots locales de entrenamiento

## Alcance T1

Implementa la base local de S1–S2/S8 del [plan](../arquitectura/entrenamiento-datasets-importados-plan.md), conforme al [ADR 0052](../adr/0052-preparacion-local-de-datasets-importados.md). No agrega endpoints, catálogo de entrenamiento, admisión, trabajos, splits ni entrenamiento. No modifica el importador ZIP ni el contrato remoto `DatasetRevision.complete`.

## Interfaz pública

```python
from app.services.training_snapshots import TrainingSnapshots

# Dependencias de servidor, nunca rutas proporcionadas por el cliente.
source = TrainingSnapshots(sessions, imported_dataset_service, durable_snapshot_root)
snapshot = source.create(owner_id, dataset_id)
reference = source.get(owner_id, snapshot["id"])
for metadata, chunk in source.iter_verified(owner_id, snapshot["id"]):
    # chunk <= 1 MiB; un archivo puede producir varios chunks.
    consume(metadata, chunk)
```

`create` siempre crea una identidad nueva. Para reutilizar una cohorte, persistir su ID y llamar `get`/`iter_verified`; no volver a llamar `create` al reiniciar. El descriptor contiene propietario, dataset/revisión, nombre/descripción capturados, clases ordenadas, conteos/tamaño y SHA256 del manifiesto. Los miembros preservan clase, ID de miembro, import de origen, ruta original/relativa, nombre almacenado, SHA256 y tamaño.

La resolución exige igualdad exacta de propietario tanto para dataset como para snapshot. Un propietario ajeno, incluido `-1`, recibe 404; no hay bypass de desarrollo. La autenticación HTTP y la selección del propietario siguen siendo responsabilidad de la integración futura T3, no de una ruta nueva en T1.

`SnapshotIntegrityError`, errores de E/S o errores de esquema abortan la operación; no deben traducirse a éxito. Una integración HTTP futura debe sanitizar errores del sistema operativo antes de mostrarlos. La iteración debe agotarse correctamente antes de publicar cualquier derivado: verificar un archivo no garantiza que los siguientes existan.

## Captura, almacenamiento e integridad

- La captura usa la misma compuerta transaccional de la cola que confirmación (`_gate`). Un `INSERT SELECT` fija todos los miembros, no solo la última importación. La transacción termina antes de copiar. No se crean trabajos de cola ni entrenamiento.
- Las filas de captura se recorren mediante páginas de 64, con cursor estable por ID. La lectura/copia usa chunks de 1 MiB. El mapa de clases ocupa memoria proporcional al número de clases, no al número de archivos.
- La raíz local debe ser privada (sin permisos de grupo/otros), durable y administrada por el servidor. La creación y publicación usan descriptores de directorio y `O_NOFOLLOW`; no se siguen enlaces simbólicos en ancestros de la raíz ni en referencias de origen/lectura. Las referencias relativas rechazan escapes, rutas absolutas y barras inversas.
- El preflight incluye bytes de audio, 8 KiB por miembro más cabecera para manifiesto/overhead y reserva configurable (1 MiB por defecto). No es una reserva exclusiva de disco; un ENOSPC posterior también debe abortar sin publicación consumible.
- Cada archivo es una copia privada, no un hardlink. SHA256/tamaño se comprueban durante la copia. Archivos y manifiesto quedan con modo 0400; staging/raíz con 0700. Estos permisos no protegen frente a un administrador que los cambie: las lecturas vuelven a comprobar integridad.
- El manifiesto canónico JSON Lines usa claves ordenadas y codificación ASCII estable. Su hash se persiste en DB. Las etiquetas verificadas se leen del manifiesto, no del catálogo mutable ni de las filas auxiliares de captura.
- Se sincronizan archivos, manifiesto y directorios con `fsync`; el directorio privado se renombra antes de confirmar `ready` en DB. Solo `ready` permite consultar/consumir.
- Una lectura verifica el manifiesto y copia cada archivo a un spool privado antes de entregar sus chunks. Hasta 1 MiB permanece en memoria; los archivos mayores usan un temporal del sistema. Configurar `TMPDIR` privado con espacio suficiente para al menos un archivo y el manifiesto. Esa capacidad temporal es adicional al preflight de creación.

No se deducen grupos/grabaciones ni independencia; son T2. No se verifican aquí GPU, PostgreSQL operacional, calidad ML ni entrenamiento real.

## Persistencia y migración explícita

Tablas nuevas: `training_snapshot` y `training_snapshot_member`. Importar el módulo no ejecuta DDL. El runtime no migra implícitamente ni repara un esquema ausente/incompatible.

El operador debe detener **todos** los escritores antes de invocar, con un engine elegido explícitamente:

```python
from scripts.migrate_training_snapshots import migrate_snapshots
migrate_snapshots(engine, writers_stopped=True)
```

El migrador valida las tablas de importación/compuerta requeridas y los tipos/columnas del esquema existente; para tablas de snapshot comprueba también PK y nullabilidad. Solo agrega las dos tablas ausentes; no modifica datos/tablas previos. Requiere SQLite o PostgreSQL. La bandera es una declaración del operador, no un mecanismo para detener procesos. En esta tarea se ejecutó únicamente contra SQLite sintético en memoria, nunca sobre la DB real.

Retener conjuntamente DB y raíz durable. Un snapshot `ready` se recupera por su ID con identidad y clases originales. No hay GC ni borrado de fuentes. Ante fallo antes del rename se limpia únicamente el staging creado por esa llamada. Ante fallo/crash después del rename y antes del commit queda un directorio retenido y una fila no consumible; T1 no lo promueve automáticamente ni sustituye su cohorte. Requiere diagnóstico operacional autorizado, no volver a crear silenciosamente la cohorte bajo la misma identidad. Las filas `building` y los directorios huérfanos no tienen recolector automático.

## Evidencia focal observada

Comandos ejecutados desde `backend/`, con `bash timeout=30`; ningún timeout. Prefijo exacto común (seguido de los selectores indicados):

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHON_DOTENV_DISABLED=1 DATABASE_URL=sqlite:// CUDA_VISIBLE_DEVICES='' PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 /home/kevin/Work/fama/.venv/bin/python tests/run_isolated_training_checks.py
```

El usuario seleccionó «Accept the documented evidence limitation» para continuar el cierre sin fabricar logs retrospectivos; esta disposición no concede consentimiento nativo de revisión ni operaciones reales. Recibo consolidado: [verificación T1](../receipts/imported-training-t1-verification.json).

Las salidas completas stdout/stderr y códigos están en el transcript de herramientas del worker; este manual conserva selectores, resultado y extractos, no es una exportación de los logs crudos. Los scratch indicados fueron limpiados por el runner, no son archivos de evidencia retenidos.

| Orden | Selectores exactos añadidos al prefijo | Exit / stdout observado | Scratch (sufijo) |
| --- | --- | --- | --- |
| 1 RED | `tests/test_training_snapshots.py::test_complete_cohort_survives_reopen` | 1; `ModuleNotFoundError: No module named 'app.services.training_snapshots'`; `1 failed in 0.29s` | `0ejf8ki5` |
| 2 GREEN | `tests/test_training_snapshots.py::test_complete_cohort_survives_reopen` | 0; `1 passed in 0.62s` | `cr39s51d` |
| 3 RED | `tests/test_training_snapshot_migration.py::test_migration_requires_acknowledgement_and_existing_import_schema` | 1; `ModuleNotFoundError: No module named 'scripts.migrate_training_snapshots'`; `1 failed in 0.03s` | `e02691_0` |
| 4 GREEN | `tests/test_training_snapshot_migration.py::test_migration_requires_acknowledgement_and_existing_import_schema` | 0; `1 passed in 0.05s` | `_2z817o0` |
| 5 RED | `tests/test_training_snapshots.py::test_corrupt_snapshot_rejects_before_delivering_bytes` | 1; `Failed: DID NOT RAISE SnapshotIntegrityError`; `1 failed in 0.48s` | `3kvnycin` |
| 6 GREEN | `tests/test_training_snapshots.py::test_corrupt_snapshot_rejects_before_delivering_bytes` | 0; `1 passed in 0.50s` | `z1e8wbbc` |
| 7 | `tests/test_training_snapshots.py::test_owner_mismatch_does_not_disclose_or_publish tests/test_training_snapshots.py::test_failed_creation_has_no_consumable_snapshot` | 0; `8 passed in 1.81s` | `13_zh5z4` |
| 8 RED | `tests/test_training_snapshots.py::test_symlinked_snapshot_ancestor_is_rejected_before_writes` | 1; `NotADirectoryError` al leer después de publicar incorrectamente; `1 failed in 0.51s` | `0tscyvu6` |
| 9 | `tests/test_training_snapshots.py::test_symlinked_snapshot_ancestor_is_rejected_before_writes tests/test_training_snapshots.py::test_append_after_capture_preserves_exact_cohort tests/test_training_snapshots.py::test_failed_creation_has_no_consumable_snapshot` | 1; `RuntimeError: Mutation blocked: os.mkdir`; `1 failed in 0.54s` | `yv45sor_` |
| 10 | mismos selectores que 9 | 1; fallo de fixture por parche global recursivo de `disk_usage` durante upload; `1 failed, 1 passed in 0.85s` | `rt8uyn1d` |
| 11 GREEN | mismos selectores que 9 | 0; `8 passed in 1.88s` | `t26ky2t7` |
| 12 | `tests/test_training_snapshot_migration.py::test_migration_is_idempotent_and_result_is_publicly_usable tests/test_training_snapshot_migration.py::test_incompatible_existing_schema_is_not_repaired tests/test_training_snapshots.py::test_complete_cohort_survives_reopen tests/test_training_snapshots.py::test_corrupt_snapshot_rejects_before_delivering_bytes tests/test_training_snapshots.py::test_owner_mismatch_does_not_disclose_or_publish` | 0; `6 passed in 1.47s` | `3x5higpm` |
| 13 RED | `tests/test_training_snapshots.py::test_verified_labels_come_from_canonical_manifest` | 1; `AssertionError: assert {'wrong'} == {'birds'}`; `1 failed in 0.51s` | `qqz0p_du` |
| 14 GREEN | `tests/test_training_snapshots.py::test_verified_labels_come_from_canonical_manifest tests/test_training_snapshots.py::test_complete_cohort_survives_reopen` | 0; `2 passed in 0.93s` | `vv0fg45n` |
| 15 | `tests/test_training_snapshots.py::test_corrupt_snapshot_rejects_before_delivering_bytes tests/test_training_snapshots.py::test_complete_cohort_survives_reopen tests/test_training_snapshots.py::test_private_copy_is_independent_of_catalog_and_original_bytes tests/test_training_snapshots.py::test_membership_crosses_batch_boundary` | 0; `8 passed in 2.00s` | `i89fnku9` |
| 16 | `tests/test_training_snapshots.py::test_unconfined_catalog_references_are_not_published tests/test_training_snapshots.py::test_owner_mismatch_does_not_disclose_or_publish tests/test_training_snapshot_migration.py::test_migration_requires_acknowledgement_and_existing_import_schema` | 0; `8 passed in 1.74s` | `x0nzp7t0` |
| 17 | `tests/test_training_snapshots.py::test_verified_iteration_spills_and_bounds_chunks` | 0; `1 passed in 0.55s` | `g3h3qxrk` |
| 18 RED | `'tests/test_training_snapshots.py::test_failed_creation_has_no_consumable_snapshot[manifest_space]'` | 1; `Failed: DID NOT RAISE any of (SnapshotIntegrityError, OSError)`; `1 failed in 0.52s` | `g954jq2w` |
| 19 GREEN | `'tests/test_training_snapshots.py::test_failed_creation_has_no_consumable_snapshot[manifest_space]' tests/test_training_snapshots.py::test_append_after_capture_preserves_exact_cohort tests/test_training_snapshots.py::test_verified_labels_come_from_canonical_manifest` | 0; `3 passed in 1.09s` | `0ldhmwp1` |
| 20 | `tests/test_training_snapshots.py::test_failure_after_rename_is_not_visible_or_cleaned_as_staging tests/test_training_snapshots.py::test_failed_creation_has_no_consumable_snapshot` | 0; `8 passed in 1.78s` | `lxsr7haw` |

El guard permaneció intacto. El fallo 9 fue un intento innecesario de `mkdir` sobre ancestros ya existentes: se corrigió abriendo primero los directorios y creando únicamente componentes ausentes dentro de la raíz autorizada. No se amplió el guard ni se cambió entorno. El fallo 10 fue una recursión de fixture, no una regresión de confirmación: el parche se restaura antes de ejecutar el append.

No se atribuye RED individual a las triangulaciones que ya pasaron con la implementación del slice anterior. Los conteos por ejecución no son una suma de casos únicos ni sustituyen la suite combinada. No hubo skips ni deselecciones en estas ejecuciones; después de cada fallo fail-fast quedaron los selectores posteriores sin ejecutar hasta la siguiente ejecución documentada.

## Suite combinada ejecutada por el padre

Fixtures revisadas: `test_dataset_import_api.imports` usa SQLite memoria y validador sintético; el caso de rechazo de sandbox en `test_dataset_import_execution` reemplaza `Popen` por un fallo sintético; `test_dataset_import_manifests` usa objetos remotos en memoria. El worker no ejecutó esta regresión completa; el padre sí la ejecutó mediante `bash_background` (job-1), con evento terminal exit 0: **66 passed in 16.30s**, sin skips/deselecciones. El runner acreditó 66 conexiones SQLite memoria, red bloqueada, 30 rutas protegidas intactas y limpieza del scratch. El padre comprobó además hashes de ocho rutas locales preservadas. Esto cubre la comprobación del padre sobre los comandos reportados y no acredita PostgreSQL/Docker/GPU. Log crudo de esta ejecución: `/tmp/gp81Qz9r/gentle-jobs-uc8bz8/job-1.log` (artefacto temporal de sesión). Comando exacto desde la raíz:

```bash
cd backend && PYTHONDONTWRITEBYTECODE=1 PYTHON_DOTENV_DISABLED=1 DATABASE_URL=sqlite:// CUDA_VISIBLE_DEVICES='' PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 /home/kevin/Work/fama/.venv/bin/python tests/run_isolated_training_checks.py tests/test_training_snapshots.py tests/test_training_snapshot_migration.py tests/test_dataset_import_api.py tests/test_dataset_import_execution.py tests/test_dataset_import_manifests.py
```

Verificación independiente inicial: exit 0, **4 passed in 1.36s**, cero skips/deselecciones; ownership (2/-1), append postcaptura y usabilidad del migrador. Sin blocker severo de código; detectó que la fixture de migración ya creaba las tablas de snapshot, por lo que faltaba demostrar su creación. El padre corrigió solo la prueba: ambas tablas ausentes, servicio rechazado antes de migrar, migrador dos veces y servicio utilizable después. Módulo corregido: exit 0, **3 passed in 0.54s**, cero skips/deselecciones, tres conexiones SQLite memoria/30 rutas protegidas intactas/cleanup PASS. Se añadió también aserción de `iter_verified` con clase/audio esperado. Recheck del mismo verificador sobre el selector aislado: **exit 1, 1 failed in 0.67s**, porque las tablas ya estaban ausentes y el DROP incondicional fallaba antes del migrador. Corrección final de la misma fixture: `drop(checkfirst=True)` mantiene la precondición explícita sin depender del orden de colección. Padre ejecuta una vez ese selector exacto: **exit 0, 1 passed in 0.47s**, cero skips/deselecciones, una conexión SQLite memoria/30 rutas protegidas intactas/cleanup PASS. Queda observada creación desde tablas ausentes, idempotencia y create/get/iteración verificada. No hubo cambio de producción, otro barrido ni un segundo verificador. El verificador no emitió después un nuevo veredicto global; el cierre de esta brecha concreta lo acredita el padre con el selector que aquel indicó. La prueba focal intercala confirmación real **después** de captura y antes de copia, sin transacción de snapshot abierta; no demuestra por sí sola todas las carreras multiproceso. Host observado Python 3.14.8; estos resultados no acreditan la imagen Docker Python 3.12. Sin DB real, GCS, pesos, entrenamiento ni migraciones operacionales.
