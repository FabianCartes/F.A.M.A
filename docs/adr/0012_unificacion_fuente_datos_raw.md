# ADR 0012: Unificación de Almacenamiento de Datos Crudos (SSOT) en `backend/data/raw`

* **Estado:** Aceptado / Implementado  
* **Fecha:** 2026-09-26  
* **Decisores:** Equipo F.A.M.A.  
* **Área:** Arquitectura de Software Backend, Data Lake & Ingesta, MLOps y Pipelines de Entrenamiento  

---

## 1. Contexto y Problema

Durante la evolución del proyecto y la incorporación de la vista de **Ingesta y Data Lake** conectada a Google Cloud Storage (GCS), se originó una inconsistencia de almacenamiento denominada *"split-brain"* entre los subsistemas de entrenamiento y el servicio de ingesta:

1. **Scripts CLI y Recetas de Entrenamiento Preexistentes:**  
   Los scripts de entrenamiento de diagnóstico industrial de motores ([`backend/train_car_engine_model.py`](../../backend/train_car_engine_model.py), [`backend/train_and_ensemble_engines.py`](../../backend/train_and_ensemble_engines.py), [`backend/training/prepare_engine_data.py`](../../backend/training/prepare_engine_data.py)), las recetas YAML en [`backend/training/recipes/`](../../backend/training/recipes/) y los scripts PoC bioacústicos ([`backend/poc/`](../../backend/poc/)) consumían los audios y metadatos desde carpetas en la raíz del repositorio:
   ```
   data/raw/
   data/engine_diagnostics/
   ```
2. **Servicio de Ingesta, Data Lake y Frontend:**  
   El servicio de sincronización con Google Cloud Storage ([`IngestionService`](../../backend/app/services/ingestion.py)) y la interfaz web ([`IngestionView.tsx`](../../frontend/components/views/IngestionView.tsx)) asumen como estándar arquitectónico que todos los datos descargados de GCS residen en:
   ```
   backend/data/raw/{nombre_dataset}/
   ```
   mientras que los espectrogramas generados por Librosa se almacenan en:
   ```
   backend/data/processed/{nombre_dataset}/
   ```
3. **Consecuencias:**  
   - Desacople entre el flujo de sincronización de la nube y los scripts de entrenamiento: al descargar datos desde GCS mediante la UI web, los scripts de entrenamiento no los encontraban.
   - Estado de sincronización inconsistente en la UI web (el frontend mostraba "Pendiente" y "0/2 archivos locales" porque buscaba en `backend/data/raw/` y no en `data/`).
   - Fragilidad en rutas relativas dependientes del directorio de trabajo actual (`cwd`).

---

## 2. Decisión Arquitectónica

Se aprueba formalmente establecer **`backend/data/raw/`** como la **Fuente Única de la Verdad (SSOT - *Single Source of Truth*)** para todos los datasets crudos del sistema (bioacústicos e industriales), acompañada de una costura desacoplada de resolución de rutas:

### 2.1 Módulo Profundo de Resolución de Rutas (`PathResolver`)
Se define una interfaz mínima y determinista en `backend/training/paths.py`:
```python
def get_project_root() -> Path:
    """Retorna la raíz canónica del repositorio de forma agnóstica a cwd."""

def get_raw_data_dir(dataset_name: Optional[str] = None) -> Path:
    """Retorna la ruta absoluta a backend/data/raw/[dataset_name]."""

def get_processed_data_dir(dataset_name: Optional[str] = None) -> Path:
    """Retorna la ruta absoluta a backend/data/processed/[dataset_name]."""
```
**Invariante:** Las rutas devueltas son siempre absolutas y ancladas a `PROJECT_ROOT`, garantizando la misma ejecución tanto desde la raíz del proyecto como desde subcarpetas, contenedores Docker o entornos CI.

### 2.2 Migración de Recetas YAML y Schemas
Las recetas de entrenamiento en `backend/training/recipes/` actualizaron sus propiedades `raw_dir` y `metadata_csv` para apuntar de forma canónica a `backend/data/raw/engine_diagnostics`.

