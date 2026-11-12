# ADR 0081: Intentos de evaluación conjunta de composiciones de tríada

Fecha: 2026-11-11. Estado: aceptado en el [plan B de evaluación conjunta](../arquitectura/triada-evaluacion-plan.md) (S2–S4).

## Contexto

Los informes de `model_evaluation` pertenecen a un `id_modelo` y a un único hash de checkpoint. Una composición estándar de tríada (`triad_composition`; las importadas siguen [ADR 0076](0076-identidad-inmutable-de-composiciones-importadas.md)) fusiona tres checkpoints con pesos versionados y no tiene fila `Modelo`. Su exactitud debe calcularse por grabación sobre la salida combinada, no promediando las accuracies individuales.

## Decisión

- Tabla aditiva `triad_composition_evaluation` (migración `0007_triad_evaluation`): un intento por composición, versión y split (`val`/`test`), con estados `pending/running/completed/failed`, las mismas restricciones de informe/error/tiempos que `model_evaluation` y `schema_version = 2`.
- La identidad congela IDs ordenados de los componentes, sus hashes de checkpoint y los pesos. `checkpoint_sha256` es el digest SHA-256 de checkpoints ordenados, pesos y clases; nunca el hash del primer componente.
- Crear o completar un intento exige que la composición almacenada conserve versión, orden, pesos y dataset, y que cada `Modelo` conserve su hash registrado. Una revisión de pesos es otra composición y no hereda informes.
- El cálculo reutiliza `RecordingEvaluator` y `TriadPredictor`; la evaluación de entrenamientos nuevos corre en el trabajo de entrenamiento, fuera de la petición HTTP. Las lecturas no ejecutan inferencia.

## Alternativas descartadas

- **Hacer nullable `model_evaluation.id_modelo`.** Cambia un contrato consumido por catálogo, guardas de publicación y reevaluación.
- **Crear una fila `Modelo` para la tríada.** Inventaría un artefacto que no existe y entraría al catálogo como modelo individual.

## Consecuencias

- La disponibilidad para inferencia, la publicación y la activación no dependen del informe conjunto.
- Las composiciones existentes y las revisiones de pesos quedan sin informe; una acción explícita de evaluación requiere alcance propio.
- La migración se probó con SQLite en memoria; PostgreSQL real queda pendiente de la verificación operativa habitual.
