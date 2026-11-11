# Presupuesto físico de importación: integración opt-in sin activación

## Estado y alcance

**T6.1 y T6.2 aceptadas; T6.3 incorpora selección común API/worker y una función
explícita para activar exclusivamente un laboratorio nuevo vacío.** La calificación
operativa, provisión SSD, locks de procesos y activación real siguen pendientes del
padre. La aceptación y la verificación independiente pertenecen al padre. No se ejecutó el ZIP real ni se inició servicio
alguno. El SSD solo recibió snapshots nuevos de fuentes públicas y artefactos
sintéticos mediante helpers del padre; no se leyeron datasets históricos ni el ZIP.

`DatasetImports(root, limits=..., storage_policy=None)` conserva el modo normal.
El opt-in conecta recepción fragmentada, preparación de intentos, manifiestos y
limpieza; no crea tablas ni activa pools. El constructor obtiene `attempt_root`
de la configuración explícita para admitir recepción antes de crear el worker.
`ImportExecution` verifica la misma raíz antes de escribir payloads. Se rechazan
el upload legacy sin reserva y las exportaciones físicas (admisión y claim), sin
incorporar ejecución de exportaciones, S76 completo, sesiones web, entrenamiento,
GCS real ni cambios a `--execution-seconds`.

## Selección común y laboratorio nuevo (T6.3, sin activación operativa)

`runtime_import_service(root, attempt_root=None)` selecciona el mismo módulo para
`get_import_service()` HTTP y el CLI de worker. Sin `FAMA_IMPORT_STORAGE_PROFILE`
conserva los límites y comportamiento existentes. Una variable vacía no equivale
a ausencia: rechaza con HTTP503 saneado; el worker sale 1 con su mensaje genérico
habitual, sin construir engine. El perfil es JSON físico absoluto, regular,
propiedad del usuario, sin enlaces ni escritura de grupo/otros y máximo 64 KiB.
Rechaza claves duplicadas, campos desconocidos y mappings incompatibles. Solo
acepta `roots`, `pools`, `free_floors` y opcional `manifest_bytes` (64 MiB por defecto).
La raíz HTTP/CLI debe coincidir con `roots.imports`; el CLI también compara su
`--staging-root` con `roots.attempts`. El builder valida los seis roles, no crea
rutas, no conecta DB, no migra, no registra pools ni modifica TMPDIR o cachés.
El rol `exports` es obligatorio para describir capacidad, **no habilita exports**.

(Histórico: `scripts.migrate_dataset_storage` ya no existe en el repositorio.) `scripts.migrate_dataset_storage.activate_empty_lab(engine, policy,
writers_stopped=True)` recibe un engine **explícito ya migrado/preparado** y una
`PhysicalStorage` de raíces previamente provisionadas. Sin el flag exacto rechaza.
Exige gate verificado, estado prepared, cero imports/datasets/jobs/grants
(incluso retirados) y cero pools. Nunca adopta un store histórico ni reactiva uno
activo. Bajo BEGIN IMMEDIATE SQLite o lock del gate PostgreSQL inserta pools/hash/
pisos y cambia prepared→active; verifica el resultado antes de commit. Cualquier
fallo revierte la transacción. `inspect_storage(engine)` permite observar el
resultado. No existe CLI nuevo, activación HTTP, engine ambiental ni creación
implícita de DB. El llamador garantiza escritores detenidos: el booleano no prueba
parada real ni reemplaza la calificación de procesos.

`backend/config/local-large-zip.sh` contiene únicamente números exportables;
no se carga automáticamente ni contiene rutas/credenciales/activación. Perfil
candidato: ZIP 6 GiB, expansión 10 GiB, WAV 96 MiB/600 s, validación 900 s,
concurrencia 1, piso 1 GiB, dataset 15 GiB/50000 archivos, chunks 16 MiB y reservas
lógicas por dueño/global 16 GiB. Requiere >=48 GiB libres y capacidad física
calificada para 26 GiB más piso. El worker mantiene default 300 s: para este ensayo
el launcher debe pasar **`--execution-seconds 900` explícitamente**.

