# Respaldo y restauración de PostgreSQL

Bloque del 23 de octubre de 2026, rama `fix/afinamiento-integral`. La CLI local del operador permite exportar una base F.A.M.A. compatible y restaurar el contenido en otra base vacía de nombre distinto. Se verifica estructura, revisión, contenido de todas las tablas y estado de las secuencias. Los archivos de audio, tensores, checkpoints, configuración privada, identidades IAM y contraseñas de usuarios SQL tienen sus propios procedimientos de conservación.

## Generar la copia

Se requieren PostgreSQL y herramientas `pg_dump`/`pg_restore` de la misma versión principal que la base; el ensayo de este bloque usa PostgreSQL 16. El perfil de origen sigue siendo el nativo ya configurado. El destino es una carpeta nueva, absoluta, física y con padre existente. Desde `backend`:

Para esta CLI, el nombre de base empieza con una letra ASCII o `_`, continúa con letras ASCII, números, `_` o `-` y tiene hasta 63 caracteres. Esto evita que `pg_restore` interprete un nombre como otra cadena de conexión. Los nombres actuales de F.A.M.A. cumplen esa condición.

```powershell
& .\.venv\Scripts\python.exe -m app.node `
    --config-dir installation/cloud-pruebas/native backup `
    --directory 'C:\Users\fabia\Desktop\F.A.M.A\backend\installation\cloud-pruebas\backups\copia-nueva' `
    --pg-bin 'C:\Users\fabia\Desktop\F.A.M.A\backend\credentials\tools\postgresql-16.15-5\pgsql\bin'
```

Elegir un nombre nuevo para cada copia. No sobrescribir una carpeta existente. El resultado `database_backup_created` significa que se produjeron `database.dump` y `manifest.json`. El manifiesto contiene revisión, tamaño/SHA-256 del archivo, recuentos/huellas por tabla y estado de las secuencias; no incluye las filas, las contraseñas ni la URL privada de conexión.

El archivo custom sí contiene información privada de la base: cuentas, hashes de contraseña, sesiones y datos de investigación. La carpeta se protege antes de escribir: modo 0700 en POSIX o ACL Windows limitada al usuario actual y SYSTEM. Los archivos heredan esa protección. Se conservan bajo `backend/installation/`, excluidos de Git y de la imagen backend; también se excluyen globalmente los archivos `*.dump`. No compartir ni adjuntar el dump a recibos o conversaciones. El temporal `PGPASSFILE` se elimina al terminar normalmente o propagar errores; tras un cierre forzado del proceso, revisar los temporales privados conservados. La contraseña no se incorpora a los argumentos de los procesos.

Se utiliza una transacción de solo lectura con instantánea exportada: `pg_dump` y las huellas ven las mismas filas. El bloqueo de migración del proyecto impide coincidir con su CLI de actualización de esquema. No evita DDL de herramientas externas que ignoren ese bloqueo: usar una ventana sin mantenimiento de estructura. Las secuencias de PostgreSQL no son MVCC; si se observa que cambian durante el dump, se devuelve `backup_sequences_changed` y hay que repetir sin altas concurrentes. No se da esa carpeta por completada. La aplicación puede seguir operando; la copia representa un momento concreto, no el estado de todas las escrituras posteriores.

Si se interrumpe la operación o falta el manifiesto final, conservar/revisar la carpeta incompleta y generar una nueva. La CLI no borra resultados anteriores. `manifest.json` se publica después de sincronizar el archivo y escribir el manifiesto temporal. Esto no certifica la durabilidad del hardware ni equivale a una copia fuera del equipo.

## Restaurar en un destino separado

El operador prepara primero una base vacía y una identidad SQL autorizada para crear su estructura. La CLI no crea ni borra bases, no usa `--clean`/`--create` y rechaza incluso un destino que solo tenga esquemas, tipos o funciones propios. Tampoco permite utilizar el nombre de la base de origen, aunque se indique otro host. Los nombres de sistema como `postgres`, `template0` y `template1` no son destinos del procedimiento guiado.

La URL del destino se guarda localmente en un archivo privado absoluto, con permisos equivalentes al perfil de instalación. No colocar su contraseña en la consola ni en el comando. Desde `backend`:

```powershell
& .\.venv\Scripts\python.exe -m app.node `
    --config-dir installation/cloud-pruebas/native restore `
    --backup '<carpeta-absoluta-de-la-copia>' `
    --target-url-file '<archivo-privado-absoluto-con-la-URL-del-destino>' `
    --pg-bin 'C:\Users\fabia\Desktop\F.A.M.A\backend\credentials\tools\postgresql-16.15-5\pgsql\bin'
