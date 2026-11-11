# PostgreSQL separado para entrenamiento importado

Estado: **procedimiento administrativo ejecutado en desechable y persistente; persistente preparado, no activado**. El aprovisionador, el probe y el experimento JSON quedan retirados de la ruta operativa, no borrados. Los comandos siguientes no constituyen un ejecutor automático: comprobar cada resultado antes de avanzar. Los resultados operacionales y sus límites se registran abajo; no activar la aplicación por la sola preparación de esquemas.

## Decisión y límites

El usuario pidió «Haz el plan para simplificar el plan y dejar atras los experimentos» y «Procede con la implementacion». Se conserva la CLI pública de inicialización/verificación y se separa de la creación del clúster, que requiere intervención administrativa explícita. No se introduce otro framework ni se invocan inicializadores internos para eludir sus guardas.

Se mantiene el objetivo de [ADR 0055](../adr/0055-postgresql-separado-para-bootstrap-de-entrenamiento.md): PostgreSQL separado, sin tocar la principal. Su camino de implementación asistida queda histórico por esta nueva decisión; no se reescribe el ADR como si hubiera aprobado la nueva operación. No arrancar aplicación/workers, importar datos reales, entrenar ni acceder a GCS. Una base inicializada no acredita activación, usuario web, entrenamiento ni inferencia.

## Preparación administrativa

Un administrador ejecuta de manera controlada las etapas siguientes. No sustituirlas por `compose up` ni por el ejecutor retirado. Primero se necesita un entorno desechable nuevo; solo tras aprobar todos los controles se repiten idénticos pasos para un persistente nuevo. Una lista documental no acredita ejecución.

1. Comprobar acceso al daemon local autorizado, disponibilidad de la imagen PostgreSQL fijada y ausencia de colisiones. No buscar otros sockets, contextos remotos ni credenciales. Preparar imagen bootstrap nueva desde `backend/bootstrap/Dockerfile` y `backend/bootstrap/requirements.txt`, copiando únicamente las 30 fuentes regulares físicas de `backend/bootstrap/source-files.txt`: 32 archivos de contexto total, con estructura `app/` y `scripts/`. No usar el repositorio/backend completo, enlaces, datos, backups ni secretos como contexto. Registrar digest/ID y versiones reales; las tres dependencias directas fijadas no constituyen lock transitivo ni prueba de Python 3.12.
2. Asignar proyecto/nombres, nonce de intento, imagen, volumen y red interna **nuevos**, sin puertos publicados, clientes antiguos ni almacenamiento anterior. Rechazar colisiones; nunca adoptar recursos por nombre. Registrar IDs/etiquetas y comprobar imagen, nonce, volumen/montajes y miembros de red antes de cada operación. El alias `db` debe resolver exclusivamente al servidor nuevo en esa red nueva, nunca a las IP históricas o a la principal.
3. Crear credenciales nuevas fuera del contexto: directorio `0700`, archivos `0600`, propietario compatible con UID/GID no root del runner. El servidor recibe solo su contraseña y el runner solo el passfile libpq mediante `PGPASSFILE`. No poner contraseñas en URL, argv, logs, recibos ni Git; no reutilizar archivos existentes. No acceder a archivos reales para rellenar las plantillas de este documento.
4. Crear administrativamente una base cuyo nombre sea `fama_training_dev_` seguido de 14 dígitos, desde `template0`. Restringir conexiones antes de admitir bootstrap: revocar CONNECT público, mantener la futura cuenta de aplicación NOLOGIN y excluir otros escritores mediante roles, ACL y aislamiento controlados. `template0` define origen, no exclusividad posterior. Registrar nombre/OID y system identifier; la cuenta bootstrap necesita permiso para consultar `pg_control_system()` además de los permisos DDL requeridos. No conceder ese acceso a la futura cuenta de aplicación por arrastre.
5. Comprobar identidad de clúster/base, roles/atributos/membresías, ACL/CONNECT efectivo y sesiones ajenas antes, durante y después de inicializar/verificar. Registrar por separado los permisos efectivos, una conexión de control con las mismas credenciales y el intento fallido de conexión a la base restringida. Esos hechos acreditan el estado administrativo observado, no la causa del error del cliente: sin SQLSTATE, registrar el fallo como no clasificado, nunca como `writer_rejected` causalmente demostrado. La nueva ruta no exige atribución causal automática ni otro experimento para obtenerla; la guarda `42501` del probe histórico permanece intacta y ese probe no se ejecuta. La CLI no crea la base, detiene escritores ni mantiene esta exclusión: `--writers-stopped` es un reconocimiento del operador, no un mecanismo de aislamiento.

