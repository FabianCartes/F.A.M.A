# Admisión durable de trabajos de importación

**Estado: Corte2 (T2a–T2e) implementado y verificado dentro del alcance sintético local; revisiones nativas aprobadas y acuses consumidos.**
Los commits locales se registran en [el seguimiento, L37/L41](../arquitectura/large-zip-gcs.md).
El CLI y la prueba integral sintética de publicación se describen debajo;
no certifican operación PostgreSQL, GCS real ni despliegue.
`preview`, `confirm` y `sync` HTTP admiten trabajos durables; no ejecutan la
operación ni arrancan workers desde la petición. Una fila `queued` no acredita
validación, publicación ni sincronización. No se han iniciado servicios reales.

## T7: exportación y descarga nativa

**T7 cerrado localmente en alcance sintético; commit `9fcba8c`, revisión nativa aprobada y acuse consumido; no desplegado.** El estado y los resultados
vigentes están en [el seguimiento](../arquitectura/large-zip-gcs.md), no en los
resultados históricos de T6. No se autoriza ejecutar los comandos siguientes
sobre una base, datos o almacenamiento reales por aparecer en este manual.

### Preparación explícita

Con respaldo y escritores detenidos, después de las migraciones de importaciones,
cola y revisiones, desde `backend/`:

```bash
python -m scripts.migrate_dataset_exports --help
python -m scripts.migrate_dataset_exports --database-url '<URL autorizada>' --writers-stopped
```

Exigir exit0 y `{"version": 1, "verified": true}`. Crea/verifica solo
`dataset_export` y `dataset_export_session`; no modifica el catálogo, los WAV,
manifiestos ni el constraint de tipos de trabajos anteriores. No migra desde HTTP.
Preparar previamente una raíz física absoluta, privada, sin symlinks, compartida
por worker y servidor de descarga, y configurar:

| Variable del servidor | Contrato |
| --- | --- |
| `FAMA_EXPORT_ROOT` | Raíz privada existente, modo0700 y propiedad del usuario del proceso. No usar la raíz de importaciones ni cambiarla entre reinicios. |
| `FAMA_EXPORT_DOWNLOAD_ORIGIN` | Origen HTTPS absoluto, sin ruta/query/credenciales, por ejemplo `https://downloads.example.test`. Su ingress debe enviar `/api/ingestion/imports/exports/*/download` **directamente al backend**, sin pasar por Next. |

El origen es configuración del operador, no autodetección ni prueba del ingress.
El panel rechaza una URL del mismo origen de la página. Configurar un hostname
distinto que termine otra vez en Next **no** satisface este contrato. Mantener TLS,
sin buffering del ZIP y con plazos adecuados para transferencias largas; redactar
`ticket` de logs y trazas. No pasar Bearer a ese origen ni habilitar CORS como
sustituto de navegación nativa. No se cambia `frontend/next.config.ts` ni se
promete que sus300s permitan una descarga prolongada. La ruta desplegada necesita
autorización y comprobación separadas.

### Control HTTP y worker

Todas las rutas de control usan el prefijo `/api/ingestion/imports` y la
autenticación/propiedad existente. Una revisión parcial devuelve409; dueño ajeno,
404. Los identificadores son generados por el servidor.

| Operación | Resultado |
| --- | --- |
| `POST /datasets/{id}/revisions/{revision}/exports` con `{"request_key":"operacion-unica"}` | 202 con `id`, estado `queued` y `status_url`; repetición idéntica devuelve el mismo trabajo, otros parámetros con esa clave devuelven409. No genera el ZIP en HTTP. |
| `GET /exports/{id}` | Estado/progreso, revisión, tamaño/hash al completar y error acotado; nunca credenciales, staging o claves de ejecución. No renueva vigencia. |
| `GET /datasets/{id}/exports` | Hasta20 trabajos recientes del propietario/dataset para recuperación del panel. No es una lista completa del catálogo. |
| `POST /exports/{id}/sessions` | URL de bootstrap y `expires_at`, con `no-store`. Emite/renueva solo sobre una exportación terminada y vigente. Configuración ausente devuelve503; exportación no disponible410; ocho sesiones vigentes429. |

El worker se invoca explícitamente, una vez por intento, bajo supervisión externa:

```bash
python -m scripts.run_dataset_export_worker --help
python -m scripts.run_dataset_export_worker \
  --database-url '<URL autorizada>' --import-root '<raíz privada de importaciones>' \
  --export-root '<raíz privada de exportaciones>'
```

Devuelve `{"claimed": true|false}`: **no acredita éxito**, que se consulta por HTTP.
Lee exclusivamente el manifiesto autorizado, no listas locales ni orden del bucket.
Verifica generación, tamaño y SHA-256 de cada WAV, y reconstruye
`nombre-dataset/clase/subcarpetas/audio.wav` conservando bytes. Ante cualquier
miembro inválido, falla el trabajo sin ofrecer un ZIP parcial. Cada intento usa
su directorio, genera `export.part` y publica `export.zip` solo al completar
validaciones y fsync. Un reemplazo conserva la revisión del trabajo y reconstruye
en otro intento; no reanuda bytes de compresión ni adopta archivos parciales.

Límites iniciales: 15GiB y50.000 WAV únicos, manifiesto128MiB, registro16KiB,
un objeto transferido a la vez, ZIP_STORED con ZIP64. La cola de exportación
admite por defecto4 trabajos globales y1 por propietario, usando los valores de
`FAMA_IMPORT_CONCURRENT_IMPORTS`/`FAMA_IMPORT_JOBS_PER_OWNER` como presupuestos
**de esta cola**, separados de importaciones. No modifica la recepción simultánea
por propietario ni los64MiB/256MiB/2.000 de importación.

### Descarga, reanudación y limpieza

Abrir el enlace HTTPS mediante navegación nativa, no `fetch`/Blob. El ticket
establece una cookie HttpOnly/Secure/SameSite=Lax limitada a esa exportación y
redirige303 a una URL sin ticket. GET/HEAD posteriores se autorizan por sesión:
`Content-Disposition`, `Content-Length`, SHA-256 como ETag y `Accept-Ranges: bytes`.
Admite rangos cerrados, abiertos y sufijos, con `If-Range`; rangos no satisfacibles
o múltiples dentro de una sola petición devuelven416. Se admiten múltiples
peticiones de rango/reintentos con la misma sesión. No confundir ambos casos.

La sesión dura15min y el artefacto1h desde su publicación. Renovar requiere de
nuevo autorización de propietario y no revoca sesiones vigentes. La renovación
queda limitada a24h desde la admisión; una exportación ya vencida requiere un
trabajo nuevo. El enlace/cookie es secreto: no compartirlo. El fingerprint del
archivo rechaza sustituciones o modificaciones normales, no acredita ausencia
de corrupción física ni un host confiable comprometido.

