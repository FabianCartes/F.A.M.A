# Transferencias de datasets

En **Gestión de audios**, las importaciones privadas y el catálogo compartido aparecen en dos secciones. Un mismo nombre no convierte sus datasets en la misma colección: conservan identidades y ámbitos separados.

## Importaciones privadas · Local → GCS

1. Pulsa **Importar ZIP** para abrir las instrucciones y el flujo de importación existente. El ZIP debe tener una carpeta por clase en su raíz, con audios WAV válidos. La importación automática valida antes de conservar el contenido local; las solicitudes históricas manuales mantienen su confirmación local.
2. Importar no sube automáticamente a GCS ni inicia preparación o entrenamiento.
3. Marca las filas de ámbito **Privado** en **Catálogo** o usa **Seleccionar todos los datasets privados** para seleccionar los de la página actual. La selección comienza vacía y se limpia al actualizar el catálogo, cambiar de página o cambiar de sesión.
4. Revisa los nombres junto a **Local → GCS**, pulsa **Subir selección a GCS** y revisa los datasets y el tamaño estimado en el diálogo de la aplicación **Confirmar subida privada a GCS**. **Confirmar subida** solicita la operación; **Cancelar** o Escape cierra el diálogo sin consultar el historial ni solicitar ninguna subida. Si cambia el catálogo o la sesión, la confirmación se descarta. La interfaz busca una importación confirmada por dataset en el historial paginado; si no encuentra todas, no inicia la selección. Cada operación sincroniza la revisión completa del dataset, no solo los archivos de esa importación.
5. Un trabajo admitido queda pendiente o en ejecución; no significa que la copia remota esté completa. La pantalla consulta el progreso y distingue finalización, fallo y cancelación. Si falla parte de la admisión, los trabajos ya admitidos continúan: no se revierte el lote ni se anuncia éxito global.
6. Para recuperar trabajos tras abandonar la pantalla o gestionar una subida fallida, abre **Recuperar importaciones anteriores** dentro de **Importar ZIP**.

La copia local se conserva si falla GCS. Subirla no publica el dataset en el catálogo compartido. La columna **Acuses de subida** contiene confirmaciones históricas, no una comprobación actual del bucket. La disponibilidad privada muestra **Subida a GCS registrada (n/total)** cuando hay acuses para miembros del dataset; una proporción parcial no indica una subida completa. Con cero acuses muestra **Sin subida a GCS registrada**, que no significa ausencia verificada en GCS. Incluso con todos los acuses, no se garantiza la existencia actual de los objetos ni la publicación completa del manifiesto de la revisión. **Copia local catalogada** describe el catálogo; sus conteos locales son metadatos, no un nuevo escaneo del disco. El botón **Subir selección a GCS** permanece después de la tabla privada y antes del título **Compartidos en GCS**. **Actualizar estados** vuelve a consultar el catálogo privado y limpia la selección; no solicita subidas. Los trabajos solicitados desde la tabla se siguen en esa sección mientras permanece montada; el historial conserva la vía de consulta dentro de la ventana de importación. Abrir la ventana o recuperar una importación no admite una transferencia.

## Catálogo datasets públicos · Compartidos en GCS

Ambas tablas muestran el mismo icono decorativo de carpeta junto al nombre, sin etiquetas de dominio ni de origen (incluida **Importado ZIP**). No tienen columna **Estado**: las cantidades se comparan directamente en sus columnas, sin inferir sincronización, hashes ni identidad del contenido.

**Archivos en GCS** refleja el último listado remoto: muestra su cantidad, incluido cero. Si la consulta falla y solo se obtiene el catálogo local, el conteo es **Desconocido**, no cero. **Archivos Locales** muestra el conteo local. **Disponibilidad** conserva **GCS listado**, **Sin archivos en GCS** o **GCS desconocido**, junto a la disponibilidad local. Ninguno garantiza la existencia de los objetos en tiempo real. La tabla privada conserva **Acuses de subida**, no un conteo remoto verificado: no es equivalente al listado GCS compartido.