La red interna y la ausencia de puertos no excluyen administradores privilegiados del host/daemon. No prometer exclusividad frente a ellos. Ante identidad incierta, sesión ajena, error o timeout: detener la etapa y conservar recursos y evidencia saneada. No hay reintentos automáticos, adopción ni borrados. No repetir creación, arranque, DDL o initialize para ocultar un fallo. Un diagnóstico administrativo de solo lectura puede establecer que una consulta de disponibilidad se adelantó a un servidor ya arrancado; una única continuación acotada desde ese estado comprobado, dentro del alcance autorizado, debe registrarse por separado y no cuenta como ejecución sin incidencias. Si requiere otra creación, arranque, reinicialización, permisos nuevos o cambios de configuración, detenerse y resolver ese alcance antes. La parada debe afectar solo a recursos cuya propiedad/identidad se haya renovado.

## Secuencia de comandos administrativos

Ejecutar desde la raíz en Bash, por etapas y comprobando cada código de salida. `STATE` es un directorio privado nuevo dentro del proyecto, excluido de Git mediante su propio `.gitignore` con `*`; contiene `context/`, `admin-password`, `pgpass` y `receipt.json`. Preparar los secretos con `secrets.token_hex(32)` y creación exclusiva `os.open(..., O_CREAT|O_EXCL, 0o600)`; el passfile contiene `db:5432:*:fama_training_bootstrap:<contraseña nueva>`. Nunca imprimirlo. Copiar exclusivamente el manifiesto de fuentes al contexto y los dos archivos del build; rechazar enlaces. Los nombres siguientes son **nuevos por intento**, no nombres de contenedores históricos.

```bash
set -euo pipefail
D=(docker --host unix:///var/run/docker.sock)
PG_IMAGE='postgres:16-alpine@sha256:721873c34ceb9f8d8fc265984940dc982404c105f19ad51be9fdc5970a6080ea'
# Rellenar con los valores nuevos registrados en receipt.json, no con recursos antiguos.
STATE='<directorio privado absoluto nuevo>'
RUN='<nonce nuevo>'
PROJECT="fama-admin-test-$RUN"
VOLUME="$PROJECT-data"
NETWORK="$PROJECT-net"
DB_CONTAINER="$PROJECT-db"
DATABASE="fama_training_dev_$(date -u +%Y%m%d%H%M%S)"
LABEL=(--label "fama.admin.run=$RUN" --label "fama.admin.project=$PROJECT")
"${D[@]}" image inspect "$PG_IMAGE" >/dev/null
"${D[@]}" build --label "fama.admin.run=$RUN" --iidfile "$STATE/image-id" "$STATE/context"
IMAGE_ID="$(<"$STATE/image-id")"
```

Antes de cada creación, consultar nombres exactos con `volume ls`, `network ls` y `container ls -a`; si existe alguno, detenerse. Tras crear, registrar inmediatamente IDs y comprobar etiquetas/imagen/nombre/montajes antes de arrancar o ejecutar SQL. Docker puede devolver un volumen existente: su nombre no demuestra propiedad.