```bash
python -m scripts.run_dataset_export_worker \
  --database-url '<URL autorizada>' --import-root '<raíz privada de importaciones>' \
  --export-root '<raíz privada de exportaciones>' --cleanup-only
```

La limpieza no contacta GCS ni ejecuta trabajos. Leer `completed`, `busy` y
`failed`, no solo exit0. No borra trabajos recuperables, artefactos vigentes,
callbacks activos ni rangos en curso, incluso si su sesión vence durante la
transferencia. Usa exclusión por directorio y estado durable `deleting`; repetir
ante fallos de borrado/fsync. No borra WAV/manifiestos publicados ni referencias
inmutables de T6. Los registros históricos de trabajo/sesión se conservan; no se
introduce aquí una purga de base de datos.

Pruebas focales, con el entorno aislado descrito en el manual de integración:

```bash
../.venv/bin/python tests/run_isolated_training_checks.py tests/test_dataset_exports.py tests/test_dataset_export_migration.py -q
```

Los casos sintéticos no acreditan15GiB reales, reinicio entre procesos, fallo
físico, PostgreSQL/GCS, Docker/Python3.12 ni descarga prolongada en un navegador
contra el ingress desplegado. Véase [ADR0038](../adr/0038-complete-zip-exports-native-sessions.md).

## T5: limpieza recuperable fuera de HTTP

T5 está verificado localmente en alcance sintético; no acredita despliegue. Cancelar devuelve el
estado cancelado y libera la promesa de escritura, pero conserva los temporales
hasta mantenimiento. Publicar programa limpieza incluso si todos los miembros
son duplicados; un fallo de borrado no cambia el éxito publicado.

Desde `backend/`, únicamente sobre almacenamiento y base autorizados, ejecutar
el worker de una sola invocación con las mismas raíces privadas estables:

```bash
python -m scripts.run_dataset_import_worker \
  --database-url '<URL autorizada>' \
  --import-root '<raíz privada de importaciones>' \
  --staging-root '<raíz privada de intentos>' --cleanup-only
```

El supervisor externo decide cuándo invocarlo; HTTP no lanza el limpiador.
`--cleanup-only` no ejecuta trabajos ni sincroniza con GCS. Devuelve contadores
`completed` y `failed`: un fallo de borrado conserva la reclamación durable y
requiere otra invocación. No interpretar exit0 como cero fallos: leer `failed`.
Sin el flag, el contrato anterior `{"claimed": true|false}` se conserva.

La reclamación `deleting` bloquea nuevas admisiones y modificaciones de recepción.
El candado por importación permanece durante el borrado, sin transacción de BD
prolongada. Si el proceso cae, el siguiente limpiador retoma el borrado idempotente
y los fsync pendientes. No borrar manualmente la reclamación ni cambiar la raíz
de intentos para aparentar espacio recuperado.
Un callback que todavía finaliza mantiene su candado de intento aun después de
un timeout; mantenimiento lo omite hasta que termine o su proceso salga. Una
limpieza anterior completada no excluye limpiar staging de trabajos posteriores
fallidos: cada invocación vuelve a contrastar los archivos realmente presentes.

La limpieza protege trabajos en cola, leases activos o vencidos pendientes de
recuperación, y journals `committing`. Primero recuperar la publicación por su
trabajo; un lease vencido no autoriza descartar datos. El polling no renueva la
actividad útil. Los bytes aún presentes siguen reduciendo el espacio físico
disponible aunque la reserva esté liberada. Véase [ADR0036](../adr/0036-recoverable-import-cleanup.md).

## HTTP202 y recuperación del panel

### T3a–T3b: reserva y transferencia fragmentada por HTTP

Las entregas T3a–T3b son aditivas: **no habilitan subidas de 10 GiB**.
T3c conecta el panel con reservas y fragmentos; requiere las migraciones
explícitas de ambas entregas antes del uso. El recorrido HTTP antiguo de archivo
completo conserva su comportamiento para clientes sin reserva, pero el panel ya
no lo usa ni vuelve a él ante errores. T3d añade las cuotas del dataset descritas debajo.
Se permite conservar varios
datasets por usuario; el límite de una recepción en curso es temporal.

Con escritores detenidos, respaldo previo y autorización sobre la base elegida,
aplicar después de las migraciones de metadatos y cola:

```bash
python -m scripts.migrate_dataset_import_receipts --help
python -m scripts.migrate_dataset_import_receipts --database-url '<URL autorizada>' --writers-stopped
```

La migración crea y verifica `dataset_import_receipt_schema` y
`dataset_import_receipt`, registra versión1 y no modifica importaciones existentes.
No se ejecuta automáticamente. Exigir exit0 y `{"version": 1, "verified": true}`;
conservar el estado ante un error, sin reparación automática ni URL en diagnósticos.

| Operación autenticada | Contrato aditivo actual |
| --- | --- |
| `POST /api/ingestion/imports/{import_id}/receipt` | Cuerpo `{"name":"birds.zip","size_bytes":1234}`. Reserva el ZIP declarado más el máximo expandido configurado. La importación debe estar vacía y en recepción. |
| Repetición del POST | Mismos parámetros devuelven la misma recepción; otros parámetros o una importación cancelada devuelven409. No reserva dos veces. |
| `GET .../{import_id}/receipt` | Estado acotado: nombre, tamaño, bytes prometidos/recibidos, tamaño de fragmento y estado. No renueva actividad, libera reservas ni modifica la compuerta. |
| `POST .../{import_id}/cancel` | Conserva la protección de trabajos activos; registra limpieza pendiente y libera la promesa de escritura. No borra staging desde HTTP ni acredita espacio físico recuperado. |
| `PUT .../{import_id}/archive` | Rechazado409 si ya existe una recepción reservada; no permite eludirla por el recorrido antiguo. |

La respuesta inicial mantiene `received_bytes=0`, `status=receiving` y
`chunk_bytes=16777216` por defecto. La transferencia requiere además la migración
explícita de T3b descrita debajo. Propietario incorrecto devuelve404; falta de migración503; tamaño
declarado excesivo413; otra recepción del propietario o presupuesto agotado429;
espacio físico insuficiente507. Los rechazos no persisten cargos parciales.

| Configuración | Valor inicial |
| --- | --- |
| `FAMA_IMPORT_RESERVED_BYTES_PER_OWNER` | `received_bytes + expanded_bytes`, una importación máxima configurada. |
| `FAMA_IMPORT_RESERVED_BYTES_GLOBAL` | El valor anterior predeterminado multiplicado por `concurrent_imports`; independiente de un override del presupuesto por propietario. |
| `FAMA_IMPORT_CHUNK_BYTES` | 16 MiB (`16777216`); entero entre1 y `2**31-1`, fijado al admitir cada recepción. No cambia recepciones existentes. |

