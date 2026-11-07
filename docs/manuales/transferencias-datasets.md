# Transferencias de datasets

En **Gestión de audios**, las importaciones privadas y el catálogo compartido aparecen en dos secciones. Un mismo nombre no convierte sus datasets en la misma colección: conservan identidades y ámbitos separados.

## Importaciones privadas · Local → GCS

1. Pulsa **Importar ZIP** para abrir las instrucciones y el flujo de importación existente. El ZIP debe tener una carpeta por clase en su raíz, con audios WAV válidos. La importación automática valida antes de conservar el contenido local; las solicitudes históricas manuales mantienen su confirmación local.
2. Importar no sube automáticamente a GCS ni inicia preparación o entrenamiento.
3. Para guardar una copia privada en GCS, abre la importación correspondiente en **Recuperar importaciones anteriores** dentro de la ventana de importación.
4. Comprueba el nombre del dataset, su identificador y el de la importación. El nombre se muestra cuando está en la página actual del catálogo privado; si no está disponible, la confirmación identifica el dataset por su ID, sin inventar un nombre. Pulsa **Subir este dataset a GCS** y revisa la confirmación del navegador. Cancelar no admite el trabajo.
5. Un trabajo admitido queda pendiente o en ejecución; no significa que la copia remota esté completa. Consulta su estado, progreso y errores. La misma acción permite reanudar una subida pendiente; no existe una subida masiva desde esta pantalla.

La copia local se conserva si falla GCS. Subirla no publica el dataset en el catálogo compartido. Los conteos GCS privados son acuses durables históricos de subida, no una comprobación actual del bucket. **Actualizar estados** vuelve a consultar el catálogo privado; el historial y los trabajos se consultan dentro de la ventana de importación. Abrir la ventana o recuperar una importación no admite una transferencia.

## Catálogo compartido · GCS → Local

1. **Actualizar catálogo** consulta los datasets; no descarga ni inicia trabajos.
2. La selección comienza vacía. Marca datasets individuales o usa **Seleccionar todos los datasets compartidos** explícitamente.
3. Revisa los nombres junto a **GCS → Local**. Pulsa **Descargar seleccionados** y confirma los nombres e identificadores en la confirmación del navegador. Cancelar no realiza la solicitud.
4. Durante la descarga, la pantalla espera la respuesta HTTP del servidor. Al recibirla, informa el resultado y los conteos reales; los detalles por dataset quedan en la consola. Un error o una respuesta parcial no se anuncia como descarga completa.

Los archivos quedan en el entorno donde se ejecuta F.A.M.A., no como una descarga del dataset al navegador. Esta acción envía `preprocess:false`: no hay control de preprocesamiento ni opciones avanzadas. La preparación específica por modelo y el entrenamiento siguen siendo operaciones independientes.

**Descargar versión como ZIP** conserva su flujo de exportación al navegador. La consulta de audios, la paginación y la curación supervisada mantienen sus acciones independientes.

## Límites de la comprobación

Las pruebas de interfaz usan controles públicos y respuestas HTTP sintéticas. No acreditan acceso a GCS, permisos reales, transferencia de datos, calidad de modelos ni despliegue de la copia dev. La comprobación visual y funcional de esa copia corresponde al cierre operativo; no debe sustituirse por resultados del checkout.
