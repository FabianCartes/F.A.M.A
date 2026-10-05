# Revisar e incorporar audios

El audio inferido solo entra al dataset después de una validación explícita y una aprobación en la cola de revisión. Confirmar o corregir una clase no incorpora la muestra ni inicia un entrenamiento. El destino se conserva automáticamente al ejecutar el modelo: no se elige otro dataset durante la revisión.

## Recorrido de uso

1. En **Inferencia**, cargar un WAV y seleccionar el modelo. Conservar el resultado y su identificador de predicción; **Dataset de inferencia** muestra el ID persistido con ese resultado.
2. Elegir uno de los botones grandes: **Correcta**, con marca verde, o **Incorrecta**, con X roja. No hay una opción seleccionada por defecto. Si es incorrecta, elegir la clase corregida del catálogo asociado a esa inferencia.
3. Pulsar explícitamente **Enviar a revisión**. Elegir acierto/error o una corrección no envía por sí solo el feedback.
4. En **Gestión de audios**, consultar los pendientes y revisar la clase propuesta y el **Dataset de inferencia**. La clase será la predicha si se confirmó el acierto, o la corregida si se indicó un error. El destino es informativo: no hay selector de dataset.
5. Pulsar **Incorporar al dataset** para aceptar el audio en el dataset local persistente y dejar pendiente su copia en GCS, o **Descartar de la cola** para retirar el pendiente sin borrar físicamente la fuente ni modificar los datasets.

Antes de enviar la validación no hay un elemento en la cola. Después del envío queda pendiente, pero todavía no hay una copia de entrenamiento. La aprobación termina cuando el audio y sus metadatos locales están verificados y se confirma, en una misma transacción de base de datos, el estado procesado y la intención de sincronización. **El audio local aceptado puede usarse para preparar entrenamiento aunque GCS siga pendiente.** Aprobar no inicia entrenamiento ni garantiza que un dataset pequeño tenga particiones suficientes.

## Destino persistido y contrato de aprobación

La predicción guarda una instantánea nullable en `prediccion.dataset_name`, tomada del **modelo realmente ejecutado**, no de una selección de dominio ni del modelo que esté activo cuando se revise. El resultado la expone en `detalles.dataset_name` y la cola en `dataset_name`.

- Los predictores estándar de aves tienen el destino explícito `AvesChilenas`.
- Para un modelo registrado, se valida la asociación persistida con `conjunto_datos`: su nombre debe ser un componente de ruta válido. Su `ruta_gcp` puede coincidir con `datasets/<nombre>` o `gs://<bucket configurado>/datasets/<nombre>`, o ser la URI `file://` canónica del directorio local `backend/data/raw/<nombre>`, obtenido por el resolver de rutas del backend (en el contenedor: `file:///app/data/raw/<nombre>`). Se admite la barra final.
- La ruta local debe corresponder exactamente al nombre registrado y a un directorio existente; su destino físico debe permanecer dentro de la raíz raw. Se rechazan rutas externas, traversal incluso codificado, autoridades en `file://`, rutas malformadas y symlinks que escapen de esa raíz. No basta con que cualquier ruta local exista.
- No se supone que todos los bundles pertenezcan a ese dataset. Una asociación desconocida o inválida queda como `NULL`, sin impedir por sí sola la inferencia.

La asociación local verificada se expone en el catálogo y en los predictores registrados para inferencias nuevas. AUDIO-3a conecta la aprobación a la incorporación local y a la cola durable; AUDIO-3b agrega subida automática recuperable y consulta read-only. **Gestión de audios presenta estos estados por separado**: la cola conserva audios sin curar y el panel de sincronización muestra registros aceptados recientes.

Las predicciones antiguas o sin asociación verificable permanecen en `NULL`: no se adivina ni se rellena retrospectivamente el destino, y no existe una selección manual para repararlo. La interfaz muestra la advertencia y deshabilita la incorporación; una aprobación por API devuelve un error explícito y conserva el pendiente. **Descartar de la cola** sigue disponible.

