# Preparación de instalación y migraciones (etapa 1)

La entrada soportada es `uvicorn main:app` desde `backend/`. `/health` comprueba que el proceso responde; `/ready` exige configuración y esquema compatibles. `/api/installation/status` devuelve únicamente `required`, `configured`, `completed` o `unavailable`. El recorrido web de configuración y creación del administrador corresponde a la etapa 7 del [plan](plan_instalacion_gcp_y_asistente.md).

## Configuración del servidor

`app.configuration` concentra las fuentes de configuración de SQL, GCS y acceso. Se mantienen las variables existentes y la lectura de `backend/.env` para ejecución nativa; las variables del proceso tienen precedencia. No hay base, contraseña, bucket ni archivo de cuenta de servicio personales implícitos en el código de conexión.

| Variable | Uso |
| --- | --- |
| `DATABASE_URL` o `DATABASE_URL_FILE` | URL SQLAlchemy con credenciales; el archivo debe tener ruta absoluta. |
| `GCS_BUCKET_NAME` | Bucket existente elegido por el operador. |
| `GOOGLE_APPLICATION_CREDENTIALS` | Archivo ADC opcional; sin esta variable se utiliza la cadena ADC de Google. `GCP_KEY_PATH` se conserva como alias de compatibilidad. |
| `JWT_SECRET_KEY` o `JWT_SECRET_KEY_FILE` | Clave para el acceso heredado por token, única y aleatoria, mínimo 32 bytes. |
| `FAMA_RATE_LIMIT_KEY` o `FAMA_RATE_LIMIT_KEY_FILE` | Clave HMAC para límites persistentes, única y aleatoria, mínimo 32 bytes. |
| `FAMA_WEB_ORIGIN` | Origen web institucional completo, por ejemplo `https://fama.example.org`, sin ruta. |
| `FAMA_ALLOW_INSECURE_LOOPBACK` | `1` solo para desarrollo HTTP en loopback. |
| `FAMA_SESSION_MAX_AGE_SECONDS` / `FAMA_SESSION_IDLE_SECONDS` | Duración absoluta/inactividad; valores por defecto 28800/1800. |
| `FAMA_CONFIG_DIR` | Directorio absoluto del servidor para `installation.json`. |

El entorno sin `FAMA_CONFIG_DIR` continúa como modalidad de transición: una URL SQL explícita identifica un nodo `configured`. Al declarar `FAMA_CONFIG_DIR` se utiliza el estado persistente: pendiente hasta finalizarlo y `completed` después. La configuración ausente o inválida y los fallos SQL bloquean las rutas funcionales con 503. Un error en un registro existente devuelve `unavailable`; una caída SQL conserva la identificación de instalación.

El registro versionado solo admite parámetros públicos y referencias a secretos. `InstallationStore.save()` escribe mediante archivo temporal y reemplazo atómico; rechaza modificar un registro ya completado. Esta es una base para el asistente: todavía no implementa su autorización, finalización concurrente ni coordinación con la cuenta SQL. La pérdida del archivo requiere recuperación del operador; el futuro asistente deberá comprobar también la base antes de permitir una finalización nueva.

El operador debe ubicar el directorio y los archivos de secretos fuera de carpetas publicadas y protegerlos con ACL del usuario del servicio en Windows, o propietario y modos adecuados en Linux. Los archivos temporales se crean privados y el directorio nuevo con modo 0700 donde POSIX lo admite; esto no configura ACL de Windows. No colocar secretos en Git, navegador o respuestas HTTP. El montaje persistente y la autenticación ADC dentro de Docker se completan en la etapa 5.

Compose ya transmite origen, clave de cuotas y duraciones de sesión. Se eliminó el montaje con nombre de credencial personal: `FAMA_CREDENTIALS_DIR` selecciona el directorio del host, montado de solo lectura en `/run/fama/credentials`. Si se usa un archivo ADC, su variable debe señalar una ruta dentro del contenedor. `backend/credentials/` y `backend/installation/` están excluidos de Git y del contexto de imagen. Esto no equivale a haber desplegado o validado ADC/Cloud SQL en Docker.

## Migraciones explícitas

La CLI **no carga `.env`**: exige `DATABASE_URL` suministrada expresamente al proceso. Antes de aplicar, comprobar que apunta al destino de pruebas identificado. En PowerShell, desde `backend/`, con la variable ya preparada de forma privada:

