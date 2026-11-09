# Transferencias de datasets

En **Gestión de audios**, la sección **Catálogo** reúne dos tablas de estilo uniforme, con los títulos **Catálogo datasets privados** y **Catálogo datasets públicos**. «Públicos» identifica colecciones compartidas en la aplicación, no acceso público en Internet. La columna **Ámbito** distingue **Privado** y **Compartido**. Un mismo nombre no convierte sus datasets en la misma colección: conservan identidades, selecciones y acciones separadas.

**Disponibilidad** separa la copia local del conocimiento remoto: en privados GCS no está verificado; en compartidos se distingue un listado GCS consultado de un conteo desconocido. La paginación y los errores del catálogo privado siguen siendo independientes. No existe aquí una acción para convertir un dataset privado en público: importar o subir a GCS no lo publica ni cambia permisos.

## Catálogo datasets privados

La columna **Fecha de importación** muestra la primera fecha registrada de una solicitud de importación completada que incorporó audios al dataset privado. Se conserva aunque después se agreguen audios o cambie el dataset; no intenta calcular su última modificación. Sin historial válido muestra **No disponible**. Es la fecha de inicio de esa solicitud, no una hora exacta de finalización. La API del catálogo entrega `imported_at` en segundos Unix, derivado de los registros existentes y limitado al propietario y los datasets de la página; no requiere migración. La columna **Última Modificación** del catálogo compartido no cambia.

1. Pulsa **Importar ZIP** para abrir las instrucciones y el flujo de importación existente. El ZIP debe tener una carpeta por clase en su raíz, con audios WAV válidos. La importación automática valida antes de conservar el contenido local; las solicitudes históricas manuales mantienen su confirmación local.
2. Importar no sube automáticamente a GCS ni inicia preparación o entrenamiento. El modal resume las instrucciones en puntos y muestra solo tres límites de peso: ZIP, contenido descomprimido y cada WAV. Usa unidades decimales (1 MB = 1 000 000 bytes; 1 GB = 1000 MB): hasta 1000 MB se expresa en MB y por encima en GB, con un máximo de dos decimales truncados para no anunciar un límite mayor que el real. Los límites técnicos restantes siguen aplicándose en el servidor aunque no se enumeren en esa introducción.
3. Marca las filas de ámbito **Privado** en **Catálogo** o usa **Seleccionar todos los datasets privados** para seleccionar los de la página actual. La selección comienza vacía y se limpia al actualizar el catálogo, cambiar de página o cambiar de sesión.
4. Revisa los nombres junto a **Local → GCS**, pulsa **Subir selección a GCS** y revisa los datasets y el tamaño estimado en el diálogo de la aplicación **Confirmar subida privada a GCS**. **Confirmar subida** solicita la operación; **Cancelar** o Escape cierra el diálogo sin consultar el historial ni solicitar ninguna subida. Si cambia el catálogo o la sesión, la confirmación se descarta. La interfaz busca una importación confirmada por dataset en el historial paginado; si no encuentra todas, no inicia la selección. Cada operación sincroniza la revisión completa del dataset, no solo los archivos de esa importación.
5. Un trabajo admitido queda pendiente o en ejecución; no significa que la copia remota esté completa. La pantalla consulta el progreso y distingue finalización, fallo y cancelación. Si falla parte de la admisión, los trabajos ya admitidos continúan: no se revierte el lote ni se anuncia éxito global.
6. Para recuperar trabajos tras abandonar la pantalla o gestionar una subida fallida, abre **Recuperar importaciones anteriores** dentro de **Importar ZIP**. El modal no ofrece **Subir este dataset a GCS** ni **Consultar archivos locales**; esas acciones se realizan desde la tabla del catálogo.

La copia local se conserva si falla GCS. Subirla no publica el dataset en el catálogo compartido. La columna **Acuses de subida** contiene confirmaciones históricas, no una comprobación actual del bucket. La disponibilidad privada muestra **Subida a GCS registrada (n/total)** cuando hay acuses para miembros del dataset; una proporción parcial no indica una subida completa. Con cero acuses muestra **Sin subida a GCS registrada**, que no significa ausencia verificada en GCS. Incluso con todos los acuses, no se garantiza la existencia actual de los objetos ni la publicación completa del manifiesto de la revisión. **Copia local catalogada** describe el catálogo; sus conteos locales son metadatos, no un nuevo escaneo del disco. El botón **Subir selección a GCS** permanece después de la tabla privada y antes del título **Compartidos en GCS**. **Actualizar estados** vuelve a consultar el catálogo privado y limpia la selección; no solicita subidas. Los trabajos solicitados desde la tabla se siguen en esa sección mientras permanece montada; el historial conserva la vía de consulta dentro de la ventana de importación. Abrir la ventana o recuperar una importación no admite una transferencia.