```

El comando verifica el hash/tamaño antes de restaurar. `pg_restore --single-transaction --exit-on-error` revierte la carga si falla una sentencia SQL. Después compara las tablas/secuencias con el manifiesto del respaldo y ejecuta la comprobación pública de esquema de F.A.M.A. Solo confirma `database_restore_verified` cuando esas comprobaciones coinciden. Si la verificación posterior falla, el contenido restaurado queda para diagnóstico en el destino separado y no se debe poner en servicio; el origen se conserva.

Los archivos deben proceder de una copia propia confiable. Un dump ejecuta SQL: el hash detecta alteraciones respecto de su manifiesto, pero no es una firma ni protege frente a alguien que sustituya ambos. Esta herramienta no es un importador de dumps de terceros.

## Permisos y recuperación del nodo

Las cuentas web, sus roles internos y asignaciones se recuperan como filas. Los usuarios SQL y roles IAM pertenecen al entorno técnico y requieren preparación separada. La restauración omite propietarios y ACL del archivo; los objetos quedan a nombre de quien restaura. Antes de operar hay que preparar el propietario/migrador y un usuario diario limitado, conceder DML de negocio y lectura de `alembic_version`, mantener esta versión sin escritura y las secuencias sin UPDATE, y retirar CREATE del usuario diario. El script de pruebas existente tiene guardas para `fama_pruebas`/`fama_migrador`; no ejecutarlo sin cambios contra otro destino ni modificarlo para eludir sus guardas.

No arrancar un backend sobre la copia restaurada con las carpetas del nodo original. Preparar un perfil y una raíz persistente exclusivos, credenciales técnicas adecuadas y los archivos necesarios. Para una recuperación real deben tratarse además las sesiones/restablecimientos recuperados según la política de seguridad de la institución; el ensayo de contenido conserva esas filas para comparar y no expone un segundo servidor web.

## Resultados y alcance del ensayo

El recibo del bloque distingue pruebas sintéticas PostgreSQL locales del respaldo real de Cloud SQL y su restauración local separada. La comprobación de permisos diarios se efectúa únicamente en el destino del ensayo. No se cambia `fama_pruebas`, no se crea otra instancia GCP, no se modifica el bucket oficial y no se escribe en GCS.

**Comprobación real completada:** archivo de 57187 bytes, SHA-256 `de0cc3fdca7d474142e98d583ffdfafc40da4c83c0ff79ca1d26aa90b854dd52`, conservado en la carpeta privada `backend/installation/cloud-pruebas/backups/20261024T011708Z` (nombre UTC). Se recuperó en el PostgreSQL 16 local exclusivo, base `fama_restore_20261023_87272708`: **17 tablas y nueve secuencias** coinciden con el manifiesto; esquema `0003_autonomy`. Se observaron dos cuentas, un dataset, doce audios, un modelo inactivo, una asignación, una solicitud y una corrección tanto antes/después en el origen como en el destino. Se preparó un usuario SQL diario local nuevo y se comprobó cada privilegio DML, versión en solo lectura y secuencias sin UPDATE, sin darle CREATE ni administración de roles/bases. El perfil del nodo y sus 29 archivos conservaron hashes. No se inició aplicación web sobre la copia.

Las herramientas Windows 16.15 se descargaron de la distribución portable oficial EDB y solo se extrajeron ejecutables/DLL a `backend/credentials/tools/postgresql-16.15-5/pgsql/bin`; la instalación PostgreSQL 18 existente se conservó. El SHA-256 observado del ZIP es `43bb45f173a6f08cf1d29a97a6d8deb119e8e8093a24c00d2d1001a0ccaa8281`; no se presenta como cotejo con un checksum publicado por el proveedor. El laboratorio usó la imagen oficial `postgres:16`, digest `sha256:9e2cf6287f25c3151f4c9421ccce2b17f3e60061c111a29165e0d2cdd9ff0a97`.

**Regresión final:** 27 PASS en tres archivos (129,21 s), sin omisiones ni fallos en esta selección; incluye 14 casos de respaldo/restauración y regresión de CLI/configuración privada. No es la suite global del proyecto. No hubo cambios frontend ni se repitieron pruebas de entrenamiento. El laboratorio se retiró después de comprobar su ID/etiqueta y que su volumen no estaba compartido; los tres contenedores ajenos se conservaron. El dump y su manifiesto privados permanecen guardados. La base local restaurada fue un ensayo temporal, no un segundo entorno operativo.

Para reproducir las pruebas de respaldo, preparar un PostgreSQL 16 local **exclusivo y descartable**, guardar su URL administrativa en un archivo privado y proporcionar `FAMA_TEST_BACKUP_ADMIN_URL_FILE` con esa ruta y `FAMA_TEST_BACKUP_PG_BIN` con el directorio de herramientas. El host debe ser `127.0.0.1`, base administrativa `postgres` y puerto distinto a 5433; nunca indicar el proxy de Cloud SQL ni un servidor compartido. La fixture crea bases/roles con nombres aleatorios y retira los que creó. Sin estas variables los casos PostgreSQL se omiten. Desde `backend`, con `.env` deshabilitado:

```powershell
$env:PYTHON_DOTENV_DISABLED='1'
& .\.venv\Scripts\python.exe -m pytest --noconftest `
    tests/test_database_backup.py tests/test_cloud_node.py tests/test_installation_configuration.py -q
```

