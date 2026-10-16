# Plan de implementación: importación segura de ZIP grandes y reconstrucción desde GCS

> Copia del plan original completo proporcionado por el usuario el 16 de octubre de 2026. Su estado inicial es histórico: prevalece el [seguimiento actual](large-zip-gcs.md), con T1a implementada y verificada, T1b pendiente al recibir este texto y estrategia `feature-branch-chain` confirmada. Este documento no acredita implementación ni autorización operacional.

Estado: plan consolidado para implementar en otra sesión. No representa funcionalidades ya implementadas.

## 1. Objetivo y alcance

Permitir que el usuario:
1. Seleccione un único ZIP con su dataset.
2. Lo suba mediante fragmentos y reintentos transparentes.
3. Revise una vista previa con errores, duplicados y capacidad proyectada.
4. Confirme su publicación local.
5. Sincronice los WAV con GCS mediante lotes recuperables.
6. Descargue posteriormente un ZIP con sus carpetas reconstruidas desde GCS, incluso sin conservar el ZIP original ni los WAV locales.

### Límites confirmados

| Concepto | Máximo | Contabilización |
| --- | --- | --- |
| ZIP recibido | 10 GiB | Bytes reales del archivo comprimido |
| Contenido descomprimido por importación | 15 GiB | Bytes realmente extraídos, incluidos duplicados |
| Dataset acumulado | 15 GiB | Bytes de WAV únicos publicados |
| Archivos únicos por dataset | 50.000 | Miembros finales del dataset |

Un GiB equivale a 1024³ bytes.
Los límites son independientes: un ZIP de 8 GiB que se expanda a 16 GiB debe rechazarse.

### Valores técnicos propuestos, configurables

- Fragmentos de 16 MiB, inicialmente secuenciales.
- Paginación de 50 elementos, máximo 200 por petición.
- Límites independientes para entradas del ZIP, directorios, profundidad y longitud de rutas.
- Mantener inicialmente los límites individuales de WAV existentes, salvo que la revisión del uso real justifique ampliarlos.
- Plazos separados para recepción, validación, sincronización y exportación.
- Concurrencia y presupuestos de disco ajustados con evidencia operacional.

Estos valores técnicos no son resultados de benchmarks.

### Fuera de alcance

- Entrenamiento de modelos.
- Conversión o normalización automática del audio.
- Publicación automática en catálogos compartidos.
- Conservación del ZIP original en GCS.
- Reconstrucción byte por byte del archivo ZIP original.
- Operaciones sobre GCS real sin autorización explícita.

## 2. Punto de partida que debe verificarse al iniciar

El código revisado durante esta sesión presenta estos puntos:

| Área | Situación observada |
| --- | --- |
| Metadatos | ImportedDataset.files y DatasetImport.preview contienen listas JSON completas |
| Estado y UI | Se devuelve y procesa el preview completo; el panel renderiza toda la lista |
| Sincronización | Reescribe progreso dentro de preview y hace commit por objeto |
| Ejecución | preview, confirm y sync realizan trabajo prolongado dentro de la petición |
| Exclusión | Las mutaciones comparten un mutation.lock global |
| Limpieza | Usa created_at y ejecuta rmtree() dentro de la sección crítica |
| ZIP | El prechequeo interpreta el EOCD clásico, sin resolver explícitamente ZIP64 |
| Descarga frontend | Existe un helper basado en response.blob() |
| Reconstrucción | No se verificó una exportación completa basada en un manifiesto de GCS |

La siguiente sesión debe contrastar nuevamente estos hechos con el checkout actual. No asumir que la rama, los archivos o los contratos siguen iguales.

Archivos principales:

```text
backend/app/models/dataset_import.py
backend/app/routes/dataset_imports.py
backend/app/services/dataset_imports.py
backend/app/services/dataset_zip.py
backend/app/services/dataset_import_storage.py

backend/tests/test_dataset_import_api.py
backend/tests/test_dataset_zip_validation.py
backend/tests/test_dataset_import_sync.py

frontend/lib/api/datasetImports.ts
frontend/components/ingestion/DatasetImportPanel.tsx
frontend/components/views/__tests__/DatasetImportPanel.test.tsx
frontend/next.config.ts
```