### Eliminar del catálogo mediante archivado privado

Cada fila privada ofrece **Eliminar** en su propia columna, separada de **Consultar audios**, con un nombre accesible que identifica el dataset. El modal de la aplicación **Confirmar archivado de dataset** reutiliza el componente de confirmación de la subida privada a GCS: muestra su nombre y explica que quedará archivado, sin eliminar sus archivos locales ni las copias en GCS y sin liberar espacio. **Confirmar archivado** solicita la operación; **Cancelar** o Escape cierra el modal sin enviar ninguna solicitud y devuelve el foco al botón que lo abrió. Si cambia el catálogo o la sesión, la confirmación deja de estar disponible. No hay acción de eliminación en la tabla compartida.

La interfaz solicita `DELETE /api/ingestion/imports/datasets/{dataset_id}` con la revisión entera del catálogo en `{"revision": ...}`, usando la autenticación existente. Solo un `204` sin cuerpo confirma el archivado. Mientras espera, bloquea nuevas eliminaciones, cambios de selección privada y subidas desde esa tabla. También deshabilita eliminar durante una subida privada pendiente/en ejecución conocida por esta vista o una descarga compartida en curso. Estos controles no acreditan que el servidor esté libre de importaciones, preparación, entrenamiento u otras dependencias: la autorización y las guardas definitivas corresponden al backend.

Después del `204`, retira la fila y su selección y cierra su consulta de audios si estaba abierta. Vuelve a consultar el catálogo privado conservando las selecciones y la consulta de otros datasets que sigan presentes, sin modificar la tabla ni la selección compartida. Si falla esa consulta, muestra el error del catálogo junto con el archivado ya confirmado; no restaura acciones del dataset eliminado. Ante un rechazo, incluido `404`, `409` o `503`, muestra el detalle seguro del servidor y conserva la fila, la selección y los audios consultados. **Actualizar estados** permite volver a consultar un catálogo desactualizado.

El archivado es persistente y exige que la revisión siga vigente. El backend comprueba el propietario y oculta los datasets archivados del catálogo activo y del selector de entrenamiento; rechaza nuevas importaciones sobre ellos, transferencias, preparaciones, entrenamientos y aprobaciones de retroalimentación. Los trabajos ya admitidos y sus reintentos idempotentes continúan; se conservan archivos, historial, preparaciones y contadores. Los nombres archivados siguen reservados por la unicidad existente; no hay restauración desde la interfaz ni liberación de espacio.

## Catálogo datasets públicos · Compartidos en GCS

Ambas tablas muestran el mismo icono decorativo de carpeta junto al nombre, sin etiquetas de dominio ni de origen (incluida **Importado ZIP**). No tienen columna **Estado**: las cantidades se comparan directamente en sus columnas, sin inferir sincronización, hashes ni identidad del contenido.

**Archivos en GCS** refleja el último listado remoto: muestra su cantidad, incluido cero. Si la consulta falla y solo se obtiene el catálogo local, el conteo es **Desconocido**, no cero. **Archivos Locales** muestra el conteo local. **Disponibilidad** conserva **GCS listado**, **Sin archivos en GCS** o **GCS desconocido**, junto a la disponibilidad local. Ninguno garantiza la existencia de los objetos en tiempo real. La tabla privada conserva **Acuses de subida**, no un conteo remoto verificado: no es equivalente al listado GCS compartido.

1. **Actualizar catálogo** consulta los datasets; no descarga ni inicia trabajos.
2. La selección comienza vacía. Marca datasets individuales o usa **Seleccionar todos los datasets compartidos** explícitamente.
3. Revisa los nombres junto a **GCS → Local**. Pulsa **Descargar seleccionados** y confirma los nombres e identificadores en la confirmación del navegador. Cancelar no realiza la solicitud.
4. Durante la descarga, la pantalla espera la respuesta HTTP del servidor. Al recibirla, informa el resultado y los conteos reales; los detalles por dataset quedan en la consola. Un error o una respuesta parcial no se anuncia como descarga completa.

