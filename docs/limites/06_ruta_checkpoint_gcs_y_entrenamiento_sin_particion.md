# Problema Conocido 06: Ruta registrada del checkpoint en GCS y entrenamiento sin partición por API

**Proyecto:** Framework MLOps Híbrido para Clasificación de Audio (F.A.M.A.)  
**Fecha:** Noviembre 2026  
**Área:** Persistencia de modelos, API de entrenamiento  
**Estado:** Caracterizado; se conserva el comportamiento actual  

---

## 1. `modelo.ruta_binario_gcp` no coincide con el objeto respaldado

### Comportamiento observado

Tras `POST /api/training/models/{id}/checkpoint/backup`, el objeto real en el bucket es `models/checkpoints/sha256/<hash>.pt` (prefijo `CLOUD_PREFIX` en [`checkpoints.py`](../../backend/app/services/checkpoints.py)), mientras que `modelo.ruta_binario_gcp` conserva `models/fama_…_best.pt`. Hallazgo registrado como L14 del [plan de la etapa g](../arquitectura/integracion-mvp-g-base-integracion-plan.md).

### Por qué no se corrige el valor

A pesar de su nombre, la columna actúa como clave del archivo local: once puntos del backend obtienen el checkpoint con `Path(ruta_binario_gcp).name` bajo el directorio de checkpoints (activación, historial, predicción, entre otros). Guardar en ella la ruta del objeto en GCS cambiaría el nombre buscado a `<hash>.pt` y rompería esas lecturas.

### Impacto

No bloquea el respaldo ni la restauración: el objeto se identifica por `hash_binario`. La columna no debe usarse para deducir la ubicación del objeto en GCS.

### Alternativa evaluada

Separar la ruta local y la ruta del objeto respaldado en columnas distintas, con su migración. Implica un cambio de formato persistido y de los consumidores de la columna; requiere su propio alcance y un ADR.

---

## 2. `POST /api/training/start` acepta peticiones sin `partition_version`

### Comportamiento observado

La interfaz exige una partición guardada para iniciar un entrenamiento (L15 del plan g). La API, en cambio, admite peticiones sin `partition_version`: en ese caso usa la preparación CSV configurada para el dataset (`prepared_version`, `allow_historical_preparation`). Si no existe, responde con el error de preparación ausente:

> El dataset «<dataset>» todavía no tiene una partición preparada para entrenar. En «Particiones de entrenamiento», crea o selecciona una partición guardada y vuelve a iniciar el entrenamiento.

### Por qué se conserva

Esa ruta es la entrada pública de las preparaciones versionadas por línea de comandos ([manual](../manuales/versiones-preparadas-dataset.md)). Rechazar las peticiones sin `partition_version` retiraría ese flujo de la API, que es un contrato consumido por scripts y pruebas.

### Impacto

Un cliente distinto de la interfaz puede iniciar un entrenamiento sobre la preparación CSV en lugar de una partición guardada. El mensaje de error indica el siguiente paso cuando la preparación falta o está desfasada.
