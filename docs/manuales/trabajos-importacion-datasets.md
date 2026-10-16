# Admisión durable de trabajos de importación

**Estado: T2a y núcleo de ejecución T2b, sin integración de publicación.** Las tablas,
la admisión y la ejecución confiable están disponibles como módulos públicos;
preview, confirm y sync HTTP conservan su ejecución anterior hasta T2c–T2d. No
arrancar un worker ni presentar una fila `queued` como operación completada.

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
| Cancelación T2a | Solo trabajos pendientes; repetición idempotente. Cancelación de ejecuciones y recuperación corresponden a T2b–T2d. |

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
callback solo prepara su directorio y reporta; no debe publicar archivos compartidos.

La raíz debe existir, ser física, absoluta, privada (sin permisos de grupo/otros)
y pertenecer al usuario del proceso. Cada intento crea exclusivamente
`<job>-<attempt>-<token>` con modo 0700, sin adoptar rutas existentes ni usar un
directorio `files` compartido. No se borra staging. La separación de rutas no aísla
código malicioso bajo el mismo usuario, ni prueba fencing de publicación final.
No conectar este callback directamente a los métodos síncronos existentes.
El despacho real, journal/fsync, publicación de membresía, limpieza protegida,
HTTP202/panel y CLI de arranque permanecen en T2c–T2e. No arrancar servicios con esta entrega.

Desde `backend/`, con el entorno documentado en
[integración de entrenamiento](integracion-flujo-entrenamiento.md#reproducir-comprobaciones-aisladas):

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHON_DOTENV_DISABLED=1 DATABASE_URL=sqlite:// \
CUDA_VISIBLE_DEVICES='' PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
../.venv/bin/python tests/run_isolated_training_checks.py tests/test_dataset_import_worker.py tests/test_dataset_import_jobs.py tests/test_dataset_import_api.py tests/test_dataset_import_pages.py tests/test_dataset_import_paging_regressions.py -q --tb=short
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

**Esta evidencia demuestra fencing de estado de cola, no publicación de membresía
ni recuperación rename-before-commit.** La integración de publicación, HTTP202 y
recuperación del panel siguen abiertas en [T2c–T2e](../arquitectura/large-zip-gcs.md).
