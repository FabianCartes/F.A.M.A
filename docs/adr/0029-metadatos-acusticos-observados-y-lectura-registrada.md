# ADR 0029: Metadatos acústicos observados y lectura registrada

**Estado:** Aceptado. **Fecha:** 14 de octubre de 2026.

Ingesta guardaba 22050 Hz/5 s para cualquier audio y no actualizaba esos datos al reemplazarlo. Se decide observar la cabecera con `soundfile.info`, guardar desconocidos como null y exponer la lectura persistida en el inspector existente. Se evita decodificar/remuestrear el audio completo solo para obtener metadatos: cabecera legible no implica muestras íntegras ni calidad acústica.

## Contrato y alternativas

- Frente a mantener presets o deducir física por dataset, subida y sincronización registran samplerate y frames/samplerate observados del contenido aceptado. La subida inspecciona bytes; la sincronización inspecciona el archivo local descargado o confirmado por checksum. Los reemplazos actualizan ambos campos; un reemplazo aceptado pero ilegible borra los valores previos en lugar de conservar datos de otro contenido. Fallos de transferencia no actualizan esos registros.
- Si la cabecera no se puede leer, ambos valores quedan null; duración cero observada se conserva. No se rechaza el archivo por este motivo: validar formatos y contenido de carga es otra corrección, no se considera completada por este ADR.
- Se retira el default Python 22050 del ORM `Audio`, que sustituía incluso un null explícito en inserciones. Las columnas ya eran nullable; no se altera tipo ni nulabilidad, ni se ejecuta migración, backfill o acceso a PostgreSQL real. No se acredita el estado de defaults externos de una BD desplegada.
- El usuario confirmó ampliar GET `/api/ingestion/datasets/{dataset}/files`, sin nueva pantalla ni endpoint. `list_dataset_files` admite sesión opcional y agrega `recorded_metadata` por URI completa (dataset, bucket y ruta del objeto), no por basename. Con sesión devuelve un objeto con `sample_rate_hz`, `duration_seconds`, `source="database"` para filas existentes, o null si no está disponible la lectura registrada. Sin sesión conserva el inventario previo sin enriquecimiento.
- Fallo de consulta BD conserva inventario y metadatos no disponibles, hace rollback y no expone SQL. Null de lectura no demuestra que no exista fila: también puede significar indisponibilidad de la consulta. Fallo al crear sesión/rollback queda fuera de esta recuperación.
- Se conserva la identidad exacta del inventario local para archivos planos/anidados; `General` es etiqueta de clase, no directorio inventado. Inventario cloud usa el último componente como filename y omite marcadores de directorio. Esto evita asociar metadatos a otro objeto por una ruta truncada.

## Límites relevantes

`recorded_metadata` describe BD, no una comprobación actual del objeto cloud ni necesariamente la última versión remota. Los registros históricos pueden contener presets de la implementación anterior: no se reinterpretan ni reparan sin un nuevo recorrido aceptado de ingesta. No se añade un checksum o versión de objeto para certificar vigencia.

No modifica la física de entrenamiento/inferencia, calidad acústica, política de aceptación de formatos, seguridad integral de otros lectores, límites de carga/memoria, sincronización cloud/BD ni control de concurrencia. La nueva consulta lee solo filas del dataset solicitado, pero no añade permisos de acceso pendientes del proyecto. Se reutiliza `soundfile`, ya declarado; no cambia dependencias, credenciales ni datos reales.

Interfaces de prueba acordadas: subida/sync, lectura HTTP del inspector y listado de datasets cuando aplica. Audios WAV sintéticos, adaptador GCS falso y SQLite temporal; resultados y regresión en [KANBAN](../KANBAN.md).

**Actualización posterior (15 de octubre de 2026):** [ADR 0030](0030-cargas-acusticas-validadas-y-acotadas.md) endurece la subida: ya no acepta ilegibles/cero frames ni contenido incompatible con extensión, y aplica límites configurables. Null/cero y actualización a desconocidos siguen siendo comportamientos de registro para sync; no se elimina esa evidencia ni se reinterpreta la historia. Una subida inválida conserva el objeto/registro anterior.
