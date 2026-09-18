# Informe RDD Hito 23: Desacoplamiento Multi-Task y Separación Espectral HPSS (Fase 1)

**Fecha:** 18 de Septiembre de 2026  
**Rama:** `feat/backend-multi-model-support`  
**Metodología:** TDD Estricto + RDD (Receipt-Driven Development)  
**Artefactos Creados y Modificados:**
- `backend/training/pipelines/multitask_mapping.py`
- `backend/training/pipelines/hpss_frontend.py`
- `backend/training/models/multitask_bioacoustic.py`
- `backend/training/recipes/car_engine_diagnostics_resnet34d_multitask_hpss.yaml`
- `backend/train_multitask_hpss.py`
- `backend/tests/test_multitask_mapping.py`
- `backend/tests/test_hpss_frontend.py`
- `backend/tests/test_multitask_model.py`
- `backend/checkpoints/car-engine-diagnostics-resnet34d-multitask-hpss/weights.pt`
- `docs/fase1_multitask_hpss_receipt.json`

---

## 1. Resumen Ejecutivo y Validación de la Hipótesis Científica

El análisis del Hito 22 identificó que la función Softmax tradicional obligaba a competir a fallas mecánicas simultáneas ($\sum p_i = 1$), aplastando la probabilidad de componentes complementarias y colapsando el F1 de las clases compuestas a 35%–40%.

En este hito se diseñó e implementó una solución desacoplada bioacústica de dos frentes bajo estricto TDD (123 pruebas unitarias e integración en verde):

1. **Frontend Espectral HPSS (3 Canales):**
   - **Física de motor optimizada:** $f_{\min} = 20.0$ Hz, $f_{\max} = 8000.0$ Hz (descartando ruido blanco inútil >8 kHz), $n_{\text{fft}} = 2048$ (resolución de 15.6 Hz/bin para capturar detonación y bielas) y $hop = 256$.
   - **Separación de fuentes:** Filtro de mediana bidimensional que descompone cada audio en:
     - **Canal 0:** Mel Spectrogram original (potencia global).
     - **Canal 1 (Armónico):** Aísla silbidos continuos de correas y bombas de dirección (2–5 kHz).
     - **Canal 2 (Percusivo):** Aísla pulsos de impacto, traqueteo metálico y clics por falta de lubricación.

2. **Arquitectura Multi-Task Decoupled:**
   - Extractor `ResNet34d` con entrada nativa de 3 canales preentrenada en ImageNet.
   - Doble cabeza supervisada:
     - Cabeza A: 13 clases diagnósticas con Focal Loss ($\gamma = 2.0$).
     - Cabeza B: 7 atributos ortogonales binarios (`has_oil_fault`, `has_belt_fault`, `has_steering_fault`, `has_ignition_fault`, `has_battery_fault`, `has_brake_fault`, `is_normal`) con `BCEWithLogitsLoss`.
   - Decodificación conjunta: Inferencia modulada por compatibilidad de atributos.

---

## 2. Impacto en el Conjunto de Prueba Ciego Congelado (SHA-256: `9d587189...`, N=207)

| Métrica | Línea Base Ciega Fase 0 (Ensamble ResNet+EffNet) | **Fase 1 (MultiTask + HPSS 3-Canales)** | Mejora Absoluta |
| :--- | :---: | :---: | :---: |
| **Test Accuracy** | 69.57% | **73.91%** | **+4.34 pp** |
| **Test Macro F1** | 69.00% | **72.80%** | **+3.80 pp** |
| **Test Weighted F1** | 69.10% | **73.13%** | **+4.03 pp** |

---

## 3. Desbloqueo Radical de las Clases Compuestas (Cuello de Botella)

| Clase Mecánica | F1 Línea Base Fase 0 | **F1 Fase 1 MultiTask HPSS** | Delta F1 |
| :--- | :---: | :---: | :---: |
| `power steering combined_serpentine belt` | 35.71% | **60.00%** | **+24.29 pp** |
| `power steering combined_no oil` | 38.71% | **52.94%** | **+14.23 pp** |
| `power steering combined_no oil_serpentine belt` | 52.94% | **60.61%** | **+7.67 pp** |
| `no oil_serpentine belt` | 40.00% | **43.48%** | **+3.48 pp** |
| `serpentine_belt` (Unitaria) | 56.52% | **82.05%** | **+25.53 pp** |
| `worn_out_brakes` (Unitaria) | 90.91% | **95.24%** | **+4.33 pp** |

---

## 4. Verificación Automatizada (123/123 Pruebas en Verde)

```
============================= test session starts ==============================
platform linux -- Python 3.14.7, pytest-9.1.1, pluggy-1.6.0
rootdir: /home/kevin/Work/fama
plugins: anyio-4.15.1
collected 123 items

backend/tests/test_api_predictions.py .....                              [  4%]
backend/tests/test_benchmark.py ....                                     [  7%]
backend/tests/test_bundle_exporter.py .                                  [  8%]
backend/tests/test_bundle_predictor.py ....                              [ 11%]
backend/tests/test_cnn_predictor.py ...                                  [ 13%]
backend/tests/test_dataset_ingestors.py ..                               [ 15%]
backend/tests/test_download.py ....                                      [ 18%]
backend/tests/test_ensemble_predictor.py ..                              [ 20%]
backend/tests/test_ensemble_tuner.py ..                                  [ 21%]
backend/tests/test_evaluate.py ...............                           [ 34%]
backend/tests/test_gem_pooling.py ....                                   [ 37%]
backend/tests/test_generic_audio_dataset.py ....                         [ 40%]
backend/tests/test_generic_split.py ..                                   [ 42%]
backend/tests/test_hpss_frontend.py ...                                  [ 44%]
backend/tests/test_model_registry.py .....                               [ 48%]
backend/tests/test_multitask_mapping.py .....                            [ 52%]
backend/tests/test_multitask_model.py ..                                 [ 54%]
backend/tests/test_prediction_model.py ..                                [ 56%]
backend/tests/test_preprocess.py ................                        [ 69%]
backend/tests/test_sanitize.py ....                                      [ 72%]
backend/tests/test_schemas.py ...                                        [ 74%]
backend/tests/test_split.py ..                                           [ 76%]
backend/tests/test_test_guard.py ....                                    [ 79%]
backend/tests/test_train.py ....................                         [ 95%]
backend/tests/test_training_schemas.py .....                             [100%]

======================= 123 passed, 2 warnings in 16.83s =======================
```