La llamada normal es `POST /api/feedback/<ID feedback>/approve`, sin cuerpo JSON ni consulta de destino: basta el ID del feedback. La consulta `dataset_name` sigue siendo opcional por compatibilidad con clientes antiguos, pero solo se acepta si coincide exactamente con el destino persistido. Un valor distinto devuelve HTTP 409; nunca reemplaza el destino ni completa un `NULL`.

## Qué conserva cada operación

| Operación | Resultado |
| --- | --- |
| Inferir | Conserva una fuente única `raw_audios/<UUID>.wav` en GCS y registra su vínculo con la predicción y su destino verificable, si existe. |
| Validar/corregir | Registra feedback pendiente; no copia al dataset. |
| Incorporar | Descarga la fuente administrada de GCS, verifica el WAV y publica audio/CSV durables en local. Confirma conjuntamente `procesado=True` y `feedback_sync.pending`; no sube al dataset cloud durante la petición. |
| Descartar | Marca el feedback como procesado y lo retira de pendientes. No borra físicamente la fuente ni modifica los datasets. |

Los destinos de incorporación son:

- Objeto GCS **pendiente**, no escrito por la aprobación: `datasets/<ID canónico del dataset>/<directorio real de clase>/feedback_<ID feedback>.wav`.
- Local: `backend/data/raw/<ID canónico del dataset>/<directorio real de clase>/feedback_<ID feedback>.wav`.

El archivo local conserva los bytes exactos de la fuente. El directorio se resuelve primero contra los directorios locales existentes y, si hace falta, las clases del `metadata.csv` local. Se exige una coincidencia única tras normalización Unicode **NFC**, `casefold` y equivalencia de espacios/guiones bajos. Incluso una coincidencia exacta se rechaza si hay otro directorio normalizado equivalente. Así, `Rayadito` usa `rayadito` y `Churrín de la Mocha` puede usar `Churrín_de_la_Mocha`, preservando la etiqueta semántica en el CSV y la cola. No se eliminan acentos ni se inventan aliases taxonómicos.

Un catálogo local conocido no depende de listar GCS. Se rechazan clases desconocidas o ambiguas; si solo los metadatos respaldan la clase, puede crearse su directorio. El listado cloud se conserva únicamente como compatibilidad para datasets sin clases en local (por ejemplo, un CSV solo con cabecera). También exige una clase conocida y única; no permite crear clases inventadas. La fuente raw sigue descargándose desde GCS en el primer intento. Se rechazan symlinks en destinos, ancestros, CSV, intención y temporales, incluidos enlaces que apunten dentro de raw.

La aprobación **crea `metadata.csv` si falta** y completa su cabecera si era reducida. Incluye nombre canónico, clase semántica, frecuencia, duración, tamaño, SHA-256, procedencia `feedback_<ID>` / `human_feedback` y `file_path` relativo al dataset. Este último permite que entrenamiento resuelva directorios cuya forma no coincida con `clase.lower()`. Al ampliar un CSV legacy, conserva las filas y sus columnas; añade rutas locales verificables para sus audios, sin inventar destinos ni reparar muestras ausentes. Una fila previa sin audio verificable bloquea la actualización con error explícito.

La disponibilidad se verifica con el ingestor local usando el CSV como anotaciones semánticas. No equivale a ejecutar entrenamiento: particiones `train`/`val` existentes no se regeneran automáticamente, ni hay preprocesamiento o control de calidad acústica. Preparar o actualizar esas particiones sigue siendo parte del flujo de datos del operador.

## Reintentos, concurrencia y resolución de problemas

El primer intento fija **dataset, clase semántica, fuente, directorio físico y nombre** mediante `.feedback_<ID>.json` bajo raw. Antes de publicar los artefactos fija también el SHA-256. Cada publicación usa staging, `fsync` del archivo y del directorio. El CSV y la intención se reemplazan atómicamente; el audio se publica mediante enlace atómico **sin reemplazo** del destino. Solo se reutiliza un archivo canónico existente cuando su hash coincide; un conflicto conserva el archivo y devuelve error.

