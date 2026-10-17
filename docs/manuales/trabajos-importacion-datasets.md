# Admisión durable de trabajos de importación

**Estado: integración T2c/T2d verificada localmente y revisión nativa aprobada, con acuse consumido.**
El commit local se registra en [el seguimiento, L37](../arquitectura/large-zip-gcs.md).
T2e sigue pendiente; esta entrega no certifica operación ni despliegue.
`preview`, `confirm` y `sync` HTTP admiten trabajos durables; no ejecutan la
operación ni arrancan workers desde la petición. Una fila `queued` no acredita
validación, publicación ni sincronización. No se han iniciado servicios reales.

## HTTP202 y recuperación del panel

Cada POST de operación requiere una `request_key` de 1–100 caracteres ASCII
alfanuméricos o `_.:-`. `preview` añade `root`; `confirm`, el `preview_token`
revisado; `sync` no añade parámetros. Conservar la misma clave y parámetros ante
una respuesta de admisión perdida; no generar una clave nueva automáticamente.
El `202` incluye `id`, `import_id`, `kind`, `status`, `stage`, `progress`,
`result`, `error` y `status_url`; `Location` señala esa misma consulta.

- `GET /api/ingestion/imports/{import_id}/jobs/{execution_id}` consulta sin renovar
  actividad ni lease. No expone token de fencing, parámetros privados ni rutas.
- `POST .../jobs/{execution_id}/cancel` solo cancela `queued`.
- `POST .../jobs/{execution_id}/retry`, con una clave nueva, admite un reintento
  de un trabajo fallido o cancelado; mantiene las validaciones del estado actual.
- El GET de importación y el historial incluyen `execution`, la referencia durable
  más reciente. Tras recargar, seleccionar la importación del historial recupera
  su seguimiento; no depende del estado en memoria del navegador.

El panel distingue admisión, ejecución y finalización, consulta cada segundo
mientras hay trabajo y reintenta solo lecturas ante errores de consulta. No inicia
confirmación ni GCS por polling. Un fallo asíncrono aparece en el estado del
trabajo, no como un error retrospectivo de la petición `202`.

## Migración explícita

Este procedimiento describe una operación de mantenimiento; incorporarlo al
repositorio no autoriza ejecutarlo sobre una base real.

1. Detener escritores de API y workers y conservar el respaldo de la base.
2. Comprobar que el Corte 1 ya está migrado y que se conserva su evidencia. Esta
   migración no reemplaza ni repite el backfill de metadatos.
3. Desde `backend/`, ejecutar con el intérprete validado y un destino explícito:

   ```bash
   python -m scripts.migrate_dataset_import_jobs --database-url '<URL autorizada>' --writers-stopped
   ```

4. Exigir salida `{"version": 1, "verified": true}` y exit 0. El comando crea
   `dataset_import_job_gate` y `dataset_import_job`, comprueba columnas,
   nulabilidad, claves primarias/foráneas, checks e índices, e inicializa la compuerta de versión 1.
   No modifica las importaciones ni sus metadatos; no arranca procesos de trabajo.
5. Ante un esquema incompatible, conservarlo para diagnóstico. No borrar tablas,
   fabricar una versión ni ejecutar reparación automática para superar el fallo.

La ejecución es transaccional en SQLite y PostgreSQL. La verificación operacional
en PostgreSQL sigue pendiente; compilar DDL o probar SQLite no la sustituye. El
CLI no infiere credenciales ambientales y no imprime URL ni excepciones privadas.
La ruta de rollback de esta entrega consiste en dejar de usar el módulo aditivo,
conservando las tablas para investigación; no exige borrar importaciones.

## Identidad y capacidad

