# ADR 0048: Cargas acústicas validadas y acotadas

**Estado:** Aceptado. **Fecha:** 15 de octubre de 2026.

El usuario confirmó conservar WAV/MP3/FLAC/OGG en la subida y límites iniciales configurables de 64 MiB por archivo y 256 MiB por lote. Se valida el lote completo antes de contactar GCS: nombres, tamaños, contenedor compatible con extensión y decodificación por bloques. Se descartan las alternativas de aceptar cualquier binario o comprobar solo una cabecera: un FLAC truncado puede conservar cabecera legible pero fallar al decodificar.

## Contrato

- POST `/api/ingestion/upload` lee cada archivo en bloques de hasta 1 MiB, sin `read()` ilimitado. Cuenta bytes de contenidos de archivo, no los bytes completos del framing/campos multipart. Solo transfiere después de reunir y validar el lote.
- `FAMA_UPLOAD_MAX_FILE_BYTES=67108864` y `FAMA_UPLOAD_MAX_BATCH_BYTES=268435456` son los defaults. Deben ser enteros positivos y el límite individual no puede exceder el agregado. Configuración inválida produce HTTP 503 sanitizado; exceso de tamaño produce 413. Compose transmite ambos valores, sin cambios en `.env` real.
- El servicio aplica también los límites a llamadas directas, aunque no puede deshacer la memoria que su llamador ya asignó. El manejador HTTP y el servicio leen configuración del entorno; no se promete cambiarla concurrentemente durante una petición.
- Extensión y formato informado por el decodificador deben corresponder: WAV/WAVEX/RF64 para `.wav`, MP3/MPEG para `.mp3`, FLAC para `.flac` y OGG para `.ogg`. MIME enviado por cliente no acredita el contenido. Codecs concretos dependen del libsndfile instalado.
- Se exige frecuencia/canales positivos y al menos un frame. Se recorre el audio con float32 y bloques calculados para aproximadamente 1 MiB de muestras; errores del decodificador o conteo incompleto rechazan con 422 sanitizado. No es un verificador formal de todos los bytes/variantes de cada contenedor.
- Archivo vacío, ilegible, sin frames o incompatible con extensión rechaza todo el lote, antes de la primera transferencia. Las transferencias que fallan después de una validación correcta mantienen el contrato parcial del [ADR 0046](0046-resultados-parciales-en-subida-de-audios.md): no se añade atomicidad ni rollback cloud.

## Relación con metadatos y requisitos

Esto endurece el contrato de subida del ADR 0047: ya no se admite por esta vía un reemplazo ilegible ni audio de cero frames. Un intento rechazado conserva el objeto/registro anterior. La sincronización descendente no incorpora este filtro: puede gestionar otros objetos del dataset y conservar metadatos desconocidos o cero; no se reinterpretan datos históricos. Las pruebas de null/cero se mantienen por ese recorrido, no se relajan al nuevo contrato.

Decodificación estructural no certifica clase, silencio, ruido, calidad, aptitud para entrenamiento ni exactitud del modelo. Los límites de archivo/lote tampoco acreditan el RNF de datasets de 50 GB sin OOM, ni los tiempos de procesamiento/predicción.

La suma de contenidos queda acotada, pero existen copias, buffers del decoder y spooling multipart anterior al manejador: no se garantiza RAM total de 256 MiB, límite de tráfico/disk en el parser ni defensa frente a todas las cargas adversarias. CPU/tiempo de descompresión, concurrencia, rate limiting, límites ASGI/proxy y controles de acceso siguen pendientes antes de exposición. No se instala ni cambia dependencias ni se opera cloud/BD real.

Pruebas públicas con WAV/FLAC/OGG/MP3 sintéticos, caso FLAC truncado con cabecera legible, límites inclusivos y sin transferencias previas; Compose config aislado sin daemon. Evidencia en [KANBAN](../KANBAN.md).
