# Estado actual y pendientes para retomar F.A.M.A.

**Corte: 15 de octubre de 2026. Rama: `fix/afinamiento-integral`.**

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
| Subida de audios | Identidad por objeto completo; continúa tras fallo por archivo y registra solo aceptados; contadores sin duplicados; estados completed/partial/failed y errores sanitizados | Sin atomicidad cloud/BD, retries automáticos ni validación acústica; fallos de creación de cliente/bucket pendientes |
| Validación de nombres y API de ingesta | Subida valida dataset/clase/todos los filenames antes de transferir; nombres inválidos y destinos locales inválidos producen 422 sanitizado; sync prevalida todos los nombres del lote | Sin validación acústica, límites de carga ni atomicidad frente a fallos posteriores |
| Fallo de persistencia en ingesta | `db_error` fijo sin SQL/parámetros/detalles internos; `db_persisted=false`, rollback y reintento comprobados en lectura/inserción; operación parcial/fallida en respuesta | Mantiene HTTP 200 de resultado de lote; otros errores, fallo de rollback y atomicidad siguen pendientes |
| Longitudes de identidad | Dataset/clase hasta 100 caracteres, filename hasta 255, URI hasta 500; valida antes de transferir según esquema actual, sin truncamiento | No garantiza límites de rutas locales/temporales Windows ni valida contenido de audio |
| I/O local de descarga | Rutas extendidas Windows y temporal corto: filename 255, destino anidado y raíz larga comprobados; conflicto local falla por archivo y continúa el lote; temporal bloqueado informa `cleanup_pending=true` | No valida UNC real ni todos los filesystems/lectores; raíz del dataset y limpieza diferida requieren trabajo adicional |
| Estado global y UI de sync | Distingue completed/partial/failed por descarga/SQL/preprocesamiento; pantalla advierte persistencia, preprocesamiento y limpieza pendientes; DB no marca procesado si hubo fallos | No equivale a calidad acústica, catálogo auditado ni entrenabilidad; errores que abortan la llamada quedan separados |
| Metadatos de ingesta | Frecuencia/duración observadas de cabecera, null si desconocidas, cero conservado; reemplazos actualizados; inspector lee metadatos de BD por URI exacta | No valida muestras/calidad; datos históricos y cambios cloud posteriores no se reinterpretan; sin nueva pantalla |
| Validación de subida | WAV/MP3/FLAC/OGG con cabecera/extensión compatibles y decodificación en bloques; rechaza ilegibles/vacíos/cero frames antes de GCS; límites configurables 64 MiB/archivo y 256 MiB/lote | No se extiende a sync; límites no cubren RAM total, recepción/spooling previo, CPU, concurrencia ni RNF de 50 GB |
| Dashboard | Conteos BD reales, cero/null explícitos, métricas del último registro y solo curvas/eventos registrados; referencias históricas separadas; GET no busca/carga checkpoints | No prueba salud GCS/inferencia ni activación; no cierra otros endpoints de estado/ensamble, auditoría completa ni OE5 |

### Evidencia disponible

- Última regresión backend acotada: **338 aprobadas**, una prueba de calidad Chucao real deseleccionada, 22 archivos; tres avisos de deprecación. Incluye dashboard, modelos relacionales, entrenamiento, contratos de checkpoint, autenticación, disponibilidad, ingesta y pruebas existentes de bundles; no implica que todos los defectos de bundles estén resueltos. Aprobación local de feedback: prueba pública focal adicional anterior, **1 aprobada**, sin modificar su implementación previa.
- Última suite frontend completa: **242 aprobadas / 23 archivos**. TypeScript sin incremental y ESLint focal sin diagnósticos. Node observado 22.20.0 sigue fuera del requisito del jsdom instalado.
- Configuración/contexto Docker: **10 pruebas aprobadas**, con Compose config y cliente/API simulada; no valida el arranque integral. Incluye transmisión/defaults de los límites de carga.
- Pruebas con temporales, SQLite y adaptadores falsos. Sin cambios a `.env`, credenciales, cuentas, datasets, pesos, PostgreSQL/GCS reales ni servicios existentes. Cinco cambios locales previos del usuario preservados y fuera de los commits de afinamiento.

## 2. Correcciones pendientes de lo ya implementado

Orden recomendado para continuar, no garantía de duración ni lista exhaustiva:

1. **Ingesta:** completar validación/seguridad/portabilidad de otros lectores, formatos de sync, límites previos de recepción multipart/proxy, recursos RAM/CPU/concurrencia, fallos de raíz del dataset/cliente cloud, limpieza diferida y sanitización de otros errores. Subida estructural y límites de contenidos corregidos en [ADR 0030](../adr/0030-cargas-acusticas-validadas-y-acotadas.md), sin acreditar 50 GB ni seguridad integral. Frecuencia/duración y lectura de BD corregidas en [ADR 0029](../adr/0029-metadatos-acusticos-observados-y-lectura-registrada.md), sin certificar calidad ni reparar registros históricos. Subida parcial, persistencia fallida y estado global/UI veraz de sincronización corregidos en [ADR 0028](../adr/0028-resultados-parciales-en-subida-de-audios.md). Longitudes de identidad, `db_error`, rutas locales largas de descarga y conflictos por archivo ya corregidos para los casos documentados; nombres, respuestas HTTP de validación y escapes de descarga descritos en [ADR 0027](../adr/0027-rutas-portables-y-confinadas-en-descarga.md) ya corregidos.
2. **Catálogo y otras fuentes de estado:** diferenciar inventario cloud, registros BD, disponibilidad local y readiness en los demás endpoints/ensambles. Dashboard corregido en [ADR 0031](../adr/0031-dashboard-con-observaciones-y-origen-explicito.md); no cierra esas fuentes ni constituye auditoría completa. Resolver catálogo BD-exclusivo frente a ensambles estáticos sin sobrescribir los cambios previos de `registry.py`.
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

## 5. Concordancia con propósito, objetivos y documentación

El propósito híbrido y sus módulos están presentes; no está acreditado el cumplimiento operativo completo. OE1–OE3 están documentados; OE4 tiene implementación y pruebas de alcance específico, pero conserva defectos en otras fuentes de estado/ensamble, catálogo y pipeline. La telemetría ficticia del dashboard examinada en el contraste inicial fue corregida en AFIN-22. OE5 y los tiempos de 2 s/3 s, volumen de 50 GB y seguridad integral requieren validación adicional. No se asigna un porcentaje global de avance sin metodología.

El [contraste de objetivos actualizado](../tesis/analisis_objetivos_fama.md) conserva la revisión histórica del 2 de octubre, identifica afirmaciones superadas por las correcciones y separa requisitos implementados de los no acreditados. No sustituye el E2E ni una auditoría de producción. Los defaults de PostgreSQL, control de acceso aplazado y estado Node incompatible siguen siendo pendientes concretos.
