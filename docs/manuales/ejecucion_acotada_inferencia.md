# Ejecución acotada de inferencia

## Estado actual: verificación funcional y revisión nativa completadas

**BEXEC-1 a BEXEC-6 están completadas dentro del alcance autorizado, sin commits nuevos ni despliegue.** Al cierre original de BEXEC, la suite frontend completa no estaba verde; la corrección posterior de IngestionSync se registra al final de este documento. La evidencia usa audio sintético y adaptadores simulados: no certifica integración productiva de modelos, GCS o BD. Los incidentes anteriores se conservan como antecedentes, no como resultados válidos ni bloqueadores actuales de las comprobaciones repetidas con aislamiento.

| Comprobación vigente | Resultado y alcance |
| --- | --- |
| Backend y regresiones de feedback | 97 aprobadas en 2,54 s |
| Frontend enfocado | 43 aprobadas en 2,39 s |
| Frontend completo | 234 aprobadas / 1 fallo preexistente: `IngestionSync.test.tsx:39`, `Feedback #7`; archivo sin cambios, fuera de alcance |
| Build y TypeScript | Aprobados; build `aqhIFgT0DZzQZGFkgfdok` |
| Proxy Node con helper/config reales | 1 aprobada; espera real de 35,048 s, control negativo de 30 s |
| Next construido, rewrite hacia API falsa 49173 | HTTP 200 tras 35,010 s; evidencia separada del navegador y del endpoint real |
| Contador middleware de 110 MiB | Consumidor ASGI controlado: límite inclusivo 200 / +1 byte 413, 0 efectos; **no prueba multipart del endpoint** |
| Chromium, cinco casos UI | Todos aprobados: oversize con 0 POSTs, WAV pequeño, 500 no JSON, 503 y 504; **API falsa directa 8000, no rewrite** |
| Endpoint real `/api/predict`, raw ASGI | Archivo 100 MiB: 200 en 213 ms; +1 byte: un único 413 JSON en 144 ms, CORS y 0 efectos de predictor/upload/BD en exceso |
| Aislamiento de las repeticiones UI/endpoint | bwrap user/net, raíz read-only, tmpfs privado; rutas externas vacías y TEST-NET ENETUNREACH pre/post. Endpoint con stubs torch/ML/cloud/BD previos al import, guards fail-closed y SQLite en memoria; sin TestClient, lifespan ni modelos reales |

La revisión `review-7ba32d8c47dbb57b` aprobó únicamente BEXEC-1/2. La revisión completa `review-4a2c7479079f5355` aprobó el snapshot de 18 archivos y 1589 líneas cambiadas; reconocimiento completado y autoridad consumida (`burned`). El assessment posterior falló por la declaración de archivos untracked; su ruta conservadora se cumplió con una verificación independiente adicional de 70 pruebas enfocadas aprobadas en 2,72 s. Ese fallo de assessment no revoca ni sustituye el resultado nativo aprobado. Commits, despliegue, audio real y borrado del perfil residual requieren autorización separada; no están aprobados.

## Objetivo y contrato aprobado

Corregir el corte de inferencia a los 30 segundos sin ampliar la espera de forma ilimitada ni multiplicar el trabajo concurrente. El usuario autorizó los controles de recursos y eligió un máximo de **300 segundos de audio**, rechazando excedentes sin recorte silencioso. Se mantienen **100 MiB por archivo** y **110 MiB por solicitud multipart**.

La duración del audio no equivale al tiempo de procesamiento. La espera HTTP tendrá un presupuesto explícito y margen para responder desde el backend; no se promete detener un hilo de Python/PyTorch por cancelar un request.

## Alcance y exclusiones

- Una inferencia activa por proceso de backend, sin cola; saturación HTTP 503 con `Retry-After: 5`.
- Trabajo bloqueante fuera del event loop; cupo y temporales vivos hasta terminar el trabajo real, incluso después de desconexión o timeout.
- Rechazo efectivo del cuerpo excesivo antes de efectos externos; validación de WAV real, bytes y duración antes de GCS/modelo. MIME no autoritativo.
- GCS en inferencia: timeout SDK de 60 s por intento y `retry=None`, no deadline total de transferencia; comportamiento de otros callers conservado.
- Medición por etapas con identificador interno, duración y categoría de resultado, sin audio, rutas privadas, credenciales ni excepciones brutas.
- Backend: presupuesto asíncrono blando de 270 s en `POST /api/predict`. Proxy: 300000 ms para todos los rewrites HTTP externos, no deadline global del servidor ni cambio de rutas locales/API Next o WebSocket. Cancelar la espera no mata hilos; no hay garantía nueva de shutdown.
- **Fuera de alcance:** login, autenticación, autorización y rate limit por usuario (responsabilidad del compañero), infraestructura de jobs/colas, modificaciones del firewall o publicación de puertos, despliegue, audio real, GCS y BD reales, push y commits nuevos no solicitados explícitamente.
- Rama: `fix/limite-audio-inferencia`. Preservar cambios externos `.gitignore`, `docs/KANBAN.md`, `docs/KANBAN_VISUAL.md`. No modificar index/HEAD durante coordinación con la otra sesión.

## Tareas

- [x] BEXEC-1 — Admisión y predictor no bloqueante con ownership del trabajo/temporal; RED/GREEN observado y verificación independiente: 15 aprobadas. Sin commit nuevo autorizado; los límites del alcance se detallan abajo.
- [x] BEXEC-2 — Límite efectivo de cuerpo, WAV real y duración máxima de 5 minutos; RED/GREEN observado y verificación independiente: 40 aprobadas. Cierre funcional sin commit ni despliegue; revisión nativa del corte BEXEC-1/2 aprobada y reconocida.
- [x] BEXEC-3 — GCS opt-in, ownership y timings: 63 pruebas aprobadas por escritor y verificador independiente. Regresiones adicionales de feedback pendientes de BEXEC-5; revisión nativa del nuevo corte pendiente.
- [x] BEXEC-4 — Espera backend/proxy y prueba lenta verificadas: 70 backend y 1 proxy aprobados por escritor y verificador independiente. Runtime construido/navegador pendientes de BEXEC-5.
- [x] BEXEC-5 — Verificación funcional completada: 97 backend, 43 frontend enfocados, build/TypeScript, proxy lento, cinco casos UI y endpoint multipart real 100 MiB. Suite completa frontend: 234 pasan / 1 fallo preexistente de IngestionSync fuera de alcance; no se declara verde. Sin inferencia real ni commit nuevo.
- [x] BEXEC-6 — Documentación consolidada; revisión nativa completa aprobada y reconocida (`review-4a2c7479079f5355`), más control independiente conservador: 70 pruebas enfocadas aprobadas. Commits/despliegue pendientes de autorización separada.