El launcher del padre debe fijar scratch/TMPDIR y todas las cachés en SSD **antes
de iniciar Python**, además de la SQLite nueva en SSD. El mapping físico no mueve
por sí solo temporales Python, cachés o directorios privados de DB de fixtures.
Los writers pesados son recepción ZIP/objects, intentos/manifiestos y salidas del
validador; el sandbox nativo existente limpia entorno y liga salidas al intento.
No se deshabilitan sus guardas ni se añade fallback. Esta configuración no prueba
sandbox, stop fence, exclusión multiproceso ni disponibilidad física operacional.
T6.4 (prueba del ZIP real) sigue pendiente y separada de estos tests sintéticos.

## Interfaz y autoridad física

`PhysicalStorage(roots=..., pools=..., free_floors=..., manifest_bytes=64*1024**2)` inspecciona únicamente
raíces existentes, absolutas, físicas, privadas y del usuario actual. No prepara
rutas ni esquema. Exige seis roles: `imports`, `objects`, `attempts`, `manifests`,
`scratch`, `exports`. Los cuatro primeros comparten un pool; `objects` es
`imports/objects` y `manifests` coincide con `attempts`. Un mismo mount no puede
contarse dos veces bajo distintos identificadores. Se conservan las restricciones
de referencia Linux/ext4/xfs/tmpfs sin cuotas; Btrfs requiere calificación separada.

- `verify(db, service=None)` rechaza esquema ausente/incompatible, marcador no
  activo, configuración o mount diferentes y raíces del servicio incompatibles.
  Reutiliza la verificación estructural existente, con comprobaciones estrictas
  adicionales de tipos, CHECK, defaults, claves y unicidad. Si se pasa `service`,
  **debe tener `root` y `attempt_root` explícitos**, además de sus límites.
- `initial(db, service, identity, archive_bytes)` solicita archivo y doble expansión
  en un savepoint: 6 GiB + 2 × 10 GiB = **26 GiB**, además del piso configurado
  de **1 GiB** para el perfil previsto. El constructor no impone esos tamaños a
  otros perfiles; los límites públicos del servicio forman parte del hash.
- `acquire(db, resource=..., phase=..., attempt=..., token=..., amounts=..., policy=...)`
  pide importes aditivos por pool. Reintentar exactamente una autoridad viva es
  idempotente; cambiar importe/política o resucitar una retirada se rechaza.
  La suma incluye promesas cuyos bytes ya se materializaron: no se descuentan
  archivos ni se interpreta espacio libre como preasignación.
- `require(...)` comprueba importe, política, pool, recurso, fase, intento y token
  exactos vivos, incluyendo los campos persistidos, no solo su identificador hash.
- `retire(db, resource, durable_stop=True, phase=None)` exige atestación explícita
  del llamador y conserva tombstones. **El booleano no demuestra que un proceso
  murió.** La integración debe establecer primero el stop fence durable.

El llamador conserva la transacción y debe tomar los locks de propiedad física
**antes** del gate de cola, serializando admisión y retiro. El módulo no hace
commit ni adquiere esos locks. Los savepoints locales evitan concesiones parciales;
no sustituyen la serialización entre procesos ni la prueba de parada. En SQLite
legacy se inicia explícitamente la transacción antes del savepoint si el driver
aún no la inició: liberar el savepoint no debe publicar trabajo del llamador.
La sesión puede usar `autoflush=False`; las concesiones anteriores de esa misma
transacción siguen contando. Parámetros numéricos/identidades mal formados de
`acquire` producen `ValueError`; incompatibilidad de perfil o autoridad produce
HTTP503 y falta de capacidad HTTP507, ambos sin concesión parcial.

## Reproducción y evidencia histórica T6.1

El intento inicial desde el worktree Btrfs tuvo RED por módulo ausente y luego
rechazó su filesystem antes de SQLite. No se relajaron la allowlist, la guarda ni
el runner. El padre autorizó una recuperación: snapshot privado de fuentes
públicas bajo el destino SSD ext4 aprobado, con el runner existente sin cambios.
El helper pertenece al padre, no es un CLI nuevo del producto:

```sh
/home/kevin/Work/fama/.venv/bin/python /home/kevin/Work/fama/.git/agent-scratch/run_storage_budget_on_ssd.py tests/test_dataset_storage_budget.py
```

Cada ejecución conserva `snapshot-manifest.json`, `result.json`, `stdout.log` y
`stderr.log` bajo `/run/media/kevin/FAMA_P2/fama-dev-large-zip/`. Todos los nombres
de la tabla llevan el prefijo `storage-budget-check-`:

| Sufijo del snapshot | Exit | Resultado observado |
| --- | --- | --- |
| `umcz_yt8` | 0 | 1 PASS: GREEN original en ext4 |
| `2becy64f` | 0 | 2 PASS: segunda fase rechazada sin cargo de archivo |
| `1w95lq2f` | 0 | 3 PASS: suma con autoflush=False y bytes materializados |
| `zbmv3bqs` | 0 | 4 PASS: reintento y fencing público |
| `0zlsmgy0` | 1 | 4 PASS, 1 FAIL: rollback dejaba autoridad publicada |
| `17f001ts` | 0 | 5 PASS: corrección de transacción SQLite |
| `w7s4lzcf` | 0 | 7 PASS: rollback de ambos caminos y retiro |
| `aowve2y3` | 0 | 16 PASS: perfiles, esquema y constructor |
| `dsvcgtmc` | 1 | 11 PASS, 1 FAIL: token persistido incompatible era aceptado |
| `6gxx_zkw` | 0 | 17 PASS: identidad persistida verificada |
| `t_r60u6e` | 0 | 19 PASS: pool desconocido y privacidad revalidada |

Los dos RED de corrección fallaron con `Failed: DID NOT RAISE HTTPException`,
primero en rollback y después en identidad persistida. Ambos tienen GREEN
posterior. Las reglas que ya pasaban al añadir la prueba son comprobaciones
ordinarias, no RED fabricados. Las aserciones usan solicitudes públicas: las
fixtures pueden preparar estado incompatible, pero no se consultan filas de
concesiones para decidir el resultado esperado.

Cierre obligatorio, con los seis módulos ejecutados:

```sh
/home/kevin/Work/fama/.venv/bin/python /home/kevin/Work/fama/.git/agent-scratch/run_storage_budget_on_ssd.py tests/test_dataset_storage_budget.py tests/test_dataset_import_receipts.py tests/test_dataset_import_chunks.py tests/test_dataset_import_cleanup.py tests/test_dataset_import_quotas.py tests/test_dataset_import_worker_cli.py
```

Snapshot `storage-budget-check-peq90f7t`: **exit 0, 102 PASS en 18.82 s**;
19 casos de la política y 83 existentes. Sin skips, exclusiones ni deselecciones.
Stdout conserva los resultados por caso y CHECK_SUMMARY. Stderr contiene la
salida esperada de pruebas negativas del CLI: argumentos obligatorios ausentes
y `Import worker unavailable; preserve state and inspect the operation manual.`;
no representa un fallo de ejecución del cierre.

Todas las ejecuciones SSD informaron `source_unchanged=true` para las 302 fuentes
copiadas, 30 entradas protegidas intactas y scratch del runner retirado. El cierre
usó 101 conexiones SQLite en memoria; la última focal, 20. Guarda y bloqueo de
red/DB persistente activos, sin timeout ni recuperación adicional. Los snapshots
y sus logs se conservaron deliberadamente; no equivalen al scratch retirado.

## S14: identidad persistida frente a caché entre sesiones

Experimento autorizado y acotado a una regla pública con dos parámetros,
`require` y `acquire`. Una primera `Session(expire_on_commit=False)` conserva
una referencia fuerte a la concesión ya cargada y hace commit **antes** de que
una segunda Session modifique el token y confirme su transacción. Solo entonces
la primera sesión vuelve a solicitar autorización. Así no se confunde la caché
ORM con una transacción antigua ni con una modificación dentro de la misma sesión.
Las aserciones observan HTTP503 con el detalle exacto del perfil incompatible y,
después, HTTP507 al pedir un byte adicional: el rechazo no pierde el cargo.

Comando focal ejecutado tres veces, sin alterar el runner ni su `-x`:

```sh
/home/kevin/Work/fama/.venv/bin/python /home/kevin/Work/fama/.git/agent-scratch/run_storage_budget_on_ssd.py tests/test_dataset_storage_budget.py -k separate_sessions
```

- `storage-budget-check-7u2g6eex`: exit 1; RED de `require`, `DID NOT RAISE
  HTTPException`; 1 FAIL, 19 deseleccionados. De los dos casos seleccionados,
  `acquire` no llegó a ejecutarse por `-x`.
