# Plan ODD: Selector Dinámico de Ensamble (1 a 3 Modelos) con Ponderaciones Personalizadas

> **Metodología:** Organic Driven Development (ODD) + Test-Driven Development (TDD) + Receipt-Driven Development (RDD)  
> **Rama:** `feat/dynamic-ensemble-selector`  
> **Estado:** Completado (100% Verificado con TDD Estricto + RDD)

---

## 1. Contexto y Diagnóstico Arquitectónico

### El Problema (Rigidez en Ensamble de Modelos)
Actualmente, el entrenamiento y la inferencia en F.A.M.A. presentan un acoplamiento rígido en la selección de modelos:
* En el frontend (`TrainingView.tsx`), el usuario solo puede alternar de forma binaria entre `single` (1 modelo) y `triad` (tríada fija precableada).
* En el backend (`TrainingService`), la tríada ejecuta listas estáticas fijas (`TRIAD_ARCHITECTURES` o `ENGINE_TRIAD_ARCHITECTURES`) sin permitir al usuario:
  1. Configurar un **Dúo Ensamble (2 modelos)** para ahorrar cómputo y VRAM.
  2. Elegir qué redes preentrenadas específicas del catálogo utilizar como miembros del ensamble.
  3. Personalizar y calibrar las ponderaciones ($w_i$) de cada modelo según el dominio o la certeza empírica.

### La Solución Orgánica y Profunda
Desacoplar la topología del ensamble permitiendo componer dinámicamente de **1 a 3 modelos** con pesos normalizados ($\sum w_i = 1.0$), manteniendo contratos limpios entre Frontend (React/TypeScript), API REST (FastAPI/Pydantic) y el Orquestador de Entrenamiento (`TrainingService`).

---

## 2. Definición de Costuras (*Seams*) y Módulos Profundos

* **Costura 1: Contrato de Transporte API (`backend/app/schemas/training.py`)** [x]
  * DTO `ModelEnsembleItem`:
    * `architecture: str` (Validado contra catálogo conocido: `EfficientNet-B0`, `ConvNeXt-Nano`, `ResNet-34d`, `PANNs-CNN14`, `AudioCNN`).
    * `weight: float = Field(ge=0.0, le=1.0)`
  * DTO `StartTrainingRequest`:
    * `models: List[ModelEnsembleItem] = Field(min_length=1, max_length=3)`
    * Validador de invariante: auto-normalización determinista garantizando $\sum w_i = 1.0$.
    * Retrocompatibilidad: Si se envían los campos históricos `architecture` e `is_tri_model`, se adaptan automáticamente a la lista `models`.

* **Costura 2: Orquestador de Entrenamiento (`backend/app/services/training.py`)** [x]
  * `_run_training_worker(config)`:
    * Extrae la lista arbitraria de 1 a 3 modelos a entrenar.
    * Gestiona la telemetría en tiempo real: `current_model_index` ($1..N$) y `total_models` ($N \in \{1, 2, 3\}$).
    * Almacena los pesos calibrados en el checkpoint y metadata de entrenamiento para el registro posterior.

* **Costura 3: Interfaz de Usuario React (`frontend/components/views/TrainingView.tsx`)** [x]
  * Control segmentado selector: **1 Modelo (Individual)** | **2 Modelos (Dúo)** | **3 Modelos (Tríada)**.
  * Renderizado reactivo de $N$ filas de configuración:
    * Selector desplegable de red preentrenada del catálogo.
    * Sliders interactivos con auto-balanceo/normalización proporcional en tiempo real (`rebalanceWeights`).
    * Indicador de tiempo estimado recalculado dinámicamente ($N \times \text{tiempo\_por\_red}$).

---

## 3. Plan de Slices Verticales con TDD Estricto (Red → Green)

### 🎯 Slice 1: DTOs y Validación de Ensamble en Backend [x]
1. **Rojo (Test):** Pruebas creadas en `backend/tests/test_training_schemas.py`:
   * [x] Aceptar listas de 1, 2 y 3 modelos con ponderaciones válidas.
   * [x] Rechazar listas vacías o de más de 3 modelos con `ValidationError`.
   * [x] Normalizar ponderaciones determinísticamente para sumar 1.0.
   * [x] Verificar compatibilidad hacia atrás si se reciben campos antiguos (`architecture`, `is_tri_model`).
2. **Verde (Código):** Implementado `backend/app/schemas/training.py` y exportado en `app/schemas/__init__.py`.
3. **Validación:** 13/13 tests pasaron exitosamente en `test_training_schemas.py`.

### 🎯 Slice 2: Orquestación Dinámica en `TrainingService` [x]
1. **Rojo (Test):** Pruebas creadas en `backend/tests/test_training_service.py` y `backend/tests/test_api_training.py`:
   * [x] Validar que al solicitar 2 modelos (ej: `ConvNeXt-Nano` + `EfficientNet-B0`), el worker planifique y ejecute exactamente esos 2 modelos.
   * [x] Validar reporte de telemetría de pasos (`current_model_index`, `total_models`).
   * [x] Validar integración con el endpoint `POST /api/training/start`.
2. **Verde (Código):** Refactorizado `TrainingService.start_training` y `_run_training_worker` desacoplando constantes rígidas y soportando lista dinámica de modelos con pesos.
3. **Validación:** 3/3 tests pasaron en `test_training_service.py` y 6/6 tests pasaron en `test_api_training.py`.

### 🎯 Slice 3: Interfaz de Selección y Sliders Auto-Normalizados (Frontend) [x]
1. **Rojo/Spec:** Pruebas creadas en `frontend/lib/utils/__tests__/ensembleWeights.test.ts` y `frontend/components/views/__tests__/TrainingView.test.tsx`:
   * [x] Función utilitaria `rebalanceWeights(weights, changedIndex, newWeight)` manteniendo $\sum = 1.0$.
   * [x] Pruebas de integración para selector de 1 a 3 modelos y emisión de payload con `models`.
2. **Verde (Código):** 
   * [x] Creado `frontend/lib/utils/ensembleWeights.ts`.
   * [x] Actualizado `frontend/lib/schemas/training.ts` con `ModelEnsembleItemSchema`.
   * [x] Integrado selector de 1 a 3 modelos, cards con dropdowns y sliders interactivos en `TrainingView.tsx`.
   * [x] Conectado `handleStartTraining` enviando el payload con la lista dinámica de modelos y pesos normalizados.
3. **Validación:** 85/85 tests de Vitest pasaron exitosamente y `tsc --noEmit` superó la verificación con 0 errores.

---

## 4. Control RDD (Receipt-Driven Development) y Cierre

* Suite completa de pruebas backend: **241/241 passed (100% green)** en `pytest backend/tests`.
* Suite completa de pruebas frontend: **85/85 passed (100% green)** en `vitest run`.
* Cero regresiones en endpoints existentes y compatibilidad histórica preservada al 100%.

