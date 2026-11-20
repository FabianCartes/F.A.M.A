# Bitácora de evolución de decisiones de F.A.M.A.

La bitácora conserva lo que proponía la memoria, lo que el equipo adoptó durante el desarrollo y la evidencia que permite explicar el cambio en la defensa. Al **11 de noviembre de 2026** se han revisado las secciones **1.1 a 1.7** y **2.1 a 2.6** sobre el checkout con HEAD en **84ea7df**. [Revisión técnica del capítulo 1](revision_tecnica_capitulo_01.md), [revisión técnica del capítulo 2](revision_tecnica_capitulo_02.md).

Al revisar otro capítulo, se añade una ficha cuando aparece una decisión nueva. Si una decisión ya tiene ficha, se amplía su referencia a la tesis y se agrega la evidencia nueva. La fecha de revisión indica cuándo se incorporó el hallazgo a esta bitácora. La fecha de decisión se consigna cuando consta en la fuente. Si el código permite ver qué se adoptó y falta el motivo histórico, el motivo queda por confirmar con el equipo. Los cambios propuestos al texto se dan por aplicados cuando se verifica la versión de la memoria que los incorpora.

## Decisiones identificadas en el capítulo 1

### DEC-01. Conservar el cómputo local y precisar la persistencia en la nube

