# Consolidación del MVP local

Objetivo: registrar el MVP local en `feat/local-mvp` sin modificar el entorno desplegado. Rama de partida: `feat/imported-training-snapshots`; HEAD inicial `1470f7e0c37ad30ebc80339f744511b1a45ed4f9`.
Estrategia: commits funcionales locales, sin push/PR/merge. Pruebas: runner aislado backend, frontend y TypeScript; preservar límites y resultados históricos.

## Specs

- S1: Inventariar y respaldar archivos de trabajo y estado del índice antes de cambiar de rama o registrar commits.
- S2: Crear `feat/local-mvp` desde el HEAD inicial, conservando el contenido de archivos y el índice.
- S3: Clasificar código, pruebas, documentación y evidencia apta para Git; excluir credenciales, datasets, modelos, dumps, cachés y archivos operativos privados. Sin `git add .`, reset/clean/restauración general ni stash indiscriminado. No eliminar archivos originales.
- S4: Registrar unidades funcionales con pruebas y documentación, respetando dependencias. No incluir contenido ajeno o de pertenencia incierta sin decisión explícita. Mensajes del proyecto: tipo/alcance en inglés y descripción en español.
- S5: Verificar y documentar la rama, commits, archivos fuera de Git y pendientes, sin ejecutar inferencia, entrenamiento real, GCS, despliegue o publicación. Un directorio con datos operativos fuera de Git no implica consolidación incompleta.
- S6: Investigar y corregir el fallo de concurrencia —en código o prueba según causa demostrada— y después retomar commits funcionales, sin despliegue ni datos reales.

## Tasks

- T1 [done] S1, S3 | route: padre + explorador de clasificación de código | commit: N/A; evidencia en cierre documental. Inventario, revisión de secretos y respaldo validado.
- T2 [done] S2 | route: padre | commit: N/A. Crear rama y demostrar conservación exacta del estado.
- T5 [done] S6 | route: explorador acotado + padre, TDD y verificación independiente | commit: d465e7492be52ebd6586bd4e857f9d64ff262a44. Determinar y corregir la causa del fallo concurrente observado mediante interfaces públicas y datos sintéticos, sin debilitar guardas.
- T6 [done] S5 | route: padre | commit: 3dcd4bd. Aislar capacidad de disco en la prueba de admisión ZIP sintética; no modificar capacidad real ni guardas de almacenamiento.
- T3 [done] S3–S4 | route: padre | commit: 9774262..50ad53d (25 unidades; tabla de cierre). Registrar unidades funcionales y clasificar remanentes sin borrar contenido.
- T4 [done] S4–S5 | route: comprobaciones sintéticas + revisión independiente del alcance Git | commit: fuentes 50ad53d; cierre resoluble por historial del recibo (L20). Informar prueba, límites y correspondencia del despliegue.

## Log