## 3. Arquitectura y separación de responsabilidades

El flujo tendrá etapas independientes:
Recepción → validación → revisión → confirmación local → sincronización GCS → exportación → descarga.

No se confundirá:
- recibir el archivo con validarlo;
- validar con publicar;
- publicar localmente con sincronizar;
- sincronizar algunos objetos con completar una revisión;
- iniciar una exportación con tener un ZIP descargable.

Las operaciones prolongadas serán trabajos durables. Sus peticiones HTTP devolverán rápidamente un identificador y un estado, normalmente mediante 202 Accepted.
La consulta de estado siempre tendrá tamaño acotado.

## 4. Modelo de metadatos escalable

### Separar tres tipos de información

| Información | Persistencia |
| --- | --- |
| Estado, contadores, presupuestos y errores resumidos | Registro pequeño del trabajo |
| Archivos, pertenencia, incidencias y progreso por objeto | Registros normalizados e indexados |
| Fotografía completa de una revisión sincronizada | Manifiesto inmutable local y en GCS |

El manifiesto no será el documento mutable de progreso.

### Información por archivo

Registrar, como mínimo:
- identificador estable;
- dataset y revisión a la que pertenece;
- importación de origen;
- clase;
- ruta original y raíz seleccionada;
- ruta canónica de exportación;
- SHA-256;
- tamaño real;
- datos técnicos necesarios del audio;
- referencia al objeto local;
- estado de sincronización;
- clave y generación verificada de GCS.

Aplicar restricciones e índices para deduplicación y consultas por dataset, importación, clase y estado.

### Respuestas paginadas

El estado del trabajo incluirá únicamente:
- etapa y progreso;
- conteos y bytes;
- totales de incidencias;
- una muestra limitada;
- referencias para consultar detalles.

Archivos, clases e incidencias tendrán consultas paginadas con orden estable. Ni el listado de trabajos ni el catálogo de datasets cargarán todas las membresías para calcular sus resúmenes.

### Migración

Implementar una migración controlada:
1. Crear las estructuras nuevas.
2. Trasladar los registros existentes.
3. Verificar cantidades, tamaños, hashes y pertenencia.
4. Cambiar lectores y escritores.
5. Retirar el uso operativo de las listas monolíticas cuando la verificación sea satisfactoria.

No eliminar información existente sin comprobación y estrategia de recuperación.

## 5. Trabajos durables, locks y leases

### Trabajos prolongados

Validación, verificación previa a publicación, sincronización y exportación se ejecutarán mediante workers con estado persistido.
No utilizar tareas improvisadas en memoria de la petición ni depender de que el navegador mantenga abierta la conexión.

Cada trabajo tendrá:
- propietario autorizado;
- tipo y estado;
- progreso;
- lease de ejecución;
- heartbeat;
- intento o token de ejecución;
- resultado y error estructurado;
- información suficiente para recuperarse tras un reinicio.

### Sustituir la exclusión global prolongada

- Por trabajo: proteger recepción, staging y cambios de ejecución.
- Por dataset: proteger las transiciones cortas de publicación y recuperación.
- Admisión: coordinar transaccionalmente presupuestos y límites por usuario y globales.
- Establecer un orden de adquisición de recursos.
- Impedir que un worker cuyo lease perdió vigencia publique resultados después de ser reemplazado.

No mantener un lock de dataset durante hashing masivo, decodificación o acceso a GCS.
La publicación pendiente seguirá registrada en el journal aunque se libere el lock del proceso.
Precisión del código actual: las consultas GET de estado y listado no toman mutation.lock; no deben describirse como rechazadas directamente por ese candado.

## 6. Recepción de un único ZIP por fragmentos

### Protocolo

Disponer de operaciones para:
- crear la recepción;
- consultar el progreso durable;
- enviar un fragmento;
- finalizar el archivo;
- cancelar cuando sea seguro.

