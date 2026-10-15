# Revisión de arquitectura FastAPI y retiro del entrenamiento legacy

## Alcance y resultado

Revisión documental de S1–S4 del [seguimiento de limpieza del entrenamiento legacy](limpieza-entrenamiento-legacy.md). La implementación eliminó los 13 `backend/train_*.py`, `backend/training/trainers/standalone_trainer.py`, su `__init__.py`, seis recetas `car_engine` y sus tests exclusivos. También retiró los bloques CLI PoC, `poc.train.train_pipeline()`, `poc.benchmark.run_benchmark()` y la reexportación de `train_pipeline` desde `ml_core.train`. Se conservan clases y helpers compartidos con entrenamiento web, inferencia, lectura/evaluación de datos y presentación de métricas; no se conserva esa orquestación legacy como API Python. La revisión arquitectónica en sí fue documental y no implementó refactorizaciones, cambios de servidor ni pruebas de concurrencia.

**Conclusión:** el backend usa patrones FastAPI válidos para contratos Pydantic, dependencias, ciclo de vida y endpoints síncronos. La principal deuda de mantenibilidad observada es la concentración de rutas de varios dominios en `backend/app/main.py`. El entrenamiento actual se inicia por la UI y ejecuta un worker de hilo con estado en memoria por proceso; eso impone límites operativos claros, pero no demuestra por sí solo que se necesite una cola externa.

## S1–S4: cobertura de las solicitudes

| Spec | Cobertura documental | Evidencia y límite |
| --- | --- | --- |
| S1 — dejar solo el flujo nuevo | El flujo soportado es la vista Entrenamiento → `POST /api/training/start` → `TrainingService` → worker propio. La eliminación de scripts standalone y recetas fue ejecutada por el padre; los módulos PoC conservan interfaces compartidas, pero no los orquestadores legacy `train_pipeline`/`run_benchmark` ni la reexportación de entrenamiento. | `frontend/components/views/TrainingView.tsx:1085-1094`; `frontend/lib/api/trainingApi.ts:134-155`; `backend/app/main.py:839-859`; `backend/app/services/training.py:335-351,466-473`. La búsqueda en los módulos de aplicación/frontend no encontró una ruta a `GenericModelTrainer` ni a recetas YAML. |
| S2 — revisar arquitectura FastAPI | Se documentan prácticas correctas, deuda de organización y el alcance de las propuestas. No se extraen routers ni se cambia el runtime. | `backend/app/main.py:410-416,434,822-898`; `backend/app/schemas/training.py:86-107`; `backend/app/database.py:103-115`; `backend/app/main.py:384-405`. |
| S3 — mantener únicamente el flujo nuevo | Los manuales dejan de presentar comandos CLI de entrenamiento como procedimiento operativo y remiten al flujo de la UI. La preparación offline del dataset se distingue del entrenamiento y puede conservar su interfaz específica. | `docs/manuales/contrato_referencias_dataset_canonicas.md`; `docs/manuales/manual_usuario_plataforma.md`; frontend y backend citados para S1. |

S4 exige además retirar las funciones Python legacy. `backend/tests/test_training_entrypoints.py` comprueba que los tres imports retirados fallan sin stdout/stderr ni creación de archivos y que los cuatro exports compartidos de `ml_core.train` se conservan. `AdmittedPreparedSource` permanece porque la evaluación independiente todavía lo consume; los helpers de métricas del benchmark no entrenan modelos.

## Prácticas FastAPI válidas observadas

- **Contrato de entrada con Pydantic.** `start_training_pipeline` recibe `StartTrainingRequest`, y `backend/app/schemas/training.py` declara campos y validadores del request (`backend/app/main.py:839-859`; `backend/app/schemas/training.py:86-158`). La validación del request no depende de una receta YAML.
- **Inyección de dependencias.** `get_db` es un generador que abre y cierra la sesión, y endpoints como los de catálogo e historial lo declaran con `Depends(get_db)` (`backend/app/database.py:103-115`; `backend/app/main.py:830-832,889-896`). Es un uso convencional y localizado de dependencias.
- **Ciclo de vida de aplicación.** `lifespan` es un `asynccontextmanager` conectado al constructor `FastAPI`; realiza inicialización y mantiene el worker de sincronización de feedback durante el ciclo de vida (`backend/app/main.py:384-405,410-416`).
- **Endpoints `def` síncronos.** Las rutas de entrenamiento son `def`, no `async def` (`backend/app/main.py:822-898`). FastAPI admite este patrón y ejecuta las operaciones de ruta síncronas fuera del event loop, en un threadpool. En el inicio de entrenamiento, el handler delega además el trabajo prolongado a un hilo dedicado (`backend/app/services/training.py:466-473`). Por tanto, usar `def` aquí no constituye por sí mismo un incumplimiento de FastAPI.
- **Referencia de organización.** FastAPI recomienda `APIRouter` para dividir aplicaciones mayores en módulos; es una recomendación para modularidad, no un requisito de validez. El backend ya incluye `auth_router`, mientras que las rutas de entrenamiento y varios otros dominios se declaran directamente en `app/main.py` (`backend/app/main.py:434,822-898`).