## Verificación y evidencia

La evidencia válida actual usa HTTP/ASGI y dependencias externas simuladas, sin inferencia real ni startup de modelos/servicios reales. El intento contaminado descrito en el historial activó modelos reales y queda expresamente invalidado. Los RED/GREEN corresponden a cambios de comportamiento; las comprobaciones funcionales posteriores no inventan un RED. Los tests de umbral reducido no prueban transporte de tamaño real; la matriz superior distingue consumidor middleware, UI y endpoint multipart.

El antecedente de inferencia tiene 38 pruebas frontend enfocadas y 22 backend aprobadas, build/proxy/Chromium aprobados. La suite frontend completa mantiene un fallo preexistente en `IngestionSync.test.tsx:39` (`Feedback #7`), fuera de este alcance; no declararla verde ni corregirla sin autorización.

No se escribió código de esta etapa antes de definir la duración máxima. La evidencia acotada de BEXEC-1 se registra debajo; revisión y cierre del checklist siguen a cargo del orquestador.

## Riesgos residuales

Los controles de recursos no reemplazan autenticación. El límite de concurrencia por proceso no es un límite global de múltiples workers/réplicas. Un timeout de transporte no cancela por sí solo GCS o PyTorch, ni garantiza rollback de objetos externos. Documentar resultados tardíos y limpieza real sin inventar garantías.

## Historial de implementación y verificación

**Lectura del historial:** las secciones siguientes conservan resultados, RED/GREEN, incidentes y pendientes tal como correspondían a cada corte. Las referencias a «pendiente», «en curso», «bloqueada» o «siguiente unidad» describen ese momento, no el estado actual. La matriz superior y el checklist son la referencia vigente; los detalles finales de UI y endpoint documentan las repeticiones válidas. La incertidumbre sobre efectos externos del incidente anterior y la prohibición de borrar su perfil residual siguen vigentes.

### Evidencia observada de BEXEC-1

Contrato implementado: una solicitud admitida por proceso, sin cola; saturación 503 con `Retry-After: 5`. El predictor síncrono trabaja en el executor y conserva cupo y temporal hasta salir de su `finally`, aunque se cancele la espera HTTP. La sesión DB no se pasa al hilo. Véase [ADR 0021](../adr/0021-ejecucion-acotada-inferencia.md).

Desde `backend`, comando único repetido por transición:

```sh
DATABASE_URL=sqlite:// ../.venv/bin/python -m pytest -p no:cacheprovider tests/test_prediction_audio_metadata.py tests/test_inference_execution.py
```

| Transición | Resultado observado |
| --- | --- |
| Preparación | Error de colección: `httpx` ausente. Se reemplazó por cliente ASGI directo, sin instalar dependencias. |
| RED 1 | 9 pasan, 1 falla: el predictor bloqueaba el event loop (`prediction blocked the event loop`). |
| GREEN 1 | 10 pasan: health responde, otra predicción se rechaza y luego vuelve a admitirse. |
| RED 2 | 10 pasan, 1 falla: al cancelar el request, el cupo quedaba libre; segunda solicitud devolvía 500 en lugar de 503. |
| GREEN 2 | 11 pasan: referencia del worker conserva cupo e input tras cancelación. |
| Triangulación y limpieza | 15 pasan (última ejecución: 1,13 s): fallo tardío, errores 400/503/500, limpieza de temporales y admisión posterior entre loops. |

En cada ejecución aparecen advertencias de `sys.prefix` y `sys.exec_prefix` por la ruta `backend/../.venv`. Colección aislada mediante allowlist explícita, SQLite y adapters externos simulados; no se ejecutó lifespan, modelos, GCS ni BD reales. Las esperas de eventos incluyen watchdogs para no colgar la prueba; no constituyen deadlines productivos. Los errores/limpieza se triangularon sobre el ownership ya implementado, sin atribuirles un RED independiente.

**Límites:** la subida GCS async existente aún puede dejar su hilo vivo al cancelarse, sin retener este cupo; BEXEC-3 debe resolverlo. No hay garantía nueva de shutdown: no se mata PyTorch, el cierre ordenado depende del servidor/executor y el cierre abrupto puede dejar archivos. El spool previo, WAV/duración, presupuestos, latencia real y proxy siguen pendientes. Ninguna prueba de lifespan fue simulada como aprobada.

**Rollback acotado:** revertir únicamente la integración de `main.py`, el módulo `inference_execution.py`, sus pruebas/allowlist y documentación BEXEC-1 mediante el flujo autorizado del orquestador. No tocar auth, contratos de metadatos, cambios del compañero ni index/HEAD. No se ejecutó rollback ni se cambió el checklist.

### Transición histórica después de BEXEC-1/2

En ese corte el usuario autorizó BEXEC-3: timeout GCS opt-in de 60 s por intento, sin retries del SDK en inferencia; conservar el cupo mientras la subida real trabaje y registrar tiempos sanitizados. Esa implementación y las comprobaciones BEXEC-4/5 ya se completaron; no es el próximo paso actual. Se mantienen los límites: no es deadline total de transferencia y no se autorizan commits nuevos, autenticación ni despliegue.


### Verificación independiente de BEXEC-1

Desde `backend`, `DATABASE_URL=sqlite:// ../.venv/bin/python -m pytest -p no:cacheprovider tests/test_prediction_audio_metadata.py tests/test_inference_execution.py`: **15 aprobadas en 1,12 s**. Diff check limpio; hashes de fuente/pruebas antes y después sin drift. Avisos de prefijos del virtualenv. Primer intento del verificador desde la raíz falló por ruta relativa incorrecta; ejecución corregida a `backend/`. El escritor ejecutó el comando siete veces (preparación, dos RED, dos GREEN y dos regresiones), no seis. Sin servicios reales. No se comprobó transporte HTTP real, deadline ni shutdown: BEXEC-2/3/4 siguen pendientes, especialmente GCS y admisión previa al spool.

## Evidencia observada de BEXEC-2

El middleware adquiere el cupo antes de consumir `POST /api/predict` y cuenta bytes reales antes del spool multipart. Mantiene 110 MiB por cuerpo y 100 MiB por archivo, ambos inclusivos; rechaza exceso con un único 413 JSON sin truncar una entrada para aceptarla. `Content-Length` ausente, falso o duplicado no autoriza bytes adicionales. El handler reutiliza el lease; las llamadas directas siguen funcionando. CORS conserva errores visibles.