Por fragmento se persistirá:
- índice;
- desplazamiento;
- longitud;
- SHA-256;
- estado de aceptación durable.

Reglas:
- Toda operación verifica identidad y propiedad.
- Los identificadores y rutas físicas los genera el servidor.
- Reintentar el mismo fragmento es idempotente.
- Reutilizar su posición con contenido diferente se rechaza.
- Se rechazan huecos, solapamientos y exceso de bytes.
- Solo se reconoce progreso que pueda recuperarse después de una caída.
- Finalizar exige integridad y tamaño completos.
- El ZIP finalizado no admite modificaciones.

El navegador leerá segmentos del archivo sin cargarlo completo en memoria.

### Reanudación después de recargar

Comparar nombre, tamaño, primer fragmento y último fragmento no demuestra identidad completa.
El recorrido seguro será:
1. Seleccionar nuevamente el archivo.
2. Comprobar sus parámetros básicos.
3. Leer incrementalmente todos los fragmentos del prefijo ya aceptado.
4. Comparar sus hashes con el registro de recepción.
5. Reanudar si coinciden.

Esto no requiere reenviar el prefijo ni mantenerlo entero en memoria, pero sí leerlo. La UI mostrará “Verificando archivo para reanudar”.
Si se exige comprobar también la parte que nunca se había enviado, hará falta un compromiso completo previo del archivo. No se prometerá esa garantía utilizando solo muestras.

### Proxy

El proxy admitirá fragmentos con margen suficiente, no una petición completa de 10 GiB.
Verificar el recorrido efectivo y la configuración del despliegue. No ampliar automáticamente los buffers de Next.js a cientos de MiB como sustituto del protocolo fragmentado.

## 7. Cuotas y presupuesto físico

### Dataset

```text
current_dataset_bytes = bytes de WAV únicos existentes
added_bytes = bytes de WAV nuevos que se incorporarán
projected_dataset_bytes = current_dataset_bytes + added_bytes
```

Aplicar el equivalente para cantidad de archivos.
La vista previa expondrá estos valores. La confirmación volverá a comprobar cuota y revisión del destino antes de publicar.

Errores estructurados:
- dataset_size_limit
- dataset_entry_limit

### Disco

Durante una importación pueden coexistir:
- hasta 10 GiB del ZIP;
- hasta 15 GiB extraídos;
- datasets existentes;
- reserva operativa.

La exportación también requiere presupuesto para su ZIP temporal y gastos adicionales de formato.
Se implementarán:
- admisión por presupuesto;
- límites por usuario y globales;
- control de espacio durante la ejecución;
- cuotas de recepciones abandonadas y exportaciones;
- liberación recuperable de reservas.

Un lock por trabajo no basta para impedir sobreasignación global de disco.

## 8. Validación segura y ZIP64

### Prechequeo antes de ZipFile

Actualizar _check_directory() para:
1. Localizar y validar el EOCD clásico.
2. Interpretar los campos centinela correspondientes.
3. Leer y validar el localizador y registro ZIP64 EOCD.
4. Obtener conteos, tamaño y offset reales del directorio central.
5. Comprobar límites y coherencia dentro del archivo.
6. Rechazar estructuras truncadas, incoherentes, multidisco o no soportadas.
7. Aplicar presupuestos antes de construir todas las entradas.
8. Evitar lecturas o reservas arbitrarias basadas en valores del archivo.

Un ZIP mayor de 4 GiB no implica que todos sus campos clásicos estén saturados. Las pruebas deben cubrir cada caso relevante.

### Archivo y rutas

- Rechazar escapes de directorio, rutas absolutas y colisiones normalizadas.
- Rechazar enlaces, dispositivos y entradas especiales.
- Rechazar contenido cifrado, archivos no permitidos y ZIP anidados.
- Limitar entradas, directorios, profundidad y longitud de rutas.
- Contar bytes realmente extraídos y cortar al superar 15 GiB.

### WAV

- No confiar en extensión ni Content-Type.
- Validar estructura del contenedor y decodificación.
- Aplicar límites por archivo.
- Calcular hash y tamaño real.
- Conservar los bytes aceptados sin conversiones silenciosas.

