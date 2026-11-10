# Trabajos locales de importación ZIP

## Contrato vigente en la unidad b del MVP

La API admite trabajos durables `preview` y `confirm`; un worker separado los
 ejecuta. HTTP 202 significa admisión, no validación ni publicación terminada.
Confirmar publica miembros y WAV locales y **no encola `sync`**. La publicación
al inventario compartido queda para la unidad c; no se adelantan sus permisos.

Se retiraron la subida privada a GCS, las revisiones/manifiestos de esa subida,
la exportación ZIP y su worker, y el ledger físico `dataset_storage` con su perfil
opcional. No se usa `FAMA_IMPORT_STORAGE_PROFILE`. Las tablas de las migraciones
congeladas se conservan: esta retirada no autoriza DDL ni purga de datos.
La descarga GCS → local del inventario compartido y la sincronización de
retroalimentación son flujos distintos y se conservan.

## API y recuperación

Todas las rutas siguientes pertenecen a `/api/ingestion/imports`, requieren la
identidad web existente y comprueban propietario. No se habilita acceso anónimo.

| Operación | Contrato |
| --- | --- |
| `POST /{id}/preview` | `request_key` y `root`; valida fuera de HTTP. |
| `POST /{id}/confirm` | `request_key` y `preview_token`; confirma la revisión local revisada. |
| `GET /{id}/jobs/{execution_id}` | Estado/progreso/resultados acotados; lectura sin renovar actividad ni lease. |
| `POST /{id}/jobs/{execution_id}/cancel` | Solo cancela un trabajo `queued`. |
| `POST /{id}/jobs/{execution_id}/retry` | Clave nueva para un trabajo fallido/cancelado, sujeto al estado actual de la importación. |
| `GET /{id}` | Estado local, diagnóstico, vista previa acotada y referencia `execution`. |

La clave de operación tiene 1–100 caracteres ASCII alfanuméricos o `_.:-`.
Repetir tipo, clave y parámetros conserva la identidad; cambiarlos con la misma
clave devuelve conflicto. `confirm` exige el token exacto revisado. El 202 incluye
`id`, `import_id`, `kind`, `status`, `stage`, `progress`, `result`, `error` y
`status_url`; `Location` señala la consulta de ese trabajo.

Ya no existen `POST /{id}/sync`, las rutas `/datasets/{id}/revisions/{revision}`
y `/manifest`, ni las rutas de exportación `/datasets/{id}/revisions/{revision}/exports`,
`/datasets/{id}/exports`, `/exports/{id}`, `/exports/{id}/sessions` o
`/exports/{id}/download`. No hay sustituto de manifiesto para descargar audio local.
Las respuestas de importación, catálogo local y archivos no publican
`sync_status`, `synced_count` ni `synced_file_count`.

## Worker en primer plano

Desde `backend/`, sobre una base y raíces previamente autorizadas:

```sh
python -m scripts.run_dataset_import_worker --help
python -m scripts.run_dataset_import_worker \
  --database-url '<URL explícita de base migrada>' \
  --import-root '<raíz física privada existente>' \
  --staging-root '<raíz física privada de intentos existente>'
```

Ambas raíces deben ser absolutas, físicas, sin enlaces, privadas y propiedad del
usuario del proceso; deben compartir filesystem. La raíz de importaciones debe
coincidir con la API (`FAMA_IMPORT_ROOT`). No cambiar raíces mientras haya trabajo
recuperable. El CLI no migra, crea tablas, arranca HTTP ni configura GCS.
No obtiene la URL de `DATABASE_URL` ni carga dotenv.

Una invocación reclama como máximo un trabajo local, incluso si su lease venció.
Devuelve exit 0 con `{"claimed": true}` o `{"claimed": false}`. **Reclamar no
acredita éxito:** consultar el estado HTTP. Los trabajos históricos de tipo `sync`
no se reclaman ni se convierten en exitosos. Sus registros se conservan.

- `--watch`: ejecución supervisada en primer plano; espera dos segundos entre
  intentos, incluso sin trabajo. SIGINT/SIGTERM solicitan salida tras la operación actual.
- `--poll-seconds`: intervalo finito entre 1 y 3600 segundos; exige `--watch`.
- `--execution-seconds`: plazo cooperativo finito mayor que 0 y hasta 3600;
  predeterminado 1800. No cambia lease 60 s, heartbeat 20 s, validación ni timeout HTTP.
- `--local-only`: se conserva para los lanzadores existentes; el comportamiento
  predeterminado ya es local. No selecciona otro motor ni habilita nube.
- `--sync-only`: retirado; argparse lo rechaza.