- Tras corregir únicamente `require`, `storage-budget-check-db01j2ey`: exit 1;
  `require` PASS y `acquire` RED con el mismo mensaje; 19 deseleccionados.
- Tras corregir `acquire`, `storage-budget-check-98vsgdur`: exit 0; **2 PASS,
  19 deseleccionados**, en 0.16 s; ambos conservan el cargo. Stderr focal vacío.

La corrección de producción se limita a `populate_existing=True` en las dos
lecturas `db.get(StorageGrant, ...)` de `require` y `acquire`. No se cambian
identidades, límites, retirement, locks, contratos públicos ni activación.
El cierre de seis módulos, con el comando completo ya indicado arriba, se
ejecutó una sola vez: `storage-budget-check-ngwsxi59`, **exit 0, 104 PASS en
18.87 s**, sin deselecciones, exclusiones ni skips. Distribución: presupuesto 21,
receipts 18, chunks 20, cleanup 13, quotas 13, worker_cli 19. Los mensajes de stderr
son los mismos casos negativos esperados del CLI descritos anteriormente.
Las cuatro ejecuciones S14 conservaron 302 fuentes sin cambios y 30 entradas
protegidas; scratch retirado, solo SQLite en memoria (focal: 1/2/2 conexiones;
cierre: 103), sin timeout ni recuperación ambiental. Logs y manifiestos se
conservan en sus snapshots nuevos bajo el mismo destino SSD autorizado.
Esto acredita relectura tras commits controlados entre sesiones, **no**
serialización simultánea, fencing de procesos ni importación real. El padre
conserva la aceptación y el recheck exacto del gap; no se inició otro verificador.

## Ciclo integrado T6.2 (S12/S13)

- La reserva lógica del recibo mantiene ZIP + una expansión y sus límites previos.
  La concesión física independiente cobra ZIP + dos expansiones antes del commit.
  Append/finalize exigen la autoridad viva exacta del archivo antes de abrir payload;
  cada bloque nuevo comprueba que su tamaño no atraviese el piso físico.
- El callback posee el flock del intento hasta terminar realmente. Su preparación
  toma además el lock de importación y después el gate; valida el token vigente y
  transfiere la reserva inicial antes de extraer. El worker puede haber creado un
  directorio vacío antes: no acredita autoridad ni permite escribir payloads.
- Confirmación puede transferir la mitad de una preview no automática solamente
  con su job `succeeded` durable y su flock adquirido. La otra mitad sigue cobrando
  la extracción. Si el lock está ocupado, se conserva todo el cargo viejo y se
  necesita presupuesto nuevo. Intentos abandonados no se descuentan por timeout.
- La publicación solo libera la promesa lógica histórica; **no libera concesiones
  físicas por el estado `imported`**. Limpieza toma el lock de importación y todos
  los flocks descubiertos, confirma el fence `deleting`, elimina staging/intentos y
  sincroniza sus directorios. Solo entonces transfiere el cargo a los bytes reales
  que siguen en `objects`. Un fallo de borrado/fsync conserva el cargo anterior.
  Una raíz de intentos diferente se rechaza antes de borrar; no prueba parada.
- Sync cobra un envelope de manifiesto por intento/token. El writer limita los
  bytes antes de cada escritura y revalida el piso, incluido el próximo bloque.
  Sync posterior a limpieza no requiere resucitar la autoridad del ZIP eliminado.
  Los manifiestos locales siguen cobrados hasta su eliminación durable.
- Un marcador activo con servicio no configurado falla cerrado antes de crear
  archivos de lock. El estado `prepared` nunca autoriza un servicio físico.
  No se modifican autenticación, acceso por propietario ni rutas HTTP.

### Preparación explícita: solo metadatos nuevos y vacíos

> **Histórico.** `migrate_dataset_storage.py` y sus funciones ya no existen en el repositorio; el esquema vigente se aplica con `python -m app.schema upgrade --apply`. Lo siguiente describe el diseño anterior.

`backend/scripts/migrate_dataset_storage.py` ofrece `inspect_storage(engine)` y
`migrate_storage(engine, writers_stopped=True)`. No añade CLI, no carga dotenv ni
elige una DB ambiental. Inspeccionar no crea tablas; preparar exige gate verificado,
base de importaciones/datasets/jobs vacía y ninguna autoridad/pool previa. Crea
solo metadatos aditivos en estado `prepared`, nunca un pool activo. No adopta ni
reconcilia trabajo histórico. No se ejecutó migración sobre una DB real: las pruebas
usan SQLite en memoria y preparan pools activos explícitamente como fixtures.
La activación y reconciliación operativas siguen fuera de este corte.

