# Recuperación de emergencia del administrador

Bloque del 23 de octubre de 2026 en `fix/afinamiento-integral`. Se utiliza cuando una cuenta administradora existente perdió acceso y no puede recurrir a otro administrador. La operación se ejecuta en el terminal del responsable del backend, con el perfil privado seleccionado y permisos SQL existentes. El login web y el asistente de instalación conservan sus controles.

## Alcance y autoridad

La CLI permite inspeccionar una cuenta y restablecer su contraseña. Mantiene su ID, correo, rol, nombre, historia y asignaciones. Si está suspendida, exige `--reactivate`. No crea administradores, no asciende investigadores, no adopta instalaciones incompletas ni repara esquemas incompatibles.

Controlar el perfil privado del backend y su identidad SQL de escritura equivale a disponer de autoridad técnica sobre esas cuentas. Este procedimiento asume un servidor administrado por una persona de confianza. Las personas con acceso exclusivamente web no deben recibir ese perfil ni sus credenciales SQL. Los roles web no restringen a quien ya controla SQL o el proceso del servidor.

## 1. Inspeccionar sin cambiar nada

Desde `backend`, para el perfil de pruebas:

```powershell
& .\.venv\Scripts\python.exe -m app.node `
    --config-dir installation/cloud-pruebas/native recover-admin `
    --email '<correo-del-administrador>'
```

También se puede usar `--user-id 1` en lugar de `--email`; las opciones son excluyentes. El correo se busca normalizado, pero una coincidencia histórica ambigua se rechaza: revisar los registros y seleccionar el ID correcto, sin fusionar ni adivinar cuentas.

La respuesta `administrator_recovery_ready` muestra base, ID, correo, rol, estado y `reactivation_required`. No cambia contraseña, sesiones, recuperaciones, auditoría, cuotas ni el cierre del asistente. Comprobar que la base y la persona corresponden al incidente antes de continuar. La configuración admite PostgreSQL con `sslmode` como parámetro de URL; otros parámetros de conexión se rechazan para impedir sustituir el destino confirmado.

Si la base no está disponible, primero recuperar su conectividad. Si el esquema no es compatible, investigar o restaurar conforme a la [guía SQL](respaldo_y_restauracion_postgresql.md). No reabrir el asistente ni editar a mano `installation.json` como forma de recuperar una contraseña.

## 2. Preservar el estado antes de intervenir

Guardar una copia conforme a la [guía de respaldo](respaldo_y_restauracion_postgresql.md), en una carpeta privada nueva y en una ventana adecuada. La copia contiene información de cuentas y credenciales temporales. Conservar el responsable y motivo del incidente en el registro institucional correspondiente; la auditoría de la aplicación no guarda texto libre ni acredita el nombre de la persona que controla el terminal.

## 3. Aplicar desde un terminal interactivo

Para una cuenta activa, después de revisar el resultado anterior:

```powershell
& .\.venv\Scripts\python.exe -m app.node `
    --config-dir installation/cloud-pruebas/native recover-admin `
    --email '<correo-del-administrador>' `
    --apply --confirm-database fama_pruebas