```powershell
.\.venv\Scripts\python.exe -m app.schema status
.\.venv\Scripts\python.exe -m app.schema upgrade --apply
.\.venv\Scripts\python.exe -m app.schema status
```

Sin `--apply` no se ejecuta la migración. `status` es de lectura. Las respuestas son JSON con código y revisión, sin URL, contraseñas ni detalles SQL. Las revisiones son `0001_core` (negocio), `0002_access` (acceso web) y `0003_autonomy` (autoría de incorporaciones y solicitudes). Las dos anteriores se pueden solicitar expresamente con `--revision` para probar una actualización; la instalación final requiere la última. El [manual de autonomía](autonomia_y_solicitudes_datasets.md) contiene el comando que pide la contraseña del migrador y actualiza también los permisos de `fama_app` en la base de pruebas.

| Código | Interpretación |
| --- | --- |
| `schema_empty` | No hay tablas ni vistas de aplicación; falta migrar. |
| `schema_outdated` | Revisión conocida y compatible anterior a la última. |
| `schema_current` | Revisión y estructura comprobadas. No acredita disponibilidad de GCS o pesos. |
| `schema_incompatible` | Historia desconocida o diferencias de tablas, columnas, tipos, claves, índices o restricciones. Requiere revisión del operador. |
| `database_unavailable` | No pudo completarse la comprobación SQL. |
| `database_unsupported` | La CLI versionada admite PostgreSQL; rechaza otros motores antes de abrir o modificar sus archivos. SQLite se mantiene en las pruebas funcionales anteriores. |
| `migration_busy` | Otro operador mantiene el bloqueo de migración en esa base. |
| `migration_failed` | La migración falló y la transacción PostgreSQL se revirtió. |

Una base histórica sin revisión no se adopta mediante `stamp` ni `create_all`. La migración de sus datos se prepara en la etapa 10. Las definiciones de revisiones están congeladas en `backend/migrations/schema_0002.py`; un cambio futuro requiere una revisión nueva. La comprobación cubre el esquema esperado en el esquema SQL actual, no un inventario completo de funciones, extensiones, permisos o todos los objetos del servidor.

Las conexiones PostgreSQL tienen un límite de conexión de cinco segundos, de sentencia de cinco segundos y de espera de bloqueo de tres segundos. La comprobación realiza varias sentencias; esos límites no representan un tiempo total de cinco segundos. La actualización usa una transacción y un bloqueo asesor transaccional. No se ofrece borrado/downgrade automático.

## Identidades y arranque

El operador de migraciones necesita DDL sobre el esquema. La identidad diaria necesita conexión, uso del esquema, DML sobre las tablas de aplicación, lectura de `alembic_version` y uso de secuencias; no necesita crear tablas. Estos permisos se asignarán a las identidades reales en la etapa 4. La CLI no entrega ni conserva credenciales de migración en la aplicación.

El backend ya no crea tablas al importar ni usuarios al arrancar. `seed_initial_admin()` permanece como operación explícita de compatibilidad; el asistente posterior incorporará la creación protegida del primer administrador. Tras configurar o migrar un nodo que arrancó bloqueado, reiniciar el backend para habilitar la entrada funcional.

## Verificación aislada

Los tests de configuración y arranque se ejecutan mediante sus interfaces públicas; los tests de migración requieren `FAMA_TEST_POSTGRES_URL` de un servidor efímero. Crean y eliminan únicamente bases con nombres aleatorios propios. Las pruebas de migración se omiten si esa variable falta. No apuntarla a un servidor institucional.

```powershell
$env:PYTHONPATH = "$PWD\backend"
$env:PYTHON_DOTENV_DISABLED = '1'
$env:DATABASE_URL = 'sqlite://'
.\backend\.venv\Scripts\python.exe -m pytest --noconftest backend/tests/test_installation_configuration.py backend/tests/test_installation_startup.py backend/tests/test_schema_migrations.py -q
```

`--noconftest` evita cargar el entrenamiento global para estas pruebas de instalación. La regresión de módulos existentes usa sus fixtures habituales y adaptadores externos simulados. Esta etapa no certifica conexión Cloud SQL/GCS, inferencia, el asistente web ni despliegue institucional. Decisión: [ADR 0040](../adr/0040-configuracion-persistente-y-migraciones-explicitas.md).
