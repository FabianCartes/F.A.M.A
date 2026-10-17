# Importación, recuperación y exportación: comprobación integral sintética

T8 conecta la evidencia de los cortes anteriores con un recorrido reproducible de
recepción a descarga. No cambia límites, contratos ni producción. El cierre vigente,
commits y comprobaciones pendientes se mantienen en el [seguimiento canónico](../arquitectura/large-zip-gcs.md).
Esta guía no autoriza operaciones sobre datos, bases, GCS o servicios reales.

## Recorrido del usuario

1. Seleccionar **un ZIP** en el [panel de importación](importacion-datasets-zip.md).
   No dividirlo manualmente: el cliente envía fragmentos secuenciales.
2. Si se interrumpe la recepción, recuperar la importación y volver a seleccionar
   el ZIP original. El cliente compara todos los hashes del prefijo reconocido
   antes de enviar el resto. Mismo nombre, tamaño y extremos no prueban identidad.
3. Admitir validación y consultar su estado. `202` significa encolado, no validado.
   Revisar capacidad actual/proyectada, archivos, clases e incidencias paginados.
4. Confirmar explícitamente el token revisado. La publicación vuelve a comprobar
   cuota, revisión y titularidad; ni revisar páginas ni cerrar el modal confirma.
5. Solicitar sincronización por separado. Consultar **la revisión**: solo
   `complete` con referencia de manifiesto acredita una fotografía reconstruible.
6. Admitir exportación sobre esa revisión completa. Esperar `succeeded`, preparar
   el enlace HTTPS externo y navegar nativamente. El navegador no ensambla un Blob.
   Reintentos por rangos y renovación requieren credenciales vigentes.
7. Ejecutar mantenimiento explícito según el [manual de trabajos](trabajos-importacion-datasets.md).
   Reservas liberadas no equivalen a espacio físico recuperado. Leer los contadores
   de fallo y ocupado; no borrar staging ni referencias manualmente para desbloquear.

## Cobertura y aceptación

La prueba nueva es `backend/tests/test_dataset_import_integration.py`:
`test_receipt_to_native_export_recovers_and_remains_bounded`. Usa HTTP con la
dependencia sintética de propietario existente, workers públicos de una pasada,
SQLite en memoria, WAV originales sintéticos y generaciones de almacenamiento
simuladas. No prueba emisión/validación real de tokens de acceso.

| Criterio del plan original §14–16 | Evidencia o límite |
| --- | --- |
| Un ZIP; reanudación sin retransmisión completa; prefijo diferente rechazado | Recorrido nuevo: tres fragmentos reconocidos, nuevo consumidor HTTP, hashes de todo el prefijo, rechazo409 de fragmento intermedio alterado sin cambio del dump y envío exclusivo del sufijo. Verificación real del cliente en `DatasetImportReceiptRegressions.test.tsx`. |
| Límites exactos, exceso de un byte/archivo; duplicados internos/destino; confirmaciones competidoras | Evidencia específica ya registrada de T3d/T4: módulos `test_dataset_import_quotas.py`, `test_dataset_zip_validation.py` y pruebas públicas de importación; no se declara una nueva ejecución completa de esos cortes. |
| Rechazados sin publicación ni sincronización; confirmación explícita | El rechazo de prefijo no cambia estado; la validación integral no crea dataset; confirmar publica exactamente60/600miembros; sincronizar es otra admisión. Pruebas específicas de objetos/manifiestos inválidos siguen en T4/T6/T7. |
| Contención efectiva del procesamiento no confiable | Procedimiento separado T4 y [ADR0035](../adr/0035-contained-zip-validation.md). La fixture integral sustituye el validador por el sintético cooperativo: el runner original prohíbe subprocesos. **Esta prueba no es evidencia nueva del sandbox OS.** |
| Reinicio sin duplicación; rename antes de commit; trabajos independientes | Pruebas entre procesos T2e y T5 registradas en el manual de trabajos. T8 recrea cliente/ejecutor y recupera un lease perdido después de crear un objeto; no mata procesos ni simula fallo físico. |
| Respuestas y DOM acotados | Páginas de50/200, rechazo de201, muestra<=5; consultas contadas por HTTP para60/600archivos. Panel renderizado recorre todas las páginas sin acumular filas ni confirmar/sincronizar implícitamente. |
| Trabajo antiguo activo; limpieza/reanudación concurrentes | Evidencia específica de leases/callbacks T2/T5 y rangos activos T7. T8 limpia después de finalizar; no agrega una nueva carrera concurrente. La advertencia `R4-cleanup-open-race` queda como seguimiento separado. |
| Revisión completa, manifiesto y generaciones | Interrumpir primer sync después de crear un WAV no publica manifiesto completo; otro ejecutor verifica y completa la misma revisión. Se comprueban hashes, rutas y generaciones. |
| Exportación sin ZIP/WAV locales; integridad y varios rangos autorizados | Se retiran las fuentes locales sintéticas después de sync; el exportador reconstruye todos los bytes desde almacenamiento simulado. Se comprueban ETag, longitud, contenido y tres solicitudes de rango, expiración y renovación. T7 conserva su prueba adicional sin listas locales. |
| Descarga sin Blob; ruta efectiva | `DatasetExport.test.tsx` prueba el enlace externo; T8 HTTP prueba el protocolo, no navegación real ni ingress. Es obligatorio el origen directo al backend descrito debajo. |
| Fallos, omisiones y pendientes informados | Resultados nuevos y antecedentes se distinguen en el seguimiento. No sumar suites de distintas etapas como una nueva corrida global. |

