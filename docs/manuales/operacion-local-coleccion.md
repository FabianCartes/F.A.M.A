# Operación local de una colección trasladada

Alcance S23–S24: sesión local en primer plano sobre una **copia dedicada completa**.
No es la plataforma completa: solo router de importaciones, identidad reservada
`-1` (no cuenta ni administrador), worker local y frontend existente. No iniciar
GCS, entrenamiento, una nueva importación real ni servicios del laboratorio original.
El original debe permanecer fuera de línea indefinidamente; no se borra ni adopta.

## Preparación explícita

1. Completar el [traslado fuera de línea](traslado-local-almacenamiento.md).
   Conservar `relocation-complete.json`, `profile.json`, `environment.json`, SQLite
   y todos los roles físicos. Una copia parcial se rechaza antes de lanzar hijos.
2. Preparar una copia privada del bundle Next standalone ya compilado y verificado:
   `server.js`, `package.json`, `node_modules`, `.next`; copiar además `public`
   y `.next/static` de esa misma compilación. No instalar ni recompilar por inercia.
   La raíz debe ser física, del usuario, privada y descendiente estricta de la
   instancia nueva (`--root/ui`), nunca la raíz misma ni una carpeta externa o
   del origen. Enlaces internos de dependencias son válidos; enlaces que escapan
   del bundle se rechazan antes de crear runtime o iniciar procesos.
3. El manifiesto `.next/routes-manifest.json` debe tener exactamente una regla
   `afterFiles`: `/api/:path*` → `http://127.0.0.1:8000/api/:path*`, sin otras
   reglas beforeFiles/fallback. **API_URL en tiempo de ejecución no cambia rewrites
   compilados.** Puerto API 8000 ocupado significa rechazo, no matar al ocupante,
   elegir otro puerto ni redirigir a otro backend.

Desde el checkout y con el Python validado y Node ya disponibles:

```bash
python -B backend/scripts/run_local_collection.py --help
python -B backend/scripts/run_local_collection.py \
  --root /ruta/absoluta/nueva/local-instance \
  --frontend-root /ruta/absoluta/nueva/local-instance/ui
```

Son marcadores de rutas, no autorización para reutilizar el laboratorio.
UI por defecto `http://127.0.0.1:3000`; `--frontend-port` permite otro puerto
explícito. API siempre `127.0.0.1:8000`, sin proxy headers confiados.
No se carga `.env`: entorno mínimo con límites numéricos permitidos de la copia,
SQLite/perfil explícitos y HOME/tmp/cache de sesión bajo `root/runtime`.
El perfil, integridad SQLite actual y bindings de pools/políticas se verifican
sin aprovisionar ni migrar. El SHA histórico de SQLite no se exige después de
escrituras legítimas; no se vuelven a hashear gigabytes en cada inicio.

## Inicio, parada y límites

El launcher mantiene flock exclusivo de esta raíz y grupos propios. Solo anuncia
READY tras health de scope/módulos reales, access directo y access a través del
proxy real de Next con `development_mode=true`. Logs y `ready.json` quedan en
`runtime/session-*/`; no hay reinicios ni daemon. Catálogos legacy pueden responder
404: nube desconocida no significa cero audios ni una auditoría GCS válida.

Ctrl-C o SIGTERM solicita primero el drenaje cooperativo del worker (`900` segundos
por intento), y espera que su grupo termine antes de señalar API y frontend.
Conserva datos, perfiles, logs y copia original. `--shutdown-notice-seconds`
(predeterminado `930`, positivo y máximo `930`) acorta únicamente el aviso
DIAGNÓSTICO de espera; para API/UI se usa como máximo `30`. No reduce el límite
del intento, no fuerza una salida ni libera el bloqueo. No hay SIGKILL automático.
Durante todo el drenaje se conservan flock y manejadores idempotentes de señales,
incluso ante una segunda señal, error de diagnóstico o estado de grupo incierto.
El aviso identifica PGID aún presente; `stopped.json` se escribe solo después de
probar ausentes todos los grupos propios. Fallar su escritura no interrumpe el
drenaje ni permite un segundo launcher mientras haya hijos. Razones explícitas:
`requested_signal`, `ownedchild_exit`, `startup_failure` o `drain_failure`.
Una caída de hijo o error operativo termina con exit no cero aunque el cierre
posterior sea limpio; no se etiqueta como una parada voluntaria.
No usar pkill/killall, limpieza por nombre ni detener procesos ajenos.

La prueba sintética aislada cubre rechazo de copia incompleta, help/puerto,
rewrite externo/incompatible, confinamiento de UI y router real/auth loopback.
La copia publicada sintética preserva identidad, catálogo y descarga mediante API
real y worker real. El frontend de pruebas es un pequeño proxy Node controlado,
NO Next: sirve solo para inyectar fallo de reporte, congelar/reanudar el worker,
repetir SIGTERM, comprobar flock, procesos propios ausentes y dummy ajeno intacto.
No reemplaza la aceptación operativa del bundle Next real y la colección copiada.

## Instancia dedicada verificada

El [recibo operacional](../receipts/local-collection-operation.json) registra la
aceptación local del código `40dbd76`: dos ciclos reales con Next/API/worker,
seis páginas y 1.194 audios únicos en 15 clases (8.523.910.642 bytes), dos
muestras descargadas con tamaño/SHA correcto en cada ciclo, exclusión del
segundo launcher y parada SIGTERM con salida 0 y grupos propios ausentes.
El navegador mostró `aves_dataset`, 1.194 locales y 0 acuses históricos GCS;
«Consultar audios» abrió la primera página de 50 archivos. No hubo importación,
entrenamiento ni acción GCS. El respaldo original conservó los controles de
SQLite/perfil/entorno; esta ejecución no repite una auditoría de todos sus bytes.

La instancia quedó **detenida**, no instalada como servicio. Para iniciarla
manualmente con el mismo checkout e intérprete ya comprobados:

```bash
cd /home/kevin/Work/fama/.git/agent-worktrees/unified-import-catalog
/home/kevin/Work/fama/.venv/bin/python -B backend/scripts/run_local_collection.py \
  --root /run/media/kevin/FAMA_P2/fama-dev-large-zip/local-instance \
  --frontend-root /run/media/kevin/FAMA_P2/fama-dev-large-zip/local-instance/ui
```

Abrir `http://127.0.0.1:3000` solo después de READY; detener con Ctrl-C y esperar
el cierre. Esta ruta usa la rama de la feature, **no** la base principal `dev`.
El original `manual-large-zip-nf1me5r1` permanece como respaldo offline y nunca
debe ejecutarse simultáneamente. No borrar el checkout ni ninguna copia.

Los 404 de modelos, entrenamiento, feedback y catálogo legacy son límites
esperados del backend reducido. La etiqueta global «GCP Conectado» no prueba
acceso remoto; la vista de ingesta informa GCP desconectado y la columna de la
importación refleja solo acuses históricos. El lint global de frontend sigue sin
aprobar por 26 errores de archivos ajenos al cambio; este recibo no los corrige
ni afirma disponibilidad de la plataforma completa.
