# Revisión técnica del capítulo 2. Proyecto

La finalidad del software coincide con el checkout. F.A.M.A. integra un nodo de procesamiento acústico, un repositorio de objetos en Google Cloud Storage (GCS), persistencia relacional y una interfaz web. Los cambios principales afectan a los objetivos 2.2(a) y 2.2(b), la descripción de las actualizaciones de la interfaz y la tabla de tecnologías.

Se revisaron las secciones **2.1 a 2.6**, páginas impresas **6 a 9**, correspondientes a las páginas **17 a 20 del PDF**. El contraste del 11 de noviembre de 2026 usa el checkout con HEAD en **84ea7df**, incluidos los cambios locales de dependencias y configuración pertinentes. Las versiones se atribuyen a sus manifiestos, imágenes o recibos. La revisión del comportamiento se basa en código y evidencia existente.

## 🔴 Crítico (Contradicción texto-código)

### C1. El motor de entrenamiento web es PyTorch

**Texto de §2.6, pp. 8–9.** «PyTorch o TensorFlow actúan como los motores de Deep Learning». La tabla 2.1 también los presenta como un solo renglón bajo «PyTorch / TensorFlow».

**Implementación.** El entrenador usa PyTorch para los modelos, los lotes de entrenamiento y el cálculo de la pérdida. TensorFlow aparece como opción deshabilitada en el frontend. El proceso elige CUDA si está disponible y CPU en caso contrario. [Dependencias de Python](../../backend/requirements.txt#L1), [entrenador local](../../backend/app/services/training.py#L820), [selección de dispositivo](../../backend/app/services/training.py#L855), [selector de la interfaz](../../frontend/components/views/TrainingView.tsx#L1981).

**Redacción propuesta.** «PyTorch es el motor de entrenamiento e inferencia. Los procesos de aprendizaje automático se ejecutan en el nodo, con aceleración CUDA cuando está disponible y con ejecución en CPU cuando corresponde».

### C2. La característica implementada es el espectrograma Mel

**Texto de §2.2(b) y §2.6, pp. 6 y 8–9.** «Espectrogramas y coeficientes MFCC» y «Librosa se emplea […] extrayendo los espectrogramas y coeficientes MFCC».

**Implementación.** La preparación de ingesta usa la extracción de espectrogramas Mel de Librosa. En el entrenamiento web el cargador entrega formas de onda y TorchAudio calcula los espectrogramas por lote en el dispositivo de ejecución. Las rutas de inferencia aplican el preprocesamiento del predictor, con variantes que incluyen Librosa o separación armónico-percusiva (HPSS). La revisión de las rutas de producción no encontró extracción de MFCC para alimentar los modelos. Aquí el texto presenta MFCC como característica construida, mientras que el capítulo 1 la mencionaba como tema de estudio. [Preparación de ingesta](../../backend/app/services/ingestion.py#L499), [extractores Mel](../../backend/poc/preprocess.py#L155), [frontend acústico del entrenamiento](../../backend/app/services/training.py#L995), [frontend HPSS de motores](../../backend/app/services/predictors/engine_ensemble_predictor.py#L119).

**Redacción propuesta para §2.2(b).** «Implementar rutinas de carga y preparación de señales acústicas que permitan extraer espectrogramas Mel. Utilizar Librosa o TorchAudio según la etapa y la configuración del predictor».

### C3. El respaldo de pesos y de aportes corregidos tiene hitos propios

**Texto de §2.2(a) y §2.6, pp. 6 y 8–9.** «Asegurando tanto el almacenamiento de los modelos como el respaldo de los registros de error etiquetados». La tabla llama a GCS «Repositorio principal de datasets de audios y binarios de redes neuronales».

**Implementación.** El entrenador escribe el checkpoint en el nodo y registra su identidad y métricas en PostgreSQL. La copia en GCS se solicita por separado y verifica los bytes con la huella registrada. La predicción web sube su audio de entrada a GCS antes de ejecutar el predictor. Enviar una corrección registra el aporte. Su aprobación verifica e incorpora el audio en el dataset local y registra una copia a GCS pendiente. En GCS, la inmutabilidad de los bytes durante la vida de una generación es una propiedad del servicio. Una misma clave puede recibir una generación nueva. F.A.M.A. utiliza operaciones de creación sin reemplazo en rutas específicas, como el respaldo de checkpoints y la sincronización privada de revisiones ZIP. [Registro local de pesos y métricas](../../backend/app/services/training.py#L1261), [copia explícita](../../backend/app/services/checkpoints.py#L93), [subida previa a inferencia](../../backend/app/main.py#L730), [curación](../../backend/app/services/feedback.py#L493), [worker de copia](../../backend/app/services/feedback_sync_worker.py#L79), [objetos y generaciones de GCS](https://docs.cloud.google.com/storage/docs/objects).

**Redacción propuesta para §2.2(a).** «Integrar la descarga y la carga de audios con Google Cloud Storage. Incorporar operaciones explícitas de respaldo y recuperación de checkpoints y gestionar la sincronización de los aportes aceptados mediante curación humana».

### C4. React actualiza la vista con datos obtenidos por HTTP

**Texto de §2.2(d) y §2.6, pp. 6 y 8.** «Predicción en tiempo real» y «un Virtual DOM que asegura actualizaciones en tiempo real sin recargar la página».

**Implementación.** Durante el entrenamiento, la vista consulta el progreso cada segundo. El panel general consulta sus datos periódicamente. La predicción se solicita por HTTP al enviar el audio y la vista muestra el resultado de la respuesta. La actualización de la interfaz y la latencia de cómputo o red son aspectos distintos. El código de la vista mide el tiempo transcurrido para una solicitud concreta. [Consulta de progreso](../../frontend/components/views/TrainingView.tsx#L804), [consulta periódica del panel](../../frontend/components/views/DashboardView.tsx#L150), [solicitud y tiempo de predicción](../../frontend/components/views/PredictionView.tsx#L984).

**Redacción propuesta.** «La interfaz web presenta predicciones bajo demanda y actualiza el progreso del entrenamiento mediante consultas periódicas a la API, sin recargar la página completa».

## 🟡 Advertencia (Omisión o desfase)

### A1. El objetivo general agrupa operaciones que se solicitan por separado (§2.1, p. 6)

«Automatice el flujo» es adecuado para describir la ejecución coordinada de tareas una vez solicitadas. Conviene precisar que el sistema tiene entradas independientes para sincronizar desde GCS, preparar los datos, iniciar entrenamiento y solicitar predicciones. El entrenamiento admitido se ejecuta en un proceso hijo supervisado por el backend. La consulta de progreso permite observarlo y su ejecución continúa sin mantener una petición web abierta. En el módulo ZIP también se distinguen recepción HTTP, validación y publicación local en segundo plano y sincronización explícita de una revisión. [Sincronización y preparación](../../backend/app/main.py#L926), [inicio de entrenamiento](../../backend/app/main.py#L1068), [supervisión del proceso](../../backend/app/services/training.py#L610), [ADR de aislamiento del entrenamiento](../adr/0024-entrenamiento-aislado-spawn.md), [trabajos ZIP](../../backend/app/routes/dataset_imports.py#L351).

**Redacción propuesta.** «Desarrollar una plataforma MLOps híbrida que integre la gestión de audios en GCS, la preparación y el entrenamiento local de modelos acústicos y la consulta web de predicciones y resultados de evaluación».

### A2. La carga y descarga en ambos sentidos tienen contratos distintos (§2.2(a), p. 6)

La descarga sincroniza conjuntos autorizados y puede informar resultados parciales. La carga de audios valida el lote y crea objetos sin reemplazar una grabación con la misma clave. Si ya existe un objeto, comprueba si el contenido coincide. En caso de colisión con contenido distinto, informa el conflicto. La persistencia SQL tiene su propio resultado. Esta política es más precisa que describir todo como una sincronización bidireccional uniforme. [Autorización y resultado de descarga](../../backend/app/main.py#L926), [carga y colisiones](../../backend/app/services/ingestion.py#L884), [resultados parciales](../adr/0046-resultados-parciales-en-subida-de-audios.md).

### A3. Aclarar cómo se consultan las métricas y cuándo se usan los aportes (§2.2(c)–(d), p. 6)

«Exporte las métricas» puede entenderse como una descarga desde el panel. El flujo web persiste y consulta métricas por época y resultados de evaluación. Hay herramientas separadas que emiten resultados de evaluación en JSON. «Reincorporación de los lotes de datos corregidos» debe reflejar la secuencia de revisión, incorporación, preparación identificada e inicio explícito de un trabajo posterior. La retroalimentación es una validación humana sobre la clase predicha. El uso de memoria y el progreso del trabajo pertenecen a la telemetría operativa. [Métricas por época](../../backend/app/services/training.py#L1292), [historial web](../../backend/app/main.py#L1136), [herramienta de evaluación con salida JSON](../../backend/scripts/evaluate_engine_ensemble.py#L134), [particiones identificadas](../../backend/app/services/training.py#L478), [telemetría del nodo](../../backend/app/services/training.py#L211).

**Redacción propuesta para §2.2(c).** «Desarrollar el entrenamiento local con conjuntos preparados y particiones identificadas, registrar las métricas y los informes de evaluación y permitir que las muestras curadas se consideren en preparaciones posteriores».

**Redacción propuesta para §2.2(d).** «Implementar una interfaz web para supervisar la ingesta y el entrenamiento, solicitar predicciones y registrar confirmaciones o correcciones para su revisión».

### A4. Scrum adaptado, pruebas y evidencia de trabajo (§2.3, p. 7)

El capítulo presenta Scrum adaptado como metodología elegida. El repositorio documenta seguimiento en un tablero Kanban, cambios iterativos, pruebas automatizadas y decisiones mediante ADR. Esas evidencias permiten precisar la práctica de ingeniería, mientras que la frecuencia de los sprints, sus eventos y responsabilidades dependen de los registros del equipo. El historial de Git muestra integraciones, y el repositorio documenta ejecuciones de pruebas. «Integración continua» puede leerse como CI automatizada, por lo que conviene precisar si aquí significa integración frecuente de componentes. [Tablero](../KANBAN.md), [directrices de TDD](../../AGENTS.md#L19), [integración documentada de ramas](../manuales/integracion_dev_20261024.md), [Guía oficial de Scrum](https://scrumguides.org/scrum-guide).

**Redacción propuesta.** «El desarrollo se organizó en iteraciones cortas y se apoyó en un tablero de seguimiento. El repositorio documenta pruebas automatizadas y decisiones de arquitectura. Las prácticas de Scrum adoptadas por el equipo se describen según sus registros de planificación y seguimiento».

### A5. Los estándares se citan como referencias documentales y UML como técnica (§2.4–2.5, p. 7)

La tesis ya habla de «adaptación». Conservar esa formulación es razonable si IEEE 829-1998 e IEEE 830-1998 se usaron como referencias de estructura. IEEE identifica ambas ediciones como sustituidas. IEEE 829 describe documentación de pruebas. El protocolo experimental debe especificar, además, qué datos y artefactos se evaluaron y con qué métricas. La lista de diagramas UML en §2.5 describe una técnica de modelado. Su pertinencia se mantiene si las responsabilidades que enuncia incluyen el cliente web, el backend, la base relacional y el almacenamiento de objetos. [Historial de IEEE 829](https://standards.ieee.org/ieee/829/3787/), [ficha de IEEE 830-1998](https://standards.ieee.org/ieee/830/1222/), [contrato de evaluación por grabación](../../backend/app/services/recording_evaluator.py#L57).

**Redacción propuesta para §2.4.** «La documentación de requisitos y de pruebas tomó como referencia adaptaciones de IEEE 830-1998 e IEEE 829-1998, respectivamente. La evaluación de modelos registró el conjunto, la partición, la identidad del checkpoint y las métricas empleadas».

### A6. La tabla 2.1 debe reflejar versiones verificables y el papel de cada componente (§2.6, pp. 7–9)

«Python 3.10 o superior», «PostgreSQL 14 o superior» y «React 18 / Next.js 14 o superior» son rangos amplios. La versión de un contenedor o la declarada en un manifiesto fija una referencia reproducible para ese perfil. Su presencia no acredita todos los mínimos descritos en la tesis. Se deben incorporar FastAPI y TorchAudio porque ejecutan funciones centrales. «Alta disponibilidad» describe un criterio de arquitectura. Para afirmarla como resultado de la instalación se requerirían configuración y pruebas de redundancia o recuperación acordes con ese objetivo.

| Tecnología | Versión o alcance comprobable | Rol que debe figurar |
| --- | --- | --- |
| Python | **3.12** en la imagen del backend y la guía nativa | Lenguaje de los servicios y del pipeline de aprendizaje automático. [Dockerfile](../../backend/Dockerfile#L4), [guía nativa](../manuales/entrega_a_kevin.md#L83). |
| FastAPI y Uvicorn | Requisitos declarados **≥0.110.0** y **≥0.28.0**, respectivamente | Implementación y ejecución del servidor HTTP. [Dependencias](../../backend/requirements.txt#L16), [comando de arranque](../../backend/Dockerfile#L57). |
| PostgreSQL | **16** en Compose. Cloud SQL para el perfil institucional | Persistencia relacional, control de acceso y registros de datos, modelos, predicciones y evaluaciones. La versión de la instancia administrada se documenta según su configuración observada. [Compose](../../docker-compose.yml#L2), [ADR de conexión a Cloud SQL](../adr/0059-conexiones-cloud-explicitas-mediante-proxy.md). |
| Google Cloud Storage | Clase determinada por el bucket o el objeto. `Standard` figura en la guía de despliegue | Almacenamiento de objetos acústicos, revisiones sincronizadas y respaldos explícitos. [Guía de despliegue](../manuales/guia_despliegue_operativo_docker.md#L214), [clases de almacenamiento de GCS](https://docs.cloud.google.com/storage/docs/storage-classes). |
| PyTorch y TorchAudio | Requisitos declarados **≥2.0.0** para ambos. El recibo de la imagen probada en CPU registra **2.15.0+cu132** y **2.11.1+cu132**, respectivamente | PyTorch ejecuta los modelos. TorchAudio calcula representaciones Mel por lotes y participa en transformaciones acústicas. [Dependencias](../../backend/requirements.txt#L1), [procesamiento acústico](../../backend/poc/preprocess.py#L185), [recibo de la imagen](../receipts/verificacion_docker_cloud_y_dependencias_20261109.json#L83). |
| Librosa | Requisito declarado **≥0.10.0** | Carga, adecuación de la señal y cálculo de espectrogramas Mel en las rutas que lo emplean. [Dependencias](../../backend/requirements.txt#L3), [extractor Mel](../../backend/poc/preprocess.py#L155). |
| Next.js, React y TypeScript | **Next.js 16.4.5** en el manifiesto local, **16.3.4** en HEAD, **React 19.2.8** y **TypeScript 5.9.3** en el archivo de bloqueo consultado. Docker usa Node.js 22 | Construcción de la interfaz web y reenvío de solicitudes a la API. La memoria debe identificar la revisión o el perfil con el que presenta estas versiones. [Manifiesto](../../frontend/package.json), [archivo de bloqueo](../../frontend/package-lock.json), [Dockerfile del frontend](../../frontend/Dockerfile#L8), [recibo de actualización](../receipts/cierre_verificacion_docker_20261109.json#L27). |
| Docker y Docker Compose | Imágenes y servicios declarados en el repositorio | Empaquetado y arranque de frontend, backend y PostgreSQL local. [Compose](../../docker-compose.yml). |
| Git y GitHub | Repositorio con historial Git y remoto `origin` en GitHub | Control de versiones e integración de cambios. Los resultados experimentales y pesos tienen registros y almacenamiento propios. |

### A7. Confirmar la participación de editores y asistentes con el equipo (§2.6, pp. 8–9)

Git y GitHub se verifican con la configuración del remoto y el historial, que incluye integraciones por pull request. El archivo `GEMINI.md` contiene directrices de trabajo. Su existencia no determina si Antigravity fue el editor principal, qué edición de Gemini se utilizó ni qué consultas se optimizaron con su ayuda. Esas afirmaciones describen el proceso de autoría y requieren confirmación del equipo. Si se confirman, conviene ubicarlas como herramientas de apoyo al desarrollo. [Directrices de trabajo](../../GEMINI.md).

## 🟢 Mejora de redacción

| Ubicación | Expresión del capítulo | Redacción propuesta |
| --- | --- | --- |
| §2.1 | «Software orquestador híbrido» y «visualización de modelos predictivos» | «Plataforma MLOps híbrida para coordinar el flujo acústico y presentar predicciones, métricas y estado de ejecución». |
| §2.2(b) | «Características matemáticas» | «Representaciones acústicas de entrada, como espectrogramas Mel». |
| §2.2(d) | «Ingesta del dato» y «telemetría de errores» | «Ingesta de audios» y «registro de confirmaciones y correcciones de predicciones». |
| §2.3 | «Pivotar rápidamente» | «Ajustar el diseño a partir de los resultados de cada iteración». |
| §2.6 | «Construcción de scripts asíncronos» | «Implementación de servicios HTTP y procesos de trabajo supervisados». |
| §2.6 | «Cruces lógicos entre etiquetas y audios» | «Relaciones entre conjuntos de datos, grabaciones, modelos, predicciones y aportes de retroalimentación». |