Antes de GCS/modelo/BD, soundfile valida contenedor WAV real, frames/rate/canales positivos y duración hasta 300 s inclusive. Un exceso produce 400 sin recorte. WAV PCM24 estéreo a 48 kHz continúa aceptado y MIME no es autoritativo. Se conserva metadata/fecha de recepción y resolución de modelo previa a la validación. El chequeo de metadatos corre fuera del event loop, con referencia propia del lease: cancelar su espera no libera el cupo mientras trabaje.

Desde `backend`, comando exacto repetido en cada transición:

```sh
DATABASE_URL=sqlite:// ../.venv/bin/python -m pytest -p no:cacheprovider tests/test_prediction_audio_metadata.py tests/test_inference_execution.py tests/test_inference_input_limits.py
```

| Transición | Resultado observado |
| --- | --- |
| RED contador | 15 pasan, 1 falla: cuerpo excesivo con header falso devolvía 200, no 413. |
| GREEN contador | 16 pasan; excepción de parser cierra spools y el middleware expone 413, no 400. |
| RED admisión temprana | 16 pasan, 1 falla: segundo request intentaba leer el cuerpo y devolvía 400, no 503. |
| GREEN admisión temprana | 17 pasan; segunda solicitud no llama `receive`, primera sigue aceptada. |
| RED WAV real | 17 pasan, 3 fallan: basura, WAV vacío y FLAC con extensión WAV alcanzaban el predictor. |
| GREEN WAV real | 20 pasan; rechazo previo a efectos externos. |
| RED duración | 22 pasan, 1 falla: 300,5 s era aceptado; 299,5 y 300 s ya pasaban. |
| GREEN duración | 23 pasan; comparación entera frames/rate sin redondeo ni recorte. |
| Triangulación | 34, luego 38, 39 y dos ejecuciones de **40 aprobadas** (última: **1,59 s**); sin fallos ni skips. |

Catorce ejecuciones del runner. Advertencias de prefijos del virtualenv iguales a BEXEC-1. Se comprobó dependencia existente `soundfile>=0.12.1` en requirements y su import/uso instalado. No se instalaron paquetes. Las pruebas anteriores usan WAV sintético válido en lugar de saltarse la validación. Conftest solo incorpora el nuevo filename al allowlist; SQLite y adapters simulados, sin lifespan/modelos/cloud reales.

La triangulación cubre límite exacto del cuerpo, headers ausentes/duplicados, bytes excesivos tras el delimitador final, spools cerrados al exceder y al desconectar parcialmente, JSON/CORS, parser vacío/malformado, cancelación antes del cuerpo con admisión posterior, frecuencia/canales cero, PCM24 estéreo y health/otras rutas no afectadas. Se mantienen seis pruebas de ownership real BEXEC-1 y nueve de límites/metadatos. No se atribuye RED independiente a los casos que ya pasaron con la implementación.

**Límites restantes:** evidencia de bytes a escala de umbral, no transporte de 100/110 MiB. La metadata no decodifica el waveform ni establece un nuevo límite de memoria decodificada: no se impusieron restricciones nuevas de codec/rate/canales. Rechazos tempranos no drenan cuerpos no consumidos; el framing/transporte real sigue por verificar. Ownership/presupuestos GCS y timings siguen en BEXEC-3; deadlines backend/proxy y shutdown siguen sin garantía nueva (BEXEC-4/5). No se afirma detener PyTorch.

**Tamaño:** incremento BEXEC-2 contra el estado inicial preservado: +432/−35 (467 líneas cambiadas, incluidos archivos nuevos). Diff completo contra HEAD, incluyendo BEXEC-1 y manual previo untracked: +708/−19 (727 líneas). Los casos deterministas explican la mayor parte del incremento; no se añadió infraestructura de jobs ni nuevas áreas de producto.

**Rollback BEXEC-2:** revertir únicamente middleware, validación de entrada, reutilización del lease, fixtures WAV/allowlist y estas ampliaciones documentales; preservar BEXEC-1, el índice documental previo, auth y cambios del compañero. El padre controla revisión, checklist y cualquier operación Git. No se ejecutó rollback.

### Verificación independiente y cierre funcional de BEXEC-2

El verificador ejecutó el mismo comando de tres suites desde `backend`: **40 aprobadas en 1,34 s**. `git diff --check` sin errores; hashes SHA-256 de los seis archivos vigilados idénticos antes/después. Dos advertencias conocidas de `sys.prefix`/`sys.exec_prefix`, sin skips ni errores del runner. No detectó un defecto concreto en la ruta candidata. Validó admisión temprana, contador ASGI y 413 único, cierre de spool, límites inclusivos, CORS, WAV/duración antes de efectos externos y ownership del worker. No realizó cambios.

El usuario pidió cerrar únicamente BEXEC-2. Queda cerrado funcionalmente con estas comprobaciones, sin afirmar transporte real de 100/110 MiB, GCS/modelos/BD/auth reales, memoria decodificada acotada, deadlines, cancelación dura ni apagado garantizado. Revisión nativa aprobada sobre el corte BEXEC-1/2, no sobre toda la rama histórica: `review-7ba32d8c47dbb57b`, tier medio y lente `review-reliability`. La captura final aprobó; el reconocimiento nativo devolvió `native-approved-acknowledgement-completed`, autoridad consumida (`burned`). Identidad congelada: `sha256:fd6f52562192f44ee68e6e4f03e4bd07d8055faf52701e9a506203859cd2b9cd`. Este registro administrativo se agregó después del reconocimiento; no se modificaron código ni pruebas después de la revisión. No se realizaron commits Git ni despliegue. Los pasos BEXEC-3 a BEXEC-6 continúan pendientes según el alcance global de cada uno.

## Evidencia observada de BEXEC-3

Inferencia mantiene el wrapper async de storage y opta por timeout SDK **60 s por intento**, con `retry=None`. El wrapper ejecuta su función síncrona mediante `lease.run`, no una coroutine en el executor; el hilo SDK conserva el cupo hasta salir realmente. Cancelar durante esa subida no inicia predicción ni persistencia tardías. Los callers sin opciones siguen con cuatro argumentos posicionales y defaults anteriores. No hay deadline total de transferencia ni timeout HTTP nuevo.

Comando exacto desde `backend`, ejecutado nueve veces:

```sh
DATABASE_URL=sqlite:// ../.venv/bin/python -m pytest -p no:cacheprovider tests/test_prediction_audio_metadata.py tests/test_inference_execution.py tests/test_inference_input_limits.py tests/test_storage.py tests/test_inference_storage_timing.py
```

