# ADR 0018: Incorporación local y sincronización recuperable con GCS

* **Estado:** Aceptado
* **Área:** Curación de audios y persistencia del dataset

Aceptamos primero el audio y sus metadatos en el dataset local persistente y
confirmamos una cola durable de sincronización (*outbox*) en la misma transacción
que el feedback procesado. La copia al dataset GCS se realiza después: el usuario
puede preparar entrenamiento con el audio local aceptado sin esperar esa subida.
No hay transacción distribuida entre filesystem, base de datos y GCS.

## Contexto y alternativas

El flujo anterior escribía primero en GCS y después en local; un rollback de
PostgreSQL no podía revertir ninguna escritura externa. Exigir GCS síncrono antes
de aceptar la muestra acoplaba la incorporación local a la disponibilidad de la
subida cloud, sin resolver esa falta de atomicidad. El outbox local-first separa
aceptación y copia, a cambio de mantener estado pendiente y recuperación explícita.

No se adopta una transacción distribuida ni un broker: la intención recuperable
en filesystem y la cola relacional permiten reintentos con los componentes
existentes. Esto no promete una única petición cloud si se pierde el acuse.

## Hitos y autoridad del destino

| Hito | Significado |
| --- | --- |
| Validación humana | Confirma o corrige la clase y envía feedback a revisión; no incorpora ni entrena. |
| Incorporación local | La aprobación verifica audio/CSV durables y confirma `procesado` + `feedback_sync.pending` juntos. |
| Copia cloud confirmada | El uploader recibió éxito y confirmó `synced` en BD; no es una auditoría de existencia actual del objeto. |

`procesado` también representa descarte legacy; por sí solo no prueba incorporación.
`local_status=incorporated` registra el hito aceptado, no comprueba que el archivo
siga íntegro al consultar. La lectura no sustituye la verificación del replay/uploader.

El destino proviene de la asociación del modelo realmente ejecutado con
`conjunto_datos`, conservada en la predicción. Una URI local solo es válida si
coincide con el directorio canónico existente `backend/data/raw/<nombre>` del
resolver (en contenedor, `/app/data/raw/<nombre>`) y su destino físico permanece
dentro de raw. No se admiten URLs `file://` arbitrarias ni se rellenan históricos
`NULL`, aunque la FK del modelo sea válida ahora. Predicción 23 y feedback 5
requieren recuperación de procedencia explícita: la corrección de inferencias
nuevas no los repara por conjetura.

## Recuperación e integridad

La intención `.feedback_<ID>.json` fija fuente administrada, dataset, clase,
directorio, nombre y SHA-256. Publicación durable con staging, `fsync` y operaciones
atómicas precede al commit relacional; el audio no sobrescribe otro contenido.
Un fallo puede dejar evidencia local sin aceptación confirmada. El replay verifica
identidad, hash y CSV y completa el mismo intento, sin duplicar audio ni metadatos.
La cola deriva rutas deterministas `feedback_<ID>.wav` y no acepta claves arbitrarias.

El lock estable por feedback y el lock por dataset serializan aprobación y CSV.
El uploader comparte el orden fila feedback → inode de lock → fila sync; necesita
escritores cooperantes y un filesystem compatible con `flock`. Antes de subir
verifica intención, identidad, contención y bytes; un fallo deja `pending` con
`upload_failed` o `integrity_mismatch`, sin guardar errores privados del proveedor.
La misma clave y hash hacen idempotente la identidad, no atómicas las escrituras
cloud/BD bajo pérdida de acuse.

El lifespan inicia una pasada fuera del hilo de serving y reintenta cada 60 segundos
en lotes de 50. La subida tiene timeout de 30 segundos, sin retry interno del SDK.
El cierre señala stop y espera el trabajo en vuelo y su commit; un bloqueo de BD
o filesystem puede prolongarlo. No se abandona un hilo fingiendo cancelación.

## Consecuencias y límites

- Local-first **no significa offline**: inferencia conserva la fuente raw en GCS y
  la primera incorporación la descarga. El catálogo local evita listar GCS cuando
  es suficiente, pero no elimina esa dependencia de origen.
- Disponibilidad raw no equivale a iniciar entrenamiento, validar calidad acústica
  ni regenerar particiones `train`/`val`. Prepararlas sigue siendo responsabilidad
  del operador; no se fuerza una sincronización cloud previa.
- Gestión de audios separa revisión y registros aceptados recientes. Su GET read-only
  usa límite 50 por defecto (1–500), orden por ID descendente y refrescos manuales,
  de montaje, foco y visibilidad; no es un uploader ni un disparador de retry.
- `create_all` puede crear `feedback_sync` faltante incluso en una BD existente;
  no altera tablas existentes ni crea intenciones históricas. El script aditivo
  explícito con `--apply` y `DATABASE_URL` aprobada es una opción del operador,
  distinta de la migración de columnas de predicción. No se aplicó a una BD desplegada.
- Revertir código no revierte datos. Se preservan archivos aceptados, CSV,
  intenciones, locks y filas para recuperación; no se ofrece SQL inverso destructivo.
  PostgreSQL/GCS reales, despliegue y recuperación histórica siguen pendientes.

## Referencias

- [Manual del flujo](../manuales/flujo_revision_audios.md): contratos y resolución de fallos.
- [Próximos pasos operativos](../manuales/flujo_revision_audios.md#próximos-pasos-del-operador): autorización y conservación de evidencia.
- [Aprobación local](../../backend/app/services/feedback.py), [cola durable](../../backend/app/services/feedback_sync.py) y [worker](../../backend/app/services/feedback_sync_worker.py).
- [Migración aditiva opcional](../../backend/scripts/migrate_feedback_sync.py).
- [ADR 0016](0016-procedencia-y-persistencia-entrenamiento.md): procedencia y persistencia del entrenamiento.