### Aislamiento

Ejecutar el procesamiento no confiable en un proceso contenido con:
- memoria, CPU y plazo de ejecución limitados;
- terminación efectiva;
- acceso mínimo al staging;
- ausencia de red y credenciales de GCS;
- concurrencia acotada.

El plazo cooperativo existente no equivale a aislamiento del sistema operativo.
Un antivirus podrá añadirse como defensa complementaria si se decide y provisiona expresamente; no sustituye estos controles ni permite garantizar ausencia absoluta de malware.

## 9. Confirmación, deduplicación y publicación local

### Duplicados

Distinguir:
- duplicados internos;
- contenido ya existente en el destino;
- mismo contenido con clases incompatibles;
- contenidos distintos que solicitan la misma ruta.

Cuando exista un destino conocido, usar una fotografía coherente de sus hashes y revisión para no retener objetos redundantes después de validarlos.
Si el destino se resuelve posteriormente por equivalencia, depurar staging antes de publicar.
Eliminar un temporal después del hash evita retener una copia; no elimina su escritura inicial. No prometer validación sin I/O temporal.

### Publicación

1. Preparar y verificar los archivos nuevos fuera de la sección crítica prolongada.
2. Comprobar de nuevo revisión, cuota y estado.
3. Registrar intención durable de publicación.
4. Publicar únicamente objetos necesarios para los miembros nuevos.
5. Confirmar membresía, contadores y resultado.
6. Programar limpieza.

Preservar la comprobación de integridad y las garantías de fsync y recuperación. No eliminar la relectura de hash simplemente por rendimiento sin una garantía equivalente verificada.

## 10. Limpieza segura en segundo plano

| Dato | Uso |
| --- | --- |
| created_at | Auditoría |
| Actividad útil reciente | Expiración por inactividad |
| Heartbeat y vencimiento del lease | Propiedad del worker |
| Estado de limpieza | Reclamación y recuperación del borrado |

Reglas:
- El polling no renueva automáticamente la actividad.
- No borrar trabajos con lease activo.
- Un lease vencido exige evaluar recuperación antes de eliminar.
- No borrar datos necesarios para recuperar publicaciones pendientes.
- Reclamar la limpieza atómicamente bajo exclusión por trabajo.
- Impedir reanudación o ejecución mientras se borra staging.
- Ejecutar rmtree() fuera del recorrido HTTP.
- Hacer el borrado idempotente y reintentable.
- Distinguir reserva liberada de disco realmente recuperado.

Después de una importación exitosa, incluida una completamente duplicada, programar limpieza sin esperar el TTL. Un fallo posterior de limpieza no convierte una importación publicada en fallida.

## 11. Sincronización con GCS por lotes

Se suben WAV individuales, no ZIP intermedios.
Cada lote estará limitado por cantidad y bytes, con concurrencia acotada.

Persistir mediante registros normalizados:
- resultado por objeto;
- clave;
- generación;
- evidencia de integridad;
- progreso agregado consistente.

Los reintentos deben ser idempotentes y respetar las precondiciones de creación y generación existentes. Si una caída ocurre antes del checkpoint, se podrá verificar nuevamente el lote.
No reescribir todo el preview o manifiesto después de cada archivo.

### Publicación de revisión completa

1. Fijar una revisión coherente.
2. Sincronizar y verificar sus objetos.
3. Generar su manifiesto.
4. Publicarlo bajo una identidad inmutable.
5. Registrar esa revisión como sincronizada.

No mantener una transacción de BD abierta durante toda la transferencia de red. La fotografía se representará de forma durable.
Una revisión parcial no se presentará como completa. Los objetos de una revisión publicada no deberán eliminarse mientras sigan referenciados.

## 12. Manifiesto de reconstrucción

El manifiesto estará almacenado en GCS y será suficiente para reconstruir el dataset sin el ZIP original ni su lista local de archivos.

Contendrá:
- versión de esquema;
- identidad y revisión del dataset;
- nombre y descripción pertinente;
- cantidades y tamaño total;
- miembros con clase y ruta canónica;
- procedencia de importación;
- tamaño y SHA-256;
- clave y generación del objeto.