| Transición | Resultado observado |
| --- | --- |
| RED opciones SDK | 56 pasan, 1 falla: wrapper async no aceptaba `timeout`. |
| GREEN opciones | 57 pasan; propagación timeout/retry y fake legacy estricto de cuatro argumentos. |
| RED ownership GCS | 57 pasan, 2 fallan: después de cancelar la subida real, otra solicitud devolvía 200, no 503. |
| GREEN ownership | 59 pasan; bloqueo con eventos en fake SDK, fin/fallo tardío, health responsivo y admisión posterior, sin predicción/BD tardías. |
| RED timings | 59 pasan, 1 falla: no había eventos de etapas. |
| GREEN timings | 60 pasan; siete etapas con ID opaco, esquema fijo y fin de worker diferenciado. |
| RED privacidad | 59 pasan, 2 fallan: detalle HTTP exponía excepción GCS y Python 3.14 registraba excepción/traceback tardíos de `shield`. |
| GREEN privacidad | 61 pasan; respuesta GCS genérica y resultado/error encapsulado hasta el waiter activo. |
| Triangulación final | **63 aprobadas en 1,49 s**, sin fallos ni skips; runner custom recibe función sync y solo kwargs opt-in. |

Las 40 pruebas previas siguen aprobadas; se ejecutaron 19 de storage y cuatro casos nuevos de ownership/timings. Suite storage inspeccionada antes del runner: todos sus clientes son fakes. Conftest solo agregó filenames al allowlist; SQLite, audio sintético y SDK externo simulado. Sin lifespan, modelos ni cloud/BD reales. Advertencias conocidas de prefijos del virtualenv.

**Mediciones:** `ingress` va desde admisión hasta entrega del último chunk al parser (o interrupción); no mide toda la decodificación multipart. `read` mide lectura del upload ya parseado. `validation`, `upload` y `predict` miden ejecución real del worker, sin incluir espera del executor, y solo entonces emiten `worker_finished=true`. `persist` mide transacción en el handler; `total` mide espera ASGI de solicitudes admitidas, o desde adquisición del cupo para llamadas directas. Los eventos INFO contienen únicamente ID UUID interno, etapa fija, duración, categoría y flag de fin real; no excepciones, rutas, audio ni IDs privados. Al cancelar, total puede finalizar antes de upload. No se mide latencia real de servicios ni se afirma DB completamente no bloqueante.

**Hallazgo verificado:** el sync uploader actual no imprime excepciones (a diferencia del antecedente del plan); se mantuvo intacto. La fuga tardía vino de `asyncio.shield` en Python 3.14, comprobada mediante RED y fuente stdlib. El envelope evita poner errores de trabajo en el future; no instala un handler global ni altera el contrato legacy de errores de storage.

**Riesgos pendientes:** 60 s es timeout del SDK por intento/operación, no presupuesto wall-clock de todo el upload. GCS puede completar y dejar un objeto después de cancelar; no hay rollback. Permanecen detalles HTTP crudos preexistentes de errores de predictor/BD, fuera de esta sanitización acotada, y no se garantiza controlar logging de terceros. Deadlines backend/proxy, transporte real, recursos decodificados y shutdown siguen en BEXEC-4/5; no se mata PyTorch. No se ejecutaron suites adicionales de feedback fuera del runner autorizado.

**Tamaño:** incremento BEXEC-3 +343/−42 (385 líneas cambiadas, incluidos nuevos archivos). Diff completo contra HEAD con BEXEC-1/2 y documentos previos: +1047/−51 (1098 líneas). No se modificó el índice documental previo ni archivos fuera de la superficie autorizada.

**Rollback BEXEC-3:** retirar solo opciones/runner de storage, ownership y timings de esta unidad, pruebas/allowlist y ampliaciones documentales; preservar BEXEC-1/2 y contratos legacy, auth, índice y cambios externos. El padre controla checklist, revisión y Git; no se realizó rollback ni commit.


### Incidente de verificación independiente de BEXEC-3

El primer verificador no logró ejecutar el runner: `../.venv/bin/python: No such file or directory` (código 127). No equivale a fallo de las pruebas ni confirma las 63 aprobadas del escritor. Diff check y hashes sin cambios, pero la ejecución independiente queda pendiente. Se inició diagnóstico read-only de cwd, ruta absoluta y symlinks antes de repetir el comando con `cd` e intérprete absoluto en la misma invocación. No se instaló ni recreó ningún entorno. BEXEC-3 permanece en curso; no se inicia BEXEC-4 hasta contar con evidencia independiente.


### Verificación independiente de BEXEC-3 y transición a BEXEC-4

Incidente resuelto: la herramienta inició desde la raíz y la ruta relativa apuntaba fuera del proyecto. El intérprete del proyecto existe y resuelve a Python 3.14; no se instaló ni reparó ningún entorno. Desde `backend`, con ruta absoluta del intérprete y `cd` en la misma invocación, las cinco suites autorizadas dieron **63 aprobadas en 1,58 s**, sin skips. Diff check limpio y hashes sin cambios. Sin defectos concretos en el alcance verificado. Feedback adicional y servicios reales no fueron ejecutados.

Siguiente unidad autorizada: presupuesto asíncrono backend de 270 s para `POST /api/predict` y timeout proxy de 300000 ms para rewrites HTTP externos. El presupuesto backend es blando ante código DB síncrono; el timeout proxy no es un deadline wall-clock global ni afecta rutas locales Next/WebSocket. Prueba con backend falso que tarda 35 s: comparar el valor por defecto de 30 s contra la configuración explícita. Mantener cupo ocupado hasta terminar físicamente GCS/predictor después de vencer la espera. Sin commits, despliegue ni POST al backend real.

## Evidencia observada de BEXEC-4

Se aplica presupuesto asíncrono **270 s** exclusivamente a `POST /api/predict` admitido, desde antes del parser hasta terminar la respuesta. Al vencer cancela la espera y devuelve 504 JSON con CORS solo si no comenzaron headers; después de headers aborta sin iniciar segunda respuesta. Cancelación externa permanece cancelación. Lease y temporal continúan hasta terminar físicamente el worker. Es un presupuesto cooperativo **blando**, no SLA global: DB síncrona puede impedir su ejecución puntual; llamadas directas al handler no pasan por este middleware.

Starlette instalado captura `BaseException` en `MultiPartParser.parse` y cierra spools al cancelar. La prueba de multipart parcial confirmó archivo cerrado; no se añadieron hooks privados ni cleanup global. Se registra categoría segura `timeout` en total/ingress; fin real de upload/predict no se adelanta al 504.

Backend, cuatro ejecuciones exactas:

```sh
cd /home/kevin/Work/fama/backend && DATABASE_URL=sqlite:// /home/kevin/Work/fama/.venv/bin/python -m pytest -p no:cacheprovider tests/test_prediction_audio_metadata.py tests/test_inference_execution.py tests/test_inference_input_limits.py tests/test_storage.py tests/test_inference_storage_timing.py tests/test_inference_deadlines.py
```

- RED: **63 pasan, 1 falla**; multipart parcial seguía esperando y el watchdog externo terminaba con TimeoutError, sin 504.
- GREEN mínimo: **64 pasan**; 504 único con CORS, cierre de spool y readmisión.
- Triangulación: **68 pasan**, después **70 aprobadas en 2,05 s**, sin skips ni warnings del runner absoluto. Siete casos nuevos: multipart parcial; workers de validación, SDK upload y predictor retenidos después de 504; cancelación externa diferenciada; expiry después de headers sin segundo status; otras rutas fuera del budget. Workers con eventos/watchdogs, no inferencia real. No se atribuye RED independiente a los casos ya aprobados con el ownership anterior.

Frontend configura `experimental.proxyTimeout: 300000` junto al buffer de 110 MiB. La fuente instalada de Next en `router-server.js:417` pasa ese valor al helper para destinos HTTP externos; la rama WebSocket (`:728`) no lo pasa. Afecta todos los rewrites HTTP externos (incluido `/api/other`), no solo `/api/predict`; no cambia rutas locales Next ni crea deadline global.

Frontend, dos ejecuciones exactas:

```sh
cd /home/kevin/Work/fama/frontend && node --test tests/proxy-timeout.test.mjs
```

- RED real: **0 pasan, 1 falla**, ~30,08 s: config sin timeout hacía que los dos destinos configurados devolvieran 500 en lugar de 200; control default también abortó.
- GREEN real: **1 aprobada**, ~35,04 s (runner ~35,14 s). Backend falso loopback retrasó realmente 35 s; control default terminó alrededor de 30 s con 500/ECONNRESET, destinos `/api/predict` y `/api/other` entregaron la respuesta completa después de 35 s. Payload WAV sintético pequeño. Loader de config y helper proxy instalados, sin duplicar la constante. Sockets/timers/servidores propios cerrados en finally; watchdogs 80/95 s.
- Salida esperada del helper para control negativo: `Failed to proxy ... ECONNRESET`; aviso Node DEP0169 por `url.parse`, empleado por el helper instalado.

**Límites:** prueba de helper/config reales, no servidor Next construido ni navegador: propagación en build/runtime completo queda BEXEC-5. Ningún POST al backend real; no cloud/BD/modelos/lifespan. Timeout SDK de 60 s sigue sin garantizar transferencia total; posible objeto GCS tardío sin rollback, errores HTTP crudos preexistentes fuera de GCS, memoria decodificada y shutdown pendientes. No se matan hilos. Diff check aprobado; checklist/revisión independientes a cargo del padre.

**Tamaño:** incremento BEXEC-4 +327/−8 (335 líneas cambiadas, incluidos archivos nuevos). Diff completo contra HEAD con unidades/documentos previos: +1378/−51 (1429 líneas). Solo backend, proxy y documentación previstos; sin tercera área nueva.

**Rollback BEXEC-4:** retirar únicamente presupuesto/504/categoría timeout, configuración proxy, tests/allowlist y estas ampliaciones documentales; preservar contador/admisión y ownership BEXEC-1/2/3, auth y cambios externos. No se ejecutaron rollback, commits, index/HEAD ni despliegue.


### Verificación independiente de BEXEC-4

Las seis suites backend: **70/70 aprobadas en 2,09 s**. Prueba Node con loader/helper reales de Next y backend falso loopback: **1/1 aprobada en 35,14 s**; ambas rutas configuradas respondieron 200 a ~35 s y el control por defecto abortó a ~30 s. Avisos esperados DEP0169 y ECONNRESET del control negativo. Diff check limpio y hashes sin drift. No hubo servicios reales ni cambios del verificador. Servidor Next construido, navegador y regresiones adicionales pasan a BEXEC-5; no se certifican latencia DB real, rollback GCS ni apagado con trabajo activo.


### Bloqueador BEXEC-5A: separación de runners

Backend aislado y regresiones de feedback: **97 aprobadas en 2,54 s**. Frontend enfocado: **43 aprobadas en 2,18 s**. Suite completa: 19 archivos aprobados y 2 fallidos; 234 tests aprobados y 1 fallido. Además del fallo preexistente `IngestionSync` (`Feedback #7`), Vitest recolectó la prueba Node `tests/proxy-timeout.test.mjs` y falló con `No test suite found`. Regresión candidata: separar exclusivamente esa prueba del discovery de Vitest sin deshabilitarla en Node ni ocultar otros tests. Build/TypeScript se detuvieron antes de ejecutar; Chromium disponible, sin Playwright/Puppeteer resueltos. BEXEC-5 continúa en curso.

### Corrección acotada BEXEC-5: separación de runners

Se reutilizó el RED observado por BEXEC-5A: 19 archivos aprobados, 2 fallidos; 234 tests aprobados y 1 fallido, con `No test suite found` al recolectar la prueba Node. No se produjo ni se atribuye otro RED. `vitest.config.mts` conserva globals/jsdom y las exclusiones predeterminadas mediante `configDefaults.exclude`; agrega exclusivamente `tests/proxy-timeout.test.mjs`. No se cambió el harness Node ni se excluyeron carpetas completas.

Comandos exactos y resultados de esta corrección:

```sh
set -o pipefail; cd /home/kevin/Work/fama/frontend && npm test -- --reporter=dot 2>&1 | tail -n 65
cd /home/kevin/Work/fama/frontend && node --test tests/proxy-timeout.test.mjs
git diff --check -- frontend/vitest.config.mts docs/manuales/ejecucion_acotada_inferencia.md
```

- Vitest: exit 1, **19 archivos aprobados y 1 fallido; 234 tests aprobados y 1 fallido**, duración **4,92 s**. Desapareció el fallo nuevo de colección Node; permanece exclusivamente `IngestionSync.test.tsx:39` (`Feedback #7`), preexistente y sin corregir. La suite completa **no está verde**.
- Node explícito: exit 0, **1 aprobada**, sin skips/cancelaciones; test **35057,22 ms**, runner **35147,15 ms**. Backend falso loopback, respuesta real tras 35 s y control negativo por defecto; avisos esperados DEP0169 y ECONNRESET. La prueba no está deshabilitada. Sin servicios reales.
- Diff check: sin errores. Build/TypeScript y verificación independiente quedan al siguiente verificador; checklist y revisión pertenecen al padre.