## Hallazgos por severidad

### Media — concentración de rutas en `backend/app/main.py`

El constructor de la aplicación, middleware y lifespan comparten archivo con handlers de salud, modelos, ingesta, entrenamiento y feedback. Los handlers de entrenamiento ocupan un bloque continuo y hay un router modular incluido para autenticación, por lo que existe una vía conocida para modularizar; no se afirma que la estructura actual sea inválida ni que una extracción sea necesaria para que funcione.

**Consecuencia:** crece el coste de localizar cambios y revisar el impacto entre dominios. La prioridad es de mantenibilidad/localidad, no una corrección de runtime demostrada.

### Media — estado y worker de entrenamiento limitados al proceso

`training_service` es una instancia global de `TrainingService` (`backend/app/services/training.py:1402-1403`). El estado de job, progreso, logs y señal de detención son atributos en memoria protegidos parcialmente por un lock (`:97-111,235-270`). La admisión rechaza un segundo job cuando el mismo servicio está en `training` o `evaluating` (`:360-363`); el trabajo se lanza como `threading.Thread(..., daemon=True)` (`:466-473`).

**Consecuencias arquitectónicas derivadas del código, no de pruebas de concurrencia:**

- Un reinicio o terminación abrupta del proceso pierde el estado observable y puede terminar el hilo daemon; los checkpoints y filas ya persistidos no convierten el job en una unidad recuperable.
- Si se ejecutaran varios procesos/ workers, cada uno tendría su propio singleton, lock y worker. El bloqueo local no coordinaría admisiones ni el acceso a una GPU compartida, y solicitudes de progreso/detención podrían llegar a otro estado de proceso.
- La ruta de despliegue inspeccionada define un único servicio backend en `docker-compose.yml:23-70`; `backend/Dockerfile:57` invoca Uvicorn sin una opción `--workers`. Esto describe la configuración del repositorio, no certifica la configuración efectiva de una instalación desplegada ni evita que otra plataforma use varios procesos.

Este límite merece quedar explícito en operación. No es evidencia suficiente para imponer Celery ni otra cola: la guía oficial de FastAPI indica que el trabajo pesado puede beneficiarse de un sistema externo, a cambio de más complejidad. La necesidad depende de requisitos concretos de durabilidad, recuperación tras reinicios, coordinación multi-proceso o control de carga.

### Informativa — el diseño del worker no usa `BackgroundTasks`

El handler llama directamente al servicio, que crea su propio hilo daemon. No se debe describir esto como una tarea durable ni como una cola administrada por FastAPI. La guía de `BackgroundTasks` presenta opciones externas para cómputo pesado, no una obligación universal ni una prescripción específica de Celery.

## Recomendaciones propuestas — no implementadas

1. Mantener documentado que el estado de job es local al proceso y que el despliegue inspeccionado no acredita una coordinación multi-worker.
2. Considerar una extracción gradual a `APIRouter` solo en un cambio futuro autorizado y con pruebas de contrato; no es necesaria como condición de conformidad FastAPI para esta tarea.
3. Evaluar una cola/worker externo únicamente si se establece un requisito de persistencia del job, recuperación, coordinación entre procesos o límites de concurrencia. Comparar coste operativo y semántica de resultados antes de escoger tecnología; no asumir Celery.
4. Mantener una sola vía operativa de entrenamiento: UI → `/api/training/start` → `TrainingService`. La preparación de datos offline es un paso distinto, no una segunda ruta de entrenamiento.

Todas estas recomendaciones quedan sin implementar. Esta unidad solo modifica documentación; no cambia handlers, contratos, hilos, workers, despliegue ni tests.

## Referencias oficiales

