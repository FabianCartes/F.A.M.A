# ADR 0079: Descripción del dataset compartido (revisión 0006)

Fecha: 2026-11-11. Estado: aceptado por Kevin en el [plan de importación ZIP](../arquitectura/importacion-zip-progreso-e-inventario-plan.md) (S3, T5).

## Contexto

La tabla «Datasets locales y en GCS» debe mostrar la descripción que se escribe en Importar ZIP. Esa descripción se guardaba solo en `dataset_import.request`/`imported_dataset.description`; desde el ADR [0078](0078-gcs-como-fuente-unica-y-publicacion-del-zip.md) el catálogo es `conjunto_datos`, que no tenía dónde guardarla. `finalidad` no sirve: registra el propósito del tratamiento, no una descripción libre.

## Decisión

- La revisión `0006_dataset_description` agrega `conjunto_datos.descripcion` (`String(2000)`, nula). Es aditiva: no cambia filas ni otras tablas, y no tiene reversión destructiva.
- Al publicar un ZIP, `_claim` copia la descripción de la importación al crear el dataset. Si el dataset ya existe y su descripción es nula, la rellena; nunca sobrescribe una existente. Una descripción vacía se guarda como nula.
- `GET /api/ingestion/datasets` devuelve `description` por dataset, leída de `conjunto_datos` con el mismo filtro de acceso.
- Instalación, transferencia de historial y las pruebas toman el esquema congelado de `app.schema.head_schema()` en vez de importar una revisión fija.

## Alternativas descartadas

- **Reutilizar `finalidad`.** Cambia el significado de una columna con valor por defecto legal.
- **Leer la descripción desde `imported_dataset` al listar.** Esa tabla es del flujo de importación retirado como catálogo y no cubre datasets creados por subida directa.

## Consecuencias

- Las bases existentes deben migrar a 0006 (`python -m app.schema upgrade --apply`) y volver a aplicar el script de permisos, que ahora exige 0006.
- Los datasets anteriores quedan sin descripción hasta que alguien la registre; la tabla muestra un guion.
