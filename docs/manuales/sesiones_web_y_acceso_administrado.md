# Sesiones web y acceso administrado — implementación parcial

**18 de octubre de 2026.** Primer bloque backend implementado y probado con SQLite temporal. No hay despliegue, acceso a Cloud SQL/GCS ni cambios en cuentas reales. Decisión: [ADR 0034](../adr/0034-sesiones-web-revocables-y-registro-administrado.md).

**Actualización posterior:** el segundo bloque ya integra sesión obligatoria y asignaciones en las rutas funcionales; ver [permisos sobre recursos asignados](permisos_recursos_asignados.md). La lista de siguientes pasos y la advertencia de rutas sin protección al final describen el corte del primer bloque, no el estado del segundo. Siguen pendientes UI, gestión integral de cuentas, setup y validación/despliegue de producción.

**Tercer bloque:** ya existe [gestión backend de cuentas y recuperación administrada](gestion_cuentas_y_recuperacion.md), con revocaciones y protección del último administrador. El login web comprueba credenciales y crea sesión en una sola transacción para evitar carreras con cambios de contraseña. Las menciones de gestión pendiente abajo corresponden al corte inicial; siguen pendientes sus pantallas y los controles operacionales descritos en el manual nuevo.

## Contrato HTTP actual

| Operación | Resultado |
| --- | --- |
| `POST /api/auth/login` | Recibe email/password JSON; devuelve `{user: ...}` y cookie HttpOnly, nunca `access_token`. Credenciales incorrectas o cuenta inactiva: 401 genérico. |
| `GET /api/auth/me` | Perfil de la sesión cookie vigente; sin sesión, vencida o usuario inactivo: 401. Bearer JWT no concede acceso. |
| `POST /api/auth/logout` | Revoca la sesión presentada y borra cookie; 204, también sin sesión. No detiene entrenamientos. |
| `POST /api/auth/register` | Solo administrador vigente; anónimo 401, investigador 403, alta válida 201. Cuentas nuevas requieren contraseña de 12 a 1024 caracteres, correo hasta 150 y nombre de 2 a 150. No modifica contraseñas anteriores. |

Toda escritura exige `Origin` exactamente igual a `FAMA_WEB_ORIGIN`; origen ausente/no coincidente: 403. Las cuatro rutas envían `Cache-Control: no-store`, incluyendo errores. Validaciones no devuelven el cuerpo con contraseñas. Errores SQLAlchemy generan 503 sanitizado. Si falla el commit de autenticación, no se emite una sesión después del rollback.

## Configuración prevista (no aplicada al entorno real)

| Variable | Significado |
| --- | --- |
| `FAMA_WEB_ORIGIN` | Obligatoria. Origen público como `https://fama.example.org`, sin ruta, barra final, usuario, query ni fragmento. No es la URL interna entre Next.js y FastAPI. |
| `FAMA_SESSION_MAX_AGE_SECONDS` | Duración absoluta, default 28800 (8 h). |
| `FAMA_SESSION_IDLE_SECONDS` | Inactividad, default 1800 (30 min). Debe ser positiva y no superar duración absoluta. |
| `FAMA_ALLOW_INSECURE_LOOPBACK` | Solo `1` habilita un origen HTTP cuyo host sea localhost, 127.0.0.1 o ::1 para desarrollo. No habilita HTTP en LAN/producción. |

La duración absoluta no puede superar 31 días. Configuración inválida: 503 sin cookie. Sesiones opacas no necesitan `JWT_SECRET_KEY`; las utilidades JWT legacy siguen exigiéndola. El bootstrap existente sigue requiriendo credenciales explícitas del operador: todavía no existe el asistente web.

**Actualización del 21 de octubre:** Compose transmite la configuración de sesión y cuotas, y el arranque ya no ejecuta `create_all`. Las tablas se preparan mediante migraciones explícitas probadas con PostgreSQL temporal; ver [preparación de instalación y migraciones](preparacion_instalacion_y_migraciones.md). La configuración real `.env` no se ha modificado. Esta evidencia no acredita Cloud SQL ni despliegue institucional.

## Evidencia reproducible

Desde `backend`, con entorno aislado antes de importar módulos:

```bash
DATABASE_URL=sqlite:// PYTHON_DOTENV_DISABLED=1 PYTHONDONTWRITEBYTECODE=1 python -m pytest tests/test_web_sessions.py tests/test_auth_service.py tests/test_jwt_validation.py tests/test_auth_configuration.py tests/test_api_auth.py -q -p no:cacheprovider
```

Resultado observado: **98 PASS**, un aviso de deprecación Starlette/httpx. Incluye 32 casos de sesiones y 66 de regresión/autenticación. RED/GREEN observado para cookie sin Bearer, cierre del autorregistro, origen estricto, logout/rotación, no-cache en errores, fallo de BD, campos inválidos y commit fallido. Además se verifican vencimiento exacto absoluto/inactividad, suspensión y configuración inválida. `test_api_auth.py` usa ahora router-only: no importa `main`, carga pesos, arranca workers ni ejecuta lifespan productivo.

## Siguiente trabajo y prohibición de exposición prematura

1. Agregar asignaciones persistidas usuario–dataset y aplicar permisos a todas las rutas, listados, modelos, predicciones y feedback; retirar identidad del body/default 1 en HTTP. Capturar propiedad del trabajo para progreso/cancelación.
2. Gestión de cuentas, suspensión con revocación persistida, cambio de contraseña y preservación del último administrador. Límites de intentos con soporte multiproceso, auditoría y limpieza de sesiones expiradas.
3. Login centrado con SlicedWaves y navegación protegida. La dependencia web no está aplicada al resto de rutas: ocultar la UI no resolvería esa brecha.
4. Asistente inicial protegido por posesión del nodo, estado persistente separado de salud GCS y secretos institucionales fuera del contenedor efímero.
5. Migraciones explícitas, configuración Compose/proxy/CORS y PostgreSQL/Cloud SQL de pruebas; después, migración real solo con autorización, respaldo y restauración comprobados.

Hasta completar estos controles, **las rutas funcionales de datos/ML siguen sin aislamiento general**. Este bloque no certifica seguridad integral, disponibilidad cloud, mitigación de fuerza bruta ni preparación para producción.
