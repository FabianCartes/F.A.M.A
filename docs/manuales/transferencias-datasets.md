# Transferencias de datasets

> **Nota de sustitución (2026-11-11):** la sincronización privada y la exportación ZIP fueron retiradas; GCS es la fuente única y se mantiene la sincronización GCS→local. Ver [ADR 0078](../adr/0078-gcs-como-fuente-unica-y-publicacion-del-zip.md) y [Importar datasets ZIP](importacion-datasets-zip.md).

## Un inventario compartido

En **Gestión de audios**, el inventario compartido conserva los conteos de
**Archivos Locales** y **Archivos en GCS**. «Compartido» no significa acceso público
en Internet ni cambia la autorización existente. Un listado GCS exitoso puede
informar cero; si no se conoce el conteo remoto, se muestra **Desconocido**, no cero.
Los conteos son observaciones del inventario, no garantías actuales de integridad.

La unidad b retira de esta pantalla el catálogo privado, su selección/subida a GCS,
el archivado privado y la exportación ZIP. No se fusionan identidades por nombre.
La exportación queda como función posterior sobre el inventario compartido.

**Importar ZIP** sigue disponible para recibir, validar y conservar contenido local.
Durante esta transición, un ZIP confirmado todavía no aparece en el inventario
compartido; la publicación y sus permisos corresponden a la unidad c. Importar no
inicia preparación ni entrenamiento. El historial de importaciones conserva la
consulta local; no ofrece subida privada ni exportación.

## GCS → local

1. **Actualizar catálogo** consulta el inventario; no descarga ni inicia trabajos.
2. Marca datasets o usa **Seleccionar todos los datasets compartidos** explícitamente.
3. Revisa los nombres junto a **GCS → Local** y pulsa **Descargar seleccionados**.
   Cancelar la confirmación no solicita la transferencia.
4. Espera la respuesta del servidor y revisa resultados por dataset. Un error o
   respuesta parcial no acredita descarga completa.

Los archivos quedan en el entorno de F.A.M.A., no como un ZIP descargado al
navegador. La acción conserva `preprocess:false`; preparar y entrenar son operaciones
independientes. Esta retirada no cambia la implementación ni permisos de GCS → local.

## Consultar audios

**Consultar audios** abre el modal con selector de clase, audio, clase, tamaño y
paginación. Usa páginas de hasta 50 audios; cambiar filtro vuelve a la primera.
Las facetas pertenecen al dataset completo, no solo a la página. **Cerrar consulta**
o Escape cierra el modal y devuelve foco al origen; respuestas tardías se descartan.

**Todas las clases** no filtra. Si existe procedencia confirmada, la opción
**Retroalimentación (audios incorporados)** selecciona únicamente los audios ya
incorporados, sin mezclar la cola pendiente ni cambiar su clase. No se deduce
procedencia del nombre de archivo ni se confunde con una clase real homónima.

La consulta del inventario compartido conserva nombres de solo lectura: no añade
ZIP, descarga unitaria ni nuevas sincronizaciones. La API local de importaciones
permanece para consumidores existentes y conserva descarga individual por
propietario y SHA, aunque ya no se monte su tabla privada en esta vista.

| API acotada | Uso |
| --- | --- |
| `GET /api/ingestion/datasets/{name}/files?browse=true&limit=50` | Audios del inventario compartido. |
| `GET /api/ingestion/imports/datasets/{id}/files?browse=true&limit=50` | Miembros locales del propietario, para consumidores existentes. |

`class_name` filtra una clase exacta; `feedback=true` selecciona procedencia
confirmada. Ambos parámetros intersectan. La etiqueta virtual no es un nombre de
clase enviado al servidor. `limit` admite como máximo 200; el cursor queda ligado
al dataset, filtros y revisión/inventario. Incompatibilidad devuelve 422; cambio
de revisión/inventario, 409. Se conserva la respuesta histórica sin `browse=true`.

La respuesta incluye `files`, `classes`, `has_feedback`, total filtrado, `next_cursor`
y `snapshot`; `is_feedback` no certifica contenido remoto. Un dataset vacío, filtro
sin resultados y error son estados distintos. Reintentar solo consulta; no incorpora,
prepara, descarga ni sincroniza automáticamente.

## Importaciones y limpieza local

El modal conserva las diez importaciones más recientes del propietario, con
nombre del recibo ZIP, fecha y estado. `GET /api/ingestion/imports?latest=true`
no admite cursor; `limit` puede reducir pero no ampliar el máximo diez. Los
registros anteriores no se eliminan. Sin `latest=true` se conserva la paginación
histórica por ID. Leer historial no admite trabajos.

El resultado completado muestra incorporación local y advertencias disponibles,
sin identificadores técnicos, destinos GCS ni promesas de publicación compartida.
Las respuestas públicas ya no entregan `sync_status`, `synced_count` ni
`synced_file_count` del antiguo flujo privado.

Un fallo definitivo previo al journal cancela la solicitud y libera la promesa
SQL de recepción. Los errores de red/autenticación no prueban ese estado: consulta
antes de repetir. Los journals de publicación permanecen recuperables. La limpieza
explícita solo elimina temporales elegibles y conserva objetos publicados, historial,
trabajos activos y directorios bloqueados. Ya no existe el ledger físico opcional;
se mantienen cuotas, reserva lógica de recepción y chequeo real de espacio libre.

Desde `backend/`, únicamente con base y rutas privadas autorizadas:

```sh
python -m scripts.run_dataset_import_worker \
  --database-url '<URL explícita>' --import-root '<raíz de importaciones>' \
  --staging-root '<raíz de intentos>' --cleanup-only
```

Leer `completed` y `failed`, no solo exit 0. Para mantenimiento periódico en primer
plano añadir `--watch --poll-seconds 3600`; el intervalo predeterminado de limpieza
es 3600 s, frente a 2 s para ejecución. SIGINT/SIGTERM detienen tras la operación
actual. No combinar `--cleanup-only` con `--execution-seconds`. No requiere GCS ni
`FAMA_IMPORT_STORAGE_PROFILE`, no migra ni activa perfiles. No es simulación: la
operación real necesita autorización aparte.

Detalles de ZIP, recuperación y worker: [importación local](importacion-datasets-zip.md)
y [trabajos locales](trabajos-importacion-datasets.md).

## Retroalimentación y límites de evidencia

El registro de audios incorporados sigue siendo de consulta y distingue estado
local de copia cloud de feedback. No cambia la cola supervisada ni la sincronización
automática de retroalimentación. Sus campos `sync_status` pertenecen a otro contrato
y no se retiran con la subida privada del dataset.

Las pruebas sintéticas no acreditan GCS, permisos reales, transferencias de datos,
calidad ML, despliegue o navegador. Los recibos operativos anteriores describen su
corte histórico; no prueban la instalación del contrato reducido del checkout.