Ejemplo simplificado:

```json
{
  "schema_version": 1,
  "dataset_id": "dataset-123",
  "dataset_revision": 4,
  "name": "Aves Chilenas",
  "file_count": 1,
  "total_size_bytes": 240044,
  "files": [
    {
      "class_name": "chucao",
      "relative_path": "chucao/sesion_01/audio_01.wav",
      "original_path": "aves/chucao/sesion_01/audio_01.wav",
      "source_import_id": "import-456",
      "sha256": "<sha256>",
      "size_bytes": 240044,
      "object_key": "<private-object-key>",
      "object_generation": "<generation>"
    }
  ]
}
```

No incluir secretos, URLs firmadas ni rutas absolutas.
Generarlo y procesarlo incrementalmente. Verificar su integridad y recuperarlo desde una referencia autorizada: un hash por sí solo no acredita quién lo publicó.

### Semántica de reconstrucción

- Cada WAV único tiene una ruta canónica de exportación.
- Se conservan clases y subcarpetas aceptadas.
- Los duplicados descartados no vuelven a materializarse.
- Los conflictos de ruta se resuelven de forma determinista y visible antes de confirmar.
- No se promete conservar carpetas vacías, timestamps, compresión ni orden original de entradas.

El resultado reproduce el dataset lógico aceptado, no el ZIP original byte por byte.

## 13. Exportación desde GCS y descarga

### Exportación asíncrona

1. Autorizar usuario, dataset y revisión.
2. Validar manifiesto, límites y rutas.
3. Restringir referencias al espacio de objetos autorizado.
4. Recuperar cada objeto por su generación.
5. Verificar tamaño y SHA-256.
6. Escribir incrementalmente un ZIP compatible con ZIP64.
7. Finalizarlo solo si todos los miembros son correctos.

No inferir la estructura mediante el orden de listado del bucket.
Si falta un objeto o falla su integridad, no entregar silenciosamente un dataset incompleto.

Ejemplo:

```text
Aves-Chilenas/
├── chucao/
│   └── sesion_01/
│       └── audio_01.wav
└── colilarga/
    └── audio_02.wav
```

### Descarga nativa

No utilizar:
fetch → response.blob() → URL.createObjectURL()
para estas exportaciones.

Servir el archivo terminado mediante una descarga HTTP nativa con:
- Content-Disposition;
- Content-Length;
- identificador estable del contenido;
- soporte de rangos y reanudación;
- autorización limitada a usuario y exportación;
- vigencia y renovación controladas;
- limpieza compatible con descargas activas.

Un ticket de un solo uso puede establecer una sesión de descarga, pero no debe invalidar los GET de rango o reintentos posteriores.
La ruta efectiva debe admitir streaming prolongado sin depender del timeout de la reescritura actual de Next.js. Usar un enlace no evita ese proxy automáticamente.

## 14. Cortes verticales bajo TDD

Acordar las interfaces públicas de prueba antes de escribir tests. Cada corte observará RED, implementará GREEN y realizará la revisión correspondiente.

| Corte | Entrega | Verificación principal |
| --- | --- | --- |
| 1. Metadatos escalables | Normalización, migración, resúmenes y páginas | Equivalencia de datos, restricciones, consultas y respuestas acotadas |
| 2. Trabajos durables | Workers, leases, exclusión y admisión | Reinicios, duplicación de ejecución, worker obsoleto, concurrencia y consultas disponibles |
| 3. Cuotas y recepción | Fragmentación y reanudación | Fronteras, propietario incorrecto, reintentos, huecos y fragmento intermedio alterado |
| 4. Validación aislada | ZIP64 y contención de entrada no confiable | Estructuras malformadas, rutas, expansión, decodificador bloqueado y recursos |
| 5. Publicación y limpieza | Journal, deduplicación y expiración | Fallos entre etapas, revisión obsoleta, recuperación y carrera con limpieza |
| 6. Sincronización y manifiesto | Lotes recuperables y revisiones completas | Conflictos, checkpoints, generaciones y publicación incompleta |
| 7. Exportación y descarga | Reconstrucción desde GCS | Sin WAV locales, rutas, hashes, objetos ausentes, rangos y autorización |
| 8. Integración y operación | UX completa y documentación | Flujo completo, regresiones, memoria, BD, disco y comportamiento del despliegue |

