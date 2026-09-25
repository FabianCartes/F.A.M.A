# Lista de Tareas: Subsistema Modular de Entrenamiento y Empaquetado de Modelos

**Cambio:** `2026-09-15-modular-training-subsystem`  
**Metodología:** TDD Estricto + RDD (Receipt-Driven Development)  
**Estado:** Planificado  

---

## Fase 1: Esquemas Declarativos y Manifiesto (Pydantic v2)

- [x] 1.1 **[TDD-Red]** Crear `backend/tests/test_training_schemas.py` con pruebas para `TrainingConfig` (validación de física de audio, proporciones de split, jerarquía de pérdidas) y `ModelManifest` (validación de especificaciones de inferencia).
- [x] 1.2 **[TDD-Green]** Implementar `backend/training/schemas/config.py` con los modelos Pydantic `AudioConfig`, `LossConfig`, `SplitConfig`, `OptimizerConfig` y `TrainingConfig`.
- [x] 1.3 **[TDD-Green]** Implementar `backend/training/schemas/manifest.py` con el esquema canónico `ModelManifest` para serialización de bundles.
- [x] 1.4 **[TDD-Refactor]** Exportar limpiamente el módulo en `backend/training/schemas/__init__.py`.

---

## Fase 2: Ingestores de Datos Polimórficos (`training/datasets/`)

- [x] 2.1 **[TDD-Red]** Crear `backend/tests/test_dataset_ingestors.py` evaluando la interfaz `DatasetIngestor`, descubrimiento recursivo en `LocalFolderPAMIngestor` y normalización de columnas canónicas (`nombre_archivo`, `clase`, `labels`, `recordist`).
- [x] 2.2 **[TDD-Green]** Implementar `backend/training/datasets/base.py` con la clase abstracta `DatasetIngestor` y el modelo `AudioRecordingMetadata`.
- [x] 2.3 **[TDD-Green]** Implementar `backend/training/datasets/local_folder.py` (`LocalFolderPAMIngestor`) con soporte para carpetas por especie y anotaciones multi-etiqueta.
- [x] 2.4 **[TDD-Green]** Implementar `backend/training/datasets/xenocanto.py` (`XenoCantoIngestor`) reutilizando la lógica de descarga segura con hash SHA-256.

---

## Fase 3: Pipeline de Audio Parametrizable (`training/pipelines/`)

- [x] 3.1 **[TDD-Red]** Crear `backend/tests/test_generic_audio_dataset.py` con pruebas para `GenericAudioDataset`:
  - Respeto de `target_sr` arbitrario (ej. 32000 Hz) y duración de ventana.
  - Determinismo estricto en `is_train=False`.
  - Retorno de tensores single-label (`torch.long`) vs multi-label (`torch.float32`).
- [x] 3.2 **[TDD-Red]** Crear `backend/tests/test_generic_split.py` evaluando el particionamiento con garantía de **Zero Recordist Leakage** en single-label y multi-label.
- [x] 3.3 **[TDD-Green]** Implementar `backend/training/pipelines/dataset.py` (`GenericAudioDataset`) desacoplado de variables globales.
- [x] 3.4 **[TDD-Green]** Implementar `backend/training/pipelines/split.py` con particionado estratificado agrupado por `recordist`.

---

## Fase 4: Empaquetado de Bundles y Auto-descubrimiento en Serving

- [x] 4.1 **[TDD-Red]** Crear `backend/tests/test_bundle_exporter.py` evaluando que `BundleExporter` genere carpetas `checkpoints/<model_id>/` conteniendo `weights.pt` (state_dict puro), `manifest.json` válido y copia de la receta YAML.
- [x] 4.2 **[TDD-Red]** Crear `backend/tests/test_bundle_predictor.py` verificando que `BundleAudioPredictor` herede de `AudioPredictor`, cargue la arquitectura e inferencia leyendo solo `manifest.json` y se auto-registre en `ModelRegistry`.
- [x] 4.3 **[TDD-Green]** Implementar `backend/training/exporters/bundle_exporter.py`.
- [x] 4.4 **[TDD-Green]** Implementar `backend/app/services/predictors/bundle_predictor.py`.
- [x] 4.5 **[TDD-Green]** Integrar `discover_and_register_bundles(checkpoints_dir)` en `backend/app/services/registry.py`.

---

## Fase 5: Verificación Integral, RDD y Suite de Regresión

- [x] 5.1 Ejecutar la suite completa de pruebas unitarias y de integración (`pytest backend/tests/ -v`).
- [x] 5.2 Verificar que los 89 tests existentes continúen pasando al 100% junto a las nuevas suites.
- [x] 5.3 Redactar el informe técnico RDD de hito en `docs/19_subsistema_entrenamiento_modular_rdd.md`.
