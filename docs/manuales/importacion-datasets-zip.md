# Importar datasets ZIP y sincronizarlos posteriormente

La nueva sección **Importar dataset** de Gestión de audios conserva primero una
copia persistente local y permite sincronizarla posteriormente con GCS. No prepara
particiones, extrae tensores ni inicia entrenamiento. Implementación local: todavía
no acredita despliegue ni operación real de GCS.

Para recepción reanudable, exportación nativa y mantenimiento, consultar la
[guía integral de operación y comprobación sintética T8](integracion-importacion-datasets.md).
Los pasos Docker de este manual requieren autorización separada; no forman parte
de esa comprobación aislada.

## Contadores disponibles para el catálogo unificado

**Gestión de audios** muestra una sola tabla **Datasets disponibles (local y GCS)**
con archivos locales y archivos en GCS. Las filas **Importado ZIP** pertenecen al
catálogo privado; las filas del catálogo legado conservan sus acciones anteriores.
Los catálogos mantienen identidades separadas por origen e ID, incluso si coinciden
sus nombres e IDs. No se unen por nombre.

El catálogo privado conserva la autenticación y el modo de acceso del importador.
Si falta sesión o falla la consulta, se muestra un error específico; no se presenta
como catálogo vacío ni se convierte el fallo en contadores cero. El catálogo legado
sigue disponible. **Actualizar** y el refresco global consultan ambas fuentes.
**Primera página de importaciones** y **Siguiente página de importaciones** recorren
una página privada a la vez, sin cargar todos los miembros para obtener contadores.

En una fila importada, **Consultar audios** abre la consulta paginada de WAV propios;
pulsar un archivo lo descarga mediante la API pública autenticada. No selecciona la
fila para descargar desde GCS, preprocesar o entrenar con acciones del catálogo legado.
El conteo GCS de estas filas representa acuses históricos, no una auditoría actual
del bucket. En las filas legadas, **Desconocido** significa que no existe un conteo
remoto acreditado; no demuestra sincronización aunque haya archivos locales.

- `GET /api/ingestion/imports/datasets`: `file_count` conserva el número local
  publicado del resumen del dataset. El nuevo `synced_file_count` cuenta miembros
  únicos publicados con acuse durable de sincronización en su importación de origen
  exacta y hash. Agrega las distintas importaciones del dataset, no solo el progreso
  de una vista previa; excluye duplicados y revisiones todavía no publicadas. Cero
  es válido cuando todos los miembros siguen pendientes. Mantiene el filtro de
  propietario y la paginación; resuelve los acuses en una consulta para la página.
  Es evidencia histórica de subida, **no** una comprobación de existencia actual
  del objeto remoto ni de integridad de todo el bucket.
- `GET /api/ingestion/datasets` (legado): el nuevo `gcs_file_count` es el conteo
  explícito obtenido del listado exitoso de objetos del dataset. Puede ser cero
  para un dataset solo local después de ese listado. Si la consulta falla, es
  `null` (desconocido), nunca el número local ni un cero inferido de modo offline.
  No se modifican `file_count`, `local_file_count`, `is_synced`, `source` ni
  `gcs_available`: `file_count` sigue siendo remoto en filas GCS y local en el
  fallback. `is_synced=true` en fallback conserva su significado legado y no
  demuestra una subida. El helper de descubrimiento exclusivamente local no
  consulta GCS ni acredita un conteo remoto.

Estos campos no agregan consultas reales a GCS al catálogo privado, escrituras,
migraciones ni cambios de autorización. No habilitan acciones de entrenamiento
o acciones del catálogo legado para datasets privados.

## Perfil físico opt-in (sin activación automática)

HTTP y worker comparten `FAMA_IMPORT_STORAGE_PROFILE`, ruta absoluta a JSON
físico existente, propio, no escribible por grupo/otros, sin symlinks y <=64 KiB.
Ausencia conserva defaults; vacío/inválido/mapping diferente falla cerrado con
503 saneado (CLI exit1, sin construir engine). No prepara carpetas, DB o pools.
Véase [contrato físico y laboratorio vacío](presupuesto-fisico-importacion-dev.md)
para los seis roles, activación explícita y requisitos SSD/TMPDIR/cachés.
`backend/config/local-large-zip.sh` es solo un perfil numérico candidato, nunca se
carga automáticamente: requiere >=48 GiB libres, pool calificado 26 GiB más piso
y worker con `--execution-seconds 900` explícito. No habilita exports ni acredita
prueba con ZIP grande. El default del worker es ahora 1800 s; `--execution-seconds 900` sigue siendo una selección explícita válida, no el valor predeterminado.

## Uso