## Reproducir sin servicios ni instalaciones

Requiere el entorno local existente validado, dependencias ya disponibles y checkout
íntegro. No instalar para superar un fallo. Desde `backend/`:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHON_DOTENV_DISABLED=1 DATABASE_URL=sqlite:// \
CUDA_VISIBLE_DEVICES='' PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
../.venv/bin/python tests/run_isolated_training_checks.py \
  tests/test_dataset_import_integration.py -q -s --tb=short
```

El runner original bloquea red, credenciales y SQLite persistente, crea temporales
privados y limita cada fase a30s. Debe informar `protected_paths_unchanged`,
`private_scratch_cleanup` y exit0. No cambiarlo ni cambiar `training_host_guard.py`.
El audit guard no equivale a un sandbox OS; véase el [procedimiento aislado](integracion-flujo-entrenamiento.md#reproducir-comprobaciones-aisladas).

Desde `frontend/`, sin servidor ni navegador externo:

```bash
npm test -- components/views/__tests__/DatasetImportPages.test.tsx
```

Los dos casos nuevos recorren60/600registros con fetch simulado y página50;
prueban filas presentes/retiradas, cantidad de peticiones y ausencia de escrituras.
No constituyen un único navegador conectado al backend: ambos lados se comprueban
en sus interfaces públicas. No se introduce una dependencia de pruebas E2E.

### Mediciones observadas, no certificación de escala

Primera corrida integral corregida de T8, antes de verificación independiente:

| Métrica | 60 WAV | 600 WAV |
| --- | ---: | ---: |
| ZIP sintético recibido, bytes | 18.502 | 184.822 |
| Respuesta de50registros, bytes | 14.319 | 14.320 |
| Respuesta con límite200, bytes | 16.979 (60registros) | 56.474 (200registros) |
| Sentencias SQL por página50/200 | 5 / 5 | 5 / 5 |
| Máximo observado de archivos privados, bytes | 86.362 | 861.265 |
| Bytes de archivos privados al terminar el escenario | 0 | 0 |
| Artefactos de exportación después de mantenimiento | 0 | 0 |

`T8_METRICS` imprime valores nuevos al ejecutar. Disco se muestrea en límites de
etapa: es un máximo **observado**, no un pico continuo ni bloques físicos. El RSS
máximo Linux del proceso completo fue1.798.592KiB en ambos escenarios; incluye
imports, dependencias y fixtures acumuladas. **No es RSS aislado del worker**,
incremento atribuible al dataset ni demostración de memoria constante. Los datos
del almacenamiento simulado y las respuestas del TestClient viven en memoria.
`T8_DOM` informa el máximo de filas montadas; el contrato mantiene<=200por colección
y la prueba espera exactamente la página de50, salvo la última incompleta.

No hay un umbral de RAM/disco inventado: el acuerdo exige observar y comunicar.
No se midieron WAL, ocupación PostgreSQL ni rendimiento con15GiB/50.000archivos.

Verificación independiente posterior: `test_t8_independent.py` y
`test_t8_interaction_independent.py` aportan tres casos, aprobados tanto contra
el candidato como contra la base `9efe006` y promovidos al checkout con3PASS.
Comprueban también páginas vacías, clases/incidencias60/600, recorrido sin duplicados,
rechazos sin mutar el hash del dump y equivalencia de errores HTTP anteriores.
El segundo recorrido usa61WAV. Estas ejecuciones no se suman a los98casos de
regresión backend ni a los43frontend como una única suite global.

## Almacenamiento, manifiestos y recuperación

| Recurso | Contrato que permanece vigente |
| --- | --- |
| Entrada por importación | ZIP64MiB; expansión256MiB;2.000entradas. No habilita la propuesta de10GiB. |
| Dataset acumulado | 15GiB/50.000WAV únicos; una recepción simultánea por propietario, no un solo dataset almacenado. GiB=1024³bytes. |
| Recepción y publicación local | Reserva lógica ZIP+expansión; conservar margen libre, archivo recibido, staging de validación, copia de publicación y journals recuperables. Una reserva no preasigna disco ni cubre todos los usos del host. |
| Revisión y exportación | Conservar objetos y generaciones referenciados; manifiesto<=128MiB, registro<=16KiB. Prever un ZIP_STORED por exportación vigente, temporales por intento y concurrencia de ambas colas. No usar15GiB como presupuesto total del host. |
| Descarga | `FAMA_EXPORT_ROOT` privado/0700 y `FAMA_EXPORT_DOWNLOAD_ORIGIN` HTTPS externo, ruta directamente al backend fuera de Next; configuración no certifica el ingress. |

La identidad recuperable es la referencia autorizada de revisión: clave, generación,
SHA-256 y tamaño del manifiesto. El JSON schema1 contiene identidad/revisión del
dataset, nombre/descripción, totales y miembros con rutas original/canónica, clase,
procedencia, hash, tamaño y clave/generación de objeto. El exportador verifica la
versión y cada miembro; no aceptar una versión desconocida ni inferir compatibilidad
por el nombre del archivo. Los WAV mantienen sus bytes, sin conversión de dominio.
Véanse [ADR0037](../adr/0037-immutable-dataset-revision-manifests.md) y
[ADR0038](../adr/0038-complete-zip-exports-native-sessions.md).

Para restaurar una **copia descargable**, consultar la revisión propia completa y
exportarla desde su referencia verificada; no elegir claves arbitrarias del bucket.
Esto no restaura automáticamente tablas, usuarios ni el catálogo de la aplicación.
Si falta o cambió un objeto/generación, preservar evidencia y fuentes: la exportación
debe fallar, no omitirlo ni publicar un ZIP parcial. La migración de metadatos tiene
su [procedimiento explícito con respaldo y escritores detenidos](migracion-metadatos-importacion.md).
Recuperar jobs desde estado durable; un lease vencido no autoriza borrar staging.
Los limpiadores no son recolectores de objetos publicados: no eliminar referencias
inmutables aunque la descarga o la sesión hayan expirado.

## Fuera de esta aceptación sintética

Sin certificación nueva de fallo físico, reinicio real T6/T7, almacenamiento máximo,
PostgreSQL/GCS reales, Docker/Python3.12, build, lint global, login integrado ni
streaming prolongado desplegado. El siguiente paso operacional necesita autorización
separada para destino, credencial y operación; no se deduce de este manual.
