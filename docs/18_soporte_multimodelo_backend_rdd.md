# Informe Técnico: Arquitectura Multi-Modelo Desacoplada (Strategy + Model Registry) y Aislamiento de Persistencia Cloud en Backend FastAPI (RDD)

**Proyecto:** Framework MLOps Híbrido para Clasificación de Audio (F.A.M.A.)  
**Fecha:** Septiembre 2026  
**Fase:** Hito 18 - Refactorización de Backend: Arquitectura Multi-Modelo y Trazabilidad  
**Metodología:** ADR ([`docs/adr/0011_soporte_multimodelo_registry_strategy.md`](./adr/0011_soporte_multimodelo_registry_strategy.md)) + TDD Estricto + RDD (Receipt-Driven Development)  
**Branch:** `feat/backend-multi-model-support`  

---

## 1. Resumen Ejecutivo

En este hito se diseñó, implementó y validó formalmente la transición desde el servicio predictivo monolítico embebido en `main.py` hacia una **arquitectura desacoplada basada en Strategy Pattern y Model Registry**, cumpliendo con los estándares de **Módulos Profundos** (*Deep Modules*).

El sistema ahora soporta la selección dinámica de modelos mediante el parámetro HTTP `model_id`, manteniendo **cero regresiones en la integración con Google Cloud Storage** y asegurando la persistencia de auditoría del modelo utilizado en PostgreSQL.

---

## 2. Evidencias Auditables de Entrega (Receipts)

### 🧾 Receipt 1: Trazabilidad de Base de Datos y DTOs de Transporte
Se desacoplaron las capas de persistencia y transporte:
1. **Entidad ORM SQLAlchemy ([`backend/app/models/prediction.py`](../backend/app/models/prediction.py)):**
   - Incorporación de la columna `modelo_id = Column(String(100), nullable=True, default="chilean-birds-cnn")`.
   - Compatibilidad total con registros históricos previos.
2. **DTOs Pydantic v2 ([`backend/app/schemas/`](../backend/app/schemas/)):**
   - `ModelMetadata` y `ModelListResponse` para catálogo de modelos.
   - `PredictionResult` (objeto de valor interno) y `PredictionResponse` (contrato JSON HTTP).

*Evidencia de Pruebas Unitarias:*
```text
backend/tests/test_prediction_model.py ..                                [100%]
backend/tests/test_schemas.py ...                                        [100%]
5 passed in 0.35s
```

---

### 🧾 Receipt 2: Módulo Profundo `AudioPredictor` y Catálogo `ModelRegistry`
Se implementó la costura (*seam*) abstracta [`AudioPredictor`](../backend/app/services/predictors/base.py) y el catálogo en memoria [`ModelRegistry`](../backend/app/services/registry.py):
* **`AudioCNNPredictor` ([`cnn_predictor.py`](../backend/app/services/predictors/cnn_predictor.py)):** Extraído limpiamente desde `main.py`. Encapsula el remuestreo a $22.050\text{ Hz}$, detección de silencios por RMS, discriminación de ruido no-biológico por planitud espectral y calibración de temperatura ($T=1.5$).
* **`ChileanBirdsEnsemblePredictor` ([`ensemble_predictor.py`](../backend/app/services/predictors/ensemble_predictor.py)):** Segundo adaptador que integra el Super-Ensamble Tri-Modelo (ConvNeXt-Nano 50% + EfficientNet-B0 25% + ResNet34d 25%) bajo Dense TTA y Late Fusion, con carga perezosa (*lazy loading*) para optimizar el consumo de VRAM.
* **Resolución Dinámica:** `registry.get(model_id)` con fallback determinista al modelo por defecto (`chilean-birds-cnn`) y error controlado `ModelNotFoundError`.

*Evidencia de Pruebas Unitarias:*
```text
backend/tests/test_model_registry.py .....                               [100%]
backend/tests/test_cnn_predictor.py ...                                  [100%]
backend/tests/test_ensemble_predictor.py ..                              [100%]
10 passed in 11.79s
```

---

### 🧾 Receipt 3: Aislamiento de Persistencia Cloud (GCS) y API REST
El orquestador [`backend/app/main.py`](../backend/app/main.py) fue completamente saneado de dependencias directas de PyTorch, delegando la inferencia al `ModelRegistry` inyectado mediante `Depends(get_model_registry)`:

1. **`GET /api/models`:** Retorna el catálogo con metadatos técnicos y modelo por defecto.
2. **`POST /api/predict`:**
   - Si `model_id` es inválido: Responde `404 Not Found` de forma temprana, **garantizando que no se suba ningún archivo innecesario a Google Cloud Storage**.
   - Si `model_id` es omitido: Ejecuta el modelo por defecto manteniendo el contrato JSON histórico.
   - Si `model_id` es explícito: Resuelve la estrategia adecuada y registra la inferencia auditada en PostgreSQL.
   - Persistencia GCS: El servicio [`upload_audio_to_gcp`](../backend/app/services/storage.py) permanece 100% aislado e invariante.

*Evidencia de Pruebas de Integración (FastAPI TestClient):*
```text
backend/tests/test_api_predictions.py::test_get_models_catalogue PASSED  [ 20%]
backend/tests/test_api_predictions.py::test_predict_default_model PASSED [ 40%]
backend/tests/test_api_predictions.py::test_predict_explicit_model PASSED [ 60%]
backend/tests/test_api_predictions.py::test_predict_invalid_model_returns_404_and_aborts_gcs PASSED [ 80%]
backend/tests/test_api_predictions.py::test_predict_invalid_format_returns_400 PASSED [100%]
5 passed in 3.47s
```

---

### 🧾 Receipt 4: Suite de Regresión Completa (Cero Regresiones)
Se ejecutó la suite de pruebas completa del repositorio para verificar la interoperabilidad del núcleo bioacústico previo con la nueva arquitectura en capas del backend:

```text
============================= test session starts ==============================
platform linux -- Python 3.14.7, pytest-9.1.1, pluggy-1.6.0
rootdir: /home/kevin/Work/fama
plugins: anyio-4.15.1
collected 89 items

backend/tests/test_benchmark.py ....                                     [  4%]
backend/tests/test_cnn_predictor.py ...                                  [  8%]
backend/tests/test_download.py ....                                      [ 12%]
backend/tests/test_ensemble_predictor.py ..                              [ 15%]
backend/tests/test_evaluate.py ...............                           [ 31%]
backend/tests/test_gem_pooling.py ....                                   [ 36%]
backend/tests/test_model_registry.py .....                               [ 42%]
backend/tests/test_prediction_model.py ..                                [ 44%]
backend/tests/test_preprocess.py ................                        [ 62%]
backend/tests/test_sanitize.py ....                                      [ 66%]
backend/tests/test_schemas.py ...                                        [ 70%]
backend/tests/test_split.py ..                                           [ 72%]
backend/tests/test_train.py ....................                         [ 94%]
backend/tests/test_api_predictions.py .....                              [100%]

======================= 89 passed, 2 warnings in 25.96s ========================
```

---

## 3. Conclusión y Estado del Arte en F.A.M.A.

La arquitectura multi-modelo del backend queda formalmente **consolidada en código y verificada al 100%**. 

El sistema está listo para incorporar a futuro nuevos clasificadores (como modelos fundacionales a 32 kHz para soundscapes PAM o taxonomías exóticas) simplemente implementando una clase que herede de `AudioPredictor` y registrándola en el `ModelRegistry`, sin modificar una sola línea del orquestador HTTP ni del pipeline de persistencia cloud.
