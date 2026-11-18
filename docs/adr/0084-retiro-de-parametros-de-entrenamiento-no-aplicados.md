# ADR 0084: Retiro de los parámetros de entrenamiento que el pipeline no aplicaba

Fecha: 2026-11-18. Estado: aceptado. Retira de la entrada de entrenamiento web la configuración de ventaneo de [ADR 0005](0005_ventaneo_denso_hop_temporal.md) y el Pitch Shift de [ADR 0009](0009_pitch_shift_espectral_gpu_augmentation.md); esos ADR describen experimentos de scripts retirados y no el flujo web actual.

## Contexto

La vista de entrenamiento enviaba siempre `windowing_config` (`hop_seconds`, `aggregation_mode`, `gem_p`, `vad_threshold`) y `regularization_config.pitch_shift_enabled`. `POST /api/training/start` los aceptaba y los guardaba en el checkpoint, pero el entrenamiento no aplicaba ninguno:

- El aumento de datos es un `GPUSpecAugment` fijo (`backend/app/services/training.py`); no existe Pitch Shift en el pipeline.
- El ventaneo y la agregación temporal describen la inferencia sobre audios largos, no el entrenamiento, que usa un recorte central fijo. `build_evaluation_configuration` (`backend/app/services/standard_evaluation_guard.py`) solo marcaba `training_mismatch=True` cuando llegaban, y cada entrenamiento registraba «Discrepancia training/predictor: evaluación usa configuración publicada, sin cambiar filtros ni ventanas.».
- La ficha técnica del historial mostraba esos valores como parámetros del modelo.

## Decisión

- Retirar de la vista de entrenamiento los controles «Salto Temporal (s)», agregación temporal, «Exponente GeM (p)», «Umbral VAD Energético» y «Pitch Shift», junto con sus valores en los presets de dominio y sus explicaciones.
- `StartTrainingRequest` rechaza `windowing_config` (incluso `null`) y `RegularizationConfigSchema` rechaza `pitch_shift_enabled` (incluso `false`). La razón queda en el error de validación: «windowing_config fue retirado: el entrenamiento no aplica ventaneo ni agregación temporal.» y «pitch_shift_enabled fue retirado: el entrenamiento no aplica Pitch Shift.». Por HTTP, la respuesta es 422 con el detalle saneado común de las rutas web.
- La ficha técnica muestra los valores que un checkpoint antiguo registró con el sufijo «· no aplicado» y omite esas filas cuando el modelo no los registró.

## Alternativas descartadas

- **Aplicar el ventaneo en la predicción:** obliga a cambiar `TrainedModelPredictor`, su procedencia registrada (`implementation_provenance`) y a reevaluar todos los modelos publicados.
- **Implementar Pitch Shift en el entrenamiento:** cambia la calidad de los modelos sin una prueba automatizada capaz de detectar una regresión; requiere su propio experimento.
- **Quitar solo los controles de la interfaz:** la API seguiría aceptando y descartando en silencio valores que un cliente creería aplicados.

## Consecuencias

- Cambia el contrato de `POST /api/training/start`: un cliente que envíe esos campos recibe 422. La interfaz era el único emisor en el repositorio.
- Los entrenamientos nuevos guardan `training_config.windowing = null` y, si la física de audio coincide con la del predictor, `training_mismatch = false`; el aviso de discrepancia deja de aparecer.
- Los checkpoints y evaluaciones existentes no se modifican; el servicio conserva la lectura de los valores registrados para el historial.