- L1: Alcance de implementación: inventario, respaldo y consolidación local según S1–S5.
- L2: Inventario inicial: 270 entradas de status (44 M sin preparar, 6 M preparadas, 12 A preparadas, 2 AM, 206 entradas no rastreadas); 583 archivos no rastreados expandidos. Los contadores no equivalen a unidades funcionales ni autorizan incluir archivos privados.
- L3: Respaldo privado `.local-mvp-consolidation/worktree-before.tar.gz`: 548 archivos verificados byte a byte, SHA-256 `ea68f7aabf14ef2973ce0e2e7dcc4abb807c4f2291bd2eeb80deb2682701db70`; índice original, parches binarios, status e inventario preservados. No contiene una copia consistente de datos operativos/ignorados: esos originales permanecen intactos. Directorio 0700, respaldo/índice 0600.
- L4: `feat/local-mvp` creada desde `1470f7e0c37ad30ebc80339f744511b1a45ed4f9`. Las 548 rutas respaldadas y `git ls-files --stage -z` eran idénticas antes/después. Evidencia privada: `branch-created.json`. Ningún commit, push, cambio de servicio o de datos.
- L5: Revisión inicial: 131 JSON no rastreados válidos, sin hallazgos en patrones acotados de claves privadas/URL de credenciales/tokens ni campos sensibles JSON. Esto no equivale a auditoría exhaustiva. Logs crudos con URLs/tokens sintéticos quedan fuera de la selección y no se alteran. Código de diagnóstico temporal y directorios operativos se conservan fuera de los commits. El explorador no pudo consultar Git; su agrupación fue preliminar, no prueba del índice.
- L6: Verificación anterior a commits: job53 `cd frontend && npm test -- --run && npx tsc --noEmit --incremental false`, exit0: 469 pruebas/51 archivos, tipos sin errores. No prueba visual ni build de producción. Job52, runner aislado y 30 módulos backend: exit1, 183 aprobadas/1 fallida; `test_imported_dataset_preparation.py::test_concurrent_identical_creators_reselect_without_overwrite` recibió `source_unavailable` en vez de `publication_busy`; ejecución detenida en el primer fallo, resto no verificado. Runner confirmó 30 rutas protegidas intactas, SQLite/CPU sintéticos, red/BD real prohibidas y limpieza privada. Logs de ambos: `/tmp/gpyxvfL5/gentle-jobs-iBLmaA/job-{52,53}.log`.
- L7: Se adelanta la comprobación de T4 antes de registrar T3. Diagnóstico independiente de solo lectura `mw5dpe99-o-4ips` sobre el fallo de concurrencia, sin repetir pruebas ni corregir código. La consolidación Git no autoriza automáticamente una corrección de comportamiento ajena a su alcance. RDD consultado: on global; no revisión nativa nueva ni aprobación.
- L8: Diagnóstico independiente terminado: discrepancia de hash entre manifiesto y descriptor SQLite durante verificación de origen (`training_snapshots.py:216–225`), anterior al bloqueo de publicación y al spool de miembros. Comparación contra `1470f7e0`: comprobación y prueba sin cambios; cambios temporales existentes no prueban causalidad. Fixture SQLite compartido es hipótesis, no causa confirmada. Sin repetición ni corrección; no se acepta como aprobación ni se lanza otro verificador. T3/T4 esperan decisión humana sobre ampliar alcance para investigar/corregir este fallo antes de registrar commits, o mantener la pausa con rama y respaldo conservados.
- L9: Ampliación del alcance para investigar y corregir el fallo y retomar la consolidación; sin despliegue ni datos reales.
- L10: Exploración estática `mw5dvnmr-p-jvt5` no demostró causa. Job54, caso original aislado: 1PASS sin cambios, no prueba de corrección. Nuevo diagnóstico sintético por `get`/`iter_verified`/`create`: job55 con sesiones concurrentes sobre StaticPool falló404 durante lectura de snapshot; job56 con idénticas operaciones y solo sesiones DB serializadas pasó80 iteraciones. Diagnóstico de esta tarea preservado privadamente en `.local-mvp-consolidation/test_preparation_concurrency_diagnostics.py`, no incorporado a la suite ni usado para aceptar errores arbitrarios.
- L11: Corrección limitada a `test_imported_dataset_preparation.py`: serializar sesiones de la conexión SQLite compartida, conservando preparación/publicación concurrentes con instancias separadas;16 llamadas concurrentes, descriptor y audios fuente iguales antes/después, única versión y reselección. Job57 pasó el caso corregido y el módulo, después se detuvo con303PASS/1FAIL: `test_default_large_archive_policy_admits_reference_and_enforces_boundary` obtuvo507 por capacidad física insuficiente para una reserva declarada16.36GB. No hay blobGB: era un prerrequisito no controlado de prueba sintética.
- L12: Una corrección acotada del fixture de ZIP fija64GiB libres sintéticos solo durante esa prueba, siguiendo el patrón de `test_dataset_import_receipts.py`; no aumenta disco real ni cambia política de producción. El caso público específico de cuota y margen libre conserva rechazos429/507 y no mutación; no se afirma aprobada toda la suite de recibos. Sin instalaciones, borrados o nueva recuperación ambiental.
- L13: Job58: ZIP3 y preparación72 aprobadas (75), después falló un caso de recibos añadido como diagnóstico por depender de más de10GB libres físicos; no se corrige ese módulo ni se aprueba. Job59: caso específico controlado cuota/disco1PASS; se detuvo después porque `test_local_collection_runtime` intenta subprocess prohibido por el runner. No se cambia ni se evita la guarda; prueba no aprobada. Los módulos de aprovisionamiento/probes retirados según `postgresql-entrenamiento-separado.md:193–195` no se ejecutan como recuperación ni se presentan aprobados. Job61, cuatro módulos vigentes restantes:26PASS. Resultados fragmentados, no una suite backend completa en verde.
- L14: Commit focalizado `d465e7492be52ebd6586bd4e857f9d64ff262a44` solo contiene el test de concurrencia;20 rutas originalmente staged y todas las demás entradas del índice conservadas (job60). Native assess del rango1470f7e0..d465e749: unassessable por archivos no rastreados sin declaración; escalado4 exige verificador independiente, no aprobación nativa.
- L15: Verificador independiente `mw5ed9we-q-le2q`: S6 verificado,1PASS, lock solo DB, archivos aún paralelos, sin modificación de guardas de producción; no demuestra causalidad absoluta del fallo histórico ni contención efectiva en cada ejecución. Spot check padre posterior:5PASS (concurrencia, ZIP3 y cuota/disco), salida del runner sin casos deseleccionados,30 rutas protegidas intactas. T5/T6 cerradas funcionalmente; continúa consolidación sin despliegue.

