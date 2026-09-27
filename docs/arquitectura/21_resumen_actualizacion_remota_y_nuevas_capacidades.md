# Resumen Técnico de Integración: Novedades del Repositorio y Resolución de Conflictos

Este documento detalla todas las nuevas implementaciones, cambios arquitectónicos y correcciones aplicadas al integrar los 16 commits remotos de **Kevin Cárdenas** en la rama principal de F.A.M.A.

---

## 1. Resumen Ejecutivo de las Novedades

El compañero de equipo implementó dos grandes hitos de ingeniería acústica y arquitectura de software:

1. **Arquitectura Multi-Modelo y Desacoplamiento de Inferencia (Patrón Strategy + Model Registry):**
   - Se abandonó el acoplamiento rígido a un único modelo o a rutas globales en disco.
   - Se introdujo la interfaz abstracta `AudioPredictor` y un catálogo dinámico `ModelRegistry` que permite listar, registrar e invocar diferentes modelos de inferencia mediante HTTP (`GET /api/models` y `POST /api/predict?model_id=...`).
   - Se introdujo el concepto de **Model Bundles**: carpetas autocontenidas con un archivo `manifest.json` y `weights.pt` que se descubren automáticamente al iniciar.

2. **Subsistema Modular de Entrenamiento (`backend/training/`):**
   - Un pipeline de entrenamiento moderno desacoplado de scripts estáticos.
   - Configuración declarativa mediante recetas YAML (`training/recipes/*.yaml`).
   - Esquemas Pydantic para validación de hiperparámetros (`AudioConfig`, `AugmentationConfig`, `LossConfig`, `TrainingConfig`).
   - Soporte para ingesta de datos genérica (`GenericAudioDataset`, soporte Xeno-Canto y carpetas locales).
   - Técnicas avanzadas de data augmentation: **Mezcla aditiva de fondo (Additive Mixing)** y **Balanceo energético por RMS**.
   - Frontend espectral **HPSS de 3 canales** (Harmonic-Percussive Source Separation) en GPU.

3. **Nuevo Dominio de Aplicación: Diagnóstico Acústico de Fallas de Motores Vehiculares:**
   - Ampliación del proyecto más allá de la bioacústica hacia el análisis de sonidos de maquinaria/motores (13 clases mecánicas).
   - Entrenamiento y calibración de un **Super-Ensamble Tri-Modelo All-RMS-Balanced** (ResNet34d 60% + EfficientNet-B0 10% + PANNs CNN14 30%) alcanzando **81.16% de Accuracy** y **80.33% de Macro F1**.
   - Modelos PANNs (Pretrained Audio Neural Networks) adaptados mediante Transfer Learning.

4. **Consolidación Documental y Trazabilidad:**
   - 14 recibos técnicos de experimentos guardados en `docs/receipts/`.
   - ADR 0011 formalizando la arquitectura `ModelRegistry` y el patrón Strategy.
   - Informes técnicos `docs/18_soporte_multimodelo_backend_rdd.md` y `docs/19_subsistema_entrenamiento_modular_rdd.md`.
   - Reorganización de imágenes de matrices de confusión en `docs/images/`.

---

## 2. Detalle de Nuevos Módulos y Archivos

### A. Capa de Inferencia y Serving
| Archivo | Propósito |
| :--- | :--- |
| `backend/app/services/predictors/base.py` | Clase base abstracta `AudioPredictor` que define el contrato `predict(audio_path) -> PredictionResult` y `metadata -> ModelMetadata`. |
| `backend/app/services/predictors/cnn_predictor.py` | Estrategia concreta para el modelo convolucional baseline `AudioCNN`. |
| `backend/app/services/predictors/ensemble_predictor.py` | Estrategia concreta para el ensamble bioacústico de aves chilenas (88.68% F1). |
| `backend/app/services/predictors/engine_ensemble_predictor.py` | Estrategia para el ensamble de motores de 13 clases mecánicas. |
| `backend/app/services/predictors/bundle_predictor.py` | Predictor genérico capaz de leer cualquier carpeta con `manifest.json` y cargar su red dinámicamente. |
| `backend/app/services/registry.py` | Gestor del catálogo en memoria con inyección de dependencias FastAPI y autodescubrimiento de bundles. |
| `backend/app/schemas/model_info.py` | Esquemas Pydantic `ModelMetadata` y `ModelListResponse`. |

