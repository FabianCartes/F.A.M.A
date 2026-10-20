# Importar datasets ZIP y sincronizarlos posteriormente

La nueva sección **Importar dataset** de Gestión de audios conserva primero una
copia persistente local y permite sincronizarla posteriormente con GCS. No prepara
particiones, extrae tensores ni inicia entrenamiento. Implementación local: todavía
no acredita despliegue ni operación real de GCS.

Para recepción reanudable, exportación nativa y mantenimiento, consultar la
[guía integral de operación y comprobación sintética T8](integracion-importacion-datasets.md).
Los pasos Docker de este manual requieren autorización separada; no forman parte
de esa comprobación aislada.

## Uso

1. En **Gestión de audios**, pulsa **Importar dataset**, junto a **Descargar desde GCS
   para entrenamiento local**. Lee las instrucciones y límites en la ventana modal y pulsa
   **Importar dataset** dentro de ella para mostrar el formulario. No hay formulario
   de login en el importador: la vista de acceso y la política de roles están
   pendientes de integración. Para probar sin sesión, el operador debe habilitar
   explícitamente el modo local descrito más abajo. Fuera de ese modo, el backend
   conserva la autenticación; el panel puede recibir una sesión de la futura vista
   de acceso, pero todavía no está conectado a ella.
2. Introduce el nombre del nuevo dataset privado y, opcionalmente, su descripción.
   El formulario no ofrece añadir audios a un dataset existente: esa función queda
   pospuesta en la interfaz, sin retirar el soporte del backend. La recuperación de
   solicitudes anteriores se conserva.
3. Descarga el ejemplo sintético si lo necesitas. Selecciona un ZIP con WAV:

   ```text
   chucao/audio_01.wav
   colilarga/audio_01.wav
   ```

4. Coloca las carpetas de clases directamente en la raíz del ZIP, con los WAV
   inmediatamente dentro de cada clase. No incluyas una carpeta contenedora ni
   subcarpetas de sesiones, aunque estén vacías. Por ejemplo, `chucao/audio_01.wav`
   pertenece a la clase `chucao`; `aves/chucao/audio_01.wav` se rechaza, no se
   interpreta ni corrige automáticamente. No hay un campo para escribir la raíz.
5. Pulsa **Importar ZIP** para autorizar la validación y, solo si es válida, la
   importación local automática. No hay una segunda confirmación. El usuario debe
   organizar el ZIP; el servidor sigue comprobando estructura, seguridad y contenido.
   Una estructura incorrecta rechaza el ZIP e indica:
   «Organiza el ZIP como clase/audio.wav, sin carpeta contenedora ni subcarpetas.»
   Revisa las incidencias; cancela la solicitud rechazada y crea otra con el ZIP
   corregido. No se publica contenido parcial ni se convierten advertencias en errores.
6. Espera **Importada localmente** antes de considerar el trabajo terminado. La
   admisión del trabajo no es éxito final. Consulta y descarga sus archivos desde el panel.
   Una repetición exacta informa que no hay novedades sin incrementar los contadores.
7. Solo cuando corresponda, pulsa **Sincronizar con GCS**. Si queda en curso o falla,
   reanuda desde el mismo panel. La copia local no se elimina.

Puedes cerrar la ventana con **Cerrar importación**, Escape o pulsando el fondo
oscuro exterior. Pulsar dentro no la cierra. Cerrar solo oculta la ventana: conserva
el formulario, el ZIP seleccionado y el trabajo mientras permanezcas en la vista;
no cancela una operación ni libera su cupo. Volver a pulsar el botón permite continuar.
Una vez admitido el trabajo, el worker valida e importa en el servidor aunque cierres
el navegador; la subida todavía en curso sí necesita terminar antes de abandonar la vista.
Si recargas o abandonas la vista, usa **Recuperar importaciones anteriores** y, si
la recepción no terminó, selecciona de nuevo el ZIP original.

Se admite al menos un WAV válido único y una clase poblada. Clases vacías y pequeñas
generan advertencias; esto no significa que el dataset sea apto para entrenamiento.
Mismo hash y clase se omite; mismo contenido con otra clase bloquea la importación.
Mismo nombre y bytes diferentes se conserva con identidades independientes. El hash
no demuestra equivalencia acústica de audios recodificados.

