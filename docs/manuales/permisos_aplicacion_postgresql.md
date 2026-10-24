# Permisos de aplicación en PostgreSQL de pruebas (etapa 6)

Este paso continúa las [conexiones verificadas](conexiones_cloud_sql_y_gcs.md) y el [plan de instalación](plan_instalacion_gcp_y_asistente.md). El operador ejecutó la migración y después el script de permisos. Se comprobaron revisión/estructura `0002_access`, 15 tablas de aplicación con DML, versión de migraciones en solo lectura y acceso a las 9 secuencias. La identidad diaria sigue sin privilegios del migrador. La sección final registra el alcance de las operaciones reales.

El destino es exclusivamente `proyectotesis-fama:us-central1:fama-postgres-pruebas`, base `fama_pruebas`. El proxy nativo debe estar disponible en `127.0.0.1:5433`. La contraseña de `fama_migrador` se introduce en el terminal, sin guardarla en la configuración diaria.

## Permisos preparados

El [script SQL](../../backend/scripts/permisos_tablas_pruebas.sql) se ejecuta como `fama_migrador`. Su versión actual exige la revisión `0003_autonomy` y las 16 tablas de aplicación más `alembic_version`, presentes y pertenecientes al migrador. La comprobación real de etapa 6 descrita en este manual corresponde al corte histórico `0002_access` con 15 tablas. La actualización de autonomía añade la tabla de solicitudes y tiene su [paso controlado del operador](autonomia_y_solicitudes_datasets.md#activar-la-actualización-en-la-instancia-de-pruebas), pendiente en GCP.

| Objeto | Concesión directa a `fama_app` |
| --- | --- |
| Las 16 tablas de aplicación enumeradas por el script actual | `SELECT`, `INSERT`, `UPDATE`, `DELETE`. |
| `alembic_version` | Únicamente `SELECT`. |
| Secuencias pertenecientes a columnas de esas tablas | `USAGE`, `SELECT`; sin `UPDATE` para `setval`. |

Se normalizan primero las concesiones directas anteriores sobre esos objetos. No se concede `TRUNCATE`, opción de conceder permisos a otros usuarios ni propiedad de tablas. Se mantienen los permisos de conexión/esquema de la etapa 4: uso de `public` sin creación para la aplicación. No cambia membresías, contraseñas, datos ni permisos de otros usuarios; tampoco concede permisos sobre futuras tablas o secuencias ajenas. Una revisión futura necesitará revisar explícitamente esta lista.

Las concesiones de tabla y secuencia son independientes en [PostgreSQL 16](https://www.postgresql.org/docs/16/sql-grant.html). El script selecciona las secuencias por su dependencia de las tablas enumeradas, sin usar una concesión global sobre todo el esquema.

Las comprobaciones y cambios de permisos están dentro de un único bloque `DO`; un error revierte el bloque. El comando siguiente añade una transacción de conexión. Repetirlo conserva los datos y produce el mismo conjunto de permisos directos.

## Ejecución por el operador

Copiar el bloque completo en PowerShell. La conexión del comando apunta al destino de pruebas por el proxy nativo; no carga `.env`.

```powershell
Set-Location 'C:\Users\fabia\Desktop\F.A.M.A\backend'
$famaPermisos = @'
import getpass, json
from pathlib import Path
import psycopg2

try:
    with psycopg2.connect(
        host='127.0.0.1', port=5433, dbname='fama_pruebas',
        user='fama_migrador',
        password=getpass.getpass('Contraseña de fama_migrador: '),
        connect_timeout=5,
        options='-c statement_timeout=15000 -c lock_timeout=3000'
    ) as connection:
        with connection.cursor() as cursor:
            cursor.execute(Path('scripts/permisos_tablas_pruebas.sql').read_text(encoding='utf-8'))
            code = cursor.fetchone()[0]
    print(json.dumps({'code': code}))
except Exception:
    print(json.dumps({'code': 'runtime_permissions_failed'}))
    raise SystemExit(1)
'@
& .\.venv\Scripts\python.exe -c $famaPermisos
```

La salida esperada es `{"code": "runtime_permissions_ready"}`. La contraseña permanece oculta y no forma parte de los argumentos ni del script. La respuesta de fallo oculta detalles de conexión. Si falla, revisar destino, proxy, contraseña, revisión y propietario; no recrear la base ni cambiar la versión de Alembic para forzar el resultado.

## Verificación y alcance

Las pruebas usan PostgreSQL 16.15 local, exclusivo y descartable, con roles/contraseñas sintéticos y las migraciones reales. La interfaz probada es el script SQL ejecutado por su operador, seguido de operaciones SQL como aplicación. Se comprueban CRUD con ID autogenerado, lectura del esquema mediante `check_schema`, repetición conservando datos, rechazo de DDL y cambios de versión, reducción de concesiones directas anteriores, y rechazo de destino/usuario/revisión/propiedad incorrectos sin permisos parciales.

Para reproducir, utilizar `FAMA_TEST_ROLES_POSTGRES_URL` con un servidor local desechable como exige el [manual de usuarios SQL](usuarios_postgresql_pruebas.md#validación-aislada). Estas pruebas crean y retiran bases y roles con nombres conocidos: no apuntarlas a Cloud SQL ni a un PostgreSQL compartido. Desde la raíz, con `PYTHONPATH` en `backend` y `.env` deshabilitado:

```powershell
.\backend\.venv\Scripts\python.exe -m pytest --noconftest backend/tests/test_permisos_tablas_pruebas.py backend/tests/test_preparacion_roles_pruebas.py backend/tests/test_schema_migrations.py -q -p no:cacheprovider
```

Resultado local previo del 22 de octubre: **25 PASS/tres archivos** (73,58 s), incluidas las ocho comprobaciones nuevas de permisos. El contenedor temporal se retiró cotejando identidad y etiqueta. El [recibo de etapa 6](../receipts/instalacion_etapa6_permisos_20261022.json) separa esa regresión de las comprobaciones reales posteriores; estas no son una nueva ejecución de pytest ni de la suite global.

### Comprobación real posterior a la ejecución del operador

Con la configuración privada nativa y `fama_app`, se confirmó `schema_current`/`0002_access`, incluida la comparación estructural. Las 15 tablas de aplicación tienen SELECT/INSERT/UPDATE/DELETE sin TRUNCATE ni opción de conceder SELECT; `alembic_version` permite únicamente SELECT. Las 9 secuencias permiten USAGE/SELECT sin UPDATE. La cuenta no tiene superusuario, creación de bases/roles, creación en `public` ni membresía del migrador.

Se ejecutó CRUD sobre dos claves aleatorias de `cuota_acceso` dentro de una transacción, se revirtió y se confirmó que no quedaban filas. Otra clave sintética se insertó con commit, se leyó desde otra transacción y se eliminó con commit; una comprobación posterior confirmó su ausencia. Se utilizaron claves propias y valores de prueba, sin modificar filas de negocio ni avanzar secuencias.

Una comprobación adicional mantuvo dos conexiones simultáneas sobre otra clave sintética. La segunda escritura agotó un `lock_timeout` de 250 ms mientras la primera retenía la fila; tras revertir el intento bloqueado y confirmar la primera transacción, el reintento obtuvo el contador esperado de 3. Se eliminó la clave y se verificó ausencia posterior. Esto acredita el bloqueo de fila observado en PostgreSQL, sin afirmar concurrencia de todos los recorridos web.

En `fama-pruebas`, la identidad técnica subió un texto sintético de 39 bytes a un nombre único bajo `__fama_verificacion/etapa6/`, comprobó descarga idéntica y listado, y eliminó únicamente la generación recién creada. Se verificó ausencia de objeto vivo. Se utilizaron precondiciones de generación de la [biblioteca oficial](https://docs.cloud.google.com/python/docs/reference/storage/latest/google.cloud.storage.blob.Blob); la política de recuperación de objetos borrados del bucket conserva su comportamiento. No se operó sobre `fama-audio-records-2026`.

Dos procesos ASGI aislados, creados desde la misma configuración persistida, conservaron `installation_status=required`, `/health` 200 y `/ready`/rutas funcionales 503, sin importar modelos. Son comprobaciones de la entrada ASGI, no un despliegue HTTP/GPU completo. La instalación no se finalizó por tener ya esquema y servicios disponibles.

La etapa 6 queda verificada para esta base de pruebas y estas operaciones acotadas. El asistente, su autorización y primer administrador corresponden a la etapa 7. La autenticación/concurrencia funcional completa contra Cloud SQL, navegador, stack ML y operación institucional conservan sus etapas posteriores.