**Tamaño:** configuración +2/−1 (3 líneas cambiadas); documentación agregada únicamente en esta sección. Dos rutas modificadas por esta unidad; los cambios previos permanecen intactos.

**Rollback acotado:** retirar únicamente la importación de `configDefaults`, la exclusión exacta y esta sección documental mediante el flujo autorizado del padre. Preservar prueba Node, configuración proxy, cambios anteriores y fallo IngestionSync. No se ejecutó rollback, commit, modificación de index/HEAD ni despliegue.


### BEXEC-5A independiente: runners y build

Backend previo válido: 97 aprobadas en 2,54 s, sin cambios backend posteriores. Frontend enfocado: 43 aprobadas en 2,39 s. Suite completa: 234 aprobadas y 1 fallida, exclusivamente `IngestionSync.test.tsx:39` (`Feedback #7`), archivo sin diff; no fallo de colección de la prueba Node. Node explícito: 1 aprobada con espera real de 35,048 s. Advertencias del control negativo y DEP0169 esperadas.

Build aprobado con `NEXT_TELEMETRY_DISABLED=1 API_URL=http://127.0.0.1:49173 npm run build`; TypeScript adicional `npx --no-install tsc --noEmit` aprobado. Build ID `aqhIFgT0DZzQZGFkgfdok`. Ambos snapshots principal/standalone incluyen `proxyTimeout: 300000` y `proxyClientMaxBodySize: 115343360`; routes-manifest confirma rewrite a backend falso loopback. Diff check limpio. Sin cambios fuente por el verificador. Runtime, Chromium y transporte de tamaño real continúan en BEXEC-5B; build/config no equivalen a prueba runtime.


### Incidente de aislamiento BEXEC-5B — cierre bloqueado

El verificador informó que utilizó `with TestClient(main.app)` para un chequeo de tamaño real y activó el lifespan de producción, que registró carga de tres modelos checkpoint reales. Esto viola la restricción explícita de no startup/modelos reales. El resultado reportado 200 para 100 MiB y 413 para 100 MiB+1 **no se admite como verificación aislada válida**. No implica por sí solo que haya habido inferencia real, GCS o BD de producción: esos efectos permanecen por comprobar en el informe de incidente, sin presumir su ausencia.

Se detuvieron nuevas pruebas backend y el avance a cierre/revisión final. El proceso de prueba y su directorio temporal fueron reportados como finalizados/limpios; falta confirmar inventario de los demás recursos propios, posibles efectos persistentes y evidencia runtime/browser previa separada de este paso. No se autoriza limpieza de recursos ajenos, borrado de artefactos persistentes ni rerun automático del caso. BEXEC-5 permanece bloqueada y BEXEC-6 pendiente.


### Informe final del incidente BEXEC-5B

El verificador reportó que los procesos Next/backend falso/Chromium/Python finalizaron y el puerto loopback 49173 quedó libre. Resta el perfil temporal propio `/tmp/tmp.PA5i1UO7QC/chrome`; su limpieza falló y no se intentó borrarlo nuevamente. No hubo limpieza de artefactos del repositorio.

El harness usó `DATABASE_URL=sqlite://`, desactivó carga dotenv durante importación, reemplazó la dependencia DB por SQLite en memoria y simuló registro/predictor/upload/status ensemble. El request aceptado utilizó predictor y upload falsos. Sin embargo, `with TestClient(main.app)` activó startup global: tres checkpoints CPU cargados, intento de seed (tabla `usuario` ausente) y worker feedback con error `database_or_local_unavailable`. Los overrides del request no sustituyen los servicios globales de startup. Lectura read-only posterior confirma que el worker puede subir audio local pendiente; el mensaje de fallo no establece si hubo actividad externa previa. No se observaron efectos GCS/BD de producción ni escrituras del repositorio, pero no se certifica ausencia absoluta de efectos externos. Hashes exactos de contenido no se registraron en 5B.

Evidencia separada reportada: servidor Next construido sobre loopback recibió respuesta falsa a los 35,010 s; Chromium recibió 200 falso a los 35,034 s. El cuerpo exacto de 110 MiB llegó al backend falso como 115343360 bytes; 110 MiB+1 fue truncado por Next y abortado (115302878 bytes observados), sin respuesta al cliente acotado: **no es prueba de 413 del backend**. Chromium intentó registro Google GCM pese a flags contra networking; no se verificó interacción externa exitosa. No se admite como ejecución estrictamente restringida a loopback.

Pendientes: tamaños reales backend bajo aislamiento válido, guard de archivo sobredimensionado en UI y estados de error de navegador. No se hicieron esas últimas pruebas ni screenshots. Para reanudar se requiere un plan de aislamiento fail-closed: cliente raw ASGI sin lifespan, singleton simulado antes de importación y navegador con bloqueo efectivo de tráfico externo (o declarar la prueba no disponible). No se repite el harness contaminado ni se autoriza borrado automático del perfil residual. BEXEC-5/6 permanecen sin cierre.


### Autorización de reanudación aislada

El usuario autorizó repetir únicamente las verificaciones pendientes bajo el aislamiento corregido propuesto. No autoriza borrar el perfil residual, commits ni despliegue. Backend mediante cliente HTTP ASGI raw sin lifespan y barreras fail-closed antes de importación: startup, carga real de modelos y servicios externos deben abortar si se invocan. No repetir el harness contaminado. Navegador solo si se establece bloqueo efectivo de tráfico externo antes de lanzarlo; flags/CDP por sí solos no prueban aislamiento de procesos de fondo. Si no hay aislamiento disponible sin cambios del sistema ni instalación, declarar navegador pendiente y no ejecutarlo.


### Preflight corregido y diseño de harness temporal

El verificador nuevo se detuvo antes de importar `app.main`; no ejecutó pruebas ni navegador. Los fixtures existentes simulan adaptadores después de importación y no sirven como barrera fail-closed previa. No se interpreta esto como imposibilidad de construir un harness independiente. Exploración read-only identificó imports ML transitivos (`ml_core`/`poc`), singleton training con creación de directorio y DB con dotenv/engine import-time.

Se separará la prueba real del contador de 110 MiB (middleware y lease reales, consumidor ASGI controlado, sin importar main) de la prueba del endpoint público de 100 MiB (stubs de módulos ML/training/DB previos a importar main, DB SQLite en memoria, callbacks externos que abortan, sin lifespan). Los nombres exportados y constructores globales se comprobarán en fuente actual antes de ejecutar; no se acepta un mock que permita startup silenciosamente. Son harnesses temporales de verificación, no refactor de producción. La disponibilidad de aislamiento de red del navegador permanece desconocida; no se lo lanza sin demostrarla.