### Compatibilidad de solicitudes anteriores

Las nuevas solicitudes de la interfaz fijan `layout: "class_folders"` al crearse.
La política queda asociada a la solicitud: revalidar con una raíz distinta se
rechaza, incluso mediante la API. Una sola clase con al menos un WAV válido y
único sigue siendo suficiente; no se requieren dos clases.

También envían `auto_import: true`: un booleano estricto que autoriza únicamente
la publicación local tras validar. Omitirlo o enviar `false` conserva el recorrido
manual **Validar ZIP → Confirmar importación local**, incluso para solicitudes del
historial; no se migran solicitudes anteriores ni se confirma al abrirlas.
Las cadenas `"true"`/`"false"`, números y `null` se rechazan. Repetir una creación
idéntica conserva su identidad; cambiar esa autorización para una solicitud existente
se rechaza. Consultar el historial o actualizarlo no admite trabajos nuevos.

Las solicitudes anteriores sin esa política conservan su raíz revisada, rutas de
sesiones y recuperación desde el historial. El campo de raíz ya no es editable
en la interfaz. El contrato del backend para esos clientes y para añadir audios
a datasets existentes se mantiene; no se migran ni reinterpretan sus datos.
La exportación ZIP independiente conserva su formato y puede incluir una carpeta
contenedora y rutas históricas: no implica que ese ZIP cumpla el nuevo formato de
importación sin reorganizarlo.

## Descargar una versión como ZIP

En **Gestión de audios**, el botón **Descargar versión como ZIP** está junto a
**Descargar desde GCS para entrenamiento local** y abre una ventana independiente.
La exportación ya no forma parte del formulario **Importar dataset**.

Selecciona un dataset y su revisión sincronizada, solicita la exportación y espera
su finalización antes de preparar la descarga. **Primera página de datasets** y
**Siguiente página de datasets** permiten recorrer el catálogo sin cargarlo completo.
Si falla una página, **Reintentar conexión** vuelve a consultar esa misma página.
**Recuperar exportaciones** permite
consultar trabajos anteriores del dataset seleccionado. Cerrar la ventana no
cancela el trabajo y volver a abrirla conserva la selección y el resultado mientras
permanezcas en la vista. Si recargas la página, consulta de nuevo las exportaciones.

Este ZIP se descarga a tu equipo; no prepara datos para entrenamiento ni inicia una
importación. Requiere una revisión con manifiesto completo y la configuración del
worker de exportación y del origen HTTPS de descarga descrita en
[trabajos de importación y exportación](trabajos-importacion-datasets.md).
El worker manual `--local-only` no ejecuta exportaciones.

## Configuración del operador

### Excepción de desarrollo local

El modo sin login está **desactivado por defecto**. Requiere estas dos variables
en el proceso del backend:

```bash
FAMA_ENV=development
FAMA_IMPORT_DEV_MODE=1
```

#### Prueba manual aislada con worker externo

Este recorrido utiliza un proyecto Compose independiente, `fama-zip-manual`, sin
worker en Docker y sin reutilizar la base, los datos, las imágenes o los
checkpoints del entorno habitual. No requiere GPU. Solo se deben usar ZIP sintéticos;
GCS, exportación y entrenamiento quedan fuera de esta prueba.

Desde la raíz del repositorio, con el entorno `.venv` existente y el sandbox Linux
previamente comprobado, preparar las imágenes y una base **vacía**:

```bash
.venv/bin/python -B backend/scripts/zip_manual.py build
.venv/bin/python -B backend/scripts/zip_manual.py init --writers-stopped
.venv/bin/python -B backend/scripts/zip_manual.py up
```

`up` mantiene un relay TCP en primer plano, limitado a `127.0.0.1:3001` y al
frontend interno fijo. Solo anuncia disponibilidad después de comprobar HTTP 200
desde el host por ese puerto. Mantener esa terminal abierta; Ctrl+C cierra el relay,
sin borrar datos ni detener contenedores. Docker no publica puertos de este stack;
la red conserva su aislamiento y no recibe salida a Internet para habilitar la UI.

