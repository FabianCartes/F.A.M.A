# ADR 0082: Pesos fijos de entrenamiento en tríadas estándar

Fecha: 2026-11-12. Estado: aceptado en el [plan de pesos fijos](../arquitectura/triada-pesos-fijos-plan.md) (S1). Sustituye la parte de revisión de pesos de [ADR 0070](0070-revision-0005-y-composicion-versionada-de-triadas.md); el resto de ADR 0070 sigue vigente.

## Contexto

ADR 0070 permitía revisar los pesos de una composición sin reentrenar: cada revisión creaba una fila nueva (`version` + 1). [ADR 0081](0081-intentos-de-evaluacion-conjunta-de-triadas.md) evalúa en conjunto solo la versión 1 que registra el entrenamiento, y una revisión no hereda informes. Por eso, revisar los pesos dejaba la tríada publicada sin métricas, y mantener las métricas exigiría una reevaluación al guardar los pesos, una caché de probabilidades o una vista previa de pesos.

Los pesos no intervienen en el entrenamiento de cada componente: solo se registran en el log, en el checkpoint y en la composición.

## Decisión

- Los porcentajes de la tríada se eligen solo al configurar el entrenamiento. El editor de esa configuración no cambia.
- Se retiran la ruta `POST /api/triad-compositions/{id}/weights`, el servicio `revise_weights`, su esquema de petición y la edición de pesos en Predicción. Predicción muestra la composición en modo de solo lectura.
- Las filas de `triad_composition` existentes, incluidas las de versión > 1, no se modifican ni se borran. Siguen disponibles la lectura (`GET /api/triad-compositions/{id}`), la activación por administrador de la última versión y la publicación de la última versión de cada trabajo.
- No hay migración: la columna `version`, `previous_id` y la restricción única `(job_id, version)` se conservan para las filas existentes.

## Alternativas descartadas

- **Reevaluar al guardar los pesos.** Mantiene la revisión con métricas, pero ejecuta inferencia sobre validación y prueba en cada cambio y requiere estados de evaluación por versión y su interfaz.
- **Caché de probabilidades por componente.** Recalcularía las métricas sin inferencia, pero añade un artefacto persistido nuevo con su invalidación.

## Consecuencias

- Cada composición nueva queda en versión 1 con su evaluación conjunta del entrenamiento.
- Cambiar la proporción de una tríada exige entrenar una nueva.
- Una composición que ya tenga versión > 1 sigue utilizable para inferencia, pero no tiene evaluación conjunta y así se informa.
- Un cliente que todavía llame a la ruta retirada recibe 404 sin efectos.
