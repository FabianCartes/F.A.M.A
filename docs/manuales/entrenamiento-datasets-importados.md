# Entrenamiento de ZIP publicados y lectura de modelos importados históricos

**Estado vigente — integración MVP d:** la entrada paralela de entrenamiento importado está retirada. Los nuevos entrenamientos usan el dataset publicado en el catálogo estándar y una `partition_version`. No se crean snapshots ni preparaciones importadas desde HTTP o desde el servicio de entrenamiento. **Los modelos y artefactos históricos se conservan para lectura; no se borran tablas, filas, checkpoints ni almacenes.**

## Camino vigente para nuevos entrenamientos

1. Importe y publique el ZIP mediante el flujo de ingestión. Una confirmación local no sustituye la publicación completa en el catálogo compartido.
2. Seleccione el dataset publicado en `GET /api/training/datasets`, con los permisos habituales de `ResourceAccess`.
3. Previsualice y guarde las particiones estándar en `/api/training/datasets/{dataset_name}/partitions`, aceptando explícitamente sus advertencias cuando corresponda.
4. Inicie por separado con `POST /api/training/start`, indicando `dataset_name` y la `partition_version` guardada. Se mantiene el modelo individual, la tríada fija y el ensamble dinámico del flujo estándar.
5. Consulte progreso e historial. `started` solo acredita admisión, no entrenamiento terminado, evaluación, publicación, activación ni calidad ML.

Ejemplo de contrato, no autorización para ejecutar trabajos operacionales:

```json
{
  "dataset_name": "Bosque",
  "partition_version": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
  "architecture": "AudioCNN",
  "epochs": 1,
  "seed": 42
}
```

Para una tríada fija use `is_tri_model: true` sobre esa misma versión estándar. La versión conserva referencias y hashes; si cambia la copia local de audio se rechaza con un error de contenido local. Publicar o particionar no demuestra independencia estadística ni calidad del modelo. Un ZIP sin metadata de grabación no recupera por sí solo esa procedencia.

El flujo CSV estándar con `prepared_version` y su selección histórica explícita no se retira con este cambio. Consulte [integración del flujo de entrenamiento](integracion-flujo-entrenamiento.md) para sus prerrequisitos y límites.

## Contratos retirados

| Entrada histórica | Resultado vigente |
| --- | --- |
| `/api/training/imported/snapshots` y sus rutas de descriptor, miembros y preparaciones | Rutas no registradas: HTTP 404. |
| `GET /api/training/datasets?include_imported=true` | HTTP 422 si se suministra `include_imported` (también `false` o vacío); no se ignora ni añade colecciones privadas. |
| `imported_dataset_id`, `snapshot_id`, `imported_prepared_version` en el cuerpo de inicio o sus miembros | HTTP 422, incluso si el valor es `null`; no se inicia silenciosamente el dataset predeterminado. |
| Argumentos importados de `TrainingService.start_training` | Retirados; los consumidores nuevos deben usar `dataset_name` y particiones estándar. |
| Composición automática importada al terminar el worker | Retirada; no se crean nuevas asociaciones `ImportedModelSource` ni evaluaciones importadas desde ese worker. |

El esquema Python informa «La entrada de entrenamiento importado fue retirada; use dataset_name y partition_version.». El manejador HTTP existente sanitiza las validaciones con `{"detail":"Solicitud de autenticación inválida."}`; no interpretar ese mensaje genérico como admisión ni reintentar cambiando automáticamente la fuente.

## Lectores históricos conservados

Los siguientes contratos siguen atendiendo modelos importados **ya existentes**, sujetos a identidad, propiedad, integridad y evaluación:

- `GET /api/models?include_imported=true` y `?private_only=true`: catálogo de modelos del propietario. Este `include_imported` no es el parámetro retirado del catálogo de datasets de entrenamiento.
- `GET /api/training/history?include_imported=true`: historial privado con su procedencia persistida.
- `POST /api/predict?model_id=<ID o alias exacto>`: lectura y predicción del modelo histórico propio; no cambia el default global.
- Feedback de predicciones históricas y revisión de pesos de composiciones existentes mediante `/api/training/models/{id}/triad-weights`.
- Verificación de checkpoints, clases, perfiles, informes y asociaciones históricas. Un registro incompleto no se convierte en un modelo público.

Los importados siguen privados e inactivos globalmente. Su activación devuelve `{"success":false,"error":"Los modelos importados no pueden activarse globalmente."}` sin cambiar activos. La autorización de nuevos trabajos, progreso y parada usa el flujo estándar por usuario/dataset, sin la antigua rama `current_source_owner`.

## Retención y operación

Conserve conjuntamente la base de datos, checkpoints, snapshots y preparaciones referenciados. `TrainingSnapshots`, `ImportedDatasetPreparation`, `ImportedTrainingSource`, `ImportedModelSource` y los lectores de tríadas no se eliminan mientras predicción, historial, evaluación, feedback o revisión de pesos los utilicen. Sus raíces de servidor siguen siendo necesarias para esos lectores: `FAMA_IMPORT_ROOT`, `FAMA_TRAINING_SNAPSHOT_ROOT` y `FAMA_IMPORTED_PREPARED_ROOT`.

Esta retirada no migra ni elimina tablas/datos, no ejecuta GC, no transfiere propietarios y no autoriza cambios de permisos o DDL reales. La retirada posterior de lectores y del bootstrap de tablas es otra etapa. No elimine almacenes para «limpiar» el flujo nuevo.

## Referencias y alcance de evidencia

- [Plan vigente de integración MVP d](../arquitectura/integracion-mvp-d-snapshots-plan.md).
- [Snapshots locales históricos](snapshots-locales-entrenamiento.md).
- [Preparaciones importadas históricas](preparacion-datasets-importados.md).
- [Plan histórico T1–T5 y su Log](../arquitectura/entrenamiento-datasets-importados-plan.md), [ADR 0052](../adr/0052-preparacion-local-de-datasets-importados.md) y [ADR 0053](../adr/0053-procedencia-durable-de-entrenamiento-importado.md).

Los recibos T1–T5 documentan cortes anteriores, no la vigencia de sus entradas retiradas. Las comprobaciones de integración d usan SQLite en memoria, ZIP/WAV y checkpoints CPU sintéticos, proceso de entrenamiento diferido y el runner aislado. Los artefactos históricos sintéticos sirven para probar lectura e inferencia sin volver a abrir la entrada retirada; sus pesos no acreditan aprendizaje ni calidad ML. Los comandos y resultados nuevos deben consultarse en el cierre de d, sin atribuirles Docker/Python 3.12, GPU, PostgreSQL real, servicios remotos o entrenamiento operacional.