Los overrides son enteros positivos de hasta `2**63-1`, en bytes; una
configuración inválida falla503. No son cuotas acumuladas del catálogo. Además,
la suma de promesas existentes, nueva promesa y `free_bytes` debe caber en el
espacio libre real. Es conservador: bytes ya escritos siguen descontados del
espacio libre; no se promete preasignación física ni protección frente a otros
programas que llenen el disco. La publicación libera la promesa en la misma
transacción que los miembros y el éxito del trabajo, sin afirmar que se borraron
temporales u objetos. La siguiente admisión conserva la reconciliación de
publicaciones anteriores como respaldo de compatibilidad.

Comprobación focal, con el mismo entorno aislado documentado debajo:

```bash
../.venv/bin/python tests/run_isolated_training_checks.py tests/test_dataset_import_receipts.py -q --tb=short
```

La prueba separada entre procesos, sin relajar la guarda del runner en memoria:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHON_DOTENV_DISABLED=1 DATABASE_URL=sqlite:// \
CUDA_VISIBLE_DEVICES='' OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
../.venv/bin/python tests/run_dataset_import_receipt_process_checks.py
```

Crea una raíz privada nueva bajo `/tmp/opencode`, bloquea red/credenciales e
instala la guarda original antes de importar la aplicación en cada hijo. Solo
autoriza un SQLite sintético privado. Seis contendientes de tres propietarios
compiten tras una barrera por80bytes: solo dos propietarios reservan40bytes cada
uno. Procesos frescos observan los cargos y el rechazo sin cambio de dump; un
borrado inducido fallido conserva el archivo aunque la promesa ya esté liberada;
otro proceso reintenta el mantenimiento. Una nueva recepción comprueba tanto
presupuesto como espacio físico disponible. También verifica
la salida exacta del CLI de migración, polling inerte, hashes de insumos protegidos
y limpieza privada. Plazos y lecturas parciales acotados; no usa sleeps arbitrarios.

Véase [ADR0032](../adr/0032-durable-receipt-reservations.md). El rollback de T3a
desactiva los dos endpoints nuevos y conserva sus tablas; no elimina el catálogo
ni revierte los trabajos de T2. PostgreSQL operacional, concurrencia entre hosts,
reanudación en el navegador y escala siguen sin certificarse.

### T3b: enviar, consultar y finalizar fragmentos

**Requisito:** detener API y workers, conservar respaldo y aplicar después de la
migración de reservas, desde `backend/` y solo sobre una base autorizada:

```bash
python -m scripts.migrate_dataset_import_chunks --help
python -m scripts.migrate_dataset_import_chunks --database-url '<URL autorizada>' --writers-stopped
```

Exigir exit0 y `{"version": 1, "verified": true}`. La migración aditiva verifica
columnas, constraints, referencias, continuidad del prefijo y actividad persistida
antes de reconocer `dataset_import_chunk_schema` versión1. No modifica la versión1
de reservas, ni convierte archivos del recorrido antiguo. Repetirla es inerte;
ante incompatibilidad, preservar base y archivos, sin borrar ni reparar registros.
`create_all()` por sí solo no activa el protocolo.

Todas las rutas siguientes tienen el prefijo
`/api/ingestion/imports/{import_id}/receipt`, requieren autenticación y verifican
propiedad. Usar únicamente el identificador generado por el servidor.

| Operación | Petición y resultado |
| --- | --- |
| `PUT .../chunks/{index}` | Índice desde0, cuerpo binario `application/octet-stream`, headers `X-Chunk-Offset` y `X-Chunk-SHA256` (64 hexadecimales minúsculas). Offset = índice × `chunk_bytes`. Devuelve200 con estado acotado después de persistir bytes y reconocimiento. |
| `GET .../chunks` | `chunks`, `total`, `next_cursor`; cada elemento contiene `index`, `offset_bytes`, `length_bytes`, `sha256`. Páginas predeterminadas de50, máximo200; usar `limit` y `cursor`. Nunca devuelve todos los hashes sin límite. |
| `POST .../finalize` | Sin cuerpo. Verifica tamaño y todos los hashes fuera de la compuerta de BD, sincroniza el archivo y directorios y devuelve200 con `status=sealed`. La importación pasa a `validating`; no significa que el ZIP haya sido validado o publicado. |
| `POST .../cancel` | Rechaza trabajo activo o publicación recuperable; registra cancelación y limpieza pendiente, libera la promesa y deja el borrado/fsync al mantenimiento explícito. Un fallo posterior se reintenta sin volver a cancelar. |

Enviar secuencialmente fragmentos de exactamente `chunk_bytes`, salvo el último,
que debe ocupar el resto exacto del tamaño declarado. Una repetición idéntica
verifica también los bytes almacenados y no incrementa contadores ni renueva
actividad. Misma posición con otros bytes, huecos, solapamientos, longitud corta
o hash incorrecto devuelven409; exceso de longitud o del tamaño declarado413.
Content-Type incorrecto devuelve415; headers/índice inválidos422. Una recepción
incompleta no finaliza. Un archivo sellado rechaza cualquier PUT y la repetición
de finalize vuelve a comprobar integridad sin modificar la base.

GET de estado y páginas es inerte. Un cursor corresponde a un prefijo aceptado
concreto: si se añaden fragmentos entre páginas, devuelve409; reiniciar por la
primera página. Para reanudar, el cliente debe releer y comparar **todos** los
fragmentos del prefijo reconocido; nombre, tamaño y muestras de extremos no
demuestran identidad. El panel T3c realiza esta comprobación completa antes de continuar.

#### Recuperación y exclusión

Hay un único `receiving.part`, no otra copia completa de ensamblaje. Primero se
escriben y sincronizan bytes y directorios; después se confirma el registro del
fragmento y `received_bytes`. Tras una caída, GET reconoce solo el prefijo de BD.
Reenviar desde esa posición trunca únicamente una cola no reconocida bajo el
candado de importación; nunca trunca el prefijo aceptado.

Finalize renombra a `archive.zip` antes del commit. Si el proceso cae en esa
ventana, conservar la base y el staging y repetir finalize: relee y verifica todos
los hashes y restablece fsync antes de sellar. La limpieza protege ese archivo
recuperable aunque haya vencido TTL. No renombrar manualmente ni fabricar hashes.
Una falta/corrupción del prefijo aceptado devuelve409: requiere investigación,
no reparación automática. Los estados públicos no revelan rutas físicas.

El orden es candado por importación → compuerta de BD. La compuerta y las
transacciones se liberan antes de streaming/hashing/fsync; importaciones distintas
pueden progresar. La limpieza omite importaciones ocupadas, trabajos activos y
journals de publicación; usa actividad útil de append/finalización, no polling,
para conservar progreso reciente. No se ejecuta desde HTTP. Véase
[ADR0033](../adr/0033-durable-import-chunks.md).

#### T3c: subir y reanudar desde el panel

1. Selecciona el ZIP y pulsa **Validar ZIP**. El panel admite la reserva y usa el
   `chunk_bytes` fijado por el servidor, no un tamaño inferido del archivo.
2. Los fragmentos se leen con `File.slice()` y se calculan sus SHA-256 con Web
   Crypto, uno a la vez. Se requiere un contexto seguro (HTTPS o localhost con
   Web Crypto disponible). No se carga el ZIP completo en un ArrayBuffer.
3. **Bytes reconocidos por el servidor** muestra solo `received_bytes` confirmado;
   una petición enviada o un error de conexión no incrementan el contador.
4. Tras recargar, abre **Recuperar importaciones anteriores**, elige la recepción
   y vuelve a seleccionar el ZIP original. Pulsa **Validar ZIP**. Se muestra
   **Verificando archivo para reanudar** mientras se recorren todas las páginas
   de hashes y todos los fragmentos aceptados, también los intermedios.
5. Solo al completar esa comparación se envía el sufijo faltante. Una página
   incompleta, un prefijo que cambió o un hash distinto detienen el recorrido
   antes de enviar bytes nuevos, finalizar o admitir una validación. Selecciona
   el archivo original o cancela explícitamente; no se sustituye el prefijo.
6. Un fallo de red se presenta como error, sin suponer que la escritura fue
   rechazada. Reintentar consulta la recepción mediante el POST idempotente y
   verifica de nuevo todo el prefijo reconocido. Esto cubre respuestas perdidas
   de fragmentos o finalización sin mantener un contador local autoritativo.

La finalización de la recepción precede a la admisión del trabajo de validación.
No equivale a audios válidos, publicación local ni sincronización con GCS.
Cerrar el modal solo lo oculta: la operación en curso continúa, como antes;
no cancela la importación ni envía otra operación. Elegir otra importación del
historial elimina la selección local del archivo y el progreso anterior.

Los límites recibidos/expandidos conservadores no cambian. El rewrite existente
de Next admite cuerpos de hasta110MiB, suficiente para el fragmento por defecto
de16MiB; no se incrementan buffers ni se certifica el proxy desplegado. Un
operador que configure fragmentos mayores debe verificar todo el recorrido.
Las pruebas renderizadas usan transporte simulado y archivos sintéticos; no
certifican un navegador real ni operación a10GiB. Rollback de T3c: retirar juntos
el helper de recepción y su integración/pruebas del panel; conservar las
migraciones y recepciones T3a–T3b. No volver al PUT antiguo para una reserva.

#### Comprobaciones sintéticas de T3b

Desde `backend/`, con el intérprete validado, sin servicios ni datos reales:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHON_DOTENV_DISABLED=1 DATABASE_URL=sqlite:// \
CUDA_VISIBLE_DEVICES='' PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
../.venv/bin/python tests/run_isolated_training_checks.py tests/test_dataset_import_chunks.py -q --tb=short

PYTHONDONTWRITEBYTECODE=1 PYTHON_DOTENV_DISABLED=1 DATABASE_URL=sqlite:// \
CUDA_VISIBLE_DEVICES='' PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
../.venv/bin/python tests/run_dataset_import_chunk_process_checks.py
```