| Concepto | Contrato actual |
| --- | --- |
| Importación | Identidad y metadatos del archivo recibido, no un intento de ejecución. |
| Trabajo | Operación persistida `preview`, `confirm` o `sync`, con parámetros exactos. |
| Idempotencia | Propietario + importación + tipo + clave de operación; mismos parámetros devuelven la misma identidad, también si terminó. Otros parámetros con la misma clave se rechazan. |
| Reserva de ejecución | Fila `queued` o `running`; la transición terminal libera capacidad en la misma transacción. No es una reserva de bytes ni de disco. |
| Exclusión de admisión | Un `UPDATE` a la compuerta obtiene exclusión de escritura en la base antes de contar e insertar. No se realiza I/O prolongada durante esa transacción. |
| Exclusión por importación | Índice único parcial impide dos trabajos activos de la misma importación. No excluye importaciones independientes durante ejecución. |
| Límite global | `FAMA_IMPORT_CONCURRENT_IMPORTS`, valor predeterminado existente 4, sin ampliación. |
| Límite por propietario | `FAMA_IMPORT_JOBS_PER_OWNER`, predeterminado conservador 1. Ambos límites deben ser enteros positivos acotados. |
| Cancelación | Solo trabajos pendientes; repetición idempotente. La cancelación de la importación y la sustitución del ZIP se rechazan mientras existe trabajo activo, aunque el lease haya vencido. |

Las consultas no actualizan actividad, heartbeat, lease ni la compuerta. Un aviso
en memoria no es necesario para que el trabajo permanezca en la base.

## Comprobaciones sintéticas reproducibles

### Contrato del núcleo T2b

`ImportJobQueue.claim(lease_seconds=...)` consulta la cola persistida sin depender
de avisos en memoria. Reclama un trabajo pendiente o una ejecución vencida,
incrementa intento/token y confirma antes de ejecutar. La compuerta solo protege
transacciones cortas; la reserva sigue siendo la misma fila activa al recuperar.
`heartbeat`, `progress` y `finish` requieren identidad, intento, token, estado
`running` y lease estrictamente vigente. La igualdad con el vencimiento ya impide
escribir. Rechazos por lease revierten también la compuerta. Éxito o fallo liberan
capacidad mediante el estado terminal persistido, sin contador auxiliar que reparar.

El reloj predeterminado se consulta en la base después de obtener la compuerta:
SQLite usa `julianday('now')`; PostgreSQL, `clock_timestamp()`. El reloj inyectado
solo sirve para pruebas coordinadas. No se comparan relojes de hosts de workers.
Esto no promete monotonía frente a ajustes del reloj de la base, ni operación
multihost de un archivo SQLite, ni validación operacional PostgreSQL. Los leases
deben ser finitos, positivos y como máximo 3600 segundos; elegir margen suficiente
para la resolución del reloj, latencia y contención reales.

`ImportJobWorker(queue, staging_root, execute).run_once()` ejecuta como máximo un
intento; devuelve `False` si no hay trabajo o su callback previo sigue terminando.
El callback confiable recibe `(attempt, staging, report)`, sin sesión ni transacción
abierta. Un hilo independiente renueva el lease con sesiones propias. Los valores
predeterminados son lease de 60 segundos, heartbeat cada 20 y plazo de ejecución
de 300. Se pueden inyectar duraciones y espera de heartbeat para pruebas.
Ante pérdida de lease no persiste un terminal obsoleto. Los errores persistidos son
solo `execution_failed`, `execution_timeout` o `staging_failed`, nunca excepciones.
El resultado admite únicamente `dataset_id` hexadecimal de 32 caracteres y contadores
enteros acotados `added_count`/`synced_count`; progreso entre 0 y 99, terminal exitoso 100.

El plazo acota la espera del coordinador, **no mata un hilo Python**. Un callback
debe cooperar y limitar sus propias operaciones; si se bloquea tras vencer el plazo,
ese worker no inicia más callbacks hasta que termine. No sirve para decodificadores
hostiles, no amplía su aislamiento ni permite efectos externos arbitrarios. El
callback genérico solo prepara su directorio y reporta. El ejecutor de dominio
descrito debajo publica exclusivamente a través de transacciones fenced.

La raíz debe existir, ser física, absoluta, privada (sin permisos de grupo/otros)
y pertenecer al usuario del proceso. Cada intento crea exclusivamente
`<job>-<attempt>-<token>` con modo 0700, sin adoptar rutas existentes ni usar un
directorio `files` compartido. No se borra staging. La separación de rutas no aísla
código malicioso bajo el mismo usuario, ni prueba fencing de publicación final.
Los antiguos métodos síncronos preview/confirm/sync fueron sustituidos por
`ImportExecution(queue, service, staging_root, storage=...).run_once()`. Su raíz
de intentos debe mantenerse estable entre reinicios. Preparación, hashing,
decodificación, fsync del contenido y acceso al adaptador de almacenamiento ocurren
fuera de las transacciones de publicación. La compuerta de la cola serializa las
transiciones cortas contra reclaim; el resultado exitoso se confirma junto con la
membresía o revisión de preview. Un hilo obsoleto no puede confirmar metadatos.

