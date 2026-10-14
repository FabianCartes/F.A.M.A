# ADR 0027: Rutas portables y confinadas en descarga de datasets

**Estado:** Aceptado. **Fecha:** 14 de octubre de 2026.

## Contexto

`sync_dataset_to_local` aceptaba componentes `..`, separadores Windows y nombres de dispositivos. Permitía escribir fuera del dataset; además truncaba las rutas con más de un subdirectorio. Una junction local podía redirigir incluso un objeto con nombre válido fuera del destino previsto.

## Alternativas

- Normalizar/sanitizar nombres: puede fusionar objetos distintos o cambiar su identidad sin conocimiento del usuario.
- Aceptar solo dos niveles: evita truncamiento, pero descarta jerarquías cloud legítimas.
- Validar componentes, conservar jerarquía y verificar destino resuelto: opción elegida; no renombra objetos por conjetura.

## Decisión

- El dataset debe ser un componente portable, no una ruta. Se rechazan nombres vacíos, `.`/`..`, separadores, controles, caracteres incompatibles con Windows, nombres reservados y punto/espacio final. Nombres Unicode y espacios interiores siguen permitidos.
- Cada objeto debe pertenecer al prefijo exacto del dataset y tener componentes válidos, sin componentes vacíos. Los marcadores de directorio terminados en `/` se omiten, no se transfieren.
- Se conserva toda la ruta relativa del objeto. La clase es el primer directorio, o `General` para archivos planos; el nombre de archivo es el último componente. Su identidad BD sigue siendo la URI completa.
- El destino del dataset resuelto debe permanecer bajo la raíz raw configurada, y el archivo resuelto bajo el dataset. Enlaces/junctions que redirigen fuera de esos límites se rechazan antes de descargar o crear directorios de destino.
- Dataset inválido produce `ValueError`; objeto inválido se informa como transferencia fallida, sin descargar ni registrar una fila nueva. No se corrigen nombres ni archivos históricos automáticamente.

## Consecuencias y límites

Objetos antes aceptados con nombres no portables se rechazan ahora; corregirlos requiere una decisión sobre datos reales, fuera de este cambio. No hay garantía contra sustitución concurrente de enlaces entre validación y escritura (TOCTOU), ni detección completa de alias/collisiones por mayúsculas o normalización Unicode. La raíz raw configurada se considera confiable.

La unidad inicial cubre la descarga por el servicio. La extensión siguiente incorpora nombres de subida y respuestas HTTP; otros lectores, formatos de audio y límites de peticiones siguen pendientes. Tampoco certifica seguridad de despliegue.

Pruebas públicas con GCS falso y temporales: escapes POSIX/Windows, prefijos ajenos, componentes vacíos, jerarquías anidadas, nombres Unicode y junctions Windows reales creadas/eliminadas exclusivamente dentro de las fixtures. En otras plataformas la fixture usa symlinks; solo se ejecutó aquí Windows. Evidencia: [KANBAN](../KANBAN.md).

## Extensión: nombres de subida y validación HTTP (14 de octubre de 2026)

La subida usa la misma política portable para dataset, clase y filename. No reemplaza barras por guiones ni recorta rutas a basename: entradas inválidas se rechazan sin inventar identidades. La clase omitida sigue usando `General`; una clase explícitamente vacía se rechaza. Se valida el lote completo antes de obtener el cliente cloud, evitando transferencias anteriores a un filename inválido.

La API traduce únicamente `IngestionValidationError` (subclase de `ValueError`) a HTTP 422 con texto fijo, sin eco de nombres/rutas. Un `ValueError` ajeno del proveedor no se presenta como validación del usuario. La sincronización prevalida todos los nombres de dataset antes del primer recorrido; no promete prevalidación de todos los destinos locales, éxito de todos los datasets ni atomicidad del lote. Una validación del destino local también produce 422, pero puede ocurrir después de otras sincronizaciones válidas del mismo lote.

No se validan aún longitudes contra columnas SQL, contenido/formato acústico, tamaño de carga ni colisiones por case/Unicode. La exposición SQL en `db_error` fue corregida posteriormente en AFIN-14 (véase KANBAN): texto fijo y persistencia fallida explícita, sin modificar el HTTP 200 parcial ni añadir atomicidad. Recuperación de errores del proveedor y estado parcial/global veraz requieren correcciones separadas. Pruebas HTTP reutilizan endpoints reales en una app sin lifespan productivo, con dependencia SQLite aislada y adaptador GCS falso.