### Repetición aislada: prueba A parcial

Con imports limitados a `InferenceLimits` e `InferenceExecution`, un consumidor ASGI controlado recibió **115343360 bytes** y respondió 200; con **115343361 bytes**, el middleware respondió 413 antes del efecto simulado (0 efectos). Hashes de ambos módulos idénticos antes/después. Esto valida el contador real, no el endpoint multipart ni el límite de archivo de 100 MiB. El intento inicial sin `PYTHONPATH=backend` falló antes de ejecutar (`ModuleNotFoundError: app`); el comando corregido sí produjo los resultados. No se importó main ni se inició navegador/modelos/cloud.

`unshare -n true` fue denegado (exit 1, `Operation not permitted`). `bwrap` existe, pero aún no se evaluó; no se declara imposibilidad definitiva de aislamiento. Sigue pendiente una barrera pre-import válida para el endpoint y la evaluación acotada de bwrap, sin instalaciones, sudo ni cambios del sistema. El guard del archivo en UI y estados de error continúan pendientes.


### Barrera de importación del endpoint y red aislada

El verificador no importó main: su constructor global `SuperEnsembleService` consulta `torch.cuda.is_available()` y crea `torch.device` durante importación. Bajo la restricción aplicada, aún no hay sustitución pre-import demostrada y el endpoint de 100 MiB sigue pendiente. No se confunde inicialización de dispositivo con predicción real, ni se permite ejecutar el constructor sin barreras.

El preflight bwrap **sí pasó**: namespace de usuario/red sin privilegios, root read-only y `/proc`/`/dev` aislados; tabla de rutas vacía, conexión de control a TEST-NET devolvió 101 (`ENETUNREACH`), exit 0. No se inició navegador durante el preflight. Se continúa exclusivamente con UI mediante Chromium, Next construido y backend falso dentro del mismo namespace, sin fallback a red del host ni instalación/cambios del sistema. El endpoint permanece pendiente por separado.


### Corrección de routing para ejecución UI

El rol verify completó únicamente preflight: loopback bind funciona dentro de bwrap y tráfico TEST-NET falla con ENETUNREACH. **No ejecutó UI**, porque sus restricciones read-only impiden crear perfil/harness temporal. Esto es una limitación del rol asignado, no del aislamiento probado. El orquestador corrige el routing a un worker acotado para recursos temporales propios ya autorizados: únicamente `frontend/.bexec5b-runtime/**` y `backend/.bexec5b-runtime/**`, con limpieza de archivos nuevos al finalizar y sin modificar código/config/tests existentes. No hay Agent nativo disponible. Los recursos de aplicación y Chromium deben permanecer en el mismo namespace; no se autoriza fallback de red ni cambio de producción. El endpoint de 100 MiB sigue pendiente, fuera de esta ejecución UI.


### Arranque UI aislado: bloqueo de sockets temporales

El worker temporal comprobó red aislada y arrancó Next construido/backend falso dentro del namespace. Chromium falló antes de CDP: `Failed to create socket directory` y `Failed to create a ProcessSingleton for your profile directory`; el root read-only no provee OS-temp escribible aunque el perfil esté montado. **Cero casos UI ejecutados**. Se limpiaron únicamente los archivos temporales propios, sin residuos de ese harness; status idéntico, diff check limpio y hashes de main/next.config/vitest.config sin cambios.

Repetición acotada: montar `/tmp` como tmpfs privado del sandbox y fijar TMPDIR/XDG_RUNTIME_DIR/HOME/config/cache a directorios nuevos dentro de ese tmpfs. No expone el `/tmp` del host ni modifica el perfil residual anterior. Mantener user/net namespace, proyecto read-only y preflight de rutas externas bloqueadas. No se instala software ni cambia producción; si aparece otro bloqueo concreto se reporta sin afirmar UI aprobada.


### Error de cwd del driver UI

La repetición con tmpfs privado pasó aislamiento y arrancó Next, pero el driver buscó `.next/BUILD_ID` desde la raíz; falló con ENOENT antes de Chromium. No es fallo de aplicación y no produjo resultados UI. Recursos propios limpiados, status idéntico y hashes de main/next.config/vitest.config sin cambios. Se corrige el driver a rutas absolutas, comprobadas antes de iniciar hijos, y se mantiene sandbox/user/net/tmpfs sin cambios. BEXEC-5 sigue abierta; no se atribuye esta interrupción a una limitación del producto.


### Chromium y navegación aprobados; catálogo pendiente por URL compilada

Tmpfs privado resolvió sockets/perfil: CDP conectó, UI construida cargó y navegación Dashboard → Predicción funcionó. El bundle `aqhIFgT0DZzQZGFkgfdok` intentó catálogo/hardware/feedback a `http://localhost:8000`; listener falso estaba en 49173 y no recibió solicitudes. UI mostró catálogo no disponible; **ningún caso de predicción se ejecutó**, 0 POSTs totales no equivalen a guard oversize probado. `frontend/lib/api.ts` usa NEXT_PUBLIC_API_URL cuando existe; no se modificó esa configuración.

Corrección únicamente de routing temporal: listener falso 8000 dentro del mismo namespace, con CORS para el origen de la UI; 49173 permanece como destino del rewrite. Prueba UI contra 8000 no se atribuirá al rewrite de Next. No hay cambios de fuente ni rebuild. Red externa bloqueada pre/post, cleanup propio completo y hashes main/next.config/vitest.config idénticos en el intento anterior.


### UI real: cinco casos aprobados con API falsa directa

Chromium/CDP ejecutó el build existente dentro de bwrap sin rutas externas; TEST-NET devolvió ENETUNREACH antes y después. Dashboard → Predicción seleccionó el fixture sintético `machine-model`. Backend falso directo en puerto 8000, CORS del origen propio; **no es prueba de rewrite ni de inferencia real**.

| Caso | Resultado visible | POSTs por caso | Tiempo |
| --- | --- | --- | --- |
| WAV sparse 104857601 bytes | Error de límite de 100 MiB (104857600 bytes) | 0 | 181 ms |
| WAV pequeño sintético | `alarm`, `90.00%`, controles de validación | 1 | 314 ms |
| HTTP 500 no JSON | Error HTTP 500, sin error de parseo JSON | 1 | 273 ms |
| HTTP 503 JSON, Retry-After: 2 | `Synthetic capacity exhausted.` | 1 | 269 ms |
| HTTP 504 JSON | `Synthetic inference deadline exceeded.` | 1 | 266 ms |

