# Conexiones Cloud SQL y GCS del nodo (etapa 5)

La etapa 5 del [plan de instalación](plan_instalacion_gcp_y_asistente.md) prepara configuración privada, diagnóstico independiente y selección explícita del entorno nativo o Docker. Continúa los [usuarios SQL de la etapa 4](usuarios_postgresql_pruebas.md) y aplica el [ADR 0059](../adr/0059-conexiones-cloud-explicitas-mediante-proxy.md).

## Recursos de esta prueba

| Recurso | Identificador |
| --- | --- |
| Proyecto | `proyectotesis-fama` |
| Instancia | `proyectotesis-fama:us-central1:fama-postgres-pruebas` |
| Base / usuario diario | `fama_pruebas` / `fama_app` |
| Usuario de migraciones | `fama_migrador`; su contraseña se conserva aparte. |
| Bucket de pruebas | `fama-pruebas` |
| Identidad técnica | `fama-pruebas-app@proyectotesis-fama.iam.gserviceaccount.com` |
| ADC local | `C:\Users\fabia\Desktop\F.A.M.A\backend\credentials\gcloud-pruebas\application_default_credentials.json` |
| Proxy nativo | `127.0.0.1:5433`, Cloud SQL Auth Proxy 2.26.2. |

El bucket `fama-audio-records-2026` queda fuera de estas comprobaciones. La cuenta de servicio autoriza el transporte y GCS; el usuario SQL autoriza las operaciones de base de datos; las cuentas web se crearán en una etapa posterior.

## Preparar la configuración privada

Desde PowerShell, en este equipo y con el entorno virtual existente:

```powershell
Set-Location 'C:\Users\fabia\Desktop\F.A.M.A\backend'
$famaNodeArguments = @(
    '-m', 'app.node',
    '--config-dir', "$PWD\installation\cloud-pruebas",
    'prepare',
    '--project', 'proyectotesis-fama',
    '--bucket', 'fama-pruebas',
    '--credentials-file', "$PWD\credentials\gcloud-pruebas\application_default_credentials.json",
    '--connection-name', 'proyectotesis-fama:us-central1:fama-postgres-pruebas',
    '--database', 'fama_pruebas',
    '--user', 'fama_app'
)
& .\.venv\Scripts\python.exe @famaNodeArguments
```

Introducir la contraseña de **`fama_app`** cuando se solicite; la entrada queda oculta. La salida esperada es `{"code": "configuration_prepared"}`. La contraseña no aparece como argumento ni se solicita en el chat. El directorio de destino debe ser nuevo: si ya existe, devuelve `configuration_directory_exists` y conserva su contenido. Un intento parcialmente interrumpido requiere revisar el directorio antes de elegir cómo reintentarlo; el comando no lo elimina ni sobrescribe automáticamente.

Se generan estas ubicaciones bajo `backend/installation/cloud-pruebas/`, excluidas de Git y del contexto de la imagen:

```text
cloud-pruebas/
├── native/installation.json
├── docker/installation.json
├── secrets/
│   ├── database-native
│   ├── database-docker
│   ├── jwt
│   └── rate-limit
└── compose.env
```

Los registros contienen identificadores públicos y referencias a archivos; los archivos `database-*` contienen las URL privadas con la contraseña codificada. Se generan dos claves aleatorias independientes para sesiones y cuotas. `compose.env` contiene rutas, UID/GID y nombre de conexión, sin contraseñas. Se guarda únicamente la contraseña SQL de aplicación, sin credenciales del migrador.

Antes de escribir secretos, Windows sustituye la DACL del directorio nuevo por acceso heredable para el usuario actual y SYSTEM. En POSIX, el directorio se crea con modo `0700` y los archivos de secretos con `0600`. Docker Desktop pudo leer estos archivos mediante los montajes elegidos en la comprobación descrita abajo. En otro nodo se debe preparar la configuración allí, con su identidad y sus rutas.

Las dos vistas son alternativas para estas pruebas: nativa usa loopback y rutas de Windows; Docker usa `cloud-sql-proxy:5432` y rutas del contenedor. Ambas conservan `completed=false`. Preparar secretos no crea tablas, cuentas web ni finaliza la instalación. No editar ese indicador para habilitar el backend; la finalización protegida corresponde al asistente de la etapa 7.

## Comprobar las dos conexiones

Con el proxy nativo activo, desde `backend`:

```powershell
& .\.venv\Scripts\python.exe -m app.node --config-dir "$PWD\installation\cloud-pruebas\native" check
```

Un resultado correcto tiene dos partes independientes:

```json
{
  "database": {"ok": true, "code": "database_connected"},
  "storage": {"ok": true, "code": "storage_read_connected"}
}
```

SQL ejecuta `SET TRANSACTION READ ONLY` y `SELECT 1`, con límites de conexión y sentencia. GCS renueva las credenciales si corresponde y lista como máximo un objeto; no publica su nombre. El comando toma solo el registro seleccionado y sus referencias, sin cargar `.env` ni aceptar otra URL heredada del proceso. Devuelve código de salida 0 únicamente si ambas comprobaciones pasan.

| Código | Interpretación |
| --- | --- |
| `configuration_invalid` | Registro o referencia a secreto inválidos; se ocultan rutas privadas y contenido. |
| `database_configuration_missing` / `storage_configuration_missing` | Falta configurar ese servicio. |
| `database_authentication_failed` | PostgreSQL rechazó las credenciales; revisar la contraseña del usuario elegido. |
| `database_forbidden` | PostgreSQL rechazó la operación por permisos. |
| `database_unavailable` | No se pudo completar la consulta; revisar proxy, red y estado del servidor. |
| `database_unsupported` | El diagnóstico exige PostgreSQL. |
| `storage_credentials_missing` / `storage_authentication_failed` | No se pudieron obtener o renovar las credenciales de Google. |
| `storage_project_missing` | Falta identificar el proyecto. |
| `storage_forbidden` / `storage_bucket_not_found` | Acceso denegado o bucket no encontrado. |
| `storage_unavailable` | No se pudo completar el listado; revisar red y servicio. |

Un resultado positivo no demuestra esquema compatible, permisos DML ni subida/descarga/borrado de objetos. Esas comprobaciones corresponden a la etapa 6. El diagnóstico no modifica el estado de instalación.

## Proxy y arranque nativo