El bloqueo `flock` estable por feedback abarca toda la aprobación hasta el commit. Otro bloqueo por dataset serializa publicación y lectura/reemplazo del CSV entre feedback distintos. El bloqueo de fila PostgreSQL y los locks de filesystem requieren escritores cooperantes y un filesystem Linux compatible. No hay transacción distribuida: un fallo puede dejar intención, staging, fila CSV o audio antes del commit. Es evidencia recuperable, **no una aprobación confirmada**. El error de base de datos devuelve HTTP 503; rollback revierte conjuntamente el estado y la cola, no el filesystem.

Repetir `POST /api/feedback/<ID>/approve` con el mismo destino recupera el intento: si el audio local existe, verifica el hash fijado sin volver a descargar; si falta, intenta recuperar la fuente administrada. Verifica también la fila CSV, completa lo que falta y vuelve a confirmar estado+cola. Si el commit ocurrió pero se perdió su acuse, el replay verifica los artefactos y devuelve éxito sin duplicar la fila o cambiar el estado de sincronización.

Una aprobación nueva devuelve los campos legacy `status=approved`, ID, ruta, clase y filename, más **`local_status=incorporated` y `sync_status=pending`**. El replay devuelve el estado real de la cola, incluso `synced` si posteriormente lo confirma el uploader. No modifica intentos ni outcomes cloud. Un procesado legacy sin intención de cola —incluido un descarte— no puede convertirse en aprobación. Una incorporación iniciada tampoco puede descartarse ni cambiar clase/destino por reenvío de feedback.

No borrar ni editar intenciones para cambiar destinos. Las intenciones legacy con nombre `<slug>_fb_<ID>.wav` se rechazan para recuperación explícita; este corte no renombra ni reincorpora históricos, ni rellena predicción 23/feedback 5.

| Síntoma | Comprobación o acción |
| --- | --- |
| Sin dataset de inferencia asociado | La incorporación no está disponible; HTTP 409 por API. Mantener pendiente o descartar; no adivinar el destino ni usar un override manual. |
| Error GCS al inferir | Comprobar bucket, configuración y permisos de escritura en el entorno autorizado. Sin confirmación de carga no hay resultado exitoso persistido. |
| HTTP 503 al incorporar | No hay éxito confirmado. Revisar acceso a la fuente, catálogo cloud solo si falta catálogo local, permisos y durabilidad local o disponibilidad de BD. Conservar evidencia y reintentar la misma intención. Una caída de subida al dataset GCS no participa en esta petición. |
| Fuente histórica ausente o ruta antigua | Solo se admite la fuente administrada `raw_audios/<UUID>.wav`. No se recuperan automáticamente audios históricos por nombre ni se fabrican sustitutos. La aprobación falla y el elemento permanece pendiente. |
| HTTP 409 al reenviar feedback, descartar o aprobar | El elemento terminó sin cola de aprobación, inició incorporación, carece de destino verificable o la consulta legacy intenta cambiarlo. Un replay de aprobación con cola válida sí se admite. No cambiar clase/destino mediante reenvíos. |
| HTTP 422 al incorporar | Revisar componentes de ruta válidos (no vacíos, hasta 100 caracteres, sin separadores ni controles) y ambigüedad o ausencia del catálogo. `dataset_name` no es obligatorio; si se envía por compatibilidad, debe ser válido y coincidir con el persistido. |
| Reintento incompatible con la intención | No cambiar dataset, clase, fuente ni directorio. Conservar la intención original y diagnosticar el error sin editarla. |

## Migración antes de actualizar el backend

Una base existente requiere la migración explícita de [`migrate_prediction_dataset.py`](../../backend/scripts/migrate_prediction_dataset.py). `create_all` crea tablas nuevas, pero **no altera una tabla existente**. La migración no se ejecuta automáticamente al iniciar el backend.

Procedimiento para un operador autorizado; este manual no concede autorización ni acredita que se haya ejecutado:

1. Obtener y verificar un respaldo recuperable de la base de datos, según el procedimiento del operador.
2. Pausar los escritores de **inferencia y curación** para evitar operaciones concurrentes durante el cambio.
3. Suministrar explícitamente en el entorno la `DATABASE_URL` aprobada para la base objetivo, sin imprimir su valor ni exponer secretos. El script no carga `.env` ni usa una URL por defecto.
4. Desde la **raíz del repositorio**, con el intérprete Python del entorno de dependencias existente, ejecutar **antes de actualizar el backend**:

   ```bash
   python backend/scripts/migrate_prediction_dataset.py --apply
   ```