La prueba separada instala la guarda original antes de importar la aplicación,
permite un solo SQLite privado, usa entorno allowlist, bloquea red y credenciales
conocidas y crea temporales exclusivos. Barreras y deadlines, sin sleeps, permiten
matar hijos antes de fsync, después del append durable antes de commit y después
de rename antes de commit. Intérpretes frescos comprueban estado, replay y
recuperación. Otro propietario usa la compuerta durante I/O pausado; cancelación
y limpieza no compiten con el candado. Verifica hashes de los30 insumos protegidos
y retira sus temporales. No es sandbox OS ni prueba fallos físicos de disco.

Rollback: desactivar las rutas de transferencia y conservar tablas, reservas y
staging para recuperación; no volver al PUT antiguo sobre una recepción reservada.
Límites actuales de64MiB recibidos/256MiB expandidos sin cambios. No se acredita
operación de10GiB, PostgreSQL real, Docker/Python3.12, frontend, GCS ni escala.

### T3d: capacidad acumulada del dataset

Cada dataset admite por defecto **15 GiB de WAV únicos y50.000 miembros únicos**.
Un GiB equivale a1024³ bytes. No es una cuota de almacenamiento acumulado por
usuario: se pueden conservar varios datasets. Los límites independientes de
ZIP recibido64MiB, expansión256MiB y2.000 entradas del archivo no cambian; T4
seguirá pendiente. No se habilitan subidas de10GiB por configurar estas cuotas.

| Configuración | Valor inicial | Contabilidad |
| --- | --- | --- |
| `FAMA_IMPORT_DATASET_BYTES` | `16106127360` | Bytes de WAV únicos publicados más los nuevos únicos. |
| `FAMA_IMPORT_DATASET_ENTRIES` | `50000` | Miembros publicados más los nuevos únicos. |

Se aplican mediante `ImportLimits`, igual que los otros límites; usar enteros
positivos y configuración coherente en API y workers. El límite exacto se admite;
un byte o un miembro adicional se rechaza. No se cuentan dos veces los duplicados
internos ni el contenido ya presente. Una etiqueta distinta para el mismo contenido
sigue siendo un conflicto, no una manera de eludir la deduplicación.

La vista previa acotada incluye `preview.quota`: `current_bytes/current_files`,
`new_bytes/new_files`, `projected_bytes/projected_files` y `limit_bytes/limit_files`.
El panel muestra actuales+nuevos=proyectados junto al límite efectivo revisado.
Las incidencias `dataset_size_limit` y `dataset_entry_limit` impiden confirmar:
reduce el contenido nuevo o revisa la configuración autorizada y vuelve a validar.
Una vista previa antigua sin estos campos sigue siendo legible, pero no elude
la comprobación del worker.

Confirmar vuelve a comprobar revisión y cuota bajo la compuerta de publicación,
antes del journal y antes de publicar, también durante recuperación. Si otro
trabajo cambió el destino, genera y revisa otra vista previa. Si se redujo la cuota,
el trabajo puede fallar aunque la vista previa anterior estuviera lista; consulta
su estado y conserva el staging/journal. El replay de una importación ya publicada
no agrega contenido ni falla por una reducción posterior de cuota.