`build` puede descargar paquetes únicamente dentro de las imágenes. No instala
dependencias en el host. `init` exige API y worker detenidos, crea tablas básicas y
aplica explícitamente importaciones → metadatos → trabajos → recepciones → fragmentos.
Rechaza cualquier esquema no vacío: **no repetirlo para reparar una base utilizada**.
Si falla a mitad de la preparación, conservar el estado y diagnosticar; no se
eliminan ni reinicializan datos automáticamente.

En otra terminal, desde la misma raíz:

```bash
.venv/bin/python -B backend/scripts/zip_manual.py worker
```

El worker permanece en primer plano, procesa solo validación/confirmación y espera
dos segundos entre intentos, también cuando la cola está vacía. No reclama ni
modifica trabajos `sync`, y no construye almacenamiento GCS. Mantener esa terminal
abierta mientras se prueba **http://127.0.0.1:3001**. Un trabajo reclamado no equivale
a una operación completada: revisar **Importada localmente** en el panel. Las
solicitudes históricas manuales siguen necesitando su confirmación explícita.

En Docker Engine sobre Linux, el worker del host accede a `fama_zip_manual` por
`172.30.252.30:5432`, la dirección fija de su puente interno; PostgreSQL **no publica
puertos**. La red conserva `internal: true`, sin habilitar NAT de salida para resolver
la conexión. Este recorrido no acredita Docker Desktop ni otros sistemas operativos.
Sus credenciales son públicas y exclusivas de la prueba; no desplegar esta
configuración fuera de un equipo local de confianza. El backend no publica puertos.
Las raíces `.fama-zip-manual/imports` y `.fama-zip-manual/attempts` son persistentes,
privadas, propiedad del usuario y del mismo sistema de archivos. El backend ve la
misma ruta absoluta y los mismos archivos que el worker: no mover el checkout ni
crear aliases mientras haya importaciones recuperables. Los directorios no entran
en el contexto de construcción; la imagen backend utiliza una lista de inclusión
de código Python y `requirements.txt`, sin claves, audios ni checkpoints locales.

Para comprobar o detener sin borrar:

```bash
.venv/bin/python -B backend/scripts/zip_manual.py status
.venv/bin/python -B backend/scripts/zip_manual.py check
# Primero Ctrl+C en las terminales del worker y de up; esperar su salida.
.venv/bin/python -B backend/scripts/zip_manual.py stop
```

`check` solo verifica esquema y marcadores; no ejecuta backfill. `stop` rechaza
detener la base si el worker iniciado por este lanzador sigue activo. Conserva el
volumen y las raíces privadas; para continuar, usar `up` y luego `worker`, **no `init`**.
No pulsar sincronización GCS ni exportación durante esta prueba. La subred dedicada
es `172.30.252.0/24`; si hay una colisión, detener la preparación y revisar la
configuración, sin ampliar la guarda del frontend ni alterar redes ajenas.

La prueba nativa del sandbox ya ejecutada solo acredita su alcance sintético local.
La comprobación completa con `TestClient` requiere `httpx`, ausente en el entorno
inspeccionado; no se instala automáticamente ni se presenta como aprobada.

#### Desarrollo habitual con worker en segunda terminal

Este modo usa la base persistente de desarrollo y `backend/data-dev`, no el
proyecto aislado `fama-zip-manual`. **No aplica migraciones ni inicia el worker**.
Después del arranque y la espera de salud, comprueba el esquema de importación
del backend activo antes de anunciar éxito. Si faltan tablas, marcadores de
migración o resúmenes normalizados, termina con error: conservar el estado y
coordinar inspección, respaldo y migraciones pendientes con los escritores
detenidos. No repetir `prepare_zip_manual_database --initialize` ni un backfill
antiguo para reparar esta base. Un fallo de comprobación no detiene los servicios
que ya arrancaron; no acredita que la importación esté disponible.

**Estado de esta entrega:** soporte comprobado con Docker simulado, configuración
Compose sin daemon y bases sintéticas. Todavía no se ha inspeccionado ni migrado
la base real de desarrollo, reconstruido imágenes o arrancado este recorrido.
Los comandos siguientes corresponden al paso operacional posterior, no a una
operación ya ejecutada o autorizada automáticamente por este documento.

