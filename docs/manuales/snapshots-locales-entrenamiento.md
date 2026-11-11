# Snapshots locales de entrenamiento

**Estado vigente — MVP d:** la entrada HTTP de snapshots/preparaciones importadas está retirada. Para nuevos entrenamientos publique el ZIP, guarde particiones estándar y seleccione `dataset_name` + `partition_version`; consulte el [manual vigente](entrenamiento-datasets-importados.md). Las rutas `/api/training/imported/*` ya no están registradas y los selectores importados de inicio se rechazan sin fallback.

**Retención obligatoria:** se conservan `TrainingSnapshots`, sus tablas y archivos porque los lectores de modelos importados existentes aún los necesitan para predicción, evaluación, historial, feedback y revisión de pesos. Este cambio no elimina datos ni autoriza DDL, GC, nuevas capturas o cambios de permisos operacionales.

El resto de este documento describe el contrato y la evidencia **históricos de T1**, no el camino vigente de nuevos entrenamientos ni una instrucción para volver a habilitarlo.

## Alcance T1 (histórico)

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
- Una lectura verifica el manifiesto y copia cada archivo a un spool privado antes de entregar sus chunks. Hasta 1 MiB permanece en memoria; los archivos mayores derraman en la raíz privada durable de snapshots, anclada al descriptor verificado mediante `/proc/self/fd/<fd>` (Linux). El spool y descriptor permanecen abiertos durante la entrega y se cierran al agotar o cerrar el generador. Cada lector simultáneo necesita espacio privado para un archivo de trabajo; no duplica ese archivo en el tmpfs global. El tamaño y SHA256 se comprueban completos antes de entregar bytes. El manifiesto usa su spool separado y también necesita capacidad temporal adicional al preflight de creación.
- La preparación valida además el WAV completo y necesita su propio spool mientras T1 conserva el archivo verificado. Ese segundo spool también derrama en el almacenamiento durable privado de snapshots, no en `TMPDIR`: ambos spools de audio y las lecturas concurrentes evitan agotar el volumen temporal global. Se ancla al descriptor verificado por `_root_directory` mediante `/proc/self/fd/<fd>` (runtime Linux), conserva los límites de memoria/hash/WAV y se cierra antes del descriptor. No modifica los audios inmutables ni deja índices/temporales persistentes en la raíz. Debe haber espacio adicional en ese almacenamiento privado para un WAV de trabajo. No aumentar arbitrariamente tmpfs ni omitir la verificación para preparar archivos grandes.

No se deducen grupos/grabaciones ni independencia; son T2. No se verifican aquí GPU, PostgreSQL operacional, calidad ML ni entrenamiento real.

Unidad local: commit `36bf33806d4678246c76331b7abede7c2a81e8df`. ASSESS nativo del rango exacto comprometido contra `dd929cd45c894368c69f6fde3d4606c4381ce222` quedó **unavailable** porque el proveedor exige declaración de archivos no rastreados ajenos; devolvió nativeRisk unassessable y, por escalación de seguridad, independiente requerida. No devolvió `reviewDue` ni continuación de revisión. No se inició lineage, no hubo consentimiento de review ni aprobación nativa; no se modificó autoridad ni se limpiaron archivos ajenos para forzarla. La verificación funcional e independiente anterior no se presenta como review nativa.

## Persistencia y migración explícita

Tablas nuevas: `training_snapshot` y `training_snapshot_member`. Importar el módulo no ejecuta DDL. El runtime no migra implícitamente ni repara un esquema ausente/incompatible.

**Histórico:** el migrador `scripts.migrate_training_snapshots` fue retirado y la revisión Alembic 0005 no crea estas tablas (ADR 0070). Un esquema nuevo no las incluye; las bases anteriores que las conservan no se modifican. No hay instrucción de migración vigente para ellas; el esquema vigente se aplica con `python -m app.schema upgrade --apply`.

### Permisos de PostgreSQL para finalizar cualquier dataset

La migración de esquema no concede permisos a la cuenta de aplicación. Además de sus permisos existentes de captura y lectura, `fama_training_app` necesita `UPDATE` exclusivamente sobre `state`, `file_count`, `total_size_bytes`, `classes` y `manifest_sha256` de `public.training_snapshot`. Sin ese permiso, la copia puede publicarse en disco y fallar la confirmación `ready`; el endpoint devuelve el error genérico de fuente no disponible. La salud de la API y la lectura del catálogo no verifican esta capacidad.

**Histórico:** el script `backend/scripts/grant_training_snapshot_updates.sql` fue retirado junto con las tablas de snapshots. El procedimiento que describía ya no se ofrece; lo siguiente conserva el contexto de la concesión que se aplicó.

La concesión se aplicó seleccionando la base mediante la configuración privada del operador, sin credenciales en argumentos, documentación o logs. El script retirado admitía bases `fama_training_dev_<14 dígitos>`, exige una cuenta de aplicación sin atributos administrativos y rechaza permisos preexistentes para cambiar la identidad/propietario/revisión. No crea roles, no concede `DELETE`, no cambia la identidad del snapshot y no concede `UPDATE` de tabla completa. Se puede aplicar de nuevo: la concesión es idempotente y queda persistida en PostgreSQL para **todos los datasets presentes y futuros**. No depende de la sesión de UI ni de un contenedor de API; debe incluirse al aprovisionar o restaurar otro entorno con esta cuenta limitada.

Verificar después con la identidad real de la aplicación los cinco `has_column_privilege(..., 'UPDATE')`, la ausencia de permisos para modificar identidad/propietario/revisión y un `EXPLAIN UPDATE` sobre los cinco campos con `WHERE false`. No usar `EXPLAIN ANALYZE`: este último sí ejecuta la consulta. Un test SQLite no valida concesiones PostgreSQL. El recibo de la corrección conectada es [snapshot-permissions-repair.json](../receipts/snapshot-permissions-repair.json).

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
