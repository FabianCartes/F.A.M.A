# Usuarios PostgreSQL de pruebas (etapa 4)

Este procedimiento corresponde exclusivamente a la instancia `proyectotesis-fama:us-central1:fama-postgres-pruebas` y a su base vacía `fama_pruebas`, con PostgreSQL 16. Continúa el [plan de instalación](plan_instalacion_gcp_y_asistente.md) y la separación entre operador DDL y aplicación DML del [ADR 0040](../adr/0040-configuracion-persistente-y-migraciones-explicitas.md).

La cuenta de servicio de Google Cloud autoriza el proxy y el acceso a GCS. Los usuarios siguientes son identidades internas de PostgreSQL; las cuentas administrador/investigador de la web se crearán después en sus tablas.

## Preparación desde Cloud SQL Studio

1. Seleccionar la instancia `fama-postgres-pruebas` y abrir **Cloud SQL Studio**.
2. Entrar con la base `fama_pruebas`, el usuario `postgres` y la contraseña que conserva el operador.
3. Confirmar el destino con `SELECT current_database(), current_user;`.
4. Copiar y ejecutar completo [preparar_roles_pruebas.sql](../../backend/scripts/preparar_roles_pruebas.sql).

El script es una operación inicial y atómica: crea ambos roles y sus permisos de conexión/esquema dentro de un único bloque `DO`. Rechaza otra base y tablas, vistas o secuencias preexistentes en `public`. Si alguno de los roles ya existe, falla sin modificarlo ni dejar creado el otro. Los roles son compartidos por las bases de la misma instancia PostgreSQL; por eso hay que seleccionar también la instancia indicada. La comprobación SQL del nombre de base no identifica por sí sola un servidor.

| Usuario | Finalidad | Permisos iniciales |
| --- | --- | --- |
| `fama_migrador` | Ejecutar las migraciones explícitas. | Conexión y uso/creación en `public`; las tablas que cree le pertenecerán. |
| `fama_app` | Ejecutar el backend diariamente. | Conexión y uso de `public`; sin creación de tablas o esquemas persistentes. |

Ambos se crean sin privilegios de superusuario, creación de bases o creación de roles. Se retira `CREATE` sobre `public` de `PUBLIC` en esta base de pruebas. El permiso de tablas no se deduce de `USAGE`: las concesiones de lectura/escritura se aplicarán después de migrar. La aplicación no está lista para operar sobre datos con este paso aislado.

La consulta final devuelve dos filas. `admite_login` y `usa_esquema` deben ser verdaderos para ambos; `superusuario`, `crea_bases` y `crea_roles`, falsos. `crea_tablas` debe ser verdadero solo para `fama_migrador`.

## Contraseñas y siguiente paso

El script utiliza `PASSWORD NULL`: todavía no permite autenticarse con esos usuarios. Las contraseñas se asignan desde **Usuarios** de la instancia, actualizando el listado y utilizando **Cambiar contraseña** en cada cuenta. Elegir claves distintas y conservarlas en el gestor del operador. Así no se escriben contraseñas en el script ni en el editor SQL. Después se volverán a comprobar los atributos de ambos roles.

El operador comunicará únicamente el resultado de la operación. La sesión de Studio no verifica la ruta de red desde el PC; la comprobación local mediante proxy se documenta a continuación. La preparación de secretos del backend continúa en la etapa 5, y las migraciones remotas y los permisos sobre tablas, en la etapa 6.

## Proxy nativo y comprobación desde el PC