El journal `committing` se confirma antes de rename. La recuperación verifica los
hashes en el destino si el rename ya ocurrió, reestablece fsync de directorios y
completa membresía sin duplicarla. Los conflictos de revisión/titularidad se
revalidan antes de publicar. Véase [ADR0031](../adr/0031-fenced-import-publication.md).

`DatasetImports.cleanup(db)` es mantenimiento explícito; nunca se invoca al crear,
recibir o confirmar desde HTTP. Excluye filas con trabajos `queued`/`running`
(también leases vencidos) y todo journal `committing`; marca expiración antes de
borrar staging cancelado. No elimina objetos publicados ni directorios privados
de intentos. La recolección completa y asíncrona de estos últimos sigue en Corte5.
La limpieza toma primero el mismo candado por importación que la recepción y
omite una recepción ocupada sin marcarla como vencida. Después toma la compuerta
de cola para revalidar elegibilidad; libera la compuerta antes del borrado pero
mantiene el candado de recepción hasta terminar. No se toma el orden inverso.

No se inicia un proceso de operación desde este manual ni automáticamente desde
la API. El supervisor/CLI operativo y su evidencia de reinicio integral siguen
en T2e. Sin un proceso explícito que invoque el ejecutor, los trabajos permanecen
durablemente pendientes. No se han ampliado límites ni el aislamiento del decoder.

Desde `backend/`, con el entorno documentado en
[integración de entrenamiento](integracion-flujo-entrenamiento.md#reproducir-comprobaciones-aisladas):

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHON_DOTENV_DISABLED=1 DATABASE_URL=sqlite:// \
CUDA_VISIBLE_DEVICES='' PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
../.venv/bin/python tests/run_isolated_training_checks.py tests/test_dataset_import_execution.py tests/test_dataset_import_async_api.py tests/test_dataset_import_worker.py tests/test_dataset_import_jobs.py tests/test_dataset_import_api.py tests/test_dataset_import_sync.py tests/test_dataset_import_verifier_regressions.py tests/test_dataset_import_pages.py tests/test_dataset_import_paging_regressions.py -q --tb=short
```

Ese runner conserva su guarda original y solo admite SQLite en memoria. La
comprobación separada de persistencia y admisión simultánea usa procesos frescos:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHON_DOTENV_DISABLED=1 DATABASE_URL=sqlite:// \
CUDA_VISIBLE_DEVICES='' PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
../.venv/bin/python tests/run_import_job_process_checks.py
```

El coordinador crea almacenamiento exclusivo bajo `/tmp/opencode`, pasa a los
hijos un entorno acotado sin credenciales ambientales y libera barreras por pipes.
Cada hijo instala la guarda original antes de importar la aplicación, bloquea red
y lectura de credenciales, y permite exclusivamente su SQLite privado. Se prueban
nueve admisiones simultáneas, límites global/propietario, tres repeticiones
simultáneas, visibilidad después de salir los procesos y liberación persistente.
También se prueban doble claim simultáneo, recuperación de claim tras salida del
proceso, ejecución bloqueada reemplazada al vencer, rechazo de tres escrituras
obsoletas al despertar, directorios distintos y recuperación después de matar un
hijo sintético bloqueado. Readiness (incluidas líneas parciales), finalización y
limpieza de hijos tienen plazos acotados; el coordinador siempre espera sus salidas.
Se comprueban limpieza y hashes de los insumos protegidos. No es un sandbox OS.

**El procedimiento entre procesos anterior demuestra fencing de cola, no todavía
la publicación de membresía integrada.** Las pruebas de `ImportExecution` añaden
recuperación de rename, publicación obsoleta rechazada y separación de staging
con datos sintéticos; la evidencia integral de caída/reinicio entre procesos
de publicación permanece en [T2e](../arquitectura/large-zip-gcs.md). No confundir
estas pruebas con operación PostgreSQL, GPU, GCS real o validación de escalabilidad.