### B. Subsistema de Entrenamiento (`backend/training/`)
| Módulo | Componentes |
| :--- | :--- |
| `training/schemas/` | `config.py` y `manifest.py` con validación estricta de hiperparámetros y metadatos de exportación. |
| `training/datasets/` | `base.py`, `local_folder.py`, `xenocanto.py`. Abstracciones de fuentes de audio. |
| `training/pipelines/` | - `hpss_frontend.py`: Separación armónica-percusiva en 3 canales.<br>- `additive_mixing.py`: Mezcla aditiva con audio de fondo.<br>- `multitask_mapping.py`: Mapeo multi-etiqueta (falla mecánica + subsistema).<br>- `dataset.py`: `GenericAudioDataset` parametrizado por `AudioConfig`.<br>- `split.py`: Particionamiento estratificado a prueba de fugas de datos.<br>- `losses.py`: Soporte para Cross-Entropy, Focal Loss y Asymmetric Loss (ASL). |
| `training/models/` | `multitask_bioacoustic.py` (ResNet34d/EfficientNet multitarea) y `panns_cnn14.py` (PANNs CNN14). |
| `training/exporters/` | `bundle_exporter.py`: Exportación a bundles desacoplados con pesos y manifiesto. |
| `training/recipes/` | Recetas YAML para entrenamiento reproducible de motores con ConvNeXt, EfficientNet y ResNet. |

---

## 3. Conflictos Detectados y Errores Corregidos

Durante el merge y las pruebas automáticas se identificaron y solucionaron 5 incidencias:

### 1. Colisión de nombres en la documentación
- **Conflicto:** El documento local previo `docs/18_modelo_de_producto...` colisionaba con el nuevo `docs/18_soporte_multimodelo_backend_rdd.md`.
- **Solución:** Se renombró de forma segura el documento de arquitectura de producto a `docs/20_modelo_de_producto_despliegue_y_arquitectura_operativa.md`.

### 2. Error de importación `NameError: name 'Any' is not defined`
- **Ubicación:** `backend/training/pipelines/dataset.py:83`.
- **Causa:** El código remoto utilizaba `Optional[Any]` en la firma del método pero olvidó importar `Any` de `typing`.
- **Solución:** Se corrigieron los imports añadiendo `Any`.

### 3. Error de importación `NameError: name 'Optional' is not defined`
- **Ubicación:** `backend/training/exporters/bundle_exporter.py:35`.
- **Causa:** Se utilizaba `Optional[Dict[str, Any]]` sin importar `Optional`.
- **Solución:** Se añadió `Optional` a los imports de `typing`.

### 4. Falso positivo de Ruido Blanco en audios cortos acolchados con ceros
- **Ubicación:** `cnn_predictor.py`, `ensemble_predictor.py` y `engine_ensemble_predictor.py`.
- **Causa:** Cuando un audio tiene menos de 5 segundos (por ejemplo 2 segundos), la función de preprocesamiento `load_and_fix_length` rellena el resto con ceros. Al calcular la planitud espectral (`spectral_flatness`) sobre señales con segmentos mudos, el valor matemático resultante tiende a 1.0 (máxima planitud), provocando que señales reales (como aves o tonos de prueba) se clasificaran erróneamente como `"Ruido / Señal no biológica"`.
- **Solución:** Se optimizó el cálculo para evaluar la planitud espectral únicamente sobre las porciones activas de la señal (`waveform[np.abs(waveform) > 1e-4]`), manteniendo la detección de ruido blanco real sin clasificar erróneamente audios válidos cortos.

### 5. Unificación armónica en `backend/app/main.py`
- **Conflicto:** En `origin/main` el archivo `main.py` había sido simplificado solo para inferencia con `ModelRegistry`, perdiéndose la configuración de CORS para el frontend Next.js, el evento `lifespan` de precarga, y los endpoints de Ingesta GCS, Entrenamiento y Dashboard MLOps.
- **Solución:** Se fusionaron ambos mundos:
  - Se mantuvo `CORSMiddleware` (imprescindible para el frontend).
  - Se preservó el catálogo `ModelRegistry` y el endpoint `GET /api/models`.
  - El endpoint `POST /api/predict` ahora soporta tanto el parámetro de consulta `model_id` como la invocación estándar por defecto, enriqueciendo la respuesta JSON con la información requerida tanto por el contrato de catálogo como por las vistas del frontend (`modelo`, `is_fallback`, `modelos_activos`, `modelo_id`).
  - Se conservaron todas las rutas de Ingesta, Entrenamiento y Dashboard MLOps.

---

## 4. Estado de Validación y Calidad del Software

- **Backend PyTest:** **174 pruebas pasadas**, 3 omitidas (tests de pesos que requieren checkpoints locales pesados), **0 fallas** (100% éxito).
- **Frontend TypeScript:** `npx tsc --noEmit` completado con **0 errores de compilación**.
- **Control de Versiones:** Rama `main` sincronizada con commit merge `f30a5bb`. Se preserva copia de seguridad íntegra en la rama local `backup-local-work`.
