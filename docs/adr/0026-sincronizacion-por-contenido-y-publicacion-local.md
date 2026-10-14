# ADR 0026: Sincronización por contenido y publicación local de transferencias completas

**Estado:** Aceptado. **Fecha:** 14 de octubre de 2026.

La sincronización existente confundía igual tamaño con igual contenido, descargaba encima del archivo previo y registraba transferencias fallidas como audios disponibles. Se corrige ese recorrido: checksum del proveedor, staging local exclusivo y registro únicamente de transferencias aceptadas, sin añadir funcionalidades de acceso.

## Decisión

- Un archivo local se omite solo cuando su contenido coincide con MD5 o, si no hay MD5, CRC32C declarado por el proveedor. El cálculo lee por chunks de 1 MiB; son checksums de transporte, no autenticación criptográfica ni certificación de calidad acústica. Sin checksum no se deduce identidad por tamaño: se intenta descargar.
- La descarga escribe en un temporal exclusivo del mismo directorio. Antes de publicar se comprueba tamaño declarado cuando existe y checksum cuando está disponible. Solo entonces se reemplaza el destino; una transferencia fallida conserva bytes previos y elimina su staging en el manejo normal de errores.
- El tamaño de transferencias aceptadas procede de los bytes locales observados, no de un valor ficticio si el proveedor omite tamaño.
- En BD solo se admiten transferencias `downloaded`/`skipped`. Los errores dejan el dataset en `sincronizacion_parcial`; no producen una fila de audio nuevo. Los registros aceptados anteriormente se conservan y sus contadores se agregan desde las filas persistidas.
- La identidad relacional del audio usa su URI de objeto completa dentro del dataset, no solo basename. Dos clases con `audio.wav` mantienen dos registros; no se inventa el directorio `General` en la URI de un objeto plano.

## Límites

No hay transacción distribuida entre archivos y BD, locks de escritores concurrentes ni garantía nueva de durabilidad ante caída/pérdida de energía. Un fallo SQL puede dejar archivo publicado sin registro actualizado; no se añade reconciliación automática. Los contadores describen filas aceptadas conservadas, no una auditoría actual del cloud. No se borran objetos o registros retirados del proveedor ni se reparan rutas históricas ficticias por conjetura.

Este cambio corresponde a `sync_dataset_to_local`. La subida, estimaciones de sincronización del catálogo por conteos, validación de rutas/formatos y metadatos acústicos prefijados siguen como correcciones separadas. Tampoco certifica particiones listas para entrenar ni calidad de audio. SDK/metadatos del proveedor siguen determinando la versión leída; no se promete un snapshot cloud inmutable.

Interfaces públicas acordadas: sincronización y lectura de datasets de entrenamiento. Pruebas con adaptador GCS falso, archivos locales temporales y SQLite, sin datos/servicios reales; resultados en [KANBAN.md](../KANBAN.md).