```bash
"${D[@]}" volume create "${LABEL[@]}" "$VOLUME"
NETWORK_ID="$("${D[@]}" network create --internal "${LABEL[@]}" "$NETWORK")"
DB_ID="$("${D[@]}" container create --pull never --name "$DB_CONTAINER" \
  "${LABEL[@]}" --network "$NETWORK_ID" --network-alias db --restart no \
  --memory 512m --cpus 1 \
  --mount "type=volume,src=$VOLUME,dst=/var/lib/postgresql/data" \
  --mount "type=bind,src=$STATE/admin-password,dst=/run/secrets/pg-admin,readonly" \
  -e POSTGRES_USER=fama_training_bootstrap -e POSTGRES_DB=postgres \
  -e POSTGRES_PASSWORD_FILE=/run/secrets/pg-admin "$PG_IMAGE")"
# Validar mediante inspect: etiqueta RUN, nombre, imagen, red interna y solo montajes previstos.
# Guardar DB_ID/NETWORK_ID/VOLUME antes del arranque. No publicar puertos.
"${D[@]}" container start "$DB_ID"
```

Comprobar que PID 1 ya es `postgres` y `pg_isready -h 127.0.0.1 -U fama_training_bootstrap -d postgres` devuelve éxito: el servidor temporal de initdb no acredita disponibilidad final. Si falla o expira el límite acordado, conservar estado y diagnosticar; no repetir la creación ni migrar el timeout a otra ejecución. Un estado transitorio observado después del arranque debe documentarse antes de continuar según la recuperación acotada descrita arriba. Una vez listo, comprobar que la red solo contiene `DB_ID` y ejecutar SQL únicamente en ese contenedor ya identificado:

```bash
"${D[@]}" container exec -i "$DB_ID" psql -X -qAt -v ON_ERROR_STOP=1 \
  -U fama_training_bootstrap -d postgres <<SQL
CREATE DATABASE "$DATABASE" TEMPLATE template0 ALLOW_CONNECTIONS false;
REVOKE CONNECT ON DATABASE "$DATABASE" FROM PUBLIC;
CREATE ROLE fama_training_app NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
ALTER DATABASE "$DATABASE" ALLOW_CONNECTIONS true;
SELECT datname, oid, pg_get_userbyid(datdba), datallowconn,
       has_database_privilege('fama_training_app', oid, 'CONNECT')
FROM pg_database WHERE datname='$DATABASE';
SELECT system_identifier FROM pg_control_system();
SELECT count(*) FROM pg_stat_activity WHERE datname='$DATABASE';
SQL
```

Registrar OID y system identifier observados. Exigir propietario `fama_training_bootstrap`, `datallowconn=true`, CONNECT de aplicación `false`, rol NOLOGIN y cero sesiones al destino. Esta verificación administrativa establece el estado observado, no atribuye la causa de un error de conexión. Las consultas y comprobaciones deben repetirse tras la inicialización y antes de cerrar el entorno.

Crear un runner **nuevo por operación** (initialize/check) con la imagen por ID, sin puertos, no root, filesystem de solo lectura, sin capabilities, `no-new-privileges`, temporal `/tmp` y únicamente el passfile montado read-only. El ENTRYPOINT de esa imagen ya es la CLI pública; no sustituirlo por el probe.

```bash
RUNNER_ID="$("${D[@]}" container create --name "$PROJECT-initialize" "${LABEL[@]}" \
  --network "$NETWORK_ID" --user "$(id -u):$(id -g)" --read-only \
  --cap-drop ALL --security-opt no-new-privileges:true \
  --tmpfs /tmp:rw,noexec,nosuid,size=64m,mode=1777 --memory 256m --cpus 1 \
  --mount "type=bind,src=$STATE/pgpass,dst=/run/secrets/pgpass,readonly" \
  -e PGPASSFILE=/run/secrets/pgpass -e HOME=/tmp "$IMAGE_ID" \
  --database-url "postgresql+psycopg2://fama_training_bootstrap@db:5432/$DATABASE" \
  --training-development --expected-system-id "$SYSTEM_ID" \
  --expected-database-oid "$DATABASE_OID" --initialize --writers-stopped)"
# Registrar RUNNER_ID; validar identidad, imagen, montajes y miembros de red antes de start.
"${D[@]}" container start "$RUNNER_ID"
"${D[@]}" container wait "$RUNNER_ID"  # debe imprimir 0; validar ese valor, no solo exit de docker wait
"${D[@]}" container logs "$RUNNER_ID"  # guardar privadamente; compartir solo JSON de éxito reconocido
```