5. Verificar el resultado: `dataset_name added` si agregó la columna, o `dataset_name already present` si ya existía. Solo después de comprobar el éxito, continuar la actualización y la reanudación de escritores conforme al procedimiento autorizado de despliegue.

El script soporta **SQLite y PostgreSQL** y agrega `dataset_name VARCHAR(100) NULL` a `prediccion`. Es idempotente si la columna ya existe; no hace backfill: las filas antiguas conservan `NULL`. No exige instalar dependencias nuevas ni se debe sustituir la URL aprobada por una base elegida automáticamente.

## Intención durable de sincronización (AUDIO-2 + AUDIO-3a/3b)

La cola **record-only** está conectada a la aprobación local, al sincronizador, a su arranque gestionado y a la consulta de estados de Gestión de audios. La aprobación verifica audio/CSV durables antes de encolar y marcar `procesado` en su misma transacción. La mera existencia de una intención de cola no prueba por sí sola que los archivos sigan íntegros: el replay los vuelve a comprobar.

La tabla `feedback_sync` tiene una fila por `id_retroalimentacion` (clave primaria y FK restrictiva). Conserva dataset, clase semántica, directorio canónico, objeto, ruta relativa y SHA-256 de los bytes que se subirán. `pending`/`synced` son independientes de `retroalimentacion.procesado`: ese booleano legacy también representa descarte. No se crean intenciones para registros históricos.

Contrato de [`FeedbackSyncQueue`](../../backend/app/services/feedback_sync.py), con sesión SQLAlchemy suministrada por el llamador:

- `enqueue(db, feedback_id, *, dataset_name, storage_class, sha256)`: exige ID entero positivo, dataset igual al persistido en la predicción, componentes de ruta válidos y hash hexadecimal minúsculo de 64 caracteres. La clase semántica proviene del feedback/predicción; la aprobación suministra el directorio ya resuelto y verificado, no una ruta del cliente.
- Deriva `datasets/<dataset>/<storage_class>/feedback_<ID>.wav` y la ruta local relativa `<dataset>/<storage_class>/feedback_<ID>.wav`. No recibe rutas absolutas, bucket ni clave arbitraria. La aprobación nueva usa este mismo nombre; no renombra los archivos legacy `<slug>_fb_<ID>.wav`.
- Un duplicado exacto devuelve la misma identidad y estado; un destino, clase o hash diferente devuelve `ValueError` sin reemplazar la intención. Las instantáneas retornadas son inmutables; no hay protección contra cambios SQL directos fuera del módulo.
- `get(db, feedback_id)` devuelve una instantánea o `None`; `pending(db, limit=50)` devuelve pendientes ordenados por menor número de intentos y luego ID, independientemente de `procesado`. `recent(db, limit=50)` consulta solo filas con feedback procesado, por ID descendente. Ambas lecturas exigen límites enteros entre 1 y 500.
- `mark_outcome(db, feedback_id, *, success, error_code=None)` registra un intento: fallo conserva `pending` y solo admite `upload_failed` o `integrity_mismatch`, nunca mensajes, rutas o secretos del proveedor. Éxito limpia el error y marca `synced`; repetir éxito no incrementa intentos. `synced` es terminal y no admite volver a pendiente. El uploader de AUDIO-3b llama éxito solo tras confirmar la subida; la aprobación local no llama `mark_outcome`.

Las operaciones no hacen commit ni rollback; las escrituras hacen flush de la sesión y pueden incluir cambios pendientes del llamador. Este controla confirmación, rollback y errores de base de datos. La cola no escribe archivos, calcula hashes, sube bytes, reclama trabajos ni ejecuta reintentos. El sincronizador posee sus propias sesiones y coordina la exclusión con el mismo lock de filesystem de aprobación. SQLite no proporciona `FOR UPDATE`; PostgreSQL real no se ha ejercitado.

### Creación explícita del esquema de sincronización

Con respaldo verificado, escritores pausados y `DATABASE_URL` explícita aprobada por el operador, desde la raíz:

```bash
python backend/scripts/migrate_feedback_sync.py --apply
```

El [script](../../backend/scripts/migrate_feedback_sync.py) no carga `.env`, no importa la aplicación ni elige una base por defecto. Soporta PostgreSQL/SQLite y requiere la tabla legacy `retroalimentacion`. Crea **solo** `feedback_sync`; devuelve `feedback_sync added` o `feedback_sync already present` al reejecutarse. No modifica columnas, filas ni estados anteriores, no hace backfill y no declara audios históricos localmente listos. Si la tabla ya existe, no repara ni valida un esquema incompatible: inspeccionarlo es responsabilidad del operador.

El modelo también está registrado en `Base.metadata`: el `create_all` del arranque puede crear esta tabla faltante tanto en una base nueva como en una existente; no altera tablas ya presentes ni inserta intenciones. Esto difiere de la migración de columnas de `prediccion`. El script es una acción operativa explícita disponible antes del despliegue, no un hook de arranque. No se ejecutó sobre una base desplegada.

Las pruebas de [cola](../../backend/tests/test_feedback_sync_queue.py) y [migración](../../backend/tests/test_feedback_sync_migration.py) usan SQLite temporal y la interfaz pública, verifican reconstrucción de sesión/módulo, duplicados, resultados, rollback y conservación de históricos. Comparan además el contrato de columnas de migración y metadata. No prueban PostgreSQL real, integridad de archivos, contención física/symlinks ni sincronización cloud.

Rollback de código: retirar modelo, registro, módulo, script, pruebas y esta sección sin tocar AUDIO-1. No se proporciona ni ejecuta una migración destructiva inversa. Si un operador ya creó la tabla y guardó intenciones, debe preservar esos registros y definir una recuperación explícita; revertir código no revierte datos.

## Sincronización automática y consulta de estados (AUDIO-3b)

`FeedbackSyncWorker(session_factory, raw_data_dir).run_once()` es la costura pública de reintento para código de aplicación y pruebas: posee y cierra sesiones, limita cada pasada a 50 candidatos por defecto (configurable entre 1 y 500) y devuelve contadores `attempted`, `synced`, `failed` de outcomes confirmados en BD. No es un endpoint HTTP de escritura. El runner recorre candidatas por ID con un cursor de página en memoria, volviendo al inicio al agotar el recorrido. A diferencia de la lectura `pending` de la cola, su cursor usa una clave inmutable: los intentos crecientes de otro archivo fallido no pueden impedir volver a un lock que ya se liberó. Avanza incluso si un lock no puede reclamarse o falla el commit: esas entradas no pueden incrementar intentos de forma segura, pero no monopolizan los lotes pequeños mientras siga vivo el runner. Un reinicio vuelve a empezar el recorrido; el estado y los intentos confirmados siguen siendo durables.

Antes de subir, revalida feedback procesado, dataset y clase de la predicción, fuente administrada y su coincidencia con la intención local, directorio/nombre canónicos, objeto determinista, ruta relativa y SHA-256. Rechaza archivos ausentes/corruptos, rutas externas y symlinks en archivo, intención o ancestros. Lee los bytes verificados bajo exclusión y entrega esos mismos bytes al adaptador, sin descargar fuentes, modificar CSV, inferir ni borrar archivos. La consulta de estados no vuelve a verificar los archivos: `incorporated` describe el hito local aceptado, no una auditoría física actual.

El orden de exclusión compartido es **fila de feedback → inode estable `.feedback_<ID>.json.lock` → fila de sync**, manteniéndolo hasta el commit. Usa `FOR UPDATE SKIP LOCKED` cuando el motor lo soporta y `flock` no bloqueante para omitir un uploader ocupado en SQLite o procesos cooperantes. No elimina ni reemplaza el lock. Una aprobación puede esperar ese mismo lock y luego devolver el outcome real.