```

La CLI solicita el correo de confirmación y la contraseña nueva dos veces. La contraseña tiene entre 12 y 1024 caracteres y no puede estar formada solo por espacios. No se recorta ni se normaliza. Se lee con entrada oculta; no hay parámetro de contraseña ni archivo de contraseña nueva. Se exige terminal interactivo y se rechaza una lectura que no pueda ocultarla. Ctrl+C/EOF cancela antes de aplicar.

Si la cuenta está suspendida y corresponde reactivarla, añadir `--reactivate` explícitamente. Usar esa opción sin `--apply` conserva la inspección de solo lectura. Para el entorno oficial, sustituir tanto perfil como nombre confirmado por los que indique su inspección; no reutilizar por suposición los nombres del ejemplo.

`administrator_recovered` confirma el cambio. La respuesta incluye base, ID y si hubo reactivación; no devuelve contraseña, hash, cookie ni token. Una cancelación durante la entrada de datos o un error de confirmación no modifica cuentas. La CLI no inicia una sesión automáticamente.

Si se interrumpe la operación después de entrar en la fase de aplicación o se pierde su conexión SQL, puede devolver `administrator_recovery_outcome_unknown`. Comprobar el login y la auditoría antes de repetir: ese resultado no afirma ni éxito ni reversión. La prueba de desconexión de este bloque corta una conexión mientras espera el gate; no simula una pérdida de confirmación después de un commit ya ejecutado.

## 4. Comprobar el acceso y la auditoría

1. Abrir el login habitual e ingresar con la contraseña elegida localmente.
2. Revisar el perfil y el acceso administrativo.
3. En **Administración → Auditoría y mantenimiento**, comprobar **Acceso recuperado por el operador** para ese ID. Si se reactivó, aparece también **Cuenta reactivada**.

La operación revoca todas las sesiones y enlaces de recuperación de esa cuenta. Las sesiones de otros usuarios permanecen vigentes. Las cuotas de acceso se conservan: si aparece HTTP 429, respetar `Retry-After`; cambiar otra vez la contraseña no evita esa espera.

El evento tiene `actor_id: null` porque no hubo una sesión administradora actuando. El tipo de evento identifica el canal del operador; no identifica por sí solo a la persona que ejecutó el comando. Un fallo al registrar la auditoría revierte contraseña, revocaciones y reactivación.

## Consistencia y límites

La identidad y el rol se consultan nuevamente bajo el gate de cuentas, después de la entrada del terminal. Si otro administrador degradó a la cuenta mientras el operador confirmaba, la recuperación se rechaza y no la asciende de nuevo. El login condicional y las revocaciones mantienen el protocolo transaccional existente.

El procedimiento no exige detener el backend: las sesiones se invalidan en SQL. No soluciona pérdida de credenciales SQL/IAM, archivos privados inaccesibles, una base dañada, desaparición de la cuenta administradora o pérdida de su rol. Esos casos requieren diagnóstico o restauración. No hay nueva ruta de recuperación HTTP, clave maestra, envío de correo ni modificación automática durante el arranque.

La confirmación comprueba perfil/base y cuenta; no certifica por sí sola la identidad de una instancia remota mal configurada con el mismo nombre de base. La protección del servidor, sus credenciales y el destino del proxy siguen siendo responsabilidad operativa.

## Diagnósticos

| Código | Acción del operador |
| --- | --- |
| `administrator_recovery_ready` | Revisar destino y cuenta; la consulta no aplicó cambios. |
| `administrator_recovered` | Acceso restablecido; iniciar sesión y revisar auditoría. |
| `administrator_recovery_database_confirmation_required` | Confirmar el nombre exacto mostrado por la inspección. |
| `administrator_recovery_identity_mismatch` / `identity_ambiguous` | Revisar correo/ID; no asumir ni fusionar identidades. |
| `administrator_recovery_target_not_found` / `administrator_required` | No hay una cuenta elegible; investigar/restaurar, no promover usuarios. |
| `administrator_recovery_reactivation_required` | Una cuenta suspendida necesita una decisión explícita de reactivación. |
| `administrator_recovery_password_invalid` / `password_mismatch` | Volver a introducir una contraseña admitida y su confirmación. |
| `administrator_recovery_interactive_terminal_required` | Ejecutar desde el terminal del operador con entrada oculta disponible. |
| `administrator_recovery_cancelled` | Se canceló antes de aplicar. |
| `administrator_recovery_outcome_unknown` | Verificar login/auditoría antes de repetir; la conexión o la operación se interrumpió durante la fase de aplicación. |
| `administrator_recovery_installation_not_completed` / `schema_not_current` | Resolver instalación/esquema mediante sus procedimientos propios. |
| `administrator_recovery_configuration_invalid` / `unavailable` | Revisar configuración, conexión y permisos; la salida omite detalles secretos. |

Algunos códigos de la tabla se abrevian tras `/`; todos llevan el prefijo `administrator_recovery_`.

## Verificación de este bloque

Las pruebas utilizan PostgreSQL 16 local exclusivo, perfiles privados sintéticos, CLI y HTTP autenticado. Únicamente se sustituye la entrada física del terminal; hashes, transacciones, revocaciones y conexiones son reales. Cubren cuenta activa/suspendida, nueva contraseña, sesiones ajenas, enlace antiguo, cuotas conservadas, reversión por permisos de auditoría, confirmaciones erróneas, esquema/instalación incompatible y contención de dos escritores.

**Resultado final:** 85 PASS en cuatro archivos backend (222,55 s), sin SKIP ni fallos en esta selección; veinte casos corresponden a la recuperación PostgreSQL. Frontend: veinte pruebas administrativas aprobadas (13,00 s), TypeScript y lint focal de panel/prueba sin diagnósticos. No se declara suite global. La entrada física del terminal se sustituyó en las pruebas; no se pidió teclear una contraseña real para ensayar la recuperación. El laboratorio y su volumen exclusivo se retiraron después de comprobar ID, etiqueta, imagen y ausencia de montajes compartidos; los contenedores existentes se conservaron.

La comprobación sobre `fama_pruebas` utilizó exclusivamente la inspección del administrador ID 1: activo y con rol administrador, sin pedir ni cambiar su contraseña. Las huellas de cuentas/credenciales, perfil, 29 archivos locales y dump SQL anterior quedaron conservadas. No se comparó el vencimiento deslizante de inactividad, que puede actualizar el HTTP en vivo. El restablecimiento efectivo se ensayó únicamente con cuentas sintéticas locales; no se reinició el nodo ni se accedió a GCS. [ADR 0066](../adr/0066-recuperacion-local-de-administradores-existentes.md), [evidencia](../receipts/recuperacion_emergencia_20261023.json) y [bitácora](bitacora_acceso_e_instalacion.md).

Para reproducir las pruebas, preparar PostgreSQL 16 local exclusivo y descartable, guardar su URL administrativa en un archivo privado e indicar su ruta mediante `FAMA_TEST_RECOVERY_ADMIN_URL_FILE`. Se exige host `127.0.0.1`, base administrativa `postgres` y puerto distinto a 5433; no usar el proxy de Cloud SQL ni un servidor compartido. La fixture crea y retira sus propias bases y roles aleatorios. Sin esa variable se omiten los casos PostgreSQL. Desde `backend`, con `PYTHON_DOTENV_DISABLED=1` y `DATABASE_URL=sqlite://` para aislar la colección de las pruebas web existentes:

```powershell
& .\.venv\Scripts\python.exe -m pytest --noconftest `
    tests/test_operator_recovery.py tests/test_account_management.py `
    tests/test_security_audit.py tests/test_cloud_node.py -q
```