Los archivos quedan en el entorno donde se ejecuta F.A.M.A., no como una descarga del dataset al navegador. Esta acción envía `preprocess:false`: no hay control de preprocesamiento ni opciones avanzadas. La preparación específica por modelo y el entrenamiento siguen siendo operaciones independientes.

**Descargar versión como ZIP** conserva su flujo de exportación al navegador. La consulta de audios, la paginación y la curación supervisada mantienen sus acciones independientes.

## Consultar audios de un dataset

El botón **Consultar audios**, disponible en las tablas privada y compartida, abre el mismo modal de la aplicación. Incluye un selector de **Clase**, una tabla con **Audio**, **Clase** y **Tamaño**, el total del filtro y navegación **Anterior** / **Siguiente**. La interfaz solicita páginas de hasta 50 audios. Cambiar el filtro vuelve a la primera página; las clases disponibles corresponden al dataset completo, no solo a los audios de la página actual. El botón **Cerrar consulta**, en la esquina superior derecha del modal, o la tecla Escape cierran la ventana y devuelven el foco al botón de origen.

**Todas las clases** no aplica filtro. Las clases reales conservan sus nombres. Si existe procedencia de retroalimentación confirmada, aparece además **Retroalimentación (audios incorporados)**: reúne únicamente audios ya incorporados, sin mezclar la cola pendiente ni modificar su clase de entrenamiento. Sigue siendo una opción distinta de una clase real llamada «Retroalimentación». Un nombre de archivo o la ausencia de metadatos no acreditan esa procedencia; los registros históricos sin origen reconocido permanecen consultables en sus clases reales.

En privados, pulsar el nombre descarga ese audio al navegador mediante la ruta existente protegida por propietario y SHA. En compartidos, los nombres son de solo lectura: este modal no ofrece descargas unitarias, ZIP ni nuevas sincronizaciones. Las transferencias completas y la exportación ZIP existentes conservan sus acciones independientes. Los tamaños del modal usan MB decimales hasta 1000 MB y GB estrictamente por encima, truncando a dos decimales.

La carga, un dataset vacío y un filtro sin resultados tienen estados distintos. Un error conserva el detalle disponible y permite **Reintentar**; no elimina audios ni realiza acciones automáticamente. Si la revisión o el inventario cambia durante la navegación, vuelve a consultar la primera página. Una respuesta tardía de una consulta cerrada se descarta.

### Contrato de consulta acotada

- Privados: `GET /api/ingestion/imports/datasets/{dataset_id}/files?browse=true&limit=50`.
- Compartidos: `GET /api/ingestion/datasets/{dataset_name}/files?browse=true&limit=50`.
- `class_name` selecciona una clase exacta y `feedback=true` selecciona procedencia confirmada. Si se proporcionan ambos, se aplica su intersección. La interfaz envía uno u otro; no envía la etiqueta virtual como nombre de clase.
- `limit` no puede superar 200. `cursor` pertenece al dataset, los filtros y su revisión o inventario. Un cursor incompatible se rechaza con `422`; una revisión o inventario cambiado, con `409`.
- La respuesta acotada incluye `files`, las facetas globales `classes` y `has_feedback`, el `total` filtrado, `next_cursor` y `snapshot`. Cada archivo incluye `is_feedback`, que indica origen reconocido, no una verificación remota de su contenido. El acceso privado se comprueba antes de calcular facetas y páginas; no admite consultar nuevos datasets archivados en este modo.
- Sin `browse=true`, cada ruta mantiene su respuesta histórica. No hay migración ni cambios de formato persistido o de la ruta de descarga privada.

La procedencia privada procede de los metadatos persistidos del miembro o de su importación de origen, con unión limitada al propietario. En compartidos se exige una coincidencia canónica del registro persistido de incorporación con el dataset, la ruta relativa y la clave de objeto del inventario; para un elemento remoto se exige además su estado sincronizado. Eso no sustituye una comprobación actual del contenido en GCS. La paginación limita la respuesta HTTP compartida, pero conserva el recorrido completo del inventario que ya realizaba el servidor.