El 22 de octubre el operador confirmó las contraseñas de ambos usuarios. Se descargó el binario oficial Windows x64 de Cloud SQL Auth Proxy **2.26.2** en `backend/credentials/tools/cloud-sql-proxy-2.26.2.exe` y se verificó su SHA-256: `41cfddfe79fdb5eb89a42c8c76149384eb1c564cfcaa7369a3261c95a5338b35`. La [publicación oficial](https://github.com/GoogleCloudPlatform/cloud-sql-proxy/releases/tag/v2.26.2) contiene ese hash.

El proceso de esta comprobación se inició sin ventana visible, enlazado a `127.0.0.1:5433`, usando explícitamente `backend/credentials/gcloud-pruebas/application_default_credentials.json`. Los parámetros fueron `--address=127.0.0.1`, `--port=5433`, `--credentials-file=...`, `--run-connection-test`, `--structured-logs` y el nombre de conexión de la instancia de pruebas. No se usó autenticación SQL por IAM: los logins SQL son `fama_migrador` y `fama_app`, con sus contraseñas. El directorio `backend/credentials/gcloud-pruebas/runtime/` conserva el PID y los logs locales, excluidos de Git y del contexto Docker.

El proxy informó `Connection test passed`. Esto acredita el transporte hacia la instancia con la identidad técnica elegida; la contraseña de cada usuario se comprueba aparte desde el terminal del operador. La consulta de lectura es `SELECT current_database(), current_user`, con host `127.0.0.1`, puerto `5433` y base `fama_pruebas`. La entrada se solicita mediante `getpass` y la conexión se configura de solo lectura. Este paso no aplica migraciones, no concede todavía DML y no cambia `backend/.env`.

El operador confirmó después mediante captura del terminal los resultados `('fama_pruebas', 'fama_migrador')` y `('fama_pruebas', 'fama_app')`. Queda verificado el login SQL de ambos usuarios desde el PC por el proxy nativo. La captura no acredita todavía permisos sobre tablas ni una migración remota.

El proxy se necesita mientras se use esa conexión local. Para revisar el proceso de esta prueba, consultar el PID en `proxy-process.json` y cotejar su ruta/argumentos con el binario y la instancia indicados antes de detenerlo. La preparación privada del backend, el diagnóstico y la selección de Docker continúan en el [manual de conexiones de etapa 5](conexiones_cloud_sql_y_gcs.md).

## Validación aislada

La interfaz comprobada es el script SQL ejecutado por un dueño de base con `CREATEROLE` y sin privilegio de superusuario, y las conexiones SQL de los usuarios resultantes. Cuatro pruebas con PostgreSQL 16.15 local verifican:

- Creación sin contraseña, migración real `0001_core`/`0002_access` mediante la CLI existente y rechazo de DDL persistente por la aplicación, incluso si `PUBLIC` tenía `CREATE`.
- Rechazo de otra base sin crear roles.
- Rechazo de una base con contenido sin cambiarlo.
- Colisión con un rol preexistente: reversión completa y preservación de su contraseña.

Para reproducir, iniciar un servidor PostgreSQL 16 local **exclusivo y descartable**. La suite crea y retira `fama_pruebas` y los roles con los nombres indicados; no usar un servidor compartido ni un proxy hacia Cloud SQL. Proporcionar su URL administrativa en `FAMA_TEST_ROLES_POSTGRES_URL`, con host loopback, usuario/base `postgres`. Sin esa variable las pruebas se omiten. Desde la raíz, con `.env` deshabilitado:

```powershell
$env:PYTHON_DOTENV_DISABLED = '1'
.\backend\.venv\Scripts\python.exe -m pytest --noconftest backend/tests/test_preparacion_roles_pruebas.py -q -p no:cacheprovider
```

Resultado del 22 de octubre: **4 PASS** en 4,73 s. El contenedor temporal fue retirado. El [recibo](../receipts/instalacion_etapa4_roles_20261022.json) separa esa validación local de las consultas GCP y de la ejecución SQL que corresponde al operador.

Referencias: [roles de PostgreSQL 16](https://www.postgresql.org/docs/16/sql-createrole.html), [usuarios de Cloud SQL](https://docs.cloud.google.com/sql/docs/postgres/create-manage-users) y [Cloud SQL Studio](https://docs.cloud.google.com/sql/docs/postgres/manage-data-using-studio).
