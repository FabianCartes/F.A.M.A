# 23. Plan de corrección de los pendientes operacionales 7–14

Objetivo: corregir los puntos 7–14 de [estado_actual_y_pendientes.md §2](../manuales/estado_actual_y_pendientes.md#2-correcciones-pendientes-de-lo-ya-implementado), detectados al operar contra la instalación oficial.
Rama: `fix/pendientes-operacion` (desde `mvp`). Entrega: un commit por punto, con prueba primero (TDD). Verificación manual contra `fama_pruebas` y el bucket `fama-pruebas`, con el nodo oficial detenido.
Pruebas backend: `cd backend && PYTHONDONTWRITEBYTECODE=1 PYTHON_DOTENV_DISABLED=1 DATABASE_URL=sqlite:// GCS_BUCKET_NAME=test-bucket CUDA_VISIBLE_DEVICES='' PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 ../.venv/bin/python -m pytest -q -p no:cacheprovider <archivos>`. Pruebas frontend: `cd frontend && npm test -- <archivos>`.

## Especificaciones

- **S13 — Progreso de entrenamiento sin error para investigadores.** Si el último trabajo en memoria pertenece a otra cuenta, `GET /api/training/progress` no responde 403 a un investigador: informa que no hay un entrenamiento propio visible, sin exponer datos del trabajo ajeno. La vista Entrenamiento no muestra «No se pudo consultar el progreso (HTTP 403). Reintentar consulta de progreso.» en ese caso, sino un estado neutro, como en Predicción («La consulta fue correcta, pero no hay modelos publicados ni modelos seleccionables.»). El administrador y el dueño del trabajo mantienen su acceso actual.
- **S12 — Duplicados por contenido en la incorporación de feedback.** La incorporación de feedback compara el SHA-256 del audio con los audios ya registrados en el dataset destino (como `dataset_zip.py`). Si el contenido ya existe, no crea un audio nuevo y lo informa en la interfaz.
- **S9 — Telemetría de VRAM por dispositivo.** `GET /api/training/hardware` mide la VRAM usada a nivel de dispositivo (`torch.cuda.mem_get_info` o NVML), de modo que incluya la memoria del proceso hijo de entrenamiento. La temperatura se informa cuando NVML está disponible (`nvidia-ml-py` en las dependencias).
- **S10 — Rótulo del botón de checkpoint.** En **Entrenamiento → Historial**, el botón muestra **Descargar desde GCS** cuando solo existe el respaldo remoto y **Sincronizar en GCS** cuando hay copia local.
- **S8 — Disponibilidad local en el selector de entrenamiento.** Cada opción de «Dataset para entrenamiento» indica si existe copia local (por ejemplo, «sin copia local, descárgalo primero»), reutilizando el recuento «En este equipo» de la vista de datasets.
- **S14 — Comparación de contenido local y GCS.** «Datasets locales y en GCS» compara al menos recuento, tamaño y huellas registradas, e indica «Coincide» o las diferencias, en lugar del aviso permanente «Contenido sin comparar».
- **S7 — Progreso de la descarga GCS → Local.** La descarga se ejecuta como operación consultable en el servidor: la interfaz muestra audios descargados / audios totales, informa el fin (correcta, parcial o fallida, con nuevos/omitidos/errores), libera **Actualizar**, refresca los recuentos y recupera el estado real aunque se pierda la respuesta original.
- **S11 — Super-Ensamble sin nombres fijos.** `backend/app/main.py` deja de definir el Super-Ensamble por nombres de archivo de los checkpoints históricos, una vez que la tríada reentrenada lo reemplace en Predicción.

## Tareas

| ID | Spec | Bloque | Ruta | Estado | Commit |
| --- | --- | --- | --- | --- | --- |
| T1 | S13 | A | delegada (worker, en paralelo con T2) | pendiente | — |
| T2 | S12 | A | delegada (worker, en paralelo con T1) | pendiente | — |
| T3 | S9 | A | delegada (worker; comparte `training.py` con T1, va después) | pendiente | — |
| T4 | S10 | B | delegada (worker) | pendiente | — |
| T5 | S8 | C | delegada (worker) | pendiente | — |
| T6 | S14 | C | delegada (worker) | pendiente | — |
| T7 | S7 | C | delegada (worker) | pendiente | — |
| T8 | S11 | D | por decidir; requiere la tríada reentrenada | bloqueada | — |

## Registro

- R1: Origen: puntos 7–14 de `estado_actual_y_pendientes.md` §2, a resolver en el orden A (13, 12, 9), B (10), C (8, 14, 7), D (11).
- R2: Línea base de la rama (sin cambios): `test_training_service.py`, `test_api_training.py`, `test_api_feedback.py` y `test_feedback_local_approval.py` dan 157 aprobadas y 14 fallidas, todas en `test_api_training.py`; la primera falla porque la respuesta del historial incluye `compositions`. Sin `GCS_BUCKET_NAME`, 41 casos de `test_feedback_local_approval.py` fallan con `storage_configuration_missing`. Se registran como fallos previos y no se atribuyen a este plan.