Solo `True` del adaptador de subida confirma cloud: `False`, ausencia de acuse o excepción conserva `pending` con `upload_failed`. Una inconsistencia local conserva `pending` con `integrity_mismatch`. Incrementa intentos al confirmar cada outcome; nunca almacena mensajes privados del proveedor. Un fallo de commit se propaga sin declarar éxito: si hubo rollback, el próximo intento publica los mismos bytes en la misma clave; si el commit ocurrió y perdió el acuse, la reconstrucción ve `synced` y no sube otra vez. No existe transacción distribuida ni garantía de una única petición cloud bajo pérdida de acuse; sí identidad idempotente, sin duplicados locales/CSV.

El lifespan conserva carga de modelos y seeding inicial. Después inicia una tarea propia que hace una primera pasada de recuperación sin bloquear la disponibilidad HTTP por una caída cloud, y luego reintenta cada **60 segundos**. La pasada corre fuera del hilo de serving; excepciones de BD/local se registran como `database_or_local_unavailable`, sin detalles privados, y el loop continúa. El adaptador existente recibe timeout de **30 segundos** (configurable en el runner, máximo 60) y deshabilita retries internos del SDK para esta subida. El timeout limita la operación de red según el SDK, no sustituye límites operativos de BD/filesystem. No introduce broker ni dependencias nuevas.

Al cerrar, primero señala `stop`, no empieza nuevos uploads y despierta la espera periódica; después **espera la tarea y el trabajo en vuelo**, incluyendo su outcome/commit. No cancela `to_thread` pretendiendo que terminó. Un adaptador inyectado debe respetar el timeout; una BD o filesystem bloqueado puede prolongar el cierre. No se ejecutan escrituras desde un hilo abandonado después de retornar el lifespan.

### Contrato para Gestión de audios

`GET /api/feedback/sync?limit=50` devuelve un array de estados recientes por ID de feedback descendente, con máximo solicitado de **1 a 500**; límites inválidos devuelven HTTP 422 y BD indisponible HTTP 503 sanitizado. Solo incluye feedback procesado que tenga intención de sync; no incluye descartes legacy, históricos sin intención ni la cola de curación pendiente. No sube, reintenta, modifica outcomes ni expone rutas locales, fuente, hashes o errores privados. No requiere ni agrega un endpoint de mutación no autenticado; la política de acceso conserva la convención existente de lectura del backend.

```json
[
  {
    "id_retroalimentacion": 7,
    "id_prediccion": 12,
    "dataset_name": "AvesChilenas",
    "storage_class": "rayadito",
    "class_label": "Rayadito",
    "local_status": "incorporated",
    "sync_status": "pending",
    "attempts": 1,
    "error_code": "upload_failed"
  }
]
```

`sync_status` admite `pending` o `synced`; `error_code` es `null`, `upload_failed` o `integrity_mismatch`, y `attempts` es entero no negativo. `synced` significa subida reconocida y outcome confirmado en BD, no una consulta de existencia actual en GCS. La UI puede refrescar esta lectura independientemente de `/api/feedback/pending` y mostrar incorporación local y copia cloud como hitos distintos. No hay backfill de predicción 23/feedback 5 ni recuperación histórica automática.

### Lectura de estados en la interfaz (AUDIO-4)

**Revisar audios** muestra feedback todavía sin curar. Tras aprobar, el audio sale de esa cola; **Sincronización de audios incorporados** consulta los últimos 50 registros aceptados por `GET /api/feedback/sync?limit=50`. Son listas distintas: una cola vacía no significa que todas las copias cloud estén confirmadas. No se incluyen descartes ni históricos sin intención de sincronización.

| Estado mostrado | Interpretación y acción |
| --- | --- |
| Incorporado localmente | Hito local aceptado. Puede preparar entrenamiento antes de GCS, sin auditoría actual de archivos ni regeneración automática de particiones. |
| Pendiente de copia cloud | El backend realiza la sincronización automática; aprobar no confirma la subida. |
| Subida fallida | `upload_failed`: continúa pendiente y el backend reintenta automáticamente. |
| Integridad inconsistente | `integrity_mismatch`: requiere atención manual del operador; repetir la lectura o el intento no repara archivos. Conservar la evidencia y diagnosticarla en un entorno autorizado. |
| Copia cloud confirmada | `synced`: acuse de subida persistido, no comprobación de existencia actual del objeto. |