Los rechazos conservan miembros, revisión, objetos publicados y reserva temporal.
Las reservas de vistas previas con errores y trabajos fallidos siguen cobradas
hasta cancelación segura o publicación satisfactoria. Una caída después del rename
conserva el journal y la reserva hasta recuperación; no borres manualmente esos
objetos. Un resumen inconsistente requiere investigación y recuperación explícita,
no reparación automática. Véase [ADR0034](../adr/0034-dataset-import-quotas.md).

Comprobación focal desde `backend/`, con el entorno aislado documentado:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHON_DOTENV_DISABLED=1 DATABASE_URL=sqlite:// \
CUDA_VISIBLE_DEVICES='' PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
../.venv/bin/python tests/run_isolated_training_checks.py tests/test_dataset_import_quotas.py -q --tb=short
```

La prueba usa WAV sintéticos, SQLite en memoria y barreras controladas. Incluye
recepción fragmentada hasta descarga del WAV original y rollback de publicación;
no certifica PostgreSQL, múltiples hosts, escala,10GiB ni contención del decoder.
No requiere migración nueva de T3d. Rollback: retirar coordinadamente las adiciones
de cuota del worker, límites y panel, conservando los datos normalizados y el
protocolo T3a–T3c; no borrar tablas ni staging recuperable.

### Operaciones de ejecución de T2

Cada POST de operación requiere una `request_key` de 1–100 caracteres ASCII
alfanuméricos o `_.:-`. `preview` añade `root`; `confirm`, el `preview_token`
revisado; `sync` no añade parámetros. Conservar la misma clave y parámetros ante
una respuesta de admisión perdida; no generar una clave nueva automáticamente.
El `202` incluye `id`, `import_id`, `kind`, `status`, `stage`, `progress`,
`result`, `error` y `status_url`; `Location` señala esa misma consulta.

- `GET /api/ingestion/imports/{import_id}/jobs/{execution_id}` consulta sin renovar
  actividad ni lease. No expone token de fencing, parámetros privados ni rutas.
- `POST .../jobs/{execution_id}/cancel` solo cancela `queued`.
- `POST .../jobs/{execution_id}/retry`, con una clave nueva, admite un reintento
  de un trabajo fallido o cancelado; mantiene las validaciones del estado actual.
- El GET de importación y el historial incluyen `execution`, la referencia durable
  más reciente. Tras recargar, seleccionar la importación del historial recupera
  su seguimiento; no depende del estado en memoria del navegador.

El panel distingue admisión, ejecución y finalización, consulta cada segundo
mientras hay trabajo y reintenta solo lecturas ante errores de consulta. No inicia
confirmación ni GCS por polling. Un fallo asíncrono aparece en el estado del
trabajo, no como un error retrospectivo de la petición `202`.

## Migración explícita

Este procedimiento describe una operación de mantenimiento; incorporarlo al
repositorio no autoriza ejecutarlo sobre una base real.

1. Detener escritores de API y workers y conservar el respaldo de la base.
2. Comprobar que el Corte 1 ya está migrado y que se conserva su evidencia. Esta
   migración no reemplaza ni repite el backfill de metadatos.
3. Desde `backend/`, ejecutar con el intérprete validado y un destino explícito:

   ```bash
   python -m scripts.migrate_dataset_import_jobs --database-url '<URL autorizada>' --writers-stopped
   ```

4. Exigir salida `{"version": 1, "verified": true}` y exit 0. El comando crea
   `dataset_import_job_gate` y `dataset_import_job`, comprueba columnas,
   nulabilidad, claves primarias/foráneas, checks e índices, e inicializa la compuerta de versión 1.
   No modifica las importaciones ni sus metadatos; no arranca procesos de trabajo.
5. Ante un esquema incompatible, conservarlo para diagnóstico. No borrar tablas,
   fabricar una versión ni ejecutar reparación automática para superar el fallo.

La ejecución es transaccional en SQLite y PostgreSQL. La verificación operacional
en PostgreSQL sigue pendiente; compilar DDL o probar SQLite no la sustituye. El
CLI no infiere credenciales ambientales y no imprime URL ni excepciones privadas.
La ruta de rollback de esta entrega consiste en dejar de usar el módulo aditivo,
conservando las tablas para investigación; no exige borrar importaciones.

## Identidad y capacidad

| Concepto | Contrato actual |
| --- | --- |
| Importación | Identidad y metadatos del archivo recibido, no un intento de ejecución. |
| Trabajo | Operación persistida `preview`, `confirm` o `sync`, con parámetros exactos. |
| Idempotencia | Propietario + importación + tipo + clave de operación; mismos parámetros devuelven la misma identidad, también si terminó. Otros parámetros con la misma clave se rechazan. |
| Reserva de ejecución | Fila `queued` o `running`; la transición terminal libera capacidad en la misma transacción. No es una reserva de bytes ni de disco. |
| Exclusión de admisión | Un `UPDATE` a la compuerta obtiene exclusión de escritura en la base antes de contar e insertar. No se realiza I/O prolongada durante esa transacción. |
| Exclusión por importación | Índice único parcial impide dos trabajos activos de la misma importación. No excluye importaciones independientes durante ejecución. |
| Límite global | `FAMA_IMPORT_CONCURRENT_IMPORTS`, valor predeterminado existente 4, sin ampliación. |
| Límite por propietario | `FAMA_IMPORT_JOBS_PER_OWNER`, predeterminado conservador 1. Ambos límites deben ser enteros positivos acotados. |
| Cancelación | Solo trabajos pendientes; repetición idempotente. La cancelación de la importación y la sustitución del ZIP se rechazan mientras existe trabajo activo, aunque el lease haya vencido. |

Las consultas no actualizan actividad, heartbeat, lease ni la compuerta. Un aviso
en memoria no es necesario para que el trabajo permanezca en la base.

## Comprobaciones sintéticas reproducibles

### Contrato del núcleo T2b

`ImportJobQueue.claim(lease_seconds=...)` consulta la cola persistida sin depender
de avisos en memoria. Reclama un trabajo pendiente o una ejecución vencida,
incrementa intento/token y confirma antes de ejecutar. La compuerta solo protege
transacciones cortas; la reserva sigue siendo la misma fila activa al recuperar.
`heartbeat`, `progress` y `finish` requieren identidad, intento, token, estado
`running` y lease estrictamente vigente. La igualdad con el vencimiento ya impide
escribir. Rechazos por lease revierten también la compuerta. Éxito o fallo liberan
capacidad mediante el estado terminal persistido, sin contador auxiliar que reparar.

El reloj predeterminado se consulta en la base después de obtener la compuerta:
SQLite usa `julianday('now')`; PostgreSQL, `clock_timestamp()`. El reloj inyectado
solo sirve para pruebas coordinadas. No se comparan relojes de hosts de workers.
Esto no promete monotonía frente a ajustes del reloj de la base, ni operación
multihost de un archivo SQLite, ni validación operacional PostgreSQL. Los leases
deben ser finitos, positivos y como máximo 3600 segundos; elegir margen suficiente
para la resolución del reloj, latencia y contención reales.

`ImportJobWorker(queue, staging_root, execute).run_once()` ejecuta como máximo un
intento; devuelve `False` si no hay trabajo o su callback previo sigue terminando.
El callback confiable recibe `(attempt, staging, report)`, sin sesión ni transacción
abierta. Un hilo independiente renueva el lease con sesiones propias. Los valores
predeterminados son lease de 60 segundos, heartbeat cada 20 y plazo de ejecución
de 300. Se pueden inyectar duraciones y espera de heartbeat para pruebas.
Ante pérdida de lease no persiste un terminal obsoleto. Los errores persistidos son
solo `execution_failed`, `execution_timeout` o `staging_failed`, nunca excepciones.
El resultado admite únicamente `dataset_id` hexadecimal de 32 caracteres y contadores
enteros acotados `added_count`/`synced_count`; progreso entre 0 y 99, terminal exitoso 100.

El plazo acota la espera del coordinador, **no mata un hilo Python**. Un callback
debe cooperar y limitar sus propias operaciones; si se bloquea tras vencer el plazo,
ese worker no inicia más callbacks hasta que termine. No sirve para decodificadores
hostiles, no amplía su aislamiento ni permite efectos externos arbitrarios. El
callback genérico solo prepara su directorio y reporta. El ejecutor de dominio
descrito debajo publica exclusivamente a través de transacciones fenced.

La raíz debe existir, ser física, absoluta, privada (sin permisos de grupo/otros)
y pertenecer al usuario del proceso. Cada intento crea exclusivamente
`<job>-<attempt>-<token>` con modo 0700, sin adoptar rutas existentes ni usar un
directorio `files` compartido. No se borra staging. La separación de rutas no aísla
código malicioso bajo el mismo usuario, ni prueba fencing de publicación final.
Los antiguos métodos síncronos preview/confirm/sync fueron sustituidos por
`ImportExecution(queue, service, staging_root, storage=...).run_once()`. Su raíz
de intentos debe mantenerse estable entre reinicios. Preparación, hashing,
decodificación, fsync del contenido y acceso al adaptador de almacenamiento ocurren
fuera de las transacciones de publicación. La compuerta de la cola serializa las
transiciones cortas contra reclaim; el resultado exitoso se confirma junto con la
membresía o revisión de preview. Un hilo obsoleto no puede confirmar metadatos.

El journal `committing` se confirma antes de rename. La recuperación verifica los
hashes en el destino si el rename ya ocurrió, reestablece fsync de directorios y
completa membresía sin duplicarla. Los conflictos de revisión/titularidad se
revalidan antes de publicar. Véase [ADR0031](../adr/0031-fenced-import-publication.md).

`DatasetImports.cleanup(db)` es mantenimiento explícito; nunca se invoca al crear,
recibir o confirmar desde HTTP. Excluye filas con trabajos `queued`/`running`
(también leases vencidos) y todo journal `committing`; marca expiración antes de
borrar staging cancelado. No elimina objetos publicados ni directorios privados
de intentos. La recolección completa y asíncrona de estos últimos sigue en Corte5.
La limpieza toma primero el mismo candado por importación que la recepción y
omite una recepción ocupada sin marcarla como vencida. Después toma la compuerta
de cola para revalidar elegibilidad; libera la compuerta antes del borrado pero
mantiene el candado de recepción hasta terminar. No se toma el orden inverso.

Sin un proceso explícito que invoque el ejecutor, los trabajos permanecen
durablemente pendientes. No se han ampliado límites ni el aislamiento del decoder.

## CLI de un trabajo por invocación

Desde `backend/`, con el intérprete y el entorno operativos seleccionados por
el administrador, la interfaz es:

```bash
python -m scripts.run_dataset_import_worker --help
python -m scripts.run_dataset_import_worker \
  --database-url '<explicit-migrated-database-url>' \
  --import-root '<existing-private-absolute-import-root>' \
  --staging-root '<existing-private-absolute-attempt-root>'
