# Problema Conocido 04: Limitación en Subida Web de Directorios Jerárquicos y Datasets Completos a GCS

**Proyecto:** Framework MLOps Híbrido para Clasificación de Audio (F.A.M.A.)  
**Fecha:** Septiembre 2026  
**Área:** Data Lake & Ingesta Cloud, UI/UX Frontend e Ingesta Masiva de Datos  
**Estado:** Alternativas Caracterizadas y Mitigación Inmediata (Opción 1) Implementada  

---

## 1. Contexto y Problema Detectado

En la vista de **Ingesta y Data Lake** (`frontend/components/views/IngestionView.tsx`), el modal de carga a Google Cloud Storage (`Subir audios a GCS`) está diseñado con el siguiente flujo secuencial:

1. Selección obligatoria de un único Dataset de destino (e.g. `AvesChilenas` o `engine_diagnostics`).
2. Selección obligatoria de una única Etiqueta de Clase (e.g. `Chucao` o `normal_brakes`).
3. Carga mediante `<input type="file" multiple accept=".wav,audio/wav">` que asocia todos los archivos seleccionados exclusivamente a la clase elegida.

### Impacto Operativo
Al intentar cargar un dataset completo nuevo (que típicamente cuenta con decenas de subcarpetas correspondientes a cada clase o especie, como las 15 clases de aves o las 10 fallas de motor), el usuario no puede arrastrar la carpeta raíz completa:
* Si el navegador acepta los archivos al arrastrar una carpeta, aplana la jerarquía y asigna todos los audios a la clase seleccionada en el formulario.
* Si el usuario necesita subir 15 clases, debe repetir el proceso 15 veces consecutivas seleccionando cada clase y sus archivos respectivos.

---

## 2. Alternativas Técnicas Evaluadas

### Opción 1: Script CLI / Módulo Python con Service Account (Mitigación Inmediata)
* **Descripción:** Implementar un script de utilidad CLI (`backend/training/upload_dataset_to_gcs.py`) que aproveche la Cuenta de Servicio configurada en `backend/.env` (`GOOGLE_APPLICATION_CREDENTIALS`).
* **Mecanismo:** El script recorre recursivamente el directorio del dataset (`backend/data/raw/{dataset_name}`), infiere automáticamente el nombre de la clase a partir de la subcarpeta inmediata y sube concurrentemente los archivos a `datasets/{dataset_name}/{class_name}/{filename}`.
* **Ventajas:** No requiere cambios en el frontend; velocidad máxima de transferencia con ThreadPoolExecutor; ideal para lotes de miles de audios (e.g. 1.386 muestras de motores).
* **Desventajas:** Requiere acceso a terminal y entorno local.

### Opción 2: Extensión de la UI Web con `webkitdirectory` (Solución Frontend Integral)
* **Descripción:** Añadir en el componente React un modo de selección de directorio mediante `<input type="file" webkitdirectory directory multiple>`.
* **Mecanismo:** El navegador web preserva la propiedad `file.webkitRelativePath` (e.g. `engine_diagnostics/normal_brakes/audio1.wav`). El frontend parsea la jerarquía, agrupa los archivos por clase y despacha las peticiones en lote hacia el backend.
* **Ventajas:** Experiencia de usuario directa (Drag & Drop de carpetas completas desde el explorador del sistema operativo).
* **Desventajas:** Requiere actualizar componentes del frontend y gestionar barras de progreso multi-clase en peticiones multipart concurrentes.

### Opción 3: Carga y Desempaquetado de Archivos Comprimidos (.zip)
* **Descripción:** Exponer un endpoint en FastAPI que reciba un archivo `dataset.zip`.
* **Mecanismo:** El backend descomprime el archivo en un almacenamiento temporal, valida extensiones de audio permitidas (.wav, .mp3, .flac) y replica la estructura de directorios en Google Cloud Storage y PostgreSQL.
* **Ventajas:** Un solo archivo transportado por HTTP; compresión previa.
* **Desventajas:** Sobrecarga de CPU/disco temporal en el backend para descompresión de archivos pesados (>1 GB).

---

## 3. Decisión y Plan de Acción

1. **Corto Plazo (Activo):** Se implementa la **Opción 1** mediante el script canónico `backend/training/upload_dataset_to_gcs.py` para habilitar subidas masivas completas de forma inmediata.
2. **Mediano Plazo (Roadmap UI):** Integrar la **Opción 2** (`webkitdirectory`) en la interfaz web para usuarios que prefieran operar íntegramente desde el panel gráfico.
