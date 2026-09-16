# Propuesta de Cambio: Subsistema Modular de Entrenamiento y Empaquetado de Modelos (MLOps)

**Cambio:** `2026-09-15-modular-training-subsystem`  
**Estado:** Propuesto  
**Fecha:** 2026-09-15  
**Autor:** Senior Architect & Equipo F.A.M.A.  

---

## 1. Contexto y Motivación

En el Hito 18 se completó la refactorización del orquestador backend ([`backend/app/main.py`](../../../backend/app/main.py)) introduciendo un catálogo desacoplado ([`ModelRegistry`](../../../backend/app/services/registry.py)) y la interfaz polimórfica [`AudioPredictor`](../../../backend/app/services/predictors/base.py) para inferencia multi-modelo.

No obstante, el subsistema de **entrenamiento y preparación de datos** permanece contenido en la carpeta histórica [`backend/poc/`](../../../backend/poc/):
* **Física rígida:** Las constantes acústicas clave (`TARGET_SR = 22050`, `DURATION_SECONDS = 5.0`, `n_mels = 128`, `f_min = 800`, `f_max = 10000`) están cableadas como variables globales de módulo en [`backend/poc/preprocess.py`](../../../backend/poc/preprocess.py).
* **Dependencia de Dominio:** Los scripts de descarga, particionado y carga de datos están fuertemente acoplados a la API de Xeno-canto v3 y a las 15 especies de aves chilenas.
* **Falta de soporte para nuevos dominios:** Entrenar modelos para paisajes sonoros PAM a $32\text{ kHz}$ o clasificación multi-etiqueta (anfibios, murciélagos, bioacústica marina) requiere modificar el código fuente de la PoC.

Esta propuesta define la creación de un nuevo subsistema modular en `backend/training/`, orientado a configuración declarativa (*Config-Driven MLOps*), que genere **Model Bundles** autodescubribles por el `ModelRegistry` de producción.

---

## 2. Declaración del Problema

1. **Inflexibilidad en Ingesta:** No existe un contrato unificado para alimentar el entrenamiento desde fuentes heterogéneas (archivos locales, APIs públicas, grabadores autónomos AudioMoth).
2. **Duplicación de Código de Preprocesamiento:** Cada experimento requiere clonar o alterar funciones de `poc/preprocess.py` para variar la frecuencia de muestreo o el tamaño de ventana.
3. **Brecha entre Entrenamiento y Serving:** Los modelos entrenados exportan únicamente un archivo de pesos `.pt`. El servidor de inferencia debe deducir o programar a mano las clases, la tasa de muestreo y la arquitectura, en lugar de leer un manifiesto técnico estandarizado.

---

## 3. Solución Propuesta

Implementar el paquete `backend/training/` compuesto por 4 capas desacopladas:

1. **Capa de Configuración Declarativa (`training/configs/` y `training/schemas/`):**
   - Recetas YAML tipadas y validadas mediante esquemas Pydantic (`TrainingConfig`).
   - Define dataset, física de audio (SR, duración, n_mels, filtros espectrales), arquitectura, pérdida (`CrossEntropy`, `FocalLoss`, `BCEWithLogitsLoss`) y particiones.
2. **Capa de Ingesta Polimórfica (`training/datasets/`):**
   - Interfaz abstracta `DatasetIngestor` con implementaciones concretas:
     - `LocalFolderIngestor`: Lee directorios locales y archivos PAM.
     - `XenoCantoIngestor`: Descarga concurrente con verificación SHA-256.
3. **Capa de Pipeline Acústico Parametrizable (`training/pipelines/`):**
   - `GenericAudioDataset` libre de constantes globales. Recibe `AudioConfig` para configurar dinámicamente el remuestreo, VAD y extracción Mel en GPU/CPU.
4. **Capa de Empaquetado y Auto-Registro (`training/exporters/`):**
   - Generación de artefactos estandarizados (*Model Bundles*):
     ```text
     checkpoints/<model_id>/
     ├── weights.pt
     └── manifest.json
     ```
   - El `manifest.json` contiene la metadata requerida para que el `ModelRegistry` de FastAPI auto-registre el modelo sin necesidad de escribir adaptadores manuales.

---

## 4. Alcance y No-Objetivos (Non-Goals)

### En Alcance:
* Creación de la arquitectura `backend/training/` con esquemas Pydantic y recetas YAML.
* Abstracción `DatasetIngestor` con soporte para carpetas locales y Xeno-canto.
* `GenericAudioDataset` parametrizable para single-label y multi-label.
* Exportador de `ModelBundle` con especificación formal de `manifest.json`.
* Adaptador genérico `BundleAudioPredictor` en `backend/app/services/predictors/` que cargue modelos a partir de su `manifest.json`.

### Fuera de Alcance (Non-Goals):
* No se modificará ni eliminará el código de [`backend/poc/`](../../../backend/poc/); permanece congelado como testimonio histórico y base de evaluación de la tesis.
* No se implementarán loops de reentrenamiento continuo automatizado desde la base de datos de producción (feedback loop de usuario queda para fases posteriores).

---

## 5. Criterios de Éxito y Verificación

1. **TDD:** 100% de cobertura en tests unitarios para esquemas, ingestores, dataset genérico y exportador de bundles.
2. **Interoperabilidad:** El `ModelRegistry` de la API debe poder cargar e inferir sobre un `ModelBundle` sin modificar código de `main.py`.
3. **Regresión Cero:** Los 89 tests existentes en `backend/tests/` deben permanecer en verde en todo momento.

---

## 6. Plan de Rollback

Dado que el nuevo subsistema se desarrolla de forma aditiva en `backend/training/` y `openspec/`, cualquier anomalía no afecta el servicio de producción actual (`backend/app/`). En caso de falla, el rollback consiste simplemente en descartar la rama de desarrollo sin impacto en la base de datos ni en GCP.