1. **Actualizar catálogo** consulta los datasets; no descarga ni inicia trabajos.
2. La selección comienza vacía. Marca datasets individuales o usa **Seleccionar todos los datasets compartidos** explícitamente.
3. Revisa los nombres junto a **GCS → Local**. Pulsa **Descargar seleccionados** y confirma los nombres e identificadores en la confirmación del navegador. Cancelar no realiza la solicitud.
4. Durante la descarga, la pantalla espera la respuesta HTTP del servidor. Al recibirla, informa el resultado y los conteos reales; los detalles por dataset quedan en la consola. Un error o una respuesta parcial no se anuncia como descarga completa.

Los archivos quedan en el entorno donde se ejecuta F.A.M.A., no como una descarga del dataset al navegador. Esta acción envía `preprocess:false`: no hay control de preprocesamiento ni opciones avanzadas. La preparación específica por modelo y el entrenamiento siguen siendo operaciones independientes.

**Descargar versión como ZIP** conserva su flujo de exportación al navegador. La consulta de audios, la paginación y la curación supervisada mantienen sus acciones independientes.

## Registro de audios incorporados

Esta tabla es de consulta: muestra los últimos 50 registros aceptados en cuatro columnas: **Dataset de destino**, **Nombre del audio revisado**, **Estado local** y **Copia cloud**. En el audio distingue **Original** del nombre real **En el dataset**; este último se toma del destino persistido y no renombra el archivo. Para un dataset privado presenta su nombre legible, sin mostrar el UUID, los identificadores de feedback/predicción, el directorio técnico ni los intentos. Si los metadatos históricos no incluyen los nombres, muestra una indicación neutral de dato no disponible, nunca sustituye el nombre por la ruta o un UUID de almacenamiento. Distingue la incorporación local del acuse de copia cloud. No tiene botón de sincronización ni solicita subidas. El procesamiento automático del backend se mantiene sin cambios. La consulta se actualiza al abrir la vista, tras una revisión que la invalide y al recuperar el foco o volver a la pestaña; no es un seguimiento continuo en tiempo real. Los audios con copia cloud confirmada permanecen visibles como registro. Un error de consulta conserva los últimos datos disponibles; volver a la pestaña o recargar permite reintentar.

## Límites de la comprobación

Las pruebas de interfaz usan controles públicos y respuestas HTTP sintéticas. No acreditan acceso a GCS, permisos reales, transferencia de datos, calidad de modelos ni despliegue de la copia dev. La comprobación visual y funcional de esa copia corresponde al cierre operativo; no debe sustituirse por resultados del checkout.

## Historial reciente de importaciones ZIP

6. Para recuperar trabajos tras abandonar la pantalla o gestionar una subida fallida, abre **Recuperar importaciones anteriores** dentro de **Importar ZIP**. Muestra solo las **10 importaciones más recientes** del propietario, por fecha de creación descendente, identificadas por el **nombre original del ZIP**, su **fecha y hora local** y el estado; no usa el UUID como etiqueta. Si un registro antiguo no conserva recibo o fecha, lo indica sin inventar metadatos. No hay paginación en esta lista; los registros anteriores no se eliminan. La acción histórica **Subir este dataset a GCS** sigue disponible con su confirmación individual.

La consulta de esta lista utiliza `GET /api/ingestion/imports?latest=true`, con un máximo de diez resultados y sin cursor. El parámetro opcional `limit` puede reducirlo, pero no ampliar ese máximo. Los campos descriptivos aditivos son `archive_name` (nombre del recibo ZIP o `null`) y `created_at` (segundos Unix). Sin `latest=true`, la API mantiene el historial paginado por ID y su cursor existente, utilizado por la búsqueda de importaciones para subir datasets privados. La lectura no sube, cancela ni modifica importaciones.