Esta función no programa respaldos, no configura retención, no copia el archivo automáticamente fuera del equipo y no prueba restauración administrada/PITR dentro de Cloud SQL. Las copias automáticas/PITR de la instancia y su ensayo en GCP requieren su configuración y comprobación específicas. Para el entorno oficial hay que fijar frecuencia, retención, ubicación independiente, acceso y responsable de repetir el ensayo.

## Diagnósticos principales

| Código | Resultado |
| --- | --- |
| `database_backup_created` | Archivo y manifiesto producidos; falta ensayar su recuperación si es una copia nueva. |
| `database_restore_verified` | Contenido y esquema recuperados coinciden con el respaldo. |
| `backup_source_busy` | El operador de migraciones posee la exclusión; repetir en otra ventana. |
| `backup_sequences_changed` | Hubo movimiento de secuencias durante la exportación; repetir sin altas. |
| `backup_destination_exists` / `backup_path_invalid` | Conservar la carpeta existente o escoger una ruta absoluta nueva y física. |
| `backup_major_version_mismatch` | Herramientas, respaldo y servidor no tienen la misma versión principal. |
| `backup_integrity_mismatch` | Hash o tamaño distintos; no se escribió en el destino. |
| `restore_source_forbidden` / `restore_target_forbidden` / `restore_target_not_empty` | Origen, base de sistema o destino con contenido rechazados antes de la carga. |
| `restore_failed` | Falló la transacción de carga; revisar permisos, espacio y disponibilidad en el destino. |
| `restore_verification_failed` | Conservar el destino separado para diagnóstico; no ponerlo en servicio. |
| `backup_configuration_invalid` / `database_backup_operation_failed` | Revisar archivos privados, dependencias y conectividad; la respuesta no incluye secretos. |

Referencias: [pg_dump 16](https://www.postgresql.org/docs/16/app-pgdump.html), [pg_restore 16](https://www.postgresql.org/docs/16/app-pgrestore.html), [archivo de contraseñas libpq](https://www.postgresql.org/docs/16/libpq-pgpass.html), [distribución portable EDB](https://www.enterprisedb.com/download-postgresql-binaries), [ADR 0047](../adr/0047-respaldo-logico-y-restauracion-sql-separada.md), [recibo](../receipts/respaldo_postgresql_20261023.json) y [bitácora](bitacora_acceso_e_instalacion.md).