- FastAPI, [Bigger Applications — Multiple Files](https://fastapi.tiangolo.com/tutorial/bigger-applications/): recomienda `APIRouter` para modularizar aplicaciones grandes; no define la alternativa en un solo archivo como inválida.
- FastAPI, [Concurrency and `async` / `def`](https://fastapi.tiangolo.com/async/): comportamiento de las operaciones de ruta síncronas ejecutadas fuera del event loop.
- FastAPI, [Background Tasks](https://fastapi.tiangolo.com/tutorial/background-tasks/): advierte que cómputo pesado puede beneficiarse de herramientas externas y que estas añaden complejidad.

## Referencias históricas preservadas

La integración final añadió notas de retiro a las ADR e informes enumerados a continuación y convirtió enlaces a scripts/recetas eliminados en referencias textuales. Se conserva su contenido histórico, sin presentar comandos retirados como procedimientos actuales.

- `docs/adr/0012_unificacion_fuente_datos_raw.md:15,55,83` y `docs/adr/0014_delimitacion_hiperparametros_frontend_deep_modules.md:105` conservan referencias textuales a scripts o recetas YAML. Las notas de vigencia aclaran el retiro; los enlaces a los recursos eliminados se convirtieron en texto sin reescribir la decisión original.
- `docs/adr/0022-evaluaciones-finales-estandarizadas.md:312` describe históricamente `GenericModelTrainer.train_and_export` como ruta oficial obligatoria. La nota de vigencia aclara que ese entrenador fue retirado; la publicación de bundles se conserva como capacidad compartida, no como otra CLI de entrenamiento.
- `docs/modelos/10_metodo_campeon_bioacustica_fama.md:124,138`, `12_ensemble_multimodelo_rdd.md:95`, `13_ensamble_heterogeneo_convnext_rdd.md:129,136` y `16_informe_maestro_super_ensamble_fama.md:105` contienen invocaciones PoC identificadas mediante notas de vigencia como comandos históricos retirados, preservando la evidencia experimental.
- `docs/KANBAN.md` conserva referencias históricas de seguimiento a scripts retirados; no se reescriben esos registros. La búsqueda no encontró otro manual operativo que recomiende las CLIs de entrenamiento retiradas; las guías de evaluación/reevaluación encontradas usan scripts distintos, no incluidos en este retiro. Los comandos de `training.prepare_engine_data` se conservan porque preparan datasets, no lanzan entrenamiento.

## Verificación y límites de evidencia

La verificación de esta unidad fue documental y estructural: lectura de los archivos citados, búsqueda de referencias CLI/recetas en la documentación y fuentes de aplicación, e inspección de `backend/Dockerfile` y `docker-compose.yml`. Esta unidad no ejecutó pruebas, builds, servidor, entrenamiento, BD ni pruebas de concurrencia. Como evidencia de la unidad de retiro, el padre informó una línea base de 255 pruebas aprobadas y dos tests exclusivos del entrenador standalone bloqueados por la guarda de red al intentar abrir sockets Unix de `multiprocessing` (no fue un intento de acceso a Internet); adaptó el test de evaluación para recorrer `BundleExporter` → `BundleAudioPredictor` → `RecordingEvaluator` → `publish`, y completó la comprobación posterior con **322 pruebas aprobadas, 2 advertencias de librosa y exit code 0**. Esa evidencia corresponde al retiro operacional inicial y está en el seguimiento, L12, y el recibo `docs/receipts/training-legacy-independent-verification.json`. Tras el retiro callable aprobado en S4, se observó RED de tres imports todavía disponibles, GREEN focal de 38 pruebas y suite propia final de **297 pruebas aprobadas, 2 advertencias y exit code 0** (`/tmp/gentle-jobs-N3xa91/job-4.log`); la diferencia de cantidad se debe al retiro de pruebas exclusivas de los orquestadores eliminados y a los nuevos casos de retiro/preservación. La verificación independiente del candidato adicional también aprobó **297 pruebas, 2 advertencias, exit code 0 y stderr vacío**; los logs y la selección están en [el recibo final](../receipts/training-legacy-final-verification.json). La última corrección del mapa histórico fue revalidada sin modificar código ni repetir pruebas funcionales. El ASSESS nativo no pudo clasificar los archivos nuevos pese a su declaración; se aplicó verificación independiente conservadora de riesgo alto, pero no se inició ni se presume aprobada una revisión nativa. La suite global con accesos potenciales a GCS/datos reales no se ejecutó; no se presenta este resultado como validación global del backend. Las conclusiones sobre procesos múltiples son implicaciones estáticas del estado global y del worker por hilo, no resultados de ejecución.

## Key Learnings

1. El endpoint síncrono de FastAPI delega el cómputo a un hilo daemon propio.
2. El progreso de entrenamiento vive en el singleton de cada proceso.
3. La configuración Compose inspeccionada declara un servicio backend sin réplicas.