### 2.3 Migración del Almacenamiento Local y Eliminación Definitiva de `/data`
El almacenamiento de ambos dominios ha sido completamente migrado y unificado:
1. **Dominio Industrial (`engine_diagnostics`):**
   - 1.386 audios y archivos de partición (`train_metadata.csv`, `val_metadata.csv`, `test_metadata.csv`) migrados a `backend/data/raw/engine_diagnostics/`.
2. **Dominio Bioacústico (`AvesChilenas`):**
   - 15 carpetas de especies (1.206 audios) y archivos de metadatos (`metadata.csv`, `train.csv`, `val.csv`, `test.csv`) migrados a `backend/data/raw/AvesChilenas/`.
   - Archivos saneados migrados a `backend/data/processed/AvesChilenas/processed_wav`.
   - Symlink relativo de compatibilidad en `backend/data/raw/AvesChilenas/processed_wav` apuntando a `../../processed/AvesChilenas/processed_wav`.
3. **Eliminación:**
   - La carpeta raíz `data/` ha sido eliminada por completo (`rm -rf data`).

---

## 3. Plan de Implementación y Fases (TDD)

La implementación se ejecutó en **vertical slices** estrictos bajo el ciclo Red → Green → Refactor:

### Fase 1: Costura Canónica (`PathResolver`)
* **Rojo (Test):** `backend/tests/test_paths.py` validando la resolución de `get_raw_data_dir()` y `get_project_root()` bajo distintos contextos de ejecución.
* **Verde (Código):** Implementado `backend/training/paths.py`.

### Fase 2: Adaptación de Ingestor y Schemas de Entrenamiento
* **Rojo (Test):** Validación en `backend/tests/test_training_schemas.py` y `backend/tests/test_dataset_ingestors.py`.
* **Verde (Código):** Validadores de `TrainingConfig` resuelven rutas mediante `PathResolver`.

### Fase 3: Migración de Recetas YAML
* **Rojo (Test):** `backend/tests/test_recipes.py` verificando sintaxis y existencia de rutas canónicas en `car_engine_*.yaml`.
* **Verde (Config):** Rutas canónicas actualizadas en recetas YAML.

### Fase 4: Migración de Scripts CLI de Entrenamiento y PoC
* **Rojo (Test):** `backend/tests/test_cli_paths.py` verificando ausencia de rutas hardcodeadas `data/raw` o `Path("data/` tanto en `backend/training/` como en `backend/poc/` (`train.py`, `evaluate.py`, `benchmark.py`, `download.py`, `sanitize.py`).
* **Verde (Código):** Actualizados todos los scripts en `backend/training/` y `backend/poc/` utilizando `training.paths.PathResolver`.

### Fase 5: Migración de Datos Físicos y Eliminación de `/data`
* **Acción:** Migración de `AvesChilenas` y `engine_diagnostics` a `backend/data/raw/`, reubicación de audios WAV a `backend/data/processed/` y eliminación total de `/data`.
* **Verificación:** Ejecución de suite completa `pytest backend/tests` (191 pruebas pasando al 100%) y reporte de `is_synced: True` para ambos datasets en `IngestionService().list_datasets()`.

---

## 4. Consecuencias e Invariantes

### Positivas:
* **SSOT Garantizada:** Una sola ubicación para audios crudos en todo el sistema (`backend/data/raw/`).
* **Sincronización Total del Data Lake:** `IngestionService().list_datasets()` reporta `is_synced: True` tanto para `engine_diagnostics` como para `AvesChilenas`.
* **Trazabilidad Completa:** La UI web, la API FastAPI y los scripts CLI de entrenamiento comparten el mismo almacenamiento local y sincronización con GCS.
* **Portabilidad:** Cero dependencias del directorio de trabajo actual (`cwd`).

### Invariantes a Mantener:
* Ningún componente debe acceder a rutas de datos hardcodeadas fuera de `PathResolver` o `DEFAULT_LOCAL_RAW_DIR`.
* No debe existir la carpeta `data/` en la raíz del repositorio.
* Toda suite de tests unitarios e integrados debe ejecutarse limpiamente sin depender de la existencia de rutas legadas.
