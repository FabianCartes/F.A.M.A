# Admisión durable de trabajos de importación

**Estado: T2a aditivo, no es todavía el worker del Corte 2.** Las tablas y la
admisión están disponibles como módulo público de cola; preview, confirm y sync
HTTP conservan su ejecución anterior hasta el corte coordinado T2b–T2d. No
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

Desde `backend/`, con el entorno documentado en
[integración de entrenamiento](integracion-flujo-entrenamiento.md#reproducir-comprobaciones-aisladas):

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHON_DOTENV_DISABLED=1 DATABASE_URL=sqlite:// \
CUDA_VISIBLE_DEVICES='' PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
../.venv/bin/python tests/run_isolated_training_checks.py tests/test_dataset_import_jobs.py -q --tb=short
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
Se comprueban limpieza y hashes de los insumos protegidos. No es un sandbox OS.

**Esta evidencia no demuestra todavía muerte/reemplazo de un worker en ejecución,
fencing, heartbeat, publicación interrumpida, HTTP202 ni recuperación del panel.**
Esos escenarios siguen abiertos en [T2b–T2e](../arquitectura/large-zip-gcs.md).