1. En **Gestión de audios**, pulsa **Importar dataset**, junto a **Descargar desde GCS
   para entrenamiento local**. Lee las instrucciones y límites en la ventana modal y pulsa
   **Importar dataset** dentro de ella para mostrar el formulario. No hay formulario
   de login en el importador: usa la sesión web del proyecto o Bearer para la API.
   La admisión anónima está deshabilitada, incluso con flags locales antiguos.
   Importa y entrena con la misma cuenta real para conservar la propiedad del dataset.
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

### Desarrollo local autenticado

La importación anónima está **deshabilitada**. `/api/ingestion/imports/access`
conserva su formato y devuelve `development_mode: false`. Ni loopback ni
`FAMA_IMPORT_DEV_MODE=1` ni `FAMA_IMPORT_DEV_FRONTEND_IP` conceden identidad.
Las operaciones privadas de importación y exportación exigen una cuenta real
mediante sesión web o Bearer. Los datasets antiguos del propietario reservado
`-1` se conservan, sin reasignarlos ni exponerlos a otras cuentas.

El almacenamiento local y el worker `--local-only` siguen siendo independientes
de la autenticación. El flag antiguo puede seguir siendo requerido por el
checker del launcher de desarrollo; ya no habilita solicitudes anónimas.

**Recetas históricas:** los procedimientos siguientes que indican «sin sesión»
o usan el launcher de colección anónima ya no son un recorrido operativo vigente.
No ejecutarlos para preparar el nuevo entorno principal. El launcher antiguo
puede esperar una capacidad que ya está deshabilitada; su adaptación queda fuera
de este cambio. Para la nueva base, usar el procedimiento autenticado y acordar
los efectos antes de ejecutar DDL o cambiar conexiones.

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

#### Base nueva para desarrollo de entrenamiento

`prepare_zip_manual_database.py` también admite, solo mediante
`--training-development`, una base PostgreSQL nueva cuyo nombre siga exactamente
`fama_training_dev_` y catorce dígitos. Requiere `--expected-system-id` y
`--expected-database-oid`: enteros decimales positivos sin ceros iniciales,
obtenidos y comprobados previamente por el operador. Antes de inicializar o
comprobar, consulta el nombre y OID conectados y el identificador del clúster;
si no coinciden, falla sin inicializar. La cuenta debe poder consultar
`pg_control_system()`. Los destinos permitidos son `db:5432`,
`172.30.252.30:5432` y, solo en este modo, `172.30.253.30:5432`; no se admiten
parámetros en la URL. Sin opt-in se conserva exclusivamente el destino manual
anterior y su guarda original.

Ejemplo esquemático: proporcionar `--database-url <URL_SIN_CREDENCIALES_REALES>`
`--training-development --expected-system-id <ID_VERIFICADO>`
`--expected-database-oid <OID_VERIFICADO>` y `--check`, o bien
`--initialize --writers-stopped` únicamente para una base vacía autorizada y con
los escritores detenidos. Los marcadores no son valores ejecutables. No repetir
una inicialización para reparar datos ni interpretar esta opción como autorización
para modificar la base anterior o acceder a GCS.

En este modo, `--initialize` añade después de ZIP los esquemas de snapshots,
procedencia del modelo importado y sesiones/cuotas/auditoría, reutilizando sus
migradores explícitos. `--check` los verifica sin repararlos y devuelve
`training_schema_and_markers`; sin opt-in conserva `schema_and_markers` del ZIP.
No crea cuentas, preparados ni datos de ejemplo. `--writers-stopped` sigue siendo
una declaración del operador, no una exclusión de conexiones. Un fallo intermedio
puede dejar etapas ya creadas: conservar el estado y no repetir la inicialización.

#### Pendientes antes de convertir la base en principal

1. Acordar el clúster destino y los efectos. Una base creada desde `template0`
   comienza sin objetos de usuario, pero eso no impide escritores posteriores.
   En el clúster compartido, permisos/advisory locks/CONNECTION LIMIT no excluyen
   administradores privilegiados; no presentarlos como garantía absoluta.
2. Definir una ventana exclusiva verificable: API y workers detenidos, admisión
   de conexiones restringida al bootstrap y ausencia de sesiones ajenas; mantener
   esa restricción durante todas las etapas. Las sesiones observadas en un instante
   no acreditan por sí solas exclusividad continua. Si no se pueden controlar los
   clientes privilegiados, considerar un clúster de desarrollo separado, con su
   coste adicional de servicio/volumen y configuración; aún no está seleccionado.
3. Ejecutar creación e inicialización solo después de autorizar los recursos
   concretos. Mantener la base anterior, su backup y la base ya creada sin cambios.
   Registrar nombre/OID/system identifier del destino y usar el CLI protegido.