El panel expone ID de feedback/predicción, dataset, clase semántica, directorio de clase e intentos. La aprobación informa copia pendiente salvo que su respuesta real indique `synced`. Consultar o actualizar no sube archivos ni dispara un reintento: no hay botón de uploader ni nuevo POST de retry.

Las consultas de revisión y sincronización se actualizan al montar, al recuperar foco visible o volver visible la pestaña, y mediante sus controles manuales; el refresco general consulta ambas. Aprobar vuelve a consultar ambas listas. No hay polling periódico. Cada lectura cancela la anterior y descarta resultados y errores obsoletos; los listeners y peticiones se retiran al desmontar. Si falla una consulta, se informa el error y se conserva la última respuesta disponible, sin presentarla como una consulta exitosa nueva ni inventar una lista vacía.

Rollback UI: retirar `FeedbackSyncPanel.tsx`, su integración/refresco/mensajes en `IngestionView.tsx`, las pruebas nuevas y esta explicación, conservando los parciales API/schema, la aprobación local y las intenciones durables. No afecta datos ni ejecuta una reversión operativa.

Rollback del corte 3b: retirar runner y sus pruebas, wiring de lifespan/lectura en `main.py`, schema de estados, lecturas de cola y timeout opcional del adaptador, preservando aprobación local, tabla e intenciones de AUDIO-2/3a. No revertir datos ni eliminar evidencia pendiente. No se ha ejecutado rollback o despliegue real.

## Prerrequisitos y límites de verificación

La primera incorporación necesita acceso de lectura a la fuente raw administrada de GCS. El listado del catálogo requiere GCS únicamente cuando no hay catálogo local confiable. No requiere permisos de subida al dataset para aprobar localmente; la sincronización automática sí los necesita. El backend requiere acceso de escritura y durabilidad al dataset local y un sistema Linux/FS con soporte de `flock`; la protección de metadatos supone escritores cooperantes.

Las pruebas en [`test_audio_review_flow.py`](../../backend/tests/test_audio_review_flow.py) conectan los endpoints con `TestClient` sin lifespan, SQLite aislado, predictor/registro controlados y GCS falso que conserva bytes. Las de [aprobación local](../../backend/tests/test_feedback_local_approval.py) verifican disponibilidad mediante el ingestor real, catálogo local sin cloud, transacción conjunta, replay, corrupción, conflictos, symlinks e interrupciones de filesystem/BD, con WAV sintético y directorios temporales. Las pruebas de [almacenamiento](../../backend/tests/test_storage.py), [incorporación](../../backend/tests/test_feedback_storage.py) y [migración](../../backend/tests/test_prediction_dataset_migration.py) protegen la resolución de clase, los reintentos y el cambio de esquema. No acreditan acceso a GCS real, despliegue, interacción de navegador ni calidad acústica. La integración del registro con PostgreSQL y la prueba optativa de calidad real de Chucao requieren sus entornos y artefactos propios y quedan fuera de esta verificación; Chucao se omite sin `FAMA_QUALITY_MODEL_ID`, `FAMA_QUALITY_CHECKPOINT` y `FAMA_QUALITY_AUDIO`.

Las pruebas del sincronizador usan SQLite temporal, uploads falsos y sesiones propias; ejercitan identidad/integridad, resultados indeterminados de commit, reintentos, contención entre threads y procesos con **spawn**. Las pruebas de lifespan sustituyen modelos y seeding, verifican recuperación inicial, retries periódicos tras caída cloud/BD y espera real del upload en shutdown. Las HTTP verifican schema, límites y separación de la cola de curación sin iniciar servicios reales. No prueban PostgreSQL/GCS reales ni interrupción abrupta del sistema. Las pruebas frontend de AUDIO-4 ejercitan vista/panel renderizados con API simulada en jsdom: separación de colas, outcomes, refresco, fallos, respuestas tardías y cancelación. No equivalen a una verificación con navegador real o servicios desplegados.

Para la operación general, consultar el [manual de usuario](manual_usuario_plataforma.md) y la [guía de despliegue](guia_despliegue_operativo_docker.md). El cierre del flujo y sus verificaciones pendientes se siguen en el [tablero del proyecto](../KANBAN.md).