### Evidencia TDD del ciclo

Todos los snapshots siguientes usan el prefijo `storage-budget-check-` bajo el
SSD autorizado y conservan stdout/stderr/result/manifest. La ejecución focal usa:

```sh
/home/kevin/Work/fama/.venv/bin/python /home/kevin/Work/fama/.git/agent-scratch/run_storage_budget_on_ssd.py tests/test_dataset_import_physical_lifecycle.py
```

| Snapshot | Evidencia observada |
| --- | --- |
| `ofhoqbc3` | RED: constructor no acepta `storage_policy` |
| `078521n2` | Fixture incompleta: faltaba preparación del protocolo de recibos; corregida antes del RED de comportamiento |
| `zlmgveff` → `jow4tjl9` | RED: reserva física insuficiente aceptada HTTP200 → GREEN HTTP507 y posterior reserva exacta aceptada |
| `eq3wdfoj` → `qaueip69` → `xruaj0at` | RED append y luego RED finalize aceptaban token corrupto; GREEN ambos rechazan HTTP503 sin cambios de payload/recibo |
| `vlcioqug` → `ibg7oetc` | RED: intento extraía con autoridad inicial corrupta → GREEN; aparece RED transferencia confirm sin capacidad adicional |
| `8sk03aia` → `ruj8p788` | Transferencia GREEN; RED cargo de staging no se recuperaba tras borrado → GREEN conserva solo bytes publicados |
| `h7h9f_qp` → `jdiy2jca` | RED servicio no configurado creaba import → GREEN antes de locks; RED upload sin reserva |
| `3qu38cus` → `43s2lm9a` | Upload sin reserva GREEN; export físico RED → GREEN; writer de manifiesto RED superaba envelope de 32 bytes |
| `jmc2zflf` | GREEN writer acotado y piso tras transferencia; 15 PASS incluyendo migración |
| `efrkh0g8` → `ceb6y1y3` → `c_5vlh8v` | RED raíz de limpieza incorrecta aceptada → GREEN; RED sync exigía ZIP ya retirado → GREEN |
| `wyjjkmun` → `drj696qk` | RED append ignoraba piso → piso inferior GREEN y RED bloque que atravesaba el piso |
| `bd14nnpa` | GREEN límite previo a escritura; triangulación de flock ocupado y fsync fallido; 22 PASS |
| `utruikyn` → `0_7zajt3` | RED claim de export físico no rechazaba → GREEN; 22 PASS con migración y prueba posterior de cargo conservado |

La migración tuvo RED por módulo ausente en `edj28kah`, seguido de **3 PASS** en
`thl524c5`, mediante el mismo helper con `tests/test_dataset_storage_migration.py`.
Las reglas ya correctas al añadir pruebas (prepared no autoriza, retención hasta
limpieza, flock que impide borrar y fsync fallido) son triangulación del contrato
reutilizado, no RED fabricados. Las fixtures pueden sembrar corrupción; ninguna
aserción consulta filas internas de concesiones. Los efectos y capacidad restante
se observan con HTTP, archivos sintéticos y solicitudes públicas posteriores.

## Obligaciones pendientes antes de activación (T6.3/T6.4)

1. Configuración común API/worker y selección operativa de las seis raíces; ningún
   entrypoint, perfil ambiental o servicio se activa en T6.2.
2. Calificación de procesos, concurrencia real, sandbox, límites de tiempo y parada.
   Un flock sintético ocupado no acredita muerte de procesos; timeout cooperativo
   nunca se usa como tal prueba. Conservar el presupuesto 26 GiB y piso 1 GiB del
   perfil previsto, sin confundirlo con las magnitudes pequeñas de las fixtures.
3. Calificar remounts/namespaces, varios pools, PostgreSQL y Docker/Python 3.12.
   Las comprobaciones presentes son SQLite en memoria sobre ext4 con red bloqueada;
   la guarda de aplicación no equivale a un sandbox OS ni a calificación operacional.
4. Verificar ubicación/capacidad de todos los payloads bajo el nuevo destino SSD,
   conservar el original y solo después abrir una ventana manual autorizada.