```

Estos son ejemplos de interfaz, no autorización para ejecutarlos contra datos
reales. Usar una base ya migrada y los mismos directorios físicos estables en
cada reinicio. Ambas raíces deben existir, pertenecer al usuario del proceso,
tener permisos privados (0700) y compartir filesystem para permitir rename.
La raíz de importaciones debe coincidir con la usada por la API. El comando no
crea tablas, migra, carga la API ni arranca un supervisor. No infiere la URL de
`DATABASE_URL` ni carga archivos dotenv; los límites existentes de importación
y cola siguen leyendo sus variables documentadas.

Cada invocación reclama como máximo un trabajo admisible, incluido un intento
con lease vencido. Devuelve exit0 y `{"claimed": true}` si reclamó trabajo, o
`{"claimed": false}` si no había ninguno. **No es una respuesta de éxito del
dominio:** un intento reclamado puede fallar, vencer o perder su lease; comprobar
su estado por HTTP. Los fallos de configuración/cola devuelven exit1 con mensaje
sanitizado; argparse devuelve exit2 por argumentos inválidos. La supervisión
externa decide la siguiente invocación y su backoff; no lanzar un bucle sin espera
sobre `claimed=false` o exit1.

La sincronización solo ocurre al reclamar un `sync` previamente admitido. El
adaptador GCS crea el cliente perezosamente y usa `GCS_BUCKET_NAME` y las
credenciales operativas existentes; no se validaron aquí. No ejecutar un worker
contra una cola con trabajos remotos sin autorizar ese acceso. El plazo del
callback no mata hilos Python: una terminación del proceso puede dejar un lease
y un journal recuperables, no un resultado exitoso. Conservar staging, objetos y
la base; reiniciar con las mismas raíces y consultar la recuperación. Este CLI
no incorpora aislamiento de decoder ni limpieza automática de intentos.

Desde `backend/`, con el entorno documentado en
[integración de entrenamiento](integracion-flujo-entrenamiento.md#reproducir-comprobaciones-aisladas):

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHON_DOTENV_DISABLED=1 DATABASE_URL=sqlite:// \
CUDA_VISIBLE_DEVICES='' PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
../.venv/bin/python tests/run_isolated_training_checks.py tests/test_dataset_import_execution.py tests/test_dataset_import_async_api.py tests/test_dataset_import_worker.py tests/test_dataset_import_jobs.py tests/test_dataset_import_api.py tests/test_dataset_import_sync.py tests/test_dataset_import_verifier_regressions.py tests/test_dataset_import_pages.py tests/test_dataset_import_paging_regressions.py -q --tb=short
```