La incorporación de este modal al checkout no acredita por sí sola su despliegue. Sustituir la API activa requiere mantenimiento autorizado por separado; la aceptación visual sigue correspondiendo al usuario, sin automatización de navegador.

Tras el reinicio, se autorizó y aplicó la actualización local de API y frontend: imagen `fama-audio-browser-modal:local`, cinco fuentes backend y tres archivos de interfaz verificados por hash. Se conservó el contenedor anterior detenido para recuperación y se respaldó PostgreSQL, comprobando su restauración en una instancia temporal sin red con los conteos de 33 tablas coincidentes. No se ejecutó ninguna migración. La API saludable y la interfaz en `http://127.0.0.1:3000` respondieron a las comprobaciones HTTP; ambas rutas publican el modo opcional `browse` y el acceso privado sin sesión sigue rechazándose con `401`, también a través del proxy frontend. Esto no sustituye una comprobación visual ni una consulta o descarga autenticada de audios reales.

## Registro de audios incorporados

Esta tabla es de consulta: muestra los últimos 50 registros aceptados en cuatro columnas: **Dataset de destino**, **Nombre del audio revisado**, **Estado local** y **Copia cloud**. En el audio distingue **Original** del nombre real **En el dataset**; este último se toma del destino persistido y no renombra el archivo. Para un dataset privado presenta su nombre legible, sin mostrar el UUID, los identificadores de feedback/predicción, el directorio técnico ni los intentos. Si los metadatos históricos no incluyen los nombres, muestra una indicación neutral de dato no disponible, nunca sustituye el nombre por la ruta o un UUID de almacenamiento. Distingue la incorporación local del acuse de copia cloud. No tiene botón de sincronización ni solicita subidas. El procesamiento automático del backend se mantiene sin cambios. La consulta se actualiza al abrir la vista, tras una revisión que la invalide y al recuperar el foco o volver a la pestaña; no es un seguimiento continuo en tiempo real. Los audios con copia cloud confirmada permanecen visibles como registro. Un error de consulta conserva los últimos datos disponibles; volver a la pestaña o recargar permite reintentar.

## Límites de la comprobación

Las pruebas de interfaz usan controles públicos y respuestas HTTP sintéticas. No acreditan acceso a GCS, permisos reales, transferencia de datos, calidad de modelos ni despliegue de la copia dev. La comprobación visual y funcional de esa copia corresponde al cierre operativo; no debe sustituirse por resultados del checkout.

## Fallos de importación y mantenimiento de temporales

Un error definitivo de validación o ejecución local anterior a la publicación deja la solicitud **cancelada**, conserva el diagnóstico y libera su reserva lógica de recepción. Las advertencias por sí solas no cancelan. Pulsa **Nueva importación** y selecciona el ZIP corregido: se usa una identidad nueva. Una pérdida de conexión, un error de autenticación o un tiempo de espera del cliente no prueban un fallo terminal del servidor; conserva la solicitud y consulta su estado. Una confirmación con publicación pendiente de recuperación no se cancela automáticamente. Un fallo posterior de GCS conserva la importación local.

La cancelación no elimina inmediatamente los archivos ni declara libre su espacio físico. El mantenimiento existente retira únicamente temporales elegibles, conserva los objetos publicados y el historial, y omite trabajos activos, confirmaciones en curso y directorios todavía bloqueados por un escritor. Las reservas físicas solo se recuperan tras la limpieza efectiva.

Para una ejecución explícita, desde `backend/`, usa el intérprete validado y las rutas privadas existentes del mismo perfil que la API y los workers:

```sh
python -m scripts.run_dataset_import_worker --database-url "$DATABASE_URL" --import-root "$IMPORT_ROOT" --staging-root "$STAGING_ROOT" --cleanup-only
```

Para mantenimiento periódico en un proceso de primer plano dedicado, añade `--watch --poll-seconds 3600`. Con `--cleanup-only --watch`, el intervalo predeterminado es 3600 segundos; con `--local-only --watch` o `--sync-only --watch` sigue siendo 2 segundos. Se ejecuta una pasada al arrancar y luego espera entre pasadas. SIGINT/SIGTERM detienen el proceso después de la operación actual. No necesita configuración GCS, no migra ni activa perfiles y no sustituye los requisitos del almacenamiento físico vigente. No combines `--execution-seconds` con `--cleanup-only`.