5. El padre conserva ASSESS y la única verificación independiente de esta unidad
   de concurrencia/rutas (riesgos 4 y 2), así como commits y seguimiento canónico.

La nota anterior de T6.1 sobre ausencia de diferencial solo describe aquel corte
independiente. T6.2 sí modifica consumidores compartidos y exige la comparación
pública baseline/candidato mediante el helper read-only suministrado por el padre.

## Cierre observado T6.2

La suite requerida se particionó **antes** de ejecutarla para no exceder el timeout
externo de 25 s del helper (bash foreground 30 s; guarda interna original 30 s).
No hubo timeout, retry, background ni cambio del runner/guarda.

```sh
/home/kevin/Work/fama/.venv/bin/python /home/kevin/Work/fama/.git/agent-scratch/run_storage_budget_on_ssd.py tests/test_dataset_storage_budget.py tests/test_dataset_import_physical_lifecycle.py tests/test_dataset_storage_migration.py tests/test_dataset_import_receipts.py tests/test_dataset_import_chunks.py tests/test_dataset_import_cleanup.py
/home/kevin/Work/fama/.venv/bin/python /home/kevin/Work/fama/.git/agent-scratch/run_storage_budget_on_ssd.py tests/test_dataset_import_execution.py tests/test_dataset_import_quotas.py tests/test_dataset_import_worker_cli.py tests/test_dataset_import_manifests.py
/home/kevin/Work/fama/.venv/bin/python /home/kevin/Work/fama/.git/agent-scratch/run_storage_lifecycle_differential.py
```

- Primera partición: `storage-budget-check-u3ic6z5r`, **exit 0, 94 PASS en
  17.78 s**, 95 conexiones SQLite en memoria, stderr vacío.
- Segunda: `storage-budget-check-fsh1c1q3`, **exit 0, 54 PASS en 14.23 s**,
  52 conexiones SQLite en memoria. Stderr contiene únicamente los mensajes de
  CLI negativos esperados ya descritos en T6.1 (usage/argumentos obligatorios y
  `Import worker unavailable; preserve state and inspect the operation manual.`).
- Total del cierre: **148 PASS**, sin skips, exclusiones ni deselecciones. Ambas
  particiones conservaron las 306 fuentes copiadas sin cambios, las 30 entradas
  protegidas intactas y retiraron el scratch privado. Logs completos y manifiestos
  SHA permanecen en esos snapshots; no se borraron los artefactos de evidencia.
- Diferencial ejecutado una vez después de implementar: **exit 0**,
  `storage-public-differential-ojgomkpg/result.json`. Baseline fijo
  `91399af45f1f2dfc5a8052421fb43ddff2754a6b` y candidato ejecutaron el mismo probe
  público, SHA256 `55a76f82a676d643076c6ef2b0b18b047bfe2abbaae5fe23e2b4b114960ca067`.
  Cada brazo: 1 PASS, exit 0, stderr vacío, una conexión SQLite en memoria,
  30 protegidos intactos y scratch retirado (1.01 s baseline, 0.98 s candidato).
  Exit, traza pública proyectada y stderr coinciden exactamente. La proyección
  común excluye IDs/tiempos **antes** de comparar: preview, publicación/replay,
  catálogo, descarga SHA, reserva, chunks/replay/rechazo conservando prefijo,
  finalize, cancel, cleanup y descarga retenida. No se afirma igualdad del stdout
  crudo del runner, que contiene rutas/tiempos; ambos stdout originales se conservan.
  El candidato permaneció byteidéntico al snapshot durante el diferencial.
- La última focal previa al cierre, `0_7zajt3`, ejecutó lifecycle+migration:
  **22 PASS en 6.18 s**, exit 0, sin deselecciones; 22 conexiones SQLite en memoria,
  306 fuentes sin cambios, 30 protegidos intactos, cleanup del scratch y stderr vacío.

La integración excede la heurística de 400 líneas porque reserva, transferencia,
retiro, pruebas públicas y explicación deben preservar un único ciclo coherente;
no se comprimió código ni se separó artificialmente una recepción insegura.
La evidencia sigue siendo sintética: no se activa perfil, servicio ni migración
real, no se abre el ZIP original, no se prueba escala máxima ni varios procesos.
Los resultados no sustituyen ASSESS/verificación independiente del padre.
