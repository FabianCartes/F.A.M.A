# ADR 0015: Fallos explícitos de inferencia y validación aislada

* **Estado:** Aceptado
* **Área:** Inferencia, contrato HTTP y validación del backend

## Contexto y decisión

Los predictores de motor y de bundles podían devolver clases y confianzas plausibles cuando faltaban pesos o fallaba la inferencia. Esa simulación ocultaba la indisponibilidad del modelo y podía persistirse como una predicción real. Se elimina el resultado fabricado, sin introducir modo de demostración: pesos ausentes, corruptos o incompatibles producen `ModelWeightsError`; los errores de ejecución se propagan explícitamente. La carga de componentes debe ser completa y compatible, no una carga parcial presentada como inferencia válida.

El silencio o la ausencia legítima de señal siguen siendo resultados válidos, pero no sustituyen la disponibilidad de los modelos requeridos. La inferencia usa decodificación estricta para evitar que audio corrupto se transforme en silencio sintético; el cargador compartido conserva su modo tolerante por defecto para entrenamiento. No se modificó el comportamiento productivo de entrenamiento ni se eliminaron alternativas basadas en modelos reales. Autenticación, descargas y reordenamiento de cargas a GCS quedaron fuera del alcance.

## Contrato y consecuencias

- HTTP distingue entrada malformada tipada (`MalformedAudioError`, 400), pesos no disponibles (`ModelWeightsError`, 503) y fallos inesperados de ejecución (500). No todo error de decodificación está normalizado como 400: los errores no tipados permanecen explícitos como 500. Las predicciones fallidas no se persisten; el contrato de éxito se conserva. Esto no implica revertir una carga previa a GCS.
- El registro puede elegir un checkpoint entrenado como modelo predeterminado, incluso de otro dominio. Las pruebas deterministas del endpoint deben controlar y restaurar explícitamente el predictor, sin confundir respuestas simuladas de prueba con evidencia de calidad real.
- Las pruebas de integración de base de datos crean filas propias con identificadores dinámicos y limpian solo sus datos, restaurando el registro. Deben ejecutarse contra una base desechable identificada explícitamente, no contra la configuración por defecto ni datos reales.
- Los localizadores de checkpoints de prueba se anclan a `__file__`, no al directorio de ejecución. La presencia de un archivo no prueba compatibilidad ni calidad; un salto por localización incorrecta tampoco prueba que falten pesos.

## Evidencia y límites aceptados

La verificación integral independiente final registró **379 pruebas aprobadas, cero fallos y cero omisiones**, en CPU, con PostgreSQL desechable, filas propias y eliminación confirmada del contenedor aislado. Esta evidencia sustituye los resultados parciales anteriores; no se volvió a ejecutar la suite para esta migración documental.

La comprobación real de **Chucao con confianza >= 0,95**, sin resultado simulado, pasó únicamente con el checkpoint confiable `backend/checkpoints/fama_efficientnet_b0_1790539191_efficientnet_b0_best.pt` y el audio `audios_prueba/audio_prueba.wav`, seleccionados explícitamente para esa ejecución. No demuestra calidad sobre un corpus representativo, ejecución en GPU ni funcionamiento del contenedor de inferencia; usar PostgreSQL en Docker no constituye esa última prueba. Estos límites se aceptaron como seguimientos separados, junto con la advertencia no bloqueante **R3-001** sobre decodificación y la observación de activación de un modelo inexistente, cuyo comportamiento productivo no se cambió.

## Trazabilidad

Las unidades de trabajo fueron revisadas y reconocidas individualmente; **no se afirma aprobación RDD agregada de la rama**:

| Unidad | Commit |
| --- | --- |
| Decodificación estricta optativa | `1f6354b` |
| Predictor de motor sin simulación | `33b8345` |
| Predictor de bundles sin simulación | `b5c0787` |
| Contrato HTTP y documentación | `78114e4` |
| Expectativas de pruebas de entrenamiento, sin cambios productivos | `4d339c3` |
| Selección controlada de predictor y prueba real separada | `472fd46` |
| Filas propias y seguridad de integración PostgreSQL | `78cf664` |
| Localizadores de checkpoints independientes del directorio de ejecución | `1541683` |

Este ADR conserva la decisión y la evidencia material del registro `odd/tasks/remove-predictor-simulation.md`; Git conserva el historial completo del registro operativo. Las revisiones individuales no autorizan publicación, PR ni integración de la rama.