El plazo cooperativo no mata hilos Python. Mientras un callback vencido siga
terminando, ese worker no inicia otro. Errores de infraestructura producen exit 1
con diagnóstico saneado; argumentos inválidos producen exit 2 antes de recursos.
Un proceso terminado puede dejar un lease o journal recuperable, no un éxito.

## Recepción y cuotas que se conservan

La recepción reanudable usa `POST /{id}/receipt`, `PUT /{id}/receipt/chunks/{index}`,
`GET /{id}/receipt/chunks` y `POST /{id}/receipt/finalize`. La reserva SQL del ZIP
más su expansión **no es el ledger físico retirado**: sigue limitando la recepción
con `FAMA_IMPORT_RESERVED_BYTES_PER_OWNER` y `FAMA_IMPORT_RESERVED_BYTES_GLOBAL`.
Se conserva una recepción activa por propietario, presupuesto global y comprobación
del espacio libre real con margen `FREE_BYTES`. Liberar la promesa no acredita borrado.

Los bloques predeterminados son de 16 MiB (`FAMA_IMPORT_CHUNK_BYTES`); se fijan al
admitir la recepción. Envío secuencial, offset exacto, tamaño y SHA-256 son obligatorios.
Una repetición idéntica comprueba también los bytes guardados, sin incrementar
contadores. Reanudar exige comparar todos los bloques reconocidos. Finalizar
verifica todo el ZIP, sincroniza bytes/directorios y sella antes de admitir preview.
Un archivo completo recibido no acredita WAV válidos.

Se conservan las cuotas acumuladas por dataset: 15 GiB de WAV únicos y 50.000
miembros por defecto, configurables con `FAMA_IMPORT_DATASET_BYTES` y
`FAMA_IMPORT_DATASET_ENTRIES`. Se revalidan al publicar, sin contar duplicados dos
veces. Revisión obsoleta o resumen inconsistente falla sin reparar datos.

## Publicación, seguridad y mantenimiento

El worker conserva validación ZIP64 contenida mediante Bubblewrap, namespaces,
seccomp, límites de recursos y verificación de resultados. Si falta el sandbox,
rechaza sin fallback. Los tests sintéticos del runner en memoria usan explícitamente
el validador directo; no acreditan contención OS, PostgreSQL, GCS ni Docker/Python 3.12.

La compuerta serializa transacciones cortas; hashing, decodificación y fsync de
contenido quedan fuera. Cada intento tiene su directorio privado exclusivo.
Los tokens de fencing y leases impiden publicar desde un intento obsoleto.
El journal `committing` precede a rename; la recuperación verifica los hashes del
destino y restablece fsync antes de completar membresía una sola vez.

Un fallo definitivo anterior al journal cancela la importación y libera su promesa
lógica; conserva diagnóstico y temporales para mantenimiento. Los journals de
publicación no se cancelan automáticamente. Las advertencias solas no cancelan.

La limpieza es explícita, nunca un efecto de consultas o mutaciones HTTP:

```sh
python -m scripts.run_dataset_import_worker \
  --database-url '<URL explícita de base migrada>' \
  --import-root '<raíz física privada existente>' \
  --staging-root '<raíz física privada de intentos existente>' --cleanup-only
```

Leer `completed` y `failed`, no solo exit 0. `--cleanup-only --watch` usa un intervalo
predeterminado de 3600 segundos y admite `--poll-seconds`; rechaza `--execution-seconds`.
No contacta GCS. Solo retira staging elegible; conserva objetos publicados, historial,
trabajos activos (también leases vencidos), journals y directorios todavía bloqueados.
Una reclamación durable `deleting` impide nuevas modificaciones; se mantiene el
candado de importación durante borrado y fsync, sin transacción larga. Repetir tras
un fallo, sin borrar manualmente la reclamación ni cambiar la raíz de intentos.

## Comprobación aislada

Desde `backend/`, con el intérprete validado y sin servicios ni datos reales:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHON_DOTENV_DISABLED=1 DATABASE_URL=sqlite:// \
CUDA_VISIBLE_DEVICES='' PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
../.venv/bin/python tests/run_isolated_training_checks.py \
  tests/test_dataset_import_async_api.py tests/test_dataset_import_jobs.py \
  tests/test_dataset_import_execution.py tests/test_dataset_import_worker_cli.py \
  tests/test_dataset_import_receipts.py tests/test_dataset_import_chunks.py \
  tests/test_dataset_import_integration.py
```

Usa SQLite en memoria, WAV sintéticos y scratch privado, con red bloqueada y
límites por fase. Es una guarda de aplicación, no un sandbox OS. Informar resultados
nuevos y fallos, sin reutilizar recibos históricos. Los procedimientos operativos
requieren autorización independiente; aparecer en este manual no autoriza ejecutarlos.