Para check, crear otro runner con el mismo contrato y nombre `$PROJECT-check`, añadir `-e PGOPTIONS='-c default_transaction_read_only=on'` antes de la imagen y sustituir `--initialize --writers-stopped` por `--check`. Comparar inventario antes/después y exigir recibo JSON y código 0. Nunca repetir initialize ante un fallo. Finalmente, con los runners detenidos y sin sesiones, ejecutar en el administrador `ALTER DATABASE "<DATABASE>" ALLOW_CONNECTIONS false`, comprobar `datallowconn=false` y realizar el intento de conexión siguiente. Un exit no cero demuestra que ese intento falló, no su causa si no hay SQLSTATE. Después detener exclusivamente `DB_ID` tras renovar su identidad. Guardar el recibo saneado; no eliminar contenedores ni volúmenes.

```bash
# Solo después de comprobar identidad, datallowconn=false y ausencia de sesiones.
if "${D[@]}" container exec "$DB_ID" psql -X -qAt -v ON_ERROR_STOP=1 \
  -U fama_training_bootstrap -d "$DATABASE" -c 'SELECT 1' \
  >"$STATE/disabled-connect.stdout" 2>"$STATE/disabled-connect.stderr"; then
  printf '%s\n' 'ERROR: la base deshabilitada aceptó una conexión'
  exit 1
fi
"${D[@]}" container stop --time 10 "$DB_ID"
# Renovar inspect y exigir State.Running=false; conservar todos los recursos.
```

Para la prueba negativa de esquema ausente, crear otra base vacía con nombre generado desde `template0`, restringir su CONNECT y usar su OID real en un runner `--check` read-only: debe terminar con código 1. Comparar `pg_dump --no-owner --no-privileges` antes/después; solo excluir las líneas `\\restrict`/`\\unrestrict` con tokens aleatorios de psql si aparecen. No borrar tablas de la base preparada para fabricar esta prueba. Deshabilitar conexiones de la base auxiliar y conservarla junto a los demás recursos.

Estas etapas se ejecutan de forma asistida: los marcadores y las comprobaciones humanas no se sustituyen por valores de ejemplo ni por un `compose up`. El procedimiento no se considera validado hasta observar todos sus resultados. Para el persistente, elegir nombres y secretos nuevos, conservar las mismas comprobaciones y no conectar aplicación/workers.

## CLI pública soportada: plantillas posteriores a los prerrequisitos

Estas plantillas se ejecutan **dentro del runner no root de la imagen source-only nueva**, conectado solo a la red nueva; no son comandos de creación del runner o de la base. Sustituir los marcadores por identidades administrativas verificadas. `<DATABASE>` debe cumplir el patrón anterior; `<SYSTEM_ID>` y `<DATABASE_OID>` son enteros positivos observados, no valores inventados. `/ruta/privada/pgpass` representa el passfile nuevo montado con permisos compatibles; no se solicita su contenido.

Inicialización única del esquema vacío dedicado:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHON_DOTENV_DISABLED=1 \
PGPASSFILE='/ruta/privada/pgpass' \
python -B scripts/prepare_zip_manual_database.py \
  --database-url 'postgresql+psycopg2://fama_training_bootstrap@db:5432/<DATABASE>' \
  --training-development --expected-system-id '<SYSTEM_ID>' \
  --expected-database-oid '<DATABASE_OID>' --initialize --writers-stopped