La verificación inicial tuvo un incidente de aislamiento que llegó a activar
Docker y restaurar contenedores existentes; su inspección y parada se autorizaron
por separado. La verificación pendiente se completó después con un PATH cerrado,
Docker simulado y 12 pruebas independientes de esquema, conservando la evidencia
del incidente. No equivale a aceptación del nuevo recorrido desplegado ni descarta
efectos sobre los datos durante aquel arranque. Véase el
[registro de verificación y recuperación](../arquitectura/dev-import-readiness.md#log).

Desde la raíz del repositorio, con Docker accesible y Compose >= 2.24.4:

```bash
./iniciar_fama.sh --dev --build
```

En una **segunda terminal**, desde la misma raíz y con el intérprete `.venv`
validado y el sandbox Linux disponible:

```bash
.venv/bin/python -B backend/scripts/dev_imports.py check
.venv/bin/python -B backend/scripts/dev_imports.py worker
```

`check` consulta el backend de desarrollo que ya está ejecutándose y verifica
tablas, restricciones, marcadores y presencia de resúmenes; no revalida todos los
archivos, no modifica datos ni prueba la conexión del host a PostgreSQL o el
sandbox. `worker` usa esa configuración, comprueba que la raíz física coincide y
supervisa en primer plano únicamente validación/publicación local, con una espera
entre intentos. No inicia contenedores, migra, reclama trabajos GCS ni realiza
exportaciones. Sus credenciales se transportan en memoria sin agregarlas al argv
del proceso del worker ni mostrarlas en la salida del lanzador. No ejecutar
directamente la opción interna `--worker-config`, cuya salida contiene la conexión.
Una segunda instancia de este comando se rechaza mientras el worker conserve su
lock. Ctrl+C solicita terminar después del intento actual; esperar su salida antes
de detener servicios o migrar. No usar simultáneamente otro lanzador contra esta
misma cola: el lock solo supervisa instancias de este comando.

La API y el worker ven los mismos archivos de
`backend/data-dev/dataset-imports`, montados también en su ruta física absoluta
del host. Los intentos persisten en `backend/data-dev/dataset-import-attempts`.
No se mueve ni copia contenido existente. Mantener ambas raíces privadas, con el
mismo propietario y sistema de archivos; no mover el checkout ni cambiar rutas
mientras haya trabajo recuperable. La ruta del host es para Docker Engine sobre
Linux: el worker accede al puente de desarrollo en `172.30.253.30:5432`, sin publicar
PostgreSQL. La conexión efectiva y la recuperación de contenido preexistente se
deben comprobar en el paso operacional; no se deducen del esquema.

Para comandos Compose directos con el overlay, exportar primero desde la raíz:

```bash
export FAMA_DEV_IMPORT_ROOT="$(pwd -P)/backend/data-dev/dataset-imports"
```

El lanzador y `dev_imports.py` fijan esta variable por sí mismos; no aceptan un
directorio distinto por un override heredado. El worker verifica un daemon local
Unix, no usa una conexión Docker remota. Las imágenes y nombres de contenedores
siguen siendo los del arranque habitual: `--build` puede reemplazar imágenes y
recrear esos servicios, aunque la base y los datos de desarrollo sean separados.
Conserva además los prerrequisitos GPU del Compose habitual. No usar datos reales,
entrenamiento o acciones GCS para la aceptación sintética de este recorrido.

Abre **http://127.0.0.1:3000**. El script anuncia **Importación sin sesión habilitada**
y selecciona explícitamente `docker-compose.yml` y `docker-compose.dev.yml`.
Este último no se carga automáticamente. `--help` no necesita Docker.

El overlay **reemplaza** las publicaciones mediante `!override`: solo el frontend
publica `127.0.0.1:3000`; backend y PostgreSQL no publican puertos al host.
Los tres servicios usan exclusivamente la red dedicada `fama-dev`, subred
`172.30.253.0/24`. El frontend tiene `172.30.253.10`; el backend admite esa IP exacta
mediante `FAMA_IMPORT_DEV_FRONTEND_IP`, además de loopback. No admite la subred completa.
Uvicorn arranca con `--no-proxy-headers` y el frontend usa el proxy interno
`http://backend:8000`, sin URL pública alternativa. Si hay colisión de subred,
no amplíes la guarda: elige otra subred y cambia coordinadamente las tres IP y
la variable del peer; vuelve a validar Compose antes de arrancar.

Se conserva la base de desarrollo en el volumen `fama_dev_pgdata` del proyecto
y los archivos en `backend/data-dev`, separados de los datos normales. No se monta
la clave GCS del Compose base en el backend de desarrollo. Las imágenes, nombres
de contenedor y checkpoints se comparten con el arranque normal: **no ejecutar ambos
modos simultáneamente**, ni usar entrenamiento como comprobación del importador.
Se conserva el requisito GPU del Compose base; este modo no instala sus prerrequisitos.

Al inicializar ese volumen por primera vez, PostgreSQL crea una base vacía aunque
conserve el nombre `fama_db`. Por eso el catálogo puede informar que no hay modelos
publicados ni seleccionables: compartir checkpoints no copia sus registros y
evaluaciones en la base de desarrollo. El volumen normal `fama_pgdata` no se borra.
No copies ni publiques modelos automáticamente para resolver ese mensaje; usar
registros reales en desarrollo requiere una operación independiente autorizada.

Para diagnosticar, valida la configuración final sin iniciar contenedores:

```bash
export HOST_UID=$(id -u) HOST_GID=$(id -g)
docker compose -f docker-compose.yml -f docker-compose.dev.yml config --quiet
docker compose -f docker-compose.yml -f docker-compose.dev.yml ps
docker compose -f docker-compose.yml -f docker-compose.dev.yml logs backend
```

Con el frontend iniciado, `curl -f http://127.0.0.1:3000/api/ingestion/imports/access`
debe devolver `{"development_mode":true}`. Un 403 indica un peer no admitido;
un 503 indica que se solicitó la excepción fuera de `FAMA_ENV=development`.
Para una prueba manual, descarga el ZIP sintético del importador, valídalo y
confírmalo; **no pulses Sincronizar con GCS** ni uses datasets reales.

Para desactivar, recrea **todos** los servicios con el arranque normal:

```bash
./iniciar_fama.sh --force-recreate
```

Sin `--dev`, el script fija solo el Compose normal incluso si el entorno contiene
`COMPOSE_FILE`. La capacidad debe volver a `{"development_mode":false}` y las
peticiones de importación sin sesión deben devolver 401. Esto restaura también
las publicaciones normales de frontend, backend y PostgreSQL; **no las endurece**.
Los datos de prueba permanecen separados y no se borran ni transfieren a cuentas.

#### Desarrollo directo sin Docker

Usa una base y un directorio persistente de pruebas. Arranca el backend enlazado
solo a `127.0.0.1` o `::1`, con ambas variables y `--no-proxy-headers`, sin proxy
ni túnel. No definas `FAMA_IMPORT_DEV_FRONTEND_IP` en ese modo.
La guarda usa el peer ASGI real: no publicar esta facilidad en servidores compartidos.
Quien controla Docker o la máquina, o puede acceder al frontend de desarrollo,
no queda aislado por esta excepción. No es autenticación entre contenedores.

- `FAMA_IMPORT_DEV_MODE=1` sin `FAMA_ENV=development` rechaza las rutas del importador
  con 503. Un cliente fuera de loopback y del peer exacto configurado recibe 403; las rutas no confían
  en `Host`, `Forwarded` ni `X-Forwarded-For` para admitirlo.
- Solo se sustituye la identidad de las solicitudes de importación sin credenciales.
  Se reserva el propietario `-1`, sin crear cuentas ni reutilizar usuarios reales.
  Todas las sesiones locales sin login comparten esa identidad: **no hay aislamiento
  entre navegadores o personas que accedan a ese mismo backend local**.
- Los filtros por propietario se conservan en consulta, ampliación, confirmación,
  cancelación, descarga y sincronización. No se da acceso a colecciones de cuentas
  reales ni al catálogo legacy como destino. Un Bearer presente se valida normalmente;
  si es inválido, no se convierte en una solicitud anónima local.
- `GET /api/ingestion/imports/access` solo informa `development_mode`; no lista
  usuarios, datasets ni límites. El frontend consulta esa capacidad antes de habilitar
  el formulario. No existe un interruptor de bypass controlado por el navegador.
- Quita `FAMA_IMPORT_DEV_MODE` o usa `0` y reinicia el backend para volver al acceso
  autenticado. Los objetos locales de desarrollo permanecen con propietario `-1`;
  no se transfieren automáticamente a ninguna cuenta.

Esta excepción no desactiva `/api/auth/me` ni la autenticación de otras rutas,
no prepara entrenamiento y no concede autorización para operaciones reales en GCS.

### Almacenamiento y límites

`FAMA_IMPORT_ROOT` debe ser una ruta absoluta física persistente, sin enlaces.
El valor por defecto es `backend/data/dataset-imports`, cubierto por el bind de
`backend/data` en el Compose versionado. Esto no acredita otros despliegues ni su
capacidad disponible. No usar `/tmp`, el navegador o la capa efímera del contenedor.
Mantener el directorio fuera de `data/raw` y de cualquier servidor de archivos
público. No configurar el prefijo remoto privado como fuente del catálogo legacy.

Los límites requieren sesión o la excepción local en `GET /api/ingestion/imports/limits` y se
configuran como enteros positivos mediante `FAMA_IMPORT_<CAMPO_EN_MAYÚSCULAS>`:

| Campo | Valor por defecto |
|---|---:|
| `RECEIVED_BYTES` | 67.108.864 |
| `EXPANDED_BYTES` | 268.435.456 |
| `ENTRIES` | 2.000 |
| `DEPTH` | 12 |
| `PATH_BYTES` | 240 bytes UTF-8 |
| `AUDIO_BYTES` | 33.554.432 |
| `AUDIO_SECONDS` | 600 |
| `VALIDATION_SECONDS` | 60 |
| `FREE_BYTES` | 536.870.912 |
| `TTL_SECONDS` | 86.400 |
| `CONCURRENT_IMPORTS` | 4 solicitudes activas globales |

Una sola mutación de almacenamiento se admite simultáneamente por volumen. Si el
lock está ocupado, el servidor devuelve 409 y no comienza otra operación. Las
solicitudes activas reservan cupo hasta finalizar, cancelar o vencer. La limpieza
se ejecuta al iniciar otra mutación: borra solamente staging propio vencido,
incluidos ZIP temporales de importaciones finalizadas; nunca los objetos publicados
ni el staging de una confirmación pendiente de recuperación. No es un cron separado.

La expansión se cuenta con bytes realmente leídos, no solamente con cabeceras ZIP.
Se rechazan rutas ambiguas, archivos especiales, cifrado, archivos no WAV y ZIP
anidados. El worker usa ahora un proceso contenido para interpretar ZIP, extraer
y decodificar WAV; si no puede establecer la contención, rechaza la validación sin
fallback. El presupuesto cooperativo del motor interno no es por sí solo un sandbox.
La sincronización conserva sus límites cooperativos y no queda contenida por T4.
Consulte [prerrequisitos, límites y comprobación T4](trabajos-importacion-datasets.md#t4-validacion-zip64-contenida)
antes de operar; esta entrega local no acredita el entorno desplegado.
El proxy actual admite 110 MiB; aumentar el límite recibido sobre ese valor requiere
revisar el proxy por separado. No se modifica su configuración en esta entrega.

## Persistencia y recuperación

Las tablas nuevas no cambian el formato de registros legacy. La migración explícita
es `python -m scripts.migrate_dataset_imports` desde `backend/` (dry-run sin conexión);
`--apply` crea únicamente las tablas ausentes en la base configurada y **requiere
autorización operacional**. El arranque actual de la aplicación también usa
`Base.metadata.create_all`; no actualiza tablas existentes. Ninguna migración real
se ejecutó durante la implementación.

Después de una interrupción, usa la misma sesión o identidad local de desarrollo y
**Recuperar importaciones anteriores**. Reenviar el ZIP original idéntico restablece
el archivo retenido si se perdió o corrompió; no permite sustituirlo por otros bytes.
La recepción confirma la durabilidad del archivo, su directorio y el directorio padre.
Si un trabajo automático falla con la importación en `committing`, usa **Reintentar
trabajo**. Conserva el tipo `preview`, la raíz y el token revisados; el worker recupera
el diario existente sin volver a validar ni reemplazar su staging. Si perdió el lease,
un worker puede reclamar el mismo trabajo pendiente y recuperarlo. El diario permite
verificar los archivos ya movidos y publicar una vez; no se cancela ni limpia mientras
sea recuperable. Las solicitudes manuales conservan su reintento de confirmación.
Mientras exista ese diario, una confirmación equivalente en otro destino espera
su recuperación; no puede dejarlo bloqueado permanentemente por equivalencia.
Si un destino cambió después de la vista previa, valida nuevamente; se rechaza antes
de publicar. Si cambió la integridad local, conserva el estado y solicita recuperación
al operador; no sobrescribas archivos manualmente.

La sincronización se liga al contenido de la importación confirmada, con progreso
persistente por archivo y hasta tres intentos para errores transitorios. No existe
un demonio residente: cada acción explícita procesa un lote hasta completar o llegar
al presupuesto; después se reanuda. Un estado `synced` acredita la verificación del
contenido de ese snapshot durante la ejecución, no vigilancia permanente del bucket
ni que ampliaciones posteriores del dataset estén sincronizadas. Volver a solicitar
una sincronización completada vuelve a verificar sus objetos.

## Verificación y exclusiones

La regresión automática S12 usa `test_dataset_import_automatic.py`: peticiones ASGI
reales sin HTTPX, SQLite en memoria y validador sintético directo. Comprueba autorización,
rechazos sin publicación parcial, reintentos antes del diario y después de rename,
reemplazo de leases vencidos, cuotas, reservas y conservación de bytes. El panel
renderizado comprueba admisión única, recuperación de solo lectura, cierre durante
publicación, rechazo visible y compatibilidad manual. Esta evidencia no recertifica
el sandbox nativo ni acredita reinicios físicos o un navegador desplegado.

Comprobación focalizada S12 desde `backend/`, sin instalar HTTPX:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHON_DOTENV_DISABLED=1 DATABASE_URL=sqlite:// \
CUDA_VISIBLE_DEVICES='' PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
../.venv/bin/python -B tests/run_isolated_training_checks.py tests/test_dataset_import_automatic.py -q --tb=short
```

Los tests nuevos usan WAV/ZIP sintéticos, SQLite en memoria, temporales privados,
red bloqueada y GCS simulado. Comando desde `backend/` con el intérprete validado:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHON_DOTENV_DISABLED=1 DATABASE_URL=sqlite:// \
CUDA_VISIBLE_DEVICES='' PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
../.venv/bin/python tests/run_isolated_training_checks.py \
  tests/test_dataset_zip_validation.py tests/test_dataset_import_api.py \
  tests/test_dataset_import_sync.py tests/test_dataset_import_migration.py \
  tests/test_dataset_import_dev_mode.py tests/test_dataset_import_verifier_regressions.py \
  tests/test_import_legacy_isolation.py tests/test_ingestion_service.py tests/test_local_dataset_catalogue.py
```

El runner es una guarda de aplicación, no sandbox del sistema operativo. No valida
PostgreSQL real, Docker/Python 3.12, calidad ML, navegador real o disponibilidad GCS.
No ejecutar como regresión el caso de inventario real
`test_cli_paths.py::test_ingestion_service_both_datasets_synced`.
Frontend: `npm test`, `npm run lint`, `npm run build`; reportar resultados vigentes
en el [seguimiento](../arquitectura/dataset-zip-import.md), no reutilizar evidencia histórica.
Una prueba real GCS necesita autorización de destino, operación y credencial.

Pruebas del arranque y fusión real de Compose (sin daemon ni contenedores), desde la raíz:

```bash
bash tests/test_iniciar_fama.sh
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python tests/test_compose_import_dev.py
```

La prueba HTTP de desarrollo realiza una importación ZIP sintética desde el peer
Docker, verifica aislamiento/Bearer y retorno al modo normal. No acredita navegador,
red Docker real ni el arranque de las imágenes; esos pasos requieren prueba operacional.
Política de acceso: [ADR 0028](../adr/0028-importacion-local-docker.md).