- **Propuesta inicial.** La tesis planteaba combinar almacenamiento en Google Cloud Platform y cómputo local. El objetivo de diseño ya mencionaba PostgreSQL y la descripción tecnológica lo situaba en Cloud SQL. (§1.2, §1.4, §1.5, §1.7, OE3, y §2.6).
- **Decisión adoptada.** El nodo ejecuta la preparación, el entrenamiento y la inferencia. GCS conserva archivos y PostgreSQL guarda cuentas, permisos, metadatos y resultados. El despliegue institucional utiliza PostgreSQL en Cloud SQL a través de un proxy externo. Compose conserva un perfil con PostgreSQL local.
- **Motivo y consecuencia.** Se aprovechó el hardware local para el cómputo. Para conectar el nodo a Cloud SQL se mantuvo el controlador PostgreSQL existente y se delegó el transporte al proxy. El perfil institucional requiere operar ese proceso y gestionar los permisos de la base de datos. La estimación económica debe reflejar los servicios de cada escenario.
- **Evidencia.** [ADR 0059 sobre Cloud SQL](../adr/0059-conexiones-cloud-explicitas-mediante-proxy.md), [perfil PostgreSQL en Compose](../../docker-compose.yml#L2), [guía de entrega del nodo](../manuales/entrega_a_kevin.md).

### DEC-02. Consolidar PyTorch como motor de entrenamiento

- **Propuesta inicial.** La lista de actividades contemplaba «PyTorch/TensorFlow» y el stack los presentaba como motores del sistema. (§1.7, OE4, y §2.6).
- **Decisión adoptada.** El entrenador utiliza PyTorch y la opción TensorFlow está deshabilitada en la interfaz.
- **Motivo y consecuencia.** La iteración bioacústica documenta la adopción conjunta de PyTorch, TorchAudio y modelos de `timm`, lo que permitió integrar la extracción espectral y el entrenamiento en el mismo entorno. Queda por confirmar si el equipo hizo una comparación específica con TensorFlow antes de limitar el motor a PyTorch.
- **Evidencia.** [ADR 0001 y stack de la iteración](../adr/0001_migracion_efficientnet_frontend_gpu.md), [entrenador](../../backend/app/services/training.py#L820), [selector de la interfaz](../../frontend/components/views/TrainingView.tsx#L1981).

### DEC-03. Mover la extracción Mel del entrenamiento al procesamiento por lotes

- **Propuesta inicial.** La memoria mencionaba Librosa como herramienta de preprocesamiento y el capítulo 2 incluía espectrogramas y MFCC como salidas. La primera implementación calculaba espectrogramas con Librosa por muestra durante el entrenamiento. (§1.7, OE1 y OE4, §2.2(b) y §2.6).
- **Decisión adoptada.** El cargador entrega formas de onda y TorchAudio calcula espectrogramas Mel por lote en el dispositivo de ejecución. Librosa se conserva en la preparación explícita de ingesta y en rutas de inferencia que la requieren. El motor selecciona CUDA cuando el proceso dispone de ella y CPU en caso contrario.
- **Motivo y consecuencia.** En las pruebas iniciales la extracción por muestra saturaba la CPU y hacía que la GPU esperara los datos. El cambio desplazó ese trabajo al procesamiento por lotes y permitió mantener una ruta en CPU para equipos sin CUDA. La memoria debe describir los espectrogramas Mel como entrada implementada y conservar MFCC como tema investigado. Los tiempos de los experimentos corresponden al hardware y configuración registrados en cada prueba.
- **Evidencia.** [ADR 0003, 6 de septiembre de 2026](../adr/0003_pipeline_datos_gpu_raw_waveform.md), [preparación de ingesta](../../backend/app/services/ingestion.py#L499), [dispositivo del entrenador](../../backend/app/services/training.py#L855), [extracción por lotes](../../backend/app/services/training.py#L995).

### DEC-04. Ajustar la pérdida y la regularización durante la experimentación

- **Propuesta inicial.** La introducción vinculaba la falta de memoria con la reducción manual del conjunto para balancearlo. La decisión técnica se tomó tras observar solapamiento entre clases en el prototipo bioacústico. (§1.1.2 y §1.1.3).
- **Decisión adoptada.** Se ensayó Focal Loss para dar mayor peso a ejemplos difíciles y Mixup espectral como regularización. El entrenador web permite elegir Focal Loss o entropía cruzada y habilitar Mixup.
- **Motivo y consecuencia.** El equipo buscaba reducir el efecto de los ejemplos fáciles y mejorar la generalización ante señales solapadas. La implementación web de Focal Loss configura `gamma`. Su uso no implica ponderación explícita por frecuencia de clase. El balance de energía RMS pertenece a la experimentación de mezclas acústicas de motores y responde a un problema distinto.
- **Evidencia.** [ADR 0001 sobre Focal Loss](../adr/0001_migracion_efficientnet_frontend_gpu.md), [ADR 0002 sobre Mixup](../adr/0002_mixup_gpu_tta_inferencia.md), [pérdida y regularización del entrenador](../../backend/app/services/training.py#L1009), [mezcla aditiva de señales](../../backend/training/pipelines/additive_mixing.py).

### DEC-05. Incorporar la retroalimentación con curación humana y sincronización recuperable

- **Propuesta inicial.** El texto daba a entender que registrar una corrección expandía automáticamente el conjunto respaldado en la nube. El objetivo del software también asociaba la integración con GCS al respaldo de los registros de error. En una etapa de la implementación, la aprobación escribía primero en GCS. (§1.2, §1.6, OE3–OE5, y §2.2(a), (c) y (d)).
- **Decisión adoptada.** El investigador envía la corrección para revisión. Un usuario autorizado decide si la incorpora. La aprobación verifica y publica el audio y sus metadatos localmente, y registra la sincronización pendiente. Un proceso independiente copia el aporte a GCS. El entrenamiento posterior se inicia explícitamente sobre una preparación admitida.
- **Motivo y consecuencia.** La revisión humana reduce el riesgo de incorporar etiquetas equivocadas. Aceptar primero la muestra local permite preparar los datos aunque falle la copia remota, siempre que la fuente requerida esté disponible para la aprobación. El sistema debe conservar el estado pendiente para reintentar la sincronización.
- **Evidencia.** [ADR 0013 sobre curación](../adr/0013_bucle_retroalimentacion_curacion_semi_manual_mlops.md), [ADR 0018 sobre incorporación local](../adr/0018-incorporacion-local-y-sincronizacion-gcs.md), [aprobación](../../backend/app/services/feedback.py#L493), [worker de sincronización](../../backend/app/services/feedback_sync_worker.py#L79).

### DEC-06. Identificar las particiones y conservar juntas las grabaciones relacionadas

- **Propuesta inicial.** La introducción ofrecía trazabilidad y repetibilidad sin precisar cómo se fijaba la pertenencia de las grabaciones. El objetivo del software hablaba de reincorporar los datos corregidos. Antes de incorporar el particionado web, los conjuntos nuevos requerían preparar CSV fuera de la aplicación. (§1.4, §1.7, OE3–OE5, y §2.2(c)).
- **Decisión adoptada.** El inicio del entrenamiento admite una preparación CSV identificada o una versión explícita de particiones. Se conservan el manifiesto y la identidad de los datos usados. La preparación separa entrenamiento, validación y prueba y mantiene juntos los grupos de origen conocidos. En el flujo web, el sistema puede excluir aportes sin grupo trazable.
- **Motivo y consecuencia.** Reescribir particiones al incorporar un audio cambiaría la composición de experimentos previos y podría separar una grabación de sus derivados. Fijar las versiones permite comparar resultados bajo condiciones documentadas. Una clase con pocos grupos puede quedar representada solo en entrenamiento y la ejecución CUDA carece de garantía de reproducibilidad bit a bit.
- **Evidencia.** [ADR 0026 sobre versiones CSV](../adr/0026-versiones-preparadas-y-procedencia-curada.md), [ADR 0062 sobre particiones web](../adr/0062-particiones-explicitas-y-manifiestos-inmutables.md), [procedencia del checkpoint](../../backend/app/services/training.py#L1207).

### DEC-07. Evaluar el checkpoint antes de hacerlo elegible para inferencia

- **Propuesta inicial.** La introducción enlazaba entrenamiento, métricas y predicción de forma general y el objetivo del software hablaba de exportar métricas. En etapas de desarrollo se utilizaban métricas por época y evaluaciones con procedencia dispar. (§1.2, §1.6, §1.7, OE5, y §2.2(c)).
- **Decisión adoptada.** El servicio guarda el checkpoint y sus métricas. La evaluación estándar posterior mide por grabación en validación y prueba y vincula los informes a la huella del checkpoint y sus particiones. La activación del modelo predeterminado requiere una operación administrativa.
- **Motivo y consecuencia.** La decisión permite relacionar las métricas publicadas con el artefacto evaluado y evita sustituir automáticamente el modelo activo. La evaluación de cada componente de un entrenamiento múltiple tiene su propia evidencia. El ensamble combinado requiere su propia evaluación.
- **Evidencia.** [ADR 0017 sobre disponibilidad y activación](../adr/0017-disponibilidad-y-activacion-modelos.md), [ADR 0022 sobre evaluación](../adr/0022-evaluaciones-finales-estandarizadas.md), [evaluación del modelo registrado](../../backend/app/services/training.py#L733), [consulta del historial en la API](../../backend/app/main.py#L1136), [activación administrativa](../../backend/app/main.py#L1145).

### DEC-08. Hacer explícito el respaldo de pesos en GCS

- **Propuesta inicial.** La introducción describía la nube como repositorio central. El capítulo 2 atribuía a GCS el almacenamiento de los pesos. El nombre del campo histórico `ruta_binario_gcp` podía sugerir que registrar un entrenamiento ya implicaba una copia remota. (§1.2, §1.4, §2.2(a) y §2.6).
- **Decisión adoptada.** El entrenamiento guarda los pesos en el nodo y registra su identidad. El respaldo y la restauración se solicitan por separado y verifican el contenido mediante tamaño y SHA-256.
- **Motivo y consecuencia.** La huella permite identificar los bytes que corresponden a un registro de modelo y evitar colisiones por nombre. La recuperación del checkpoint depende de conservar la asociación en PostgreSQL. El respaldo de la base de datos y la activación del modelo tienen sus propios procedimientos.
- **Evidencia.** [ADR 0063, 23 de octubre de 2026](../adr/0063-respaldo-explicito-de-checkpoints-por-contenido.md), [operaciones de respaldo y restauración](../../backend/app/routes/checkpoints.py#L35), [registro del checkpoint](../../backend/app/services/training.py#L1261).

### DEC-09. Declarar los ensambles que ofrece cada instalación

- **Propuesta inicial.** La introducción hablaba de entrenar redes neuronales y mostrar predicciones sin precisar cómo se seleccionaría un predictor. Una implementación anterior añadía ensambles estáticos al catálogo durante el arranque. (§1.2).
- **Decisión adoptada.** El registro resuelve predictores con una interfaz común. Cada instalación declara los ensambles que ofrece. El predictor de aves combina ConvNeXt-Nano, EfficientNet-B0 y ResNet34d. El de motores combina ResNet34d, EfficientNet-B0 y PANNs CNN14.
- **Motivo y consecuencia.** Se preservó el registro SQL de modelos individuales y se representaron los compuestos en el perfil de instalación. Esto permite elegir qué se ofrece por nodo. Trasladar la instalación exige trasladar la declaración y comprobar los pesos correspondientes.
- **Evidencia.** [ADR 0011 sobre registro y predictores](../adr/0011_soporte_multimodelo_registry_strategy.md), [ADR 0068 sobre ensambles por instalación](../adr/0068-declaracion-explicita-de-ensambles-por-instalacion.md), [construcción del registro](../../backend/app/services/registry.py#L531).

### DEC-10. Añadir importaciones ZIP privadas con validación en segundo plano

- **Propuesta inicial.** La ingesta descrita en la introducción consistía en descargar conjuntos desde GCS. El capítulo 2 agregó como objetivo la carga hacia GCS. El catálogo original listaba conjuntos en rutas compartidas. (§1.2, §1.7, OE4, y §2.2(a)).
- **Decisión adoptada.** Se añadió una importación privada por usuario, con recepción HTTP, validación y publicación local gestionadas como operaciones identificables. Los trabajos de validación y publicación se procesan en segundo plano en instalaciones que habilitan los workers. La sincronización de la revisión con GCS se solicita por separado.
- **Motivo y consecuencia.** El catálogo privado evita exponer los archivos de un usuario en el prefijo compartido. Una cola persistente permite consultar el resultado y recuperar trabajos sin depender de mantener la petición HTTP abierta. El módulo requiere un entorno compatible con POSIX. La publicación privada conserva un registro distinto del catálogo de entrenamiento.
- **Evidencia.** [ADR 0027 sobre importaciones privadas](../adr/0027-importaciones-zip-privadas-locales.md), [ADR 0030 sobre trabajos durables](../adr/0030-admision-durable-importaciones.md), [ADR 0069 sobre integración](../adr/0069-integracion-de-acceso-evaluacion-y-datasets.md), [publicación local en el worker](../../backend/app/services/dataset_import_execution.py#L143).

### DEC-11. Aplicar sesiones revocables y permisos por conjunto de datos

- **Propuesta inicial.** La tesis identificaba a investigador y administrador y mencionaba IAM para la conexión a Google Cloud. El diseño de acceso web evolucionó desde un contrato previo con JWT. (§1.7, OE2).
- **Decisión adoptada.** El navegador utiliza sesiones revocables con cookie HttpOnly. El backend evalúa el rol y las asignaciones de conjuntos de datos para autorizar operaciones. Las credenciales de Google corresponden al nodo que se conecta a GCS.
- **Motivo y consecuencia.** Guardar sesiones en la base facilita revocar el acceso. Las asignaciones explícitas permiten controlar el uso de audios, modelos y predicciones a partir de asociaciones comprobables. La operación web depende de que PostgreSQL esté disponible para verificar la sesión y los permisos.
- **Evidencia.** [ADR 0052 sobre sesiones](../adr/0052-sesiones-web-revocables-y-registro-administrado.md), [ADR 0053 sobre permisos](../adr/0053-asignaciones-explicitas-y-propiedad-de-entrenamiento.md), [control de recursos](../../backend/app/services/access.py#L35).

## Decisiones incorporadas al revisar el capítulo 2

### DEC-12. Aislar el entrenamiento de las solicitudes HTTP

- **Propuesta inicial.** El objetivo del software describía un orquestador local. Una implementación anterior ejecutaba el entrenamiento en un hilo y compartía el estado aleatorio con la API. (§2.1 y §2.2(c)).
- **Decisión adoptada.** La API admite el trabajo y lo inicia en un proceso hijo mediante `spawn`. Un supervisor del backend consume sus eventos. La interfaz consulta el progreso por HTTP.
- **Motivo y consecuencia.** El proceso separado aísla el estado del entrenamiento. El supervisor permite continuar aunque se cierre la pestaña y comprueba el estado final con la salida del proceso. La admisión y el control del trabajo pertenecen al proceso de la API que lo inició.
- **Evidencia.** [ADR 0024, 15 de octubre de 2026](../adr/0024-entrenamiento-aislado-spawn.md), [inicio y supervisión](../../backend/app/services/training.py#L610), [consulta periódica](../../frontend/components/views/TrainingView.tsx#L804).

### DEC-13. Preservar las grabaciones cargadas cuando hay colisiones de nombre

- **Propuesta inicial.** La tesis formulaba la carga y descarga como integración bidireccional. Antes del cambio de acceso e instalación, la carga directa utilizaba la clave de dataset, clase y nombre sin una condición de creación exclusiva. (§2.2(a)).
- **Decisión adoptada.** El servicio valida el lote y solicita la creación de cada objeto sin reemplazo. Ante una clave existente, acepta como ya presente un archivo cuyo contenido coincide y reporta el conflicto si la coincidencia no se confirma.
- **Motivo y consecuencia.** La carga por investigadores autorizados debe conservar los originales frente a reemplazos silenciosos. Una colisión puede producir un resultado parcial y el usuario puede revisar qué archivos se aceptaron.
- **Evidencia.** Cambio de implementación en `aa53e09`. [ADR 0061 sobre cargas de investigadores](../adr/0061-autonomia-investigadora-en-datasets-asignados.md), [creación y manejo de colisiones](../../backend/app/services/ingestion.py#L884).

### DEC-14. Actualizar las dependencias del frontend y conservar el archivo de bloqueo verificado

- **Propuesta inicial.** La tabla de la tesis citaba React 18 y Next.js 14 o superior. En el checkout, HEAD declaraba Next.js 16.3.4 antes del ajuste de noviembre. (§2.6, tabla 2.1).
- **Decisión adoptada.** Se actualizó el manifiesto local a Next.js 16.4.5 y se conservó el archivo de bloqueo verificado en el laboratorio Docker. La ficha distingue la versión registrada en HEAD de la actualización presente en el checkout.
- **Motivo y consecuencia.** El registro del 9 de noviembre documenta que la actualización se hizo tras revisar alertas de las dependencias de producción. Se comprobó la compilación y el funcionamiento de las pruebas del frontend en ese entorno. Para la defensa se puede citar la versión junto al manifiesto y el alcance de esa comprobación.
- **Evidencia.** [Recibo de diagnóstico de dependencias](../receipts/verificacion_docker_cloud_y_dependencias_20261109.json#L26), [recibo de actualización y validación](../receipts/cierre_verificacion_docker_20261109.json#L27), [manifiesto del frontend](../../frontend/package.json).

## Decisiones y ajustes de alcance de la memoria

| Referencia | Ajuste | Estado |
| --- | --- | --- |
| §1.4 | Centrar los ejemplos en bioacústica aviar y diagnóstico acústico de motores. Presentar otros dominios como posibles extensiones sujetas a datos y evaluación. | Propuesto en la revisión. |
| §1.6 y §1.7, OE5 | Conservar la evaluación del rendimiento y la viabilidad. Presentar el efecto del reentrenamiento con aportes curados como una pregunta que requiere una comparación documentada con la línea base. | Propuesto en la revisión. |
| §2.3–2.4 | Describir las prácticas de Scrum según los registros del equipo y reconocer el uso documentado de seguimiento Kanban, pruebas automatizadas y ADR. Presentar IEEE 829 e IEEE 830 como referencias adaptadas. | Propuesto en la revisión. |
| §2.6 | Presentar Antigravity y Gemini como herramientas de apoyo si el equipo confirma su uso y el alcance descrito. | Pendiente de confirmar con el equipo. |
| Apéndice F | Omitir F.1 y el ejemplo de manifiesto JSON. La pauta reserva ese apartado para bases no relacionales y F.A.M.A. utiliza PostgreSQL. | Aplicado al [fuente LaTeX del diccionario](anexo_f_diccionario_datos.tex) por decisión del equipo en esta conversación. |

## Ejemplos para la defensa

- **Por qué la corrección no actualiza el modelo de inmediato.** «La propuesta inicial buscaba aprovechar los errores de predicción. Durante el desarrollo incorporamos una revisión humana para controlar la calidad de las etiquetas. Después separamos la incorporación local de la copia en la nube. Así podemos preparar un nuevo entrenamiento con las muestras aprobadas y registrar qué versión usamos». Referencias **DEC-05 y DEC-06**.
- **Qué problema resolvió TorchAudio.** «En el prototipo calculábamos el espectrograma de cada grabación en CPU y eso dejaba a la GPU esperando datos. Pasamos a cargar formas de onda y calcular los espectrogramas por lote en el dispositivo de entrenamiento. Conservamos Librosa en las partes del sistema donde su procesamiento sigue siendo el adecuado». Referencia **DEC-03**.
- **Cuándo se puede usar un modelo recién entrenado.** «Guardar los pesos, evaluar el checkpoint y elegir el predeterminado son decisiones distintas. Registramos el resultado del entrenamiento, lo evaluamos sobre particiones identificadas y dejamos la activación al administrador». Referencias **DEC-06 y DEC-07**.
