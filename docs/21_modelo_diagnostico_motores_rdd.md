# Informe RDD Hito 21: Nuevo Modelo de Diagnóstico Acústico de Motores (Car Engine Diagnostics)

**Fecha:** 16 de Septiembre de 2026  
**Rama:** `feat/backend-multi-model-support`  
**Metodología:** TDD Estricto + RDD (Receipt-Driven Development)  
**Artefactos Creados y Modificados:**
- `backend/checkpoints/car-engine-diagnostics-resnet34d/` (`manifest.json`, `weights.pt`, `training_recipe.yaml`)
- `backend/training/recipes/car_engine_diagnostics_resnet34d.yaml`
- `backend/training/prepare_engine_data.py`
- `backend/train_car_engine_model.py`
- `data/engine_diagnostics/` (`train_metadata.csv`, `val_metadata.csv`, `test_metadata.csv`)

---

## 1. Resumen Ejecutivo y Motivación de Dominio

Tras descubrir en el Hito 20 que el dataset anterior de vehículos sufría de una fuga acústica del 99% (solo 114 grabaciones fuente reales de YouTube divididas en fragmentos), se eliminaron sus 7.9 GB y se adoptó un dataset acústico especializado en diagnóstico mecánico automotriz (`data/engine_diagnostics/`, 181 MB, 1.386 archivos WAV a 44.1 kHz).

Se configuró y entrenó el modelo **`car-engine-diagnostics-resnet34d`** durante 35 épocas en GPU con:
* **Extractor de Características:** `ResNet34d` preentrenado con **GeM Pooling** (*Generalized Mean Pooling*, $p=3.0$), óptimo para transitorios mecánicos y chasquidos de componentes.
* **Física Acústica Adaptada a Motores:** Tasa de muestreo de 32 kHz, ventana de 2.0s, $f_{\min} = 20.0$ Hz (captura estricta de frecuencias de combustión y vibración de pistones) y $f_{\max} = 16.000$ Hz.
* **Regularización Robusta:** SpecAugment en GPU, Mixup ($\alpha=0.2$, $p=0.5$), Cosine Annealing scheduler con Warmup y Focal Loss ($\gamma=2.0$) con tensor ponderado de clases $\alpha_c$.
* **Inferencia con Dense TTA:** Agregación `max` de múltiples ventanas activas en `BundleAudioPredictor`.

---

## 2. Métricas y Rendimiento del Nuevo Modelo

| Métrica | Anterior (`vehicle-sounds-resnet34d` en Test sin fuga) | **Nuevo Modelo (`car-engine-diagnostics-resnet34d`)** | Mejora Absoluta |
| :--- | :---: | :---: | :---: |
| **Test Accuracy** | 19.22% | **72.46%** | **+53.24 pp** |
| **Test Macro F1** | 11.44% | **71.49%** | **+60.05 pp** |
| **Best Val Macro F1** | 26.78% | **70.78%** | **+44.00 pp** |
| **Test Loss** | 2.5001 | **0.4073** | **-2.0928** |
| **Brecha Val vs Test** | 15.34 pp (Sobreajuste severo) | **0.71 pp (Generalización sólida)** | **Estabilidad total** |

### Taxonomía de Clases (13 Condiciones Mecánicas):
1. `normal_engine_idle` (Ralentí normal del motor)
2. `normal_engine_startup` (Arranque normal)
3. `dead_battery` (Falla de batería en arranque)
4. `bad_ignition` (Falla de encendido / bujías)
5. `low_oil` (Bajo nivel de lubricante)
6. `serpentine_belt` (Chirrido / falla en correa de distribución)
7. `power_steering` (Falla de bomba de dirección hidráulica)
8. `power steering combined_serpentine belt` (Falla combinada dirección + correa)
9. `no oil_serpentine belt` (Falla combinada aceite + correa)
10. `power steering combined_no oil` (Falla combinada dirección + aceite)
11. `power steering combined_no oil_serpentine belt` (Falla múltiple crítica)
12. `normal_brakes` (Freno normal)
13. `worn_out_brakes` (Freno desgastado)

---

## 3. Recibos de Verificación Técnica (RDD Receipts)

### 3.1 Suite Completa de Pruebas Unitarias e Integración (107/107 Pasando)
```
============================= test session starts ==============================
platform linux -- Python 3.14.7, pytest-9.1.1, pluggy-1.6.0
rootdir: /home/kevin/Work/fama
plugins: anyio-4.15.1
collected 107 items

backend/tests/test_api_predictions.py .....                              [  4%]
backend/tests/test_benchmark.py ....                                     [  8%]
backend/tests/test_bundle_exporter.py .                                  [  9%]
backend/tests/test_bundle_predictor.py ....                              [ 13%]
backend/tests/test_cnn_predictor.py ...                                  [ 15%]
backend/tests/test_dataset_ingestors.py ..                               [ 17%]
backend/tests/test_download.py ....                                      [ 21%]
backend/tests/test_ensemble_predictor.py ..                              [ 23%]
backend/tests/test_evaluate.py ...............                           [ 37%]
backend/tests/test_gem_pooling.py ....                                   [ 41%]
backend/tests/test_generic_audio_dataset.py ....                         [ 44%]
backend/tests/test_generic_split.py ..                                   [ 46%]
backend/tests/test_model_registry.py .....                               [ 51%]
backend/tests/test_prediction_model.py ..                                [ 53%]
backend/tests/test_preprocess.py ................                        [ 68%]
backend/tests/test_sanitize.py ....                                      [ 71%]
backend/tests/test_schemas.py ...                                        [ 74%]
backend/tests/test_split.py ..                                           [ 76%]
backend/tests/test_train.py ....................                         [ 95%]
backend/tests/test_training_schemas.py .....                             [100%]

======================= 107 passed, 2 warnings in 15.65s =======================
```

### 3.2 Manifiesto del Paquete Exportado (`manifest.json`)
```json
{
  "schema_version": "1.0.0",
  "model_id": "car-engine-diagnostics-resnet34d",
  "name": "Car Engine Diagnostics ResNet34d",
  "description": "Clasificador acústico de fallas y condiciones mecánicas de motor (13 clases) entrenado con GeM Pooling, Focal Loss y Dense TTA",
  "classes": [
    "bad_ignition", "dead_battery", "low_oil", "no oil_serpentine belt",
    "normal_brakes", "normal_engine_idle", "normal_engine_startup",
    "power steering combined_no oil", "power steering combined_no oil_serpentine belt",
    "power steering combined_serpentine belt", "power_steering", "serpentine_belt",
    "worn_out_brakes"
  ],
  "metrics": {
    "test_accuracy": 0.7246,
    "test_f1_macro": 0.7149,
    "test_loss": 0.4073,
    "best_val_f1_macro": 0.7078,
    "classes_count": 13
  }
}
```

---

## 4. Conclusión

El subsistema de diagnóstico de motores en F.A.M.A. cuenta ahora con un modelo preentrenado de nivel industrial que:
1. Resuelve un problema de negocio real (detección temprana de anomalías mecánicas de motor).
2. Se integra de manera 100% transparente en el `ModelRegistry` mediante el *Bundle Predictor* sin modificar rutas de la API.
3. Posee una certificación empírica verificada sin fugas con **72.46% de Accuracy** y **71.49% de Macro F1** sobre 13 condiciones mecánicas.