```

Comprobación posterior, con transacciones de solo lectura:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHON_DOTENV_DISABLED=1 \
PGPASSFILE='/ruta/privada/pgpass' PGOPTIONS='-c default_transaction_read_only=on' \
python -B scripts/prepare_zip_manual_database.py \
  --database-url 'postgresql+psycopg2://fama_training_bootstrap@db:5432/<DATABASE>' \
  --training-development --expected-system-id '<SYSTEM_ID>' \
  --expected-database-oid '<DATABASE_OID>' --check
```

`--initialize` y `--check` son mutuamente excluyentes. `--initialize` aplica las revisiones Alembic hasta `HEAD` (única etapa informada: `migrations`); el opt-in `--training-development` exige además la identidad esperada y valida las tablas de sesiones web; `--check` verifica que el esquema sea exactamente el `HEAD` y sus marcadores de versión, sin reparar ni hacer backfill. La imagen bootstrap incluye `migrations/` (inventario en `backend/bootstrap/source-files.txt`). No llamar funciones internas ni debilitar guardas para otro destino.

**Allowlist real de la CLI:** normalmente admite `db:5432` y `172.30.252.30:5432`, con base `fama_zip_manual`; el opt-in añade `172.30.253.30:5432` y exige el patrón de base de entrenamiento e identidad esperada. Este procedimiento usa deliberadamente **solo `db:5432` en una red nueva aislada**. Que una IP histórica esté admitida por el código no autoriza usarla aquí ni conectar a la principal.

## Criterios de salida: desechable primero, persistente después

- Conservar evidencia sin secretos de identidad, roles/ACL/sesiones, origen `template0`, imagen y recursos propios, permisos efectivos, control con las mismas credenciales, intento de conexión fallido (no clasificado si no hay SQLSTATE) y todos los stages/esquemas/marcadores de la CLI. No atribuir automáticamente la causa del fallo.
- Comparar inventario de esquema y filas antes/después de `--check` bajo `PGOPTIONS` read-only; comprobar que identidades incorrectas y esquemas ausentes se rechazan sin reparación.
- Si falla cualquier control desechable, no crear el persistente ni repetir `--initialize` para ocultarlo. Tras PASS desechable real, crear un persistente nuevo y repetir **los mismos controles**, sin atajos.
- Al terminar, comprobar ausencia de sesiones ajenas, deshabilitar nuevas conexiones y verificar rechazo; conservar el servidor detenido y recursos identificados hasta acordar activación. No cambiar conexión principal ni arrancar app/workers/GCS.

## Resultado observado de la preparación

El padre ejecutó los controles en PostgreSQL **16.15** con imagen bootstrap Python 3.12 source-only, primero desechable y después persistente. Inicialización de nueve etapas, check read-only, identidad incorrecta, esquema ausente sin reparación, inventarios y permisos/sesiones se comprobaron en ambos. El persistente conservó identidad/esquema/inventario tras reinicio. Hubo una interrupción por consulta de disponibilidad inmediata, diagnosticada y recuperada sin segundo arranque ni reinicialización; el recibo la conserva como incidencia. El recheck independiente aprobó con alcance documental/evidencia limitado, sin reproducir PostgreSQL por su cuenta.

- [Recibo desechable](../receipts/training-postgres-admin-disposable.json).
- [Recibo persistente](../receipts/training-postgres-admin-persistent.json).
- Base persistente: `fama_training_dev_20261105153618`.
- Contenedor: `fama-admin-persistent-9c4b15c847a23b49-db`.
- Volumen: `fama-admin-persistent-9c4b15c847a23b49-data`.
- Estado final: servidor detenido, conexiones de las bases deshabilitadas, futura cuenta de aplicación NOLOGIN y sin CONNECT. Recursos conservados; contraseñas no publicadas.