Ese runner conserva su guarda original y solo admite SQLite en memoria. La
comprobación separada de persistencia y admisión simultánea usa procesos frescos:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHON_DOTENV_DISABLED=1 DATABASE_URL=sqlite:// \
CUDA_VISIBLE_DEVICES='' PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
../.venv/bin/python tests/run_import_job_process_checks.py
```

El coordinador crea almacenamiento exclusivo bajo `/tmp/opencode`, pasa a los
hijos un entorno acotado sin credenciales ambientales y libera barreras por pipes.
Cada hijo instala la guarda original antes de importar la aplicación, bloquea red
y lectura de credenciales, y permite exclusivamente su SQLite privado. Se prueban
nueve admisiones simultáneas, límites global/propietario, tres repeticiones
simultáneas, visibilidad después de salir los procesos y liberación persistente.
También se prueban doble claim simultáneo, recuperación de claim tras salida del
proceso, ejecución bloqueada reemplazada al vencer, rechazo de tres escrituras
obsoletas al despertar, directorios distintos y recuperación después de matar un
hijo sintético bloqueado. Readiness (incluidas líneas parciales), finalización y
limpieza de hijos tienen plazos acotados; el coordinador siempre espera sus salidas.
Se comprueban limpieza y hashes de los insumos protegidos. No es un sandbox OS.

**El procedimiento entre procesos anterior demuestra fencing de cola.** La
publicación integrada usa un procedimiento separado, también desde `backend/`:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHON_DOTENV_DISABLED=1 DATABASE_URL=sqlite:// \
CUDA_VISIBLE_DEVICES='' ../.venv/bin/python tests/run_dataset_import_publication_process_checks.py
```

El coordinador crea una raíz0700 nueva en `/tmp/opencode`, usa un entorno
allowlist e instala la guarda original antes de importar la aplicación en cada
hijo. Solo permite su SQLite sintético privado; bloquea red y acceso a archivos
de credenciales conocidos. No relaja el runner en memoria. Un hijo recibe WAV/ZIP
sintéticos por HTTP y admite preview; otro ejecuta el CLI real. Después admite
confirmación y bloquea en una barrera exclusiva del test tras rename, antes del
commit; el coordinador mata ese proceso y espera su salida. Una consulta fresca
comprueba journal `committing`, trabajo `running`, objetos movidos pero catálogo
aún vacío. Otro intérprete recupera el mismo trabajo con reloj controlado en el
vencimiento del lease. HTTP verifica una sola membresía/revisión, descarga y hash;
otro replay no duplica contenido. También comprueba la salida de cola vacía.

Readiness, líneas parciales y procesos tienen plazos; no hay sleeps de carrera.
La raíz compartida permanece estable entre hijos y se retira al finalizar;
los hashes del runner, guarda e inventario protegido deben permanecer idénticos.
No hay hook de caída en producción. Esta guarda de aplicación no es un sandbox
OS ni prueba bloqueo de toda lectura de credenciales, I/O nativo, fallo físico de
disco o PostgreSQL. No confundir la evidencia sintética con GPU, GCS real,
despliegue o validación de escalabilidad. Estado y resultados del corte en
[el seguimiento](../arquitectura/large-zip-gcs.md).

## T4: validación ZIP64 contenida

El worker ejecuta el prechequeo ZIP/ZIP64, extracción y decoder WAV en un proceso
contenido. Conserva los límites **64 MiB recibidos / 256 MiB expandidos / 2.000
entradas** y los bytes originales. No habilita ZIP de10GiB ni implementa T5.
Los journals, fsync, cuotas, reservas y fencing permanecen fuera del decoder.

### Prerrequisitos y rechazo seguro

Se requieren Linux con namespaces de usuario, montaje, PID y red utilizables,
`/usr/bin/bwrap`, `/usr/bin/prlimit`, `libseccomp.so.2`, Python bajo `/usr` y los
módulos instalados de SoundFile/CFFI/NumPy. No se instalan automáticamente ni se
relaja el aislamiento si faltan. Un contenedor o host debe comprobarse por separado;
la imagen Docker actual no se ha reconstruido ni certificado con estos requisitos.

| Control | Política del proceso |
| --- | --- |
| Memoria | Espacio de direcciones duro:768MiB, no una medición RSS |
| CPU | Mitad de `validation_seconds`, redondeada hacia arriba, mínimo1s |
| Plazo | Incluye espera de cupo, arranque y procesamiento; SIGKILL y reap al vencer |
| Acceso | ZIP/runtime de solo lectura; solo staging del intento ligado al host con escritura |
| Red/credenciales | Namespace de red propio, seccomp sin sockets; entorno allowlist, sin home/proyecto/SDK cloud |
| Procesos | Sin fork/clone/exec ni nuevos namespaces después del arranque; capacidades retiradas |
| Salida | Lectura acotada por entradas/rutas, máximo16MiB; metadatos y archivos verificados por el padre |
| Concurrencia | Máximo4 hijos por proceso, además de la admisión durable existente |

`sandbox_unavailable` indica que no pudo lanzarse el mecanismo. `sandbox_invalid_result`
rechaza una salida ausente, excesiva, inconsistente o un hijo fallido, incluidos
errores de preparación del runtime o límites de recursos. `validation_timeout`
indica agotamiento del plazo. No interpretar estas categorías como diagnóstico
preciso de un codec ni como confirmación de publicación. La vista previa queda en
corrección; no se publica contenido por un rechazo.

El prechequeo admite centinelas independientes en EOCD y ZIP64 de un volumen con
registro final fijo. Rechaza offsets/tamaños/conteos incoherentes, directorios
ocultos tras contadores falsos, multidisco y registros extendidos no soportados.
La prueba con offset superior a4GiB usa un archivo disperso privado y un límite
sintético explícito; no modifica los valores operativos.

### Comprobación sintética separada

