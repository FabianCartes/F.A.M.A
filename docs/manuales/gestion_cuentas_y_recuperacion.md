# Gestión de cuentas y recuperación — backend

**Actualización de interfaz, 20 de octubre de 2026:** ya existe administración visual y cambio de contraseña propia; `/reset-password` se implementó en ACCESO-4A. Ver [manual de administración](administracion_visual.md). Las referencias posteriores a UI pendiente conservan el corte original del bloque backend; no describen la interfaz vigente. No se ha configurado envío de correo ni recuperación de emergencia.

**18 de octubre de 2026.** Complementa [sesiones web](sesiones_web_y_acceso_administrado.md), [permisos de recursos](permisos_recursos_asignados.md) y [ADR 0054](../adr/0054-gestion-de-cuentas-y-recuperacion-administrada.md). Sin cuentas, BD, correo o servicios reales modificados.

**Actualización posterior:** login y recuperación ya incorporan [cuotas persistentes de acceso](limites_login_y_recuperacion.md), con nueva clave HMAC explícita y respuestas 429/Retry-After. Las reservas se confirman antes de la transacción de credenciales, incluidos intentos que fallan después. La lista de pendientes del corte inicial al final debe leerse junto a esta actualización; auditoría, purga y validación de producción siguen pendientes.

**Actualización de auditoría:** las operaciones de cuentas y recuperación ahora se registran junto con su transacción y existe mantenimiento acotado explícito; ver [auditoría y limpieza](auditoria_y_limpieza_seguridad.md). No se registran secretos, no hay scheduler y no se operó sobre cuentas/BD reales. UI, emergencia del operador y validación productiva continúan pendientes.

**Acceso visual (19 de octubre):** `/login` y `/reset-password` ya están implementados; ver [acceso web y SlicedWaves](acceso_web_y_sliced_waves.md). La capacidad se retira del fragmento y se consume sin storage ni login automático. Las menciones de pantalla de recuperación ausente abajo describen el corte backend anterior; siguen pendientes los paneles administrativos y la validación real de navegador/servicios.

## Operaciones

| Método y ruta | Autorización y contrato |
| --- | --- |
| `POST /api/auth/register` | Administrador vigente crea cuenta; mismo contrato previo, contraseña de 12–1024 caracteres no formada solo por espacios. No actualiza cuentas existentes. |
| `GET /api/users?limit=50&offset=0` | Solo administrador. `{users, total, limit, offset}`; orden por ID, límite 1–100 y offset no negativo acotado. Incluye inactivos, nunca hashes o tokens. |
| `PATCH /api/users/{id}` | Solo administrador. Uno o más campos: `nombre_completo`, `rol`, `activo`. No permite email, contraseña/hash, campos extra, null explícito ni bool ambiguo. Nombre recortado de 2–150 caracteres, roles exactos y estado booleano. ID entero positivo de 32 bits. |
| `POST /api/auth/change-password` | Usuario autenticado. JSON `current_password`, `new_password`. Contraseña actual incorrecta: 400 sin cambios. Éxito: 204, revoca todas sus sesiones/recuperaciones y elimina la cookie del navegador solicitante. |
| `POST /api/users/{id}/password-reset` | Solo administrador; cuenta destino debe estar activa. Devuelve `{reset_url, expires_in: 900}` y revoca sesiones/recuperaciones anteriores. Cuenta inactiva: 409. No envía correo ni cambia todavía la contraseña. |
| `POST /api/auth/reset-password` | Presentación del token de recuperación, sin sesión requerida. JSON `token`, `new_password`. Éxito: 204, contraseña cambiada y sesiones revocadas. Token inválido, usado, expirado o cuenta no activa: 400 genérico. No inicia sesión. |

Todas las escrituras exigen `Origin` coincidente con `FAMA_WEB_ORIGIN`. Todas las respuestas, incluidos errores, llevan `Cache-Control: no-store`. Errores de validación no incluyen cuerpos con contraseñas/tokens. Fallos SQLAlchemy: 503 sanitizado. Listado y modificaciones administrativas rechazan anónimos (401) e investigadores (403); consultar perfil propio sigue disponible en `/api/auth/me`.

No existe DELETE de usuario. Suspender conserva IDs, historia y asignaciones, sin cancelar trabajos. Reactivar no recupera sesiones/tokens anteriores; las asignaciones explícitas conservadas volverán a aplicarse al iniciar una sesión nueva. Cambiar efectivamente rol o estado revoca sesiones/tokens; cambiar solo nombre o reiterar valores no lo hace.

## Último administrador y recuperación

