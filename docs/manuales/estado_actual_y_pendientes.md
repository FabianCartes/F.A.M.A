# Estado actual y pendientes para retomar F.A.M.A.

**Corte: 14 de octubre de 2026. Rama: `fix/afinamiento-integral`.**

Este resumen distingue correcciones comprobadas, defectos pendientes y funcionalidades aplazadas. No certifica que toda la plataforma funcione en producción. Evidencia y detalle por unidad: [KANBAN](../KANBAN.md).

## 1. Corregido y comprobado en pruebas aisladas

| Proceso | Resultado comprobado | Límite |
| --- | --- | --- |
| Guardado de entrenamiento | Publicación portable en Windows; mejores pesos/buffers independientes; pérdida y época del checkpoint seleccionado | Sin entrenamiento nuevo con datos reales; diez scripts experimentales aún pendientes |
| Preprocesamiento entrenamiento/inferencia | Checkpoints nuevos conservan y reproducen configuración efectiva; compatibilidad legacy identificada | No resuelve todos los bundles, HPSS ni ensambles |
| Ficha técnica | Datos explícitos del checkpoint; desconocidos visibles sin inventar valores y ceros conservados | No audita ni repara automáticamente artefactos históricos |
| Selección/inferencia | Modelos sin pesos visibles pero no seleccionables; backend rechaza temprano con 503 sanitizado | Disponibilidad no certifica compatibilidad o calidad; política del catálogo sin resolver |
| Autenticación existente | JWT estricto; clave/bootstrap explícitos sin defaults inseguros; cuentas existentes preservadas | No implementa login web, gestión administrada ni permisos generales |
| Configuración de contenedores | Variables necesarias transmitidas y JSON excluidos del contexto backend | Sin nuevo build/despliegue real; Docker Engine observado inactivo en este afinamiento |
| Descarga de datasets | Comparación MD5/CRC32C; staging y validación antes de replace; fallos conservan bytes previos y no crean audios nuevos | Sin transacción archivos/BD, limpieza cloud ni certificación acústica |
| Rutas de descarga | Componentes portables, jerarquía remota completa y destinos resueltos dentro de raw/dataset; bloquea escapes por junctions preexistentes | No bloquea cambios concurrentes de enlaces ni todas las colisiones de nombres |
| Subida de audios | Identidad por objeto completo; clases sin colisión de basename; reemplazos actualizan tamaño sin inflar contadores | Sin atomicidad cloud/BD, tratamiento nuevo de fallos parciales ni validación acústica |
| Validación de nombres y API de ingesta | Subida valida dataset/clase/todos los filenames antes de transferir; nombres inválidos y destinos locales inválidos producen 422 sanitizado; sync prevalida todos los nombres del lote | Sin validación acústica, límites/longitudes ni atomicidad frente a fallos posteriores |
| Fallo de persistencia en ingesta | `db_error` fijo sin SQL/parámetros/detalles internos; `db_persisted=false`, rollback y reintento comprobados en lectura/inserción | Mantiene HTTP 200 de resultado parcial y `status=completed` global existente; otros errores, fallo de rollback y atomicidad siguen pendientes |

### Evidencia disponible

- Última regresión backend acotada: **247 aprobadas**, una prueba de calidad Chucao real deseleccionada, 18 archivos; tres avisos de deprecación. Incluye entrenamiento, contratos de checkpoint, autenticación, disponibilidad, ingesta y pruebas existentes de bundles; no implica que todos los defectos de bundles estén resueltos.
- Última suite frontend completa observada anteriormente: **232 aprobadas / 22 archivos**; no se volvió a ejecutar en esta unidad de backend. Node 22.20.0 sigue fuera del requisito del jsdom instalado.
- Configuración/contexto Docker: **8 pruebas aprobadas**, con cliente y API simulada; no valida el arranque integral.
- Pruebas con temporales, SQLite y adaptadores falsos. Sin cambios a `.env`, credenciales, cuentas, datasets, pesos, PostgreSQL/GCS reales ni servicios existentes. Cinco cambios locales previos del usuario preservados y fuera de los commits de afinamiento.

## 2. Correcciones pendientes de lo ya implementado

Orden recomendado para continuar, no garantía de duración ni lista exhaustiva:

1. **Ingesta:** reemplazar frecuencia/duración prefijadas por datos observados o desconocidos explícitos. Acordar lectura pública de metadatos individuales para probarlos. Completar validación de otros lectores, formatos, longitudes/límites, sanitización de otros errores y resultados veraces para subidas parcialmente fallidas o persistencia fallida. `db_error` de subida/sync ya sanitizado; nombres de subida, respuestas HTTP de validación y escapes de descarga descritos en [ADR 0027](../adr/0027-rutas-portables-y-confinadas-en-descarga.md) ya corregidos.
2. **Catálogo y telemetría:** retirar cifras/estados ficticios y diferenciar inventario cloud, registros BD y disponibilidad local. Resolver catálogo BD-exclusivo frente a ensambles estáticos sin sobrescribir los cambios previos de `registry.py`.
3. **Inferencia y bundles:** revisar fuentes duplicadas y coherencia del preprocesamiento efectivo en exportación/consumo y ensambles; no basta con que las pruebas actuales de exportación pasen.
4. **Parámetros ofrecidos:** identificar los ignorados y hacer que se apliquen o se rechacen explícitamente, sin anunciar capacidades que no existen.
5. **Scripts experimentales:** corregir snapshots de mejores pesos en los diez scripts enumerados en KANBAN, sin ejecutar entrenamientos ni reinterpretar checkpoints históricos.
6. **Portabilidad y entorno:** revisar lanzadores Windows y acordar actualización a Node compatible. Aislar y ejecutar la suite backend global antes de declararla verde.

## 3. Funcionalidades aplazadas, no implementadas en esta etapa

- Login/sesión en la interfaz web.
- Autorización por roles en las operaciones sensibles.
- Gestión de cuentas y cierre del registro público: política acordada de creación exclusivamente por administradores autenticados, todavía pendiente de implementación.

El usuario pidió estabilizar primero lo existente. No se incluyen estas ampliaciones en las correcciones actuales. Su ausencia impide considerar cerrado el acceso seguro de la plataforma.

## 4. Validación operacional pendiente

Requiere autorización separada: configuración real y arranque integral con Docker/GPU/PostgreSQL/GCS; smoke en navegador del recorrido ingesta → entrenamiento → checkpoint → selección → predicción; límites de cargas/CORS/peticiones y controles de acceso antes de exposición.

No se ha acreditado el ciclo completo con datos/pesos reales durante este afinamiento. Se puede retomar desarrollo controlado en la rama actual, pero no declarar la plataforma lista para producción. Commits locales; sin push, merge ni despliegue.