### Pruebas especialmente obligatorias

- Límite exacto y exceso de un byte o archivo.
- Duplicados internos y contra el destino.
- Dos confirmaciones que compiten por capacidad.
- Reanudación con mismo tamaño y mismos extremos, pero distinto contenido intermedio.
- Trabajo antiguo activo que no debe expirar.
- Limpieza y reanudación concurrentes.
- ZIP64 con offset grande y con contadores extendidos.
- Reinicio después de rename y antes de commit.
- Sincronización parcial que no publica manifiesto completo.
- Exportación que funciona sin ZIP original ni objetos locales.
- Descarga con varios rangos autorizados.

Usar datos sintéticos, temporales privados y almacenamiento simulado. Las pruebas rutinarias no requieren generar datasets de 15 GiB.
Las mediciones de escala deben informar resultados reales; no presentar estimaciones de WAL, RAM o duración como evidencia ejecutada.

## 15. Interfaz y documentación

### Frontend

El panel deberá mostrar:
- un selector de ZIP;
- capacidad actual y proyectada;
- progreso de recepción y verificación de reanudación;
- avance de validación;
- incidencias y archivos paginados;
- confirmación explícita;
- sincronización local/GCS diferenciada;
- exportaciones y enlace de descarga.

No renderizar ni validar toda la colección en una sola respuesta.

### Documentación

Mantener los documentos del proyecto bajo docs/:
- manual de importación y reanudación;
- manual de sincronización y restauración;
- límites y requisitos de almacenamiento;
- esquema del manifiesto y compatibilidad;
- recuperación de trabajos y limpieza;
- ADR para decisiones relevantes;
- actualización de docs/README.md y docs/KANBAN.md.

No crear documentación paralela bajo odd/.

## 16. Criterios de aceptación

La implementación estará completa cuando se compruebe que:
- El usuario sube un único ZIP sin dividirlo manualmente.
- La recepción se recupera sin retransmitir todo el archivo.
- La reanudación no acepta falsamente otro prefijo.
- Se cumplen los límites de tamaño y cantidad.
- Los objetos rechazados no se publican ni sincronizan.
- El procesamiento no confiable tiene contención efectiva.
- Los trabajos sobreviven a reinicios sin duplicar publicación.
- Los trabajos independientes no comparten una exclusión global prolongada.
- Las respuestas y el DOM se mantienen acotados.
- La limpieza no elimina staging activo o recuperable.
- GCS conserva una revisión completa y reconstruible.
- La exportación verifica bytes, rutas y generaciones.
- La descarga no ensambla el ZIP completo mediante Blob en JavaScript.
- Se conservan las garantías de autorización, integridad y recuperación.
- Se informan todas las comprobaciones fallidas, omitidas o pendientes.

## 17. Instrucciones para iniciar la próxima sesión

1. Recuperar este plan y verificar git status, rama y diferencias locales.
2. Leer los AGENTS.md aplicables y los contratos/documentos actuales.
3. Confirmar herramientas de migración, ejecución de workers y runner de pruebas existentes.
4. Registrar el seguimiento bajo la política documental del repositorio.
5. Empezar por el Corte 1, sin ampliar primero los límites de producción.
6. Ejecutar TDD por cortes y verificación independiente en los cambios de seguridad, persistencia y concurrencia.
7. No usar credenciales, ejecutar operaciones remotas, instalar entornos ni publicar cambios por inferencia.

El plan queda preparado para retomarse, pero la implementación, las migraciones y las pruebas siguen pendientes.

Fin del plan original. Para retomarlo ahora, prevalece el estado del traspaso posterior: T1a implementada y verificada; continuar con T1b, después de reconciliar el checkout y resolver la estrategia de entrega pendiente.