No se permite suspender ni degradar al último administrador activo (409). Puede modificarse a sí mismo si existe otro administrador activo; una degradación/suspensión efectiva invalida también su sesión actual. Las mutaciones vuelven a verificar la autorización después de adquirir el gate transaccional de cuentas.

El administrador debe verificar la identidad del destinatario fuera de la aplicación antes de emitir recuperación. El enlace utiliza la forma `ORIGEN/reset-password#token=...`; el fragmento evita incluir el secreto en la URL recibida por el servidor o en el referrer. **La pantalla `/reset-password` aún no está implementada**: actualmente se consume mediante el endpoint JSON. La futura pantalla deberá leer y limpiar el fragmento sin guardarlo en storage ni enviarlo a analítica. No registrar cuerpos ni respuestas de estas operaciones en logs de proxy/aplicación.

El enlace es una credencial temporal: entregarlo solo por un canal institucional seguro. Reemitir invalida el anterior. También lo invalidan suspensión/reactivación, cambio de rol, cambio de contraseña y consumo exitoso. Antes del consumo la contraseña actual continúa válida; cualquier sesión nueva obtenida con ella será revocada al consumirse la recuperación. Un fallo de commit no consume el token ni cambia la contraseña.

Si no queda ningún administrador capaz de autenticarse, el flujo web depende de la [recuperación de emergencia del operador](recuperacion_emergencia_administrador.md), incorporada el 23 de octubre. Actúa sobre un administrador existente desde el terminal privado del servidor; no reabre el setup ni crea/promueve cuentas. Las referencias de los cortes anteriores a emergencia pendiente conservan su alcance histórico.

## Persistencia y despliegue pendiente

`control_cuentas` contiene una fila técnica con ID 1 para serializar mutaciones entre procesos; su primera escritura se realiza dentro de la transacción de la operación. `recuperacion_cuenta` contiene como máximo una recuperación pendiente por usuario, con digest y vencimiento. No se persiste el enlace ni el token original.

El gate no es un mutex local: PostgreSQL bloquea su fila y SQLite serializa la escritura. Las verificaciones de último administrador, mutación y revocaciones se confirman juntas. El login bloquea condicionalmente la fila de usuario con el hash aceptado y conserva la transacción hasta insertar la sesión; no utiliza el gate global para cada login.

No se ejecutaron migraciones sobre PostgreSQL local ni Cloud SQL. Las tablas ORM están registradas para el `create_all` existente, pero no reemplaza migraciones revisadas, respaldo/restauración y pruebas PostgreSQL antes del despliegue. No se cambiaron `.env`, credenciales ni bootstrap.

## Evidencia y pendientes

Pruebas públicas en `backend/tests/test_account_management.py`, con SQLite de archivo, conexiones independientes, FKs habilitadas y clientes HTTP de prueba. Incluyen revocación permanente, protección del último administrador, degradación concurrente, consumo único/caducidad exacta/reemisión de recuperación, rollback con reintento, campos/paginación/origen inválidos y creación administrada. Se reprodujo y corrigió una sesión emitida con contraseña antigua durante un cambio concurrente; no se interpreta esa prueba SQLite como validación PostgreSQL.

Resultados de la regresión en [KANBAN](../KANBAN.md). Siguen pendientes UI de acceso/cuentas/recuperación y SlicedWaves, límites persistentes de intentos/emisión, auditoría sin secretos, limpieza de expirados, setup protegido, migraciones y validación de producción. Los fallos de portabilidad/catálogo de la unidad anterior no se consideran resueltos por estas pruebas.

**Cierre observado:** 144 pruebas aprobadas en siete archivos, tres deprecaciones (229,94 s); incluye 29 casos de gestión de cuentas y regresión de sesiones, autenticación y recursos asignados. Sin exclusiones en esta selección. No incluye los archivos de portabilidad/catálogo pendientes de la unidad anterior ni acredita la suite completa.

```bash
DATABASE_URL=sqlite:// PYTHON_DOTENV_DISABLED=1 PYTHONDONTWRITEBYTECODE=1 python -m pytest tests/test_account_management.py tests/test_web_sessions.py tests/test_auth_service.py tests/test_jwt_validation.py tests/test_auth_configuration.py tests/test_api_auth.py tests/test_resource_access.py -q -p no:cacheprovider
```

Ejecutado desde `backend`. Compilación del DDL para dialecto PostgreSQL comprobada por separado, sin conexión ni ejecución contra PostgreSQL/Cloud SQL. Sin frontend, benchmarks reales, despliegue, envío de correo ni modificación de cuentas reales.