Desde `backend/`, usando el intérprete validado:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHON_DOTENV_DISABLED=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
FAMA_SYNTHETIC_SECRET=synthetic GOOGLE_APPLICATION_CREDENTIALS=/nonexistent/synthetic \
../.venv/bin/python tests/run_dataset_zip_sandbox_checks.py
```

El procedimiento usa exclusivamente temporales0700 bajo `/tmp/opencode`, WAV/ZIP
sintéticos y SQLite en memoria para HTTP. Comprueba WAV/ZIP64 aceptados, restricciones
de acceso y recursos, decoder nativo dormido sin cooperación, CPU ocupada, memoria,
salida excesiva/FIFO y proceso esperado/reaped; luego preview, confirmación, descarga
y replay por el worker real. Los entrypoints defectuosos se inyectan solo en scratch;
no hay flags de evasión en producción ni se modifica la guarda original.

Los tests de dominio/HTTP bajo `run_isolated_training_checks.py` y la prueba histórica
de publicación/reinicio usan explícitamente el validador sintético directo porque
su guarda original prohíbe subprocesos. No prueban contención ni se relaja esa guarda.
La prueba T4 anterior es complementaria; no certifica PostgreSQL, GCS, Docker3.12,
fallo físico de disco, resistencia a exploits del kernel o escalabilidad. Requiere
su propia ejecución observada, no reutilizar evidencia del corte anterior.

Rollback: retirar conjuntamente el sandbox y su conexión al worker; preservar datos,
journals e intentos recuperables. No usar rollback para aceptar entradas hostiles sin
contención. [ADR0035](../adr/0035-contained-zip-validation.md) registra la decisión.

## T6: sincronización de revisiones y manifiestos inmutables

El `sync` explícito sincroniza una fotografía durable del **dataset completo**,
no solo los hashes de la importación iniciadora. El estado de implementación y
verificación vigente está en [el seguimiento](../arquitectura/large-zip-gcs.md).
No ejecutar estas instrucciones contra recursos reales sin autorización separada.

### Preparación y ejecución

1. Detener API y workers antes de la migración aditiva, conservando el respaldo y
   los metadatos anteriores. Las migraciones previas siguen siendo prerrequisitos.
2. Desde `backend/`, con el intérprete del entorno operativo, ejecutar explícitamente:

   ```bash
   PYTHONPATH=. python -m scripts.migrate_dataset_import_revisions \
     --database-url '<explicit-database-url>' --writers-stopped
   ```

   Esperar `{"version": 1, "verified": true}` y exit0. Argumentos incompletos
   producen exit2; un fallo produce exit1 sanitizado. El comando no inicia workers,
   no transfiere archivos ni declara sincronizado contenido histórico. Un esquema
   incompatible se rechaza; preservar el estado y revisar mantenimiento.
3. Reanudar consumidores coordinados. Admitir `POST /{import_id}/sync` con una
   `request_key` nueva y consultar la URL de estado devuelta por HTTP202. El CLI
   de un trabajo mantiene sus argumentos y su semántica `claimed`, no éxito final.

| Control | Valor predeterminado y alcance |
| --- | --- |
| `FAMA_IMPORT_SYNC_BATCH_FILES` | 32 objetos; entero entre1 y200 |
| `FAMA_IMPORT_SYNC_BATCH_BYTES` | 268435456 bytes (256MiB); entero entre1 y15GiB |
| Concurrencia de transferencia | Un objeto por worker, sin futuros abandonados |
| Reintentos transitorios | Máximo3, esperas0,05 y0,1s; no reintentar conflictos de integridad |

Un WAV individual mayor que el presupuesto de lote rechaza la sincronización sin
publicar un manifiesto completo; no se excede el límite para acomodarlo. Estos
controles no amplían los límites de recepción64MiB, expansión256MiB,2000entradas,
15GiB/50000archivos únicos por dataset ni la recepción simultánea por propietario.

### Estado, reintento y recuperación

- La primera ejecución fija la revisión del trabajo. Un reemplazo por lease
  vencido recupera esa fotografía; un trabajo nuevo puede fijar la revisión actual.
- Cada lote guarda resultados normalizados, generaciones e integridad y sus
  contadores agregados. Los bytes se transfieren y verifican fuera de sesiones BD.
  Un objeto creado antes de su checkpoint se verifica de nuevo, nunca se sobrescribe.
- El resultado exitoso incluye `dataset_id`, `dataset_revision` y `synced_count`
  de esa revisión completa. Si el dataset avanzó durante la transferencia, su
  importación iniciadora permanece `pending`, no completa la revisión nueva.
- El manifiesto solo se publica después de verificar todos los miembros. La
  identidad completa queda ligada a clave, generación, SHA-256 y tamaño; una
  revisión parcial no expone referencia de manifiesto. Las revisiones publicadas
  y sus objetos se conservan; la limpieza T5 sigue limitada a staging.
- Ante fallo, conservar tablas, WAVs, journals e intentos. Reintentar explícitamente;
  no borrar objetos ni corregir contadores manualmente para forzar éxito. Un
  cambio de generación o integridad requiere recuperación autorizada, no overwrite.

### Consulta y recuperación autorizadas

Los endpoints siguientes son relativos a `/api/ingestion/imports` y requieren al
propietario autenticado del dataset:

- `GET /datasets/{dataset_id}/revisions/{revision}`: estado `pending`/`complete`,
  totales, contadores verificados y referencia de manifiesto solo si está completo.
- `GET /datasets/{dataset_id}/revisions/{revision}/manifest`: recupera el JSON a un
  temporal privado usando exclusivamente esa referencia autorizada. Verifica toda
  su integridad antes de emitir bytes y transmite la respuesta por bloques, con
  `Content-Length` y `ETag` SHA-256. Una revisión parcial o identidad no recuperable
  devuelve409; otro propietario o revisión inexistente devuelve404.

El JSON estándar contiene versión1, dataset/revisión, nombre/descripción,
cantidades/tamaño total y miembros con clase, rutas canónica/original, importación
de procedencia, tamaño/SHA-256 y clave/generación de WAV. Se genera por páginas;
su recuperación y comprobación operan por bloques. No contiene ZIP, rutas locales
absolutas, credenciales ni URLs firmadas. Su referencia autorizada acredita quién
lo publicó; un hash aportado por el cliente no concede acceso ni acredita origen.
Permite reconstruir el dataset lógico sin ZIP ni listas locales de miembros;
no promete reproducir el contenedor ZIP original. La exportación ZIP y descarga
reanudable de T7 **no están implementadas por estos endpoints**.

### Comprobaciones sintéticas

Desde `backend/`, con el mismo runner y guarda originales:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHON_DOTENV_DISABLED=1 DATABASE_URL=sqlite:// \
CUDA_VISIBLE_DEVICES='' PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
../.venv/bin/python tests/run_isolated_training_checks.py \
  tests/test_dataset_import_revision_migration.py tests/test_dataset_import_manifests.py \
  tests/test_dataset_import_sync.py tests/test_dataset_import_execution.py -q --tb=short
```

Estas pruebas usan SQLite en memoria, WAVs sintéticos, almacenamiento simulado y
temporales privados; no certifican reinicio físico, PostgreSQL/GCS reales, escala
ni despliegue. Prerrequisitos, resultados observados y límites se registran por
ejecución en el seguimiento. [ADR0037](../adr/0037-immutable-dataset-revision-manifests.md).