- L16: Auditoría Git previa independiente `mw5evumd-r-xd9e`: S3/S4 sin bloqueador grave identificado en alcance acotado; sin aprobación funcional, de producción o nativa. Ante metadatos históricos de decisión sin clasificar, se excluye `docs/receipts/imported-training-t5-verification.json` completo, sin modificarlo ni afirmar que sea secreto. Se conservan también304 archivos de logs/evidencia ejecutable fuera de Git;305 exclusiones explícitas presentes y no rastreadas.
- L17: Job63 registró25 unidades funcionales adicionales, cada una con índice privado y sincronización solo de sus rutas. Todas conservaron los bytes del worktree y las entradas del índice ajenas a su unidad. Las versiones intermedias de `main.py` se reconstruyeron por hunks, sin reescribir el archivo real; comprobación AST de26 árboles sin módulos locales ausentes, no prueba de runtime ni de símbolos dinámicos. Se mantuvieron matrices/contratos acoplados: algunas unidades superan el objetivo aproximado400 líneas; los conteos separan JSON generado de líneas no JSON.
- L18: Prueba padre posterior:26 commits antes del cierre documental,89 rutas fuente backend/frontend iguales a blobs HEAD, sin fuente pendiente ni contenido staged. Respaldo e índice original conservan sus hashes. De los548 archivos respaldados solo cambian intencionalmente el fixture ZIP y tres documentos; el test concurrente estaba limpio en el commit base y tiene su propio commit. No se afirma atestación nueva de datos operativos vivos.
- L19: Cierre integra recibo JSON, índice y tablero; reemplaza dos links Markdown nuevos a probes locales excluidos por referencias textuales explícitas, sin repetirlos.333 casos backend distintos tienen resultados aprobados observados en ejecuciones fragmentadas; se conservan fallos, falta de suite completa verde, guardas incompatibles y comprobaciones retiradas/no ejecutadas. Frontend469/51 y tipos0; verificador focal1PASS y spot padre5PASS. No se suman repeticiones como casos nuevos.
- L21: Comprobaciones estructurales del cierre: enlaces Markdown relativos nuevos resuelven en la selección Git, recibo parseable y fuentes aún iguales a HEAD. El intérprete observado es Python3.14.8 de `.venv`, no validación de la imagen Python3.12. El candidato de cierre contiene24 rutas documentales/evidencia explícitas y mantiene excluidos datos/respaldos privados. No se repiten comprobaciones denegadas ni retiradas.
- L20: Git-only completo dentro de estos límites: sin push/PR/merge/despliegue, sin GCS, entrenamiento/inferencia reales o cambios de datos. Aceptación visual, lint histórico no aprobado, backup operativo/restauración, GPU/disco y producción siguen separados. El commit de cierre se resuelve por la ruta del recibo con `git log -1 --format=%H -- docs/receipts/local-mvp-consolidation.json`; el candidato de fuentes previo es `50ad53d`.

### Unidades registradas antes del cierre documental

El primer commit de corrección es `d465e749`. Las25 unidades siguientes conservan código, pruebas, documentación y evidencia vinculada sin presentar herramientas administrativas retiradas como nuevas ejecuciones.

| Unidad | Commit | Líneas de diff no JSON |
| --- | --- | ---: |
| startup | `9774262` | 163 |
| session-schema | `ac23f9c` | 326 |
| auth | `aa40a46` | 391 |
| zip | `3dcd4bd` | 539 |
| snapshot | `f10f0c9` | 163 |
| automatic | `4100fdd` | 687 |
| evaluation-storage | `3956fcc` | 119 |
| evaluation | `6ffd2b9` | 559 |
| local-storage | `4d0e4fe` | 369 |
| catalog | `7f79acc` | 380 |
| inference | `e528a7a` | 779 |
| feedback | `9eca145` | 722 |
| feedback-preparation | `1fdb5c3` | 152 |
| history | `d3f9b8d` | 324 |
| history-ui | `8308d1a` | 434 |
| training-ui | `cc2976a` | 763 |
| training-record | `a147b64` | 305 |
| preflight | `e4a851e` | 163 |
| probe | `3b51724` | 395 |
| probe-permissions | `c764582` | 476 |
| provision | `b0b044a` | 524 |
| postgres-manual | `3987fa0` | 197 |
| manual-db | `7ed9f38` | 568 |
| runtime-manual | `2df8edc` | 255 |
| layout | `50ad53d` | 468 |