4. Verificar tablas y marcadores, cuenta/sesión real, directorios absolutos durables
   de importación/snapshots/preparados y permisos para API y workers. Inicializar
   esquemas no crea audios, cuenta, grupos ni preparados.
5. Acordar el reinicio de procesos y el cambio común de DATABASE_URL. Antes del
   arranque, controlar seeding y el worker de feedback con capacidad GCS. Un arranque
   normal no cumple por sí solo el requisito de no tocar GCS. Ante error, detener
   procesos nuevos y conservar estado; no arrancar automáticamente el runtime
   anterior, que puede reactivar efectos cloud.
6. Comprobar con la misma identidad importación confirmada → visible/bloqueos →
   preparación explícita → admisión → entrenamiento → métricas/checkpoint. Ninguna
   respuesta de inicio prueba las etapas posteriores. Inferencia UI y su requisito
   GCS permanecen como trabajo posterior separado.

Fuentes de las restricciones: [CREATE DATABASE](https://www.postgresql.org/docs/16/sql-createdatabase.html),
[atributos de roles](https://www.postgresql.org/docs/16/role-attributes.html) y
[admisión de conexiones](https://www.postgresql.org/docs/16/auth-pg-hba-conf.html).
Este checklist es diseño pendiente de prueba operacional, no un procedimiento
ya ejecutado ni una autorización para modificar el servidor.

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

**Estado al 20 de octubre de 2026:** soporte en commit `e1de562` y aceptación local
mínima completada. Tras autorizaciones separadas se verificaron respaldo y
restauración, se aplicaron las migraciones de desarrollo y se reconstruyeron los
servicios. Con el worker supervisado por el usuario en segunda terminal, el ZIP
sintético vigente publicó dos WAV; sus descargas locales conservaron tamaño y
SHA-256. No acredita escala, datasets reales, entrenamiento, reinicio físico ni
GCS. El refinamiento posterior permanece abierto en ZIP-DEV-REFINE, sin bloquear
este cierre. Los comandos siguientes documentan el procedimiento; no autorizan
repetir operaciones ni volver a ejecutar el backfill tras nuevas escrituras.

La verificación inicial tuvo un incidente de aislamiento que llegó a activar
Docker y restaurar contenedores existentes; su inspección y parada se autorizaron
por separado. La verificación pendiente se completó después con un PATH cerrado,
Docker simulado y 12 pruebas independientes de esquema, conservando la evidencia
del incidente. Esa verificación aislada no acreditaba operación desplegada; la
aceptación local posterior se registra por separado y no descarta efectos sobre
los datos durante aquel arranque. Véase el
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
PostgreSQL. La aceptación mínima comprobó la conexión efectiva al ejecutar el
worker; la recuperación de contenido preexistente sigue sin acreditarse por esa
prueba y no se deduce del esquema.

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

Usa una cuenta real y almacenamiento persistente privado. No habilites el acceso
anónimo: los flags históricos no lo restablecen. Credenciales inválidas no
conceden acceso ni permiten volver a una identidad de desarrollo. Iniciar el
backend habitual puede ejecutar seeding y sincronización de feedback; no equivale
a un entorno aislado sin GCS. No arrancarlo durante un bootstrap con escritores
detenidos.

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
| `RECEIVED_BYTES` | 6.442.450.944 (6 GiB) |
| `EXPANDED_BYTES` | 10.737.418.240 (10 GiB) |
| `ENTRIES` | 2.000 |
| `DEPTH` | 12 |
| `PATH_BYTES` | 240 bytes UTF-8 |
| `AUDIO_BYTES` | 100.663.296 (96 MiB) |
| `AUDIO_SECONDS` | 600 |
| `VALIDATION_SECONDS` | 900 |
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
El proxy admite 110 MiB por petición. La recepción fragmentada usa bloques de16MiB, no una petición de6GiB, y la validación se admite como trabajo asíncrono. El endpoint legacy de archivo completo no permite eludir el límite por petición del proxy; para ZIP grandes usar la recepción fragmentada de la interfaz. No se aumenta el body del proxy ni se elimina su timeout.

El worker dispone de1800s cooperativos por intento por defecto, frente a900s de validación; el margen también cubre hash y publicación, pero no garantiza rendimiento ni finalización de un archivo concreto. Lease60s y heartbeat20s no cambian. Los valores explícitos menores y las guardas de cuotas/espacio siguen aplicándose. El archivo de5.620.955.136bytes cabe numéricamente; su admisión no acredita integridad, calidad, importación completa ni entrenamiento.

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
