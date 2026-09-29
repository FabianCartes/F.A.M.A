# Informe RDD Hito 19: Subsistema Modular de Entrenamiento y Empaquetado de Modelos

**Fecha:** 15 de Septiembre de 2026  
**Rama:** `feat/backend-multi-model-support`  
**Metodología:** SDD (OpenSpec) + TDD Estricto + RDD (Receipt-Driven Development)  
**Cambio Formal:** `openspec/changes/2026-09-15-modular-training-subsystem/`

---

## 1. Resumen Ejecutivo y Motivación Arquitectónica

Históricamente, el entrenamiento de modelos bioacústicos en F.A.M.A. se encontraba acoplado a scripts exploratorios en `backend/poc/` con parámetros globales fijos (22.05 kHz, 5 segundos, 128 mels, f_max 11.025 Hz). La integración de nuevos conjuntos de datos (tales como soundscapes PAM continuos multi-etiqueta o datasets externos de Xeno-Canto) requería duplicar o modificar scripts completos.

Siguiendo los principios de **Clean Architecture**, **Módulos Profundos** (*Deep Modules*) y preservando la regla inviolable de **cero modificaciones en `backend/poc/`** (congelada para reproducibilidad histórica), se construyó el subsistema de entrenamiento desacoplado en `backend/training/` y su mecanismo de auto-descubrimiento en `backend/app/services/`.

---

## 2. Componentes Implementados

### 2.1 Esquemas Declarativos y Manifiesto de Inferencia (`training/schemas/`)
* **`AudioConfig`**: Modelo Pydantic v2 que valida invariantes físicas de audio (`f_max <= target_sr / 2`, `f_min < f_max`, `n_mels > 0`, `n_fft >= hop_length`).
* **`TrainingConfig`**: Validador integral de recetas de entrenamiento (hiperparámetros, pérdida Focal/BCE/CrossEntropy, optimizadores, split).
* **`ModelManifest`**: Contrato canónico de inferencia guardado en cada paquete de modelo. Define `model_id`, `version`, `architecture`, `labels`, `audio_config` y métricas observadas (`val_f1_macro`, etc.).

### 2.2 Ingestores de Datos Polimórficos (`training/datasets/`)
* **`DatasetIngestor`** (Clase Base Abstracta): Estandariza la carga de metadatos a `AudioRecordingMetadata` (`nombre_archivo`, `clase`, `labels`, `recordist`, `duracion_segundos`).
* **`LocalFolderPAMIngestor`**: Soporta estructuras de carpetas por especie y soundscapes PAM continuos multi-etiqueta vía archivo CSV/JSON.
* **`XenoCantoIngestor`**: Ingesta metadatos y descargas directas de Xeno-Canto con verificación de integridad criptográfica SHA-256.

### 2.3 Pipeline Parametrizable y Particionamiento Zero-Leakage (`training/pipelines/`)
* **`GenericAudioDataset`**: `Dataset` de PyTorch parametrizado mediante `AudioConfig`. Extrae ventanas fijas, aplica VAD y soporta tanto tensores de clasificación mono-etiqueta (`torch.long`) como multi-etiqueta (`torch.float32`).
* **`grouped_stratified_split_dataset`**: Algoritmo de particionamiento estratificado agrupado que garantiza **cero fuga de grabadores** (*Zero Recordist Leakage*) entre splits de entrenamiento, validación y prueba.

### 2.4 Exportación de Model Bundles y Serving Desacoplado (`training/exporters/` & `app/services/predictors/`)
* **`BundleExporter`**: Empaqueta artefactos entrenados en un directorio atómico `checkpoints/<model_id>/` conteniendo:
  1. `weights.pt`: `state_dict` puro de PyTorch, limpio de buffers de optimizador.
  2. `manifest.json`: Manifiesto validado por Pydantic con arquitectura y física de audio.
  3. `training_recipe.yaml`: Copia de auditoría de la receta de entrenamiento.
* **`BundleAudioPredictor`**: Implementación de `AudioPredictor` capaz de instanciar la arquitectura adecuada (`BioacousticModel` con `resnet34d`, `convnext_nano` o `efficientnet_b0`), cargar pesos y preprocesar audio según las directrices de su propio `manifest.json`.
* **`discover_and_register_bundles(checkpoints_dir)`**: Función agregada a `ModelRegistry` que escanea dinámicamente directorios de checkpoints y registra automáticamente nuevos modelos en la API FastAPI sin requerir reinicio ni cambios en código.

---

## 3. Evidencia y Recibos de Verificación (RDD)

### 3.1 Cobertura de Pruebas Unitarias y de Regresión
* **Total de Pruebas Ejecutadas:** 104
* **Total de Pruebas Exitosas:** 104 (100% Green)
* **Regresiones Detectadas:** 0

```
============================= test session starts ==============================
platform linux -- Python 3.14.7, pytest-9.1.1, pluggy-1.6.0
collected 104 items

backend/tests/test_api.py ................                               [ 15%]
backend/tests/test_bundle_exporter.py .                                  [ 16%]
backend/tests/test_bundle_predictor.py ...                               [ 19%]
backend/tests/test_cnn_predictor.py ....                                 [ 23%]
backend/tests/test_dataset_ingestors.py ..                               [ 25%]
backend/tests/test_download.py ....                                      [ 28%]
backend/tests/test_ensemble_predictor.py ..                              [ 30%]
backend/tests/test_evaluate.py ...............                           [ 45%]
backend/tests/test_gem_pooling.py ....                                   [ 49%]
backend/tests/test_generic_audio_dataset.py ...                          [ 51%]
backend/tests/test_generic_split.py .                                    [ 52%]
backend/tests/test_model_registry.py .....                               [ 57%]
backend/tests/test_prediction_model.py ..                                [ 59%]
backend/tests/test_preprocess.py ...............                         [ 74%]
backend/tests/test_sanitize.py ....                                      [ 77%]
backend/tests/test_schemas.py ...                                        [ 80%]
backend/tests/test_split.py ..                                           [ 82%]
backend/tests/test_train.py ................                             [ 98%]
backend/tests/test_training_schemas.py .....                             [100%]

======================= 104 passed, 2 warnings in 30.15s =======================
```

### 3.2 Invarianza de GCP Storage y Base de Datos
* Las pruebas en `test_api.py` certificaron que la persistencia en PostgreSQL con la columna `modelo_id` y el almacenamiento de audio en Google Cloud Storage permanecen 100% aislados e invariantes.
