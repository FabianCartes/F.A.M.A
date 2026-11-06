# Incorporación revisada de feedback importado

## Contrato local del servicio

`FeedbackService(raw_data_dir, *, import_root=None).approve_feedback(db,
id_retroalimentacion, dataset_name=None, curation_source_id=None, *, owner_id=None)`
conserva los argumentos legacy. Para una predicción importada exige `owner_id`
obtenido de la sesión autenticada: nunca del payload de feedback. `import_root`
se inyecta explícitamente o se obtiene de `FAMA_IMPORT_ROOT`, sin cargar dotenv.
La conexión y las migraciones existentes son responsabilidad del llamador.

`app.services.imported_feedback.source_for_prediction(db, prediction)` devuelve
la asociación `ImportedModelSource` persistida o `None` para una predicción legacy.
Solo admite identificadores de modelo enteros positivos canónicos (también como
string). Comprueba dataset y propietario de la asociación. Un prefijo `imported:`
sin asociación válida, o una asociación con dataset incompatible, produce 404;
no habilita el camino legacy. Un propietario ausente o distinto produce el mismo
404 antes de descargar audio o crear directorios. La capa HTTP debe autenticar y
comprobar también confirmar, rechazar y consultar la cola; este helper no sustituye
la autorización de esas operaciones.

## Qué significa aceptar

Confirmar la etiqueta solo registra feedback pendiente. Rechazar no añade miembros.
Aceptar verifica el WAV y su digest, conserva bytes locales durables en
`objects/<origin_id>/feedback_<id>.wav` bajo la raíz importada y una copia idéntica
`<raw>/imported:<dataset_id>/<clase>/feedback_<id>.wav` para el worker existente.
No requiere inventar una fila CSV de un dataset raw para representar membresía
importada: la autoridad son `DatasetMember`, `ImportedDataset` y `DatasetSummary`.

Una única transacción confirma miembro, revisión incremental, resumen,
`procesado` e intención `FeedbackSyncQueue`. Los locks de intención y mutación
permanecen adquiridos hasta el commit. Se conservan cuotas de miembros/bytes y
la comprobación de espacio del importador. La intención durable fija modelo,
propietario, dataset, clase, fuente, origen y SHA; si falla el commit, el reintento
verifica/reutiliza los objetos sin borrarlos ni volver a descargar. Un digest ya
incorporado por otro origen se rechaza con 409. Una aprobación ya confirmada no
incrementa de nuevo la revisión. Una corrección posterior al inicio se rechaza.

## Procedencia no ZIP

Cada incorporación crea un `DatasetImport` explícitamente **no archivístico**:
`request.origin = {kind: "feedback", feedback_id, prediction_id}`. No se atribuye
a un ZIP existente. Tiene `archive_sha256=None`, `preview_token=None`, un
`ImportSummary` con el mismo origen, `ImportFile` e `ImportClass` normalizados,
y metadatos de auditoría del miembro con ese origen. No crea recibos ZIP ni jobs.
Las páginas públicas de historial exponen el origen en `preview.origin`; sus
`execution` y token de preview están ausentes. Los consumidores deben distinguir
este origen de una carga ZIP, no describirlo como archivo subido o preview.
Las guardas existentes rechazan receipt/preview/confirm de este registro finalizado
sin archivo/token; un trabajo de sincronización futuro no es una ejecución ZIP.

## Límites y siguiente preparación

No se generan `recording_id` ni `group_id`, no se toca ningún snapshot previo y no
se inicia preparación o entrenamiento. La procedencia se completa explícitamente
al preparar el siguiente entrenamiento. El llamador no puede suministrar
`curation_source_id` legacy para omitir ese paso.

La respuesta `sync_status=pending` acredita una intención, **no una subida**.
`ImportFile` y el miembro permanecen pendientes; la propagación posterior del
resultado del worker a esos contadores importados es integración separada.
No se verificaron servicios reales, GCS, PostgreSQL, GPU ni entrenamiento.

Las pruebas sintéticas usan SQLite en memoria, WAV CPU, directorios temporales y
el runner con red bloqueada; sus streams están en
`docs/receipts/feedback-growth-t1-*.stdout` y `.stderr`.