La aplicación no se inició ni se cambió su conexión principal. No se importó, entrenó ni ejecutó inferencia; GCS queda fuera de esta preparación. La activación requiere su propia decisión y preparación de credenciales/servicios. El fallo de conexión sin SQLSTATE permanece no clasificado causalmente; no se modificó la guarda del probe retirado.

## Política de arranque de aplicación separada (S24/O5)

`FAMA_APP_STARTUP_POLICY` se lee del entorno del proceso al importar `app.main`, antes de sus imports de servicios. Solo acepta exactamente `normal` o `isolated`; si falta, usa `normal` y conserva el arranque ordinario. Un valor vacío, con espacios, con otra capitalización o desconocido rechaza la importación con un error que identifica la variable, sin imprimir su valor. Establecerla antes de importar la aplicación; no se carga dotenv para resolver esta política ni se modifica dinámicamente durante el lifespan.

Con `isolated`, `app.main` omite su bootstrap legacy `Base.metadata.create_all` y el lifespan no precarga modelos, no ejecuta el seed inicial ni construye/inicia el worker de sincronización de feedback. Conserva las rutas y middleware, incluida `/health` pública con `{"status":"ok"}`. No desactiva autenticación, validación de Origin ni cuotas. Una respuesta de salud solo acredita liveness: no demuestra conexión, esquema, sesión ni readiness de base de datos.

Esta política **no es un sandbox ni elimina todos los efectos de imports transitivos**: siguen existiendo configuración del engine, manejo de dotenv/rutas de credenciales, carga de librerías ML y requisitos de directorios de checkpoints/cachés. Preparar una imagen/contexto source-only auditado, sin dotenv ni credenciales cloud, filesystem privado con permisos compatibles y controles de red/destino que excluyan principal y GCS. Las operaciones de las rutas conservan sus efectos y guardas; verificar sesiones requiere acordar escrituras en estado sintético separado, no deducir permiso de `/health`.

La disponibilidad de una imagen completa de aplicación y su aislamiento deben comprobarse por separado; la imagen bootstrap administrativa no los acredita. Esta sección no autoriza iniciar servicios, reabrir la base persistente, habilitar LOGIN/CONNECT, crear usuarios/sesiones, importar, entrenar ni cambiar la conexión principal. El estado administrativo registrado arriba permanece detenido y deshabilitado hasta una autorización operacional explícita.

## Prueba autorizada de aplicación desechable: resultado y recuperación

La autorización posterior S25–S26 permitió una instancia **nueva desechable** y un usuario sintético `investigador`, sin activar la base persistente descrita arriba. El build source-only final contiene 146 archivos; preflight sin red con Python 3.12.15 e importación `isolated` aprobados. La aplicación y PostgreSQL se ejecutaron sin puertos publicados en red interna, con filesystem de aplicación read-only, usuario no root y temporales privados. Inicialización pública de nueve etapas y check de esquema read-only terminaron con código 0.

El [recibo funcional](../receipts/training-session-current.json) conserva un **fallo**, no un PASS global: salud, registro, login/me web, atributos de cookie, rechazo de Origin extranjero y Bearer alcanzaron los estados esperados; logout devolvió 503 en vez de 204 y detuvo la única ejecución. Por ello la revocación, el replay de cookie antigua y la cuota 429 quedaron sin verificar. Los preflights fallidos por fuentes omitidas y una incidencia de disponibilidad de PostgreSQL también permanecen registrados.

El rol de prueba tenía SELECT/INSERT/UPDATE sobre `usuario`, `sesion_web`, `cuota_acceso` y `evento_seguridad`, con acceso a secuencias, pero sin DELETE. La revocación vigente necesita **DELETE únicamente sobre `public.sesion_web`**; el log PostgreSQL registró rechazo de permiso sobre esa tabla y un DELETE correlacionado. No conceder DELETE en otras tablas, CREATE, TEMP ni privilegios administrativos para resolverlo. Esta observación no autoriza un cambio de permisos o una repetición por sí misma.

