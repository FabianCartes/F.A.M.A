# Integración MVP — unidad posterior: tríada estándar combinada con ajuste de pesos

Estado: **planificada, no iniciada**. Se ejecuta después de cerrar la etapa e y antes o junto con la etapa f (migración 0005); requiere autorización explícita de Kevin para implementar. Rama `mvp`, sin push ni PR.

## Problema

- La tríada estándar se entrena desde `TrainingView`, con tres arquitecturas y un peso por componente (`EfficientNet-B0`, `ConvNeXt-Nano` y `ResNet-34d`; para motores, `ResNet-34d`, `EfficientNet-B0` y `PANNs-CNN14`).
- El backend registra **tres `Modelo` independientes** (`backend/app/services/training.py`, bucle de persistencia). El peso elegido solo se guarda en el checkpoint como `ensemble_weight` (junto a `ensemble_models` y `job_id`); ningún predictor lo lee.
- La combinación de los tres modelos con revisión de pesos existía solo para la tríada **importada** (`ImportedTriad`, endpoint `triad-weights`, `TriadWeightRevision`). La etapa d retiró su creación y la etapa e su publicación, interfaz y endpoint, por la decisión de no mantener compatibilidad histórica.
- Ninguna etapa del plan original (f, g, h) cubre la tríada combinada en el flujo estándar. La subunidad «d3 tríada» del plan original dependía de los snapshots importados, que la etapa d sustituyó por `partition_version`.

## Resultado esperado

Un investigador asignado al dataset entrena una tríada estándar, la ve en el catálogo de predicción como **un solo modelo combinado**, predice con ella y puede **revisar sus pesos** sin reentrenar. Cada revisión crea una nueva versión identificable, y la anterior se conserva para la trazabilidad del historial y del feedback.

## Alcance propuesto

1. **Composición persistida.** Registro de la composición: dataset, `partition_version`, `job_id`, los tres `id_modelo` ordenados, los pesos (suma 1, no negativos), el autor, la fecha y la versión anterior en caso de revisión. Una composición revisada es una fila nueva; nunca se edita en el mismo lugar.
2. **Creación automática al finalizar el entrenamiento.** Cuando los tres componentes de un mismo `job_id` quedan registrados con hash válido, se crea la composición inicial con los `ensemble_weight` de sus checkpoints. Un entrenamiento parcial (detenido o fallido) no crea la composición.
3. **Predictor.** Se reutiliza la fusión de probabilidades de `ImportedTriadPredictor`: exactamente tres `TrainedModelPredictor`, mismas clases, pesos válidos y rechazo explícito sin probabilidades inventadas. Se renombra o generaliza a un predictor de tríada estándar; no se reintroducen la admisión por dueño ni los manifiestos importados.
4. **Registry y catálogo.** La composición se publica en `publish_from_db` como `metadata_only`, sin cargar pesos, con su propio id de catálogo, y solo para quien tiene acceso al dataset (`ResourceAccess`). Conserva el prewarm, la carga diferida y la caché de hashes de cada componente; si un componente queda bloqueado (hash ausente, inválido o cambiado), la composición también queda bloqueada.
5. **Revisión de pesos.** Nuevo endpoint estándar, autorizado por asignación al dataset (no por dueño). Valida tres pesos y responde con la nueva versión. No reentrena ni modifica checkpoints.
6. **Predicción, historial y feedback.** `/api/predict` acepta el id de la composición; `AccesoPrediccion`, historial y feedback funcionan igual que para un modelo individual. El historial de una versión no mezcla predicciones de otra.
7. **Frontend.** `PredictionView` muestra la tríada como un modelo con sus tres componentes y pesos, y ofrece la revisión de pesos reutilizando `TriadComponentsEditor`/`triadWeightsFromPercents`. Tras una revisión, selecciona la nueva versión.

## Fuera de alcance

- Recuperar tríadas importadas existentes, sus manifiestos o su dueño. Sus filas y archivos se conservan sin borrar.
- Evaluación automática de la composición en test (se puede planificar después; hoy no hay evaluación del ensamble estándar).
- Ensambles de cantidad distinta de tres componentes, y ensambles declarados (`FAMA_ENSEMBLES_JSON`), que siguen como están.
- Push, PR, despliegue, entrenamiento real y datos reales.

## Decisiones abiertas (resolver antes de implementar)

1. **Dónde se persiste la composición.** Recomendada: una tabla nueva incluida en la migración aditiva 0005 de la etapa f, que además debe revisar si todavía corresponde migrar `training_snapshot`, `training_snapshot_member` e `imported_model_source`, que el flujo activo ya no usa. Alternativa: derivar la composición solo de `job_id` y `ensemble_weight` de los checkpoints. No requiere migración, pero no permite revisiones de pesos persistentes. Por eso esta unidad conviene ordenarla junto con f.
2. **Identidad en el catálogo.** Recomendada: un id propio de composición (por ejemplo `fama_triad_<id>`), distinto de `fama_trained_model_<id>`, para no confundir componentes con composiciones.
3. **Activación como modelo por defecto.** Recomendada: la composición se puede activar como cualquier modelo, solo por un administrador.

La decisión 1 tiene consecuencias de esquema y se registra en un ADR nuevo (continúa desde `0069`).

## Pruebas primero (interfaces públicas, CPU/SQLite en memoria, runner aislado)

- Un entrenamiento de tríada completo crea una composición con los pesos del checkpoint; uno detenido o fallido no la crea.
- `/api/models` lista la composición sin cargar pesos (`metadata_only`) solo para usuarios asignados; un usuario sin asignación no la ve y recibe 404 al predecir.
- La predicción combinada pondera las probabilidades de los tres componentes; con clases incompatibles o un componente bloqueado por hash, se rechaza sin resultado inventado.
- La revisión de pesos crea una versión nueva, rechaza pesos inválidos (suma distinta de 1, negativos, cantidad distinta de tres) y conserva el historial de la versión anterior.
- El historial y el feedback de una composición exigen `require_prediction`/`require_feedback`.
- Frontend (Vitest): la composición aparece como un solo modelo, la revisión de pesos llama al endpoint estándar y selecciona la nueva versión, y no se hace ninguna solicitud con `private_only`.

## Riesgo

Item 2 (autorización de modelos combinados y de su revisión) e item 1 si se agrega una tabla (esquema persistido). Requiere verificación independiente y un commit propio por unidad de riesgo.

## Referencias

- Seguimiento de la etapa e: [integracion-mvp-e-prediccion-plan.md](integracion-mvp-e-prediccion-plan.md).
- Etapa d: [integracion-mvp-d-snapshots-plan.md](integracion-mvp-d-snapshots-plan.md).
- Fusión reutilizable: `backend/app/services/predictors/imported_triad_predictor.py`; editor de pesos: `frontend/components/training/TriadComponentsEditor.tsx`.