El proxy oficial es un proceso separado. La prueba del 22 de octubre lo dejó activo con PID 22380 y escuchando exclusivamente en `127.0.0.1:5433`. El PID es evidencia de esa sesión, no un identificador permanente. Su versión/hash y procedimiento de revisión están en el [manual de usuarios SQL](usuarios_postgresql_pruebas.md#proxy-nativo-y-comprobación-desde-el-pc).

Si se cerró, comprobar primero que el puerto esté libre y ejecutar en un terminal dedicado, desde `backend`:

```powershell
& .\credentials\tools\cloud-sql-proxy-2.26.2.exe --address=127.0.0.1 --port=5433 --credentials-file="$PWD\credentials\gcloud-pruebas\application_default_credentials.json" --run-connection-test --structured-logs 'proyectotesis-fama:us-central1:fama-postgres-pruebas'
```

En otro terminal puede iniciarse la entrada nativa con el registro elegido:

```powershell
& .\.venv\Scripts\python.exe -m app.node --config-dir "$PWD\installation\cloud-pruebas\native" serve --port 8000
```

Se enlaza a `127.0.0.1`. Mientras la instalación siga pendiente, `/health` responde 200, `/api/installation/status` indica `required`, `/ready` responde 503 con `installation_required` y las rutas funcionales quedan cerradas. No se importan los modelos para mostrar ese estado. `serve` no inicia el proxy ni ejecuta migraciones.

## Selección de Docker

La variante de nube requiere [Compose 2.24.4 o posterior](https://docs.docker.com/reference/compose-file/merge/#replace-value) por `!override`. Desde la raíz del repositorio, se puede revisar su configuración sin iniciar servicios:

```powershell
docker compose --env-file .\backend\installation\cloud-pruebas\compose.env -f docker-compose.yml -f docker-compose.cloud.yml config --services
```

Debe incluir `cloud-sql-proxy` y excluir `db`. La variante reemplaza el entorno y las dependencias del backend: no hereda la URL de PostgreSQL local. El proxy no publica puertos al host, monta ADC de solo lectura y debe superar su comprobación de disponibilidad antes del backend. Las credenciales se montan también en el backend; el estado de instalación queda en un montaje persistente.

Cuando corresponda revisar el stack completo, el mismo conjunto de argumentos admite `up --build -d`. Ese arranque conserva los requisitos GPU y de imágenes del Compose base; no se ha acreditado todavía en esta etapa. Los lanzadores anteriores siguen seleccionando desarrollo local si no reciben esta variante explícita. No se debe activar simultáneamente el perfil `local` para esta prueba de nube.

Referencias: [Cloud SQL Auth Proxy](https://docs.cloud.google.com/sql/docs/postgres/connect-auth-proxy) y [ADC local con suplantación](https://docs.cloud.google.com/docs/authentication/set-up-adc-local-dev-environment).

## Evidencia del 22 de octubre y siguiente paso

La regresión acotada aprobó **50 pruebas en ocho archivos** (82,09 s), con PostgreSQL 16.15 efímero y secretos sintéticos. Incluye configuración, ACL de Windows, aislamiento de variables anteriores, diagnóstico, Compose, arranque sin ML, migraciones y usuarios SQL. No representa la suite global del proyecto.

Se comprobaron por separado:

- Windows: diagnóstico nuevo con SQL contra PostgreSQL local desechable y listado real de `fama-pruebas`.
- Linux: el mismo diagnóstico en una imagen mínima, no root, con configuración/ADC montados de solo lectura; SQL contra esa base local y listado real del bucket.
- Proxy Docker oficial 2.26.2: transporte hacia la instancia real, `Connection test passed` y `/readiness` correcto, sin puertos publicados.
- SQL remoto nativo: el operador mostró `fama_pruebas` junto a `fama_migrador` y `fama_app` en consultas de lectura desde su PC.

Los contenedores y la red temporales fueron retirados. La imagen mínima de diagnóstico no contiene credenciales ni el backend ML completo. Se conserva el proxy nativo para continuar. El [recibo de etapa 5](../receipts/instalacion_etapa5_conexiones_20261022.json) distingue estas comprobaciones.

**Comprobación posterior del mismo día:** el operador confirmó `configuration_prepared` con la contraseña real de `fama_app`. Los registros nativo y Docker obtuvieron `database_connected` y `storage_read_connected` contra Cloud SQL y `fama-pruebas` reales. El cliente Linux utilizó la imagen mínima existente, UID/GID 10001 y montajes de solo lectura; el proxy oficial temporal no publicó puertos. La selección de servicios Compose devolvió proxy/backend/frontend sin `db`. Una consulta SQL de lectura confirmó `fama_pruebas`, `fama_app` y `schema_empty`. El nuevo proxy Docker y su red fueron retirados verificando identidad y etiquetas. No se modificaron datos ni se ejecutó DDL remoto.

## Transición a la etapa 6

El siguiente paso crea las tablas en la base de pruebas vacía mediante las migraciones existentes. Se ejecuta en el terminal del operador con la contraseña de **`fama_migrador`**, distinta de la guardada para la aplicación. El proxy nativo debe seguir disponible en `127.0.0.1:5433`.

```powershell
Set-Location 'C:\Users\fabia\Desktop\F.A.M.A\backend'
$famaMigracion = @'
import getpass, os, sys
from sqlalchemy.engine import URL
from app.schema import main

os.environ['DATABASE_URL'] = URL.create(
    'postgresql+psycopg2', username='fama_migrador',
    password=getpass.getpass('Contraseña de fama_migrador: '),
    host='127.0.0.1', port=5433, database='fama_pruebas',
    query={'sslmode': 'disable'}
).render_as_string(hide_password=False)
sys.argv = ['app.schema', 'upgrade', '--apply']
raise SystemExit(main())
'@
& .\.venv\Scripts\python.exe -c $famaMigracion
```

La URL privada solo se construye en la memoria del proceso hijo. No se imprime ni se guarda la contraseña del migrador. La CLI no carga `.env`; exige `--apply`, comprueba el esquema y utiliza las revisiones versionadas con bloqueo y transacción PostgreSQL. Si termina correctamente devuelve `{"code": "schema_current", "revision": "0002_access"}`. El [manual de migraciones](preparacion_instalacion_y_migraciones.md#migraciones-explícitas) describe los códigos de fallo; no recrear la base ni cambiar el registro de instalación para ocultarlos.

El operador confirmó después la ejecución del comando. La consulta remota de lectura observó las 16 tablas propiedad de `fama_migrador`; `fama_app` todavía no puede leerlas. El siguiente paso es aplicar los [permisos de aplicación preparados](permisos_aplicacion_postgresql.md) y comprobar desde esa identidad la revisión/estructura. Las operaciones GCS sobre objetos de prueba, el asistente y primer administrador siguen pendientes.
