# Presupuesto físico de importación: corte independiente e inactivo

## Estado y alcance

**Política independiente T6.1 comprobada con datos sintéticos; todavía inactiva.**
La revisión independiente del padre y la integración del ciclo completo siguen
pendientes. No se ejecutó el ZIP real ni se inició servicio alguno. El SSD solo
recibió snapshots nuevos de fuentes públicas y sus artefactos de prueba, mediante
el helper del padre. No se leyeron datasets históricos ni el ZIP original.

Los módulos nuevos no se exportan desde `models/__init__.py`, no crean tablas al
importarse y no están conectados a recepción, worker, publicación o limpieza.
El comportamiento predeterminado de dev no cambia. Este corte cubre la política
independiente de S12/S13; no incorpora S76 completo, sesiones web, entrenamiento,
GCS, exportaciones ejecutables ni cambios a `--execution-seconds`.

## Interfaz para el siguiente corte

`PhysicalStorage(roots=..., pools=..., free_floors=...)` inspecciona únicamente
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

## Reproducción y evidencia observada

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

## Obligaciones pendientes antes de activación (T6.2+)

1. Verificar concurrencia real con gate/locks y parada durable. El retiro probado
   es una atestación dentro de SQLite, no una prueba de muerte de procesos.
2. Añadir preparación explícita de esquema, ownership de intentos, writers acotados,
   recepción/publicación/limpieza y configuración común API/worker. Nada de ello
   está conectado por este corte. No existe `dataset_manifest_stream` nuevo.
3. Calificar remounts/namespaces, varios pools físicos y PostgreSQL. Se probaron
   raíces privadas reales de ext4 y rechazo por cambios de privacidad, no cambios
   de mount ni adquisición concurrente en varios dispositivos.
4. Calificar capacidades, pisos y ubicación de todos los archivos pesados bajo
   el destino SSD aprobado, conservando el original; recién después considerar
   la ventana manual. Un presupuesto no demuestra preasignación física,
   recuperación de bytes, lectura válida de audios ni importación completada.
5. La prueba local Python 3.14 no acredita Docker/Python 3.12. La guarda de
   aplicación no equivale a un sandbox OS. La revisión independiente sigue siendo
   necesaria antes de aceptar esta unidad de concurrencia/rutas.

No corresponde verificación diferencial de helpers compartidos: solo se añaden
módulos desconectados y se enlaza documentación; no se modificó ningún helper,
runner, migración o consumidor existente.
