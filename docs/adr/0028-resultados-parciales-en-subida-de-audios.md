# ADR 0028: Resultados parciales en subida de audios

**Estado:** Aceptado. **Fecha:** 14 de octubre de 2026.

La subida anterior abortaba al primer error de transferencia y podía dejar objetos ya enviados sin sus registros. Se elige continuar por archivo, conservar transferencias confirmadas y persistir únicamente esas entradas. No se intenta rollback cloud: podría borrar datos previos y no existe transacción distribuida con PostgreSQL.

## Contrato

- Se mantienen validaciones previas del lote completo, identidad por URI y campos existentes. `files` sigue siendo una lista de nombres, pero solo de transferencias confirmadas; `uploaded` cuenta transferencias, no objetos únicos.
- Se añaden `failed` y `errors` por archivo, con mensaje fijo sin detalles del proveedor. Un error no implica certeza de que el objeto remoto no exista: una excepción tras commit remoto puede ser ambigua. No se registra como aceptado por conjetura.
- `status=completed` indica que todas las transferencias de esta llamada y la persistencia solicitada terminaron; sin BD solicitada solo describe transferencias (`db_persisted=false`, `db_error=null`). `partial` indica alguna transferencia confirmada pero también errores de transferencia o persistencia. `failed` indica errores sin transferencias confirmadas.
- Se conserva HTTP 200 para resultados de lote, incluidos parciales/fallidos; el consumidor debe comprobar `status`, `failed` y `db_persisted`, no inferir éxito por el código. Validación previa conserva 422. Fallos al crear cliente/bucket o al hacer rollback pueden seguir interrumpiendo la llamada: este contrato no los convierte en resultados por archivo.
- Dataset en `subida_parcial` si hay errores de transferencia y `subido` si no los hay, siempre que el commit BD tenga éxito. Son estados del último intento, no una auditoría histórica ni una cola de reintentos. Cero transferencias aceptadas puede dejar un dataset con cero audios y estado parcial, sin crear filas `Audio` ficticias.
- Los contadores se agregan desde filas aceptadas conservadas. Un reemplazo fallido no modifica tamaño/registro anterior; un reintento exitoso actualiza el objeto sin duplicar filas. No se promete conservación remota en cualquier fallo del SDK, ni reconciliación cloud posterior.

## Límites

No añade idempotencia de peticiones, retries automáticos, atomicidad, backfill, control de concurrencia, validación acústica ni límites de carga. Una llamada sin archivos mantiene el comportamiento previo de operación vacía; no acredita datos disponibles. `db_persisted=true` solo confirma la transacción de registros, no que todas las transferencias hayan funcionado ni que los audios sean válidos para entrenar.

La sincronización descendente y su UI todavía pueden presentar un estado global de éxito pese a fallos; quedan separadas. No se añade interfaz nueva de subida. Pruebas por servicio, lectura pública de datasets y HTTP con adaptador GCS falso/SQLite; sin datos/servicios reales. Evidencia en [KANBAN](../KANBAN.md).