Estos comandos describen una operación con eliminación real de temporales elegibles: no son un modo de simulación. Este cambio de código no instala, inicia ni autoriza automáticamente el mantenimiento sobre datos reales; su activación requiere autorización operativa y configuración verificadas por separado. Las pruebas sintéticas no acreditan despliegue ni una comprobación física con Python 3.12.

## Historial reciente de importaciones ZIP

6. Para recuperar trabajos tras abandonar la pantalla o gestionar una subida fallida, abre **Recuperar importaciones anteriores** dentro de **Importar ZIP**. Muestra solo las **10 importaciones más recientes** del propietario, por fecha de creación descendente, identificadas por el **nombre original del ZIP**, su **fecha y hora local** y el estado; no usa el UUID como etiqueta. Si un registro antiguo no conserva recibo o fecha, lo indica sin inventar metadatos. No hay paginación en esta lista; los registros anteriores no se eliminan. El modal no ofrece **Subir este dataset a GCS** ni **Consultar archivos locales**; esas acciones se realizan desde la tabla del catálogo.

La consulta de esta lista utiliza `GET /api/ingestion/imports?latest=true`, con un máximo de diez resultados y sin cursor. El parámetro opcional `limit` puede reducirlo, pero no ampliar ese máximo. Los campos descriptivos aditivos son `archive_name` (nombre del recibo ZIP o `null`) y `created_at` (segundos Unix). Sin `latest=true`, la API mantiene el historial paginado por ID y su cursor existente, utilizado por la búsqueda de importaciones para subir datasets privados. La lectura no sube, cancela ni modifica importaciones.

### Resumen de una importación completada

Al recuperar una importación completada, el modal muestra el nombre del dataset disponible en el catálogo de la vista, los audios incorporados, el tamaño del contenido de esa importación y la cantidad y nombres de sus clases. Si el nombre no está disponible en esa vista, lo indica sin sustituirlo por un UUID. El tamaño usa MB hasta 1000 MB y GB estrictamente por encima, en unidades decimales con hasta dos decimales truncados. No es el tamaño acumulado de todo el dataset ni el peso comprimido del ZIP. Los nombres de clases se consultan en una página acotada y, si hay más, se indica cuántas quedan.

El resultado completado omite identificadores técnicos, etapas internas, porcentajes finales, cálculos de cuota, rutas, listados paginados de archivos/incidencias y destinos GCS. Conserva un conteo de advertencias y los errores de consulta; los trabajos incompletos o rechazados mantienen el diagnóstico y las guardas para corregir o reintentar. **Actualizar importaciones** vuelve a consultar las últimas diez importaciones del historial: no refresca por sí mismo el detalle ya seleccionado, no importa, no descarga ni sube a GCS. El seguimiento de un trabajo en ejecución es independiente de este botón.

### Importación en curso

Durante la subida y el procesamiento, el modal muestra un resumen del dataset o ZIP seleccionado y una etapa comprensible: subida, espera, validación de audios o guardado. El avance de subida cuenta únicamente el contenido reconocido por el servidor; la comprobación necesaria para reanudar se informa por separado. Ambos avances usan MB hasta 1000 MB y GB por encima, con las mismas unidades decimales y truncamiento del resumen final; no muestran bytes, identificadores, etapas internas ni porcentajes de trabajo que podrían confundirse con el avance del ZIP. Una subida completa todavía no acredita validación ni publicación local.

Las cantidades y el tamaño del contenido aparecen cuando están disponibles. Las cuotas, archivos y clases de revisión se conservan cuando hace falta confirmar una importación histórica o corregir un rechazo, pero no se presentan durante un trabajo activo. La posibilidad de confirmar sigue sujeta a las mismas guardas del servidor y de la interfaz. Cancelar y reintentar conservan sus condiciones anteriores. Al completarse la importación, desaparece el progreso de recepción y queda el resumen final, sin indicar erróneamente que aún se prepara la validación.

### ZIP rechazado

Cuando la validación cancela una importación con errores, el modal muestra **ZIP rechazado** y los motivos accionables, sin códigos internos ni rutas técnicas. Conserva las instrucciones del ZIP, los límites de peso, el ejemplo sintético y **Nueva importación** para enviar el archivo corregido. Las advertencias sin errores no se presentan como rechazo. Un error al consultar los motivos permite reintentar y no altera el estado de la importación.