Tras el fallo se detuvieron ambos servicios propios, se deshabilitaron las conexiones de la base desechable y se dejó su rol NOLOGIN y sin CONNECT. Los recursos y la evidencia se conservaron. No se alteraron principal, persistente ni GCS; no hubo importaciones ni entrenamiento. Posteriormente el usuario autorizó reactivar exclusivamente ese entorno, conceder DELETE solo sobre `public.sesion_web` y realizar una nueva verificación conservando el fallo anterior. La concesión se comprobó sin ampliar DELETE a otras tablas ni habilitar CREATE/TEMP. El probe de recuperación local no versionado (`docs/receipts/check_disposable_session_recovery.py`) terminó con código 0: login200, logout204 vacío/no-store, ausencia de sesión y cookie antigua401, cuatro intentos inválidos401 y siguiente429 con Retry-After válido. Las cuotas anteriores se conservaron; no se afirma conteo desde un bucket vacío.

El recibo integra ambas ejecuciones, **sin convertir el primer 503 en PASS ni afirmar éxito sin incidencias**. La revisión independiente fue estática; el padre ejecutó las comprobaciones reales. No es prueba de navegador, frontend ni flujo de importación/entrenamiento. Al terminar la recuperación se volvieron a detener ambos servicios propios, deshabilitar conexiones de la base y revocar LOGIN/CONNECT del rol, verificando cero sesiones antes de detener PostgreSQL. Recursos conservados; principal, persistente y GCS permanecen sin cambios.

## Evidencia y herramientas históricas: no operativas

Los dos intentos desechables de aprovisionamiento fallaron en la comprobación de rechazo por permisos; no acreditan éxito completo ni creación persistente válida. No se ha demostrado un fallo de acceso al passfile (`PGPASSFILE`): llegar a esa etapa indica que las consultas administrativas autenticadas previas funcionaron. La guarda de rechazo SQLSTATE `42501` fue restaurada y se informó 49 PASS tanto por el padre como por el verificador independiente; son pruebas sintéticas, no PostgreSQL real aprobado. Hubo un único fallo de startup observado del experimento JSON (job9, exit 2), no dos; no se presenta como solución ni como diagnóstico operacional disponible.

Se conservan sin borrar `backend/scripts/provision_training_postgres.py` (incluida su opción histórica `--create-persistent`), `backend/scripts/training_postgres_probe.py`, las pruebas/probes JSON, `docker-compose.training-dev.yml` y sus recibos. Quedan retirados de la recomendación operativa; no ejecutar el aprovisionador/probe/experimento JSON ni Compose como alternativa. Los recibos anteriores no prueban el estado actual ni convierten fallos históricos en éxitos.

El preflight no mutante `backend/scripts/check_training_postgres_target.py` solo observa colisiones; `target_available: true` no reserva nombres ni concede propiedad. El checker `backend/tests/check_training_bootstrap_layout.py` acredita estructura/imports con contexto acotado, no build/PG/credenciales/persistencia. El [recibo estructural](../receipts/training-bootstrap-layout.json) conserva ese alcance. Los resultados históricos 30 fuentes/32 archivos/2 servicios y pruebas simuladas no acreditan Python 3.12 ni disponibilidad como base principal. La edición documental no sustituye la ejecución: los resultados reales de la ruta administrativa se registran en los recibos anteriores. La evidencia histórica de este párrafo conserva su alcance estructural original.

Fuentes: [contextos de build](https://docs.docker.com/build/concepts/context/), [red interna](https://docs.docker.com/reference/compose-file/networks/#internal), [secretos Compose](https://docs.docker.com/reference/compose-file/secrets/) y [CREATE DATABASE PostgreSQL 16](https://www.postgresql.org/docs/16/sql-createdatabase.html).