Contadores reiniciados por caso; ningún POST de predicción en 49173. No se afirma countdown ni retry automático para 503. Un error de escape de selector del driver se corrigió antes de la ejecución exitosa. Hashes de main/next.config/vitest.config y status idénticos, diff --check aprobado; hijos propios terminados, tmpfs expirado y harness nuevo eliminado. BEXEC-5 sigue abierta por comprobación aislada del endpoint multipart de 100 MiB; BEXEC-6 pendiente.


### Endpoint real: límite inclusivo 100 MiB aprobado en aislamiento

ASGI directo de `/api/predict`, sin TestClient ni lifespan. WAV sintético PCM16 estéreo 96 kHz, duración 273.066552 s. Multipart transmitido en chunks de hasta 1 MiB, 103 llamadas receive por caso.

| Archivo | Multipart | HTTP | Predictor / upload / add / commit | Delta filas SQLite | Tiempo |
| --- | --- | --- | --- | --- | --- |
| 104857600 bytes | 104857718 bytes | 200, Chucao, confianza 0.9, db_id 1 | 1 / 1 / 1 / 1 | +1 | 213 ms |
| 104857601 bytes | 104857719 bytes | 413, error de límite de 100 MiB | 0 / 0 / 0 / 0 | 0 | 144 ms |

Una única respuesta HTTP por caso, JSON y CORS con origen enviado. Antes de importar main se inyectaron torch/nn inertes, ML/training/dataset, servicios cloud-facing, router auth falso, registry/predictor y módulo de BD con SQLite en memoria. Finder fail-closed de imports riesgosos, guard de archivos checkpoints/.env y guard de conexiones después del import. Llamadas prohibidas observadas: 0; lifespan/startup: 0; CUDA/device falsos: 1 cada uno. El texto PostgreSQL del log de create_all es hardcoded, no describe el engine inyectado.

Todos los procesos dentro de bwrap user/net namespace, raíz read-only, tmpfs privado. Sin rutas externas; TEST-NET ENETUNREACH antes/después. Hashes main/next.config/vitest.config y status idénticos, diff --check aprobado. SQLite cerrada y harness temporal propio eliminado. Prueba parsing, límites, metadata y respuestas reales con adapters simulados, **no integración de modelos/GCS/BD productivos**. Esta prueba sustituye como evidencia aislada al intento previo contaminado; no elimina el registro del incidente anterior.


### Cierre de BEXEC-6

Revisión nativa `review-4a2c7479079f5355`: riesgo medio, lente `review-reliability`, 18 archivos y 1589 líneas cambiadas. Snapshot `sha256:2341084b7d597358c72ccbb82d894814d0fbf61501ebef35c2fde43a95683456`, árbol `1ca52f6e3e9ad42916702d450cc1f16160c66278`. Resultado approved y reconocimiento `native-approved-acknowledgement-completed`, autoridad burned; no se requirió corrección. Ningún commit Git ni despliegue realizado.

El assessment posterior fue unassessable por declaración de untracked y devolvió una ruta conservadora de verificación independiente. El verificador inspeccionó fixtures antes de ejecutar seis suites existentes bajo bwrap, red aislada, raíz read-only, tmpfs privado, SQLite y sin bytecode/cache: metadata, execution, input limits, storage, storage timing y deadlines. Resultado: **70 aprobadas en 2,72 s**, diff --check sin errores y sin modificaciones. Es un subconjunto enfocado, no una repetición de las 97 pruebas backend ni de la suite frontend completa. Confirmó contratos y configuración del manual/ADR; no repitió UI, build o escala real previamente verificados.

La aprobación nativa es evidencia del snapshot indicado; esta anotación de cierre y actualización de estados es documentación administrativa posterior, no parte de sus bytes congelados. No cambia código ni comportamiento. Los pendientes históricos del registro no representan tareas abiertas actuales salvo exclusiones expresas. Se conserva el fallo frontend preexistente (234 pasan / 1 falla), las limitaciones de integración productiva y el incidente invalidado. Próximo paso: decisión humana sobre commits y eventual despliegue/prueba real, cada uno con autorización separada.


### Corrección posterior autorizada: IngestionSync

Después del cierre BEXEC, el usuario autorizó corregir la omisión de IDs y eligió mostrarlos **solo en el panel de sincronización**, no en la cola de curación. `FeedbackSyncPanel.tsx` ahora muestra los IDs persistidos de feedback/predicción; `IngestionView.test.tsx` comprueba ausencia de IDs en la región de la cola, presencia de ambos en sincronización y mantiene la exclusión global de UUIDs técnicos. El contrato ya estaba documentado en el manual de revisión de audios; no se cambió el backend ni auth.

RED/GREEN observado: IngestionSync pasó de 1 fallo / 6 aprobadas a 7/7; la prueba de ingesta pasó de 27/28 a 28/28 al acotar correctamente sus assertions por región. Verificación independiente final: **35/35 enfocadas en 5,30 s**, **235/235 frontend en 7,18 s** y TypeScript aprobado (`tsc --noEmit --incremental false`). Comandos ejecutados con bwrap, raíz read-only, red aislada y cache npm privada en tmpfs. Advertencia informativa de rendimiento jsdom; ninguna prueba falló. No se repitió build ni navegador para esta corrección; la evidencia funcional nueva es DOM renderizado.

Revisión nativa `review-551468b6b8114f9d` aprobada y reconocida, autoridad burned: snapshot `sha256:ad755e7d2b1c8b861614b37bf75b277f82f7b7abb77314ffb39437a2efaf3d13`, 20 archivos y 1612 líneas cambiadas (incluye BEXEC y esta corrección). El assessment previo no pudo resolver la declaración de untracked; se cumplió su ruta conservadora con verificación independiente. Las cifras históricas 234/235 se preservan como evidencia anterior, **no como fallo vigente**. Esta nota administrativa es posterior al snapshot revisado y no modifica código. Sin commits, staging ni despliegue.


### Commits autorizados posteriores al cierre

El usuario autorizó guardar los cambios anteriores antes de investigar Colilarga. Rama: fix/limite-audio-inferencia.

- e8a8f55ac36c83fbcb54127dc0c24dd8bad41b21: ejecución acotada, pruebas, proxy y documentación.
- 0d7d5af6c5dbab036943f180eb7688ab01653d38: IDs de sincronización y regresión de privacidad de la cola.

La autorización posterior sustituye la restricción histórica sobre commits para estos cambios. No autoriza push, despliegue ni ejecución de audio real. No hubo cambios de comportamiento ni nuevas ejecuciones de pruebas durante la entrega; se mantienen los resultados anteriores. Esta nota es documentación pasiva posterior a la revisión.
