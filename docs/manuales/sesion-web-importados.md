# Sesión web para recursos importados

La API utiliza la sesión opaca revocable existente como única identidad de navegador. Los endpoints canónicos son `/api/auth/login`, `/api/auth/me` y `/api/auth/logout`; se retira el router redundante `/api/auth/web`. No se emiten ni se aceptan JWT/Bearer para autenticar recursos importados. Esta migración no cambia la política de catálogo, publicación ni asignaciones.

## Contratos HTTP

| Interfaz | Credencial y resultado |
| --- | --- |
| `POST /api/auth/login` | JSON `email` (1–150 caracteres), `password` (1–1024); devuelve solo `user` y cookie opaca `HttpOnly`. Requiere `Origin` exacto. |
| `GET /api/auth/me` | Confirma usuario activo y sesión vigente; 401 si falta, expira o se revoca. |
| `POST /api/auth/logout` | Revoca la sesión del navegador y elimina su cookie; 204 sin cuerpo. Requiere `Origin` exacto. |
| Importación, preparación, entrenamiento, modelos e historial importados | Cookie vigente y propietario exacto. Bearer sin cookie no concede acceso. |
| Recursos legacy | Conservan sus controles vigentes de sesión, rol y asignaciones; esta migración no incorpora una barrera adicional ni convierte propiedad privada en permisos por asignación. |

`Authorization` no autentica ni cambia el usuario de una cookie válida, aunque contenga un antiguo JWT de otro usuario o una credencial inválida. Una cookie inválida nunca recupera acceso mediante esa cabecera. No existe identidad anónima local `-1`: las banderas antiguas de desarrollo no habilitan importaciones anónimas. El rol administrador tampoco concede propiedad sobre importados ajenos.

Las respuestas de autenticación y de los routers privados importados incluyen `Cache-Control: no-store`, también en errores. Los fallos SQL de autenticación devuelven 503 sin exponer consultas ni detalles de conexión. La guarda `expected_user_id`, cuando se solicita, rechaza otra identidad **antes** de refrescar el plazo de inactividad.

Se conserva el flujo ZIP → candidato → arquitectura → preparación explícita → resultado → inicio separado. El catálogo de entrenamiento, inicio, progreso, parada, historial y activación mantienen sus controles existentes de propietario. `checkpoint_persisted` sigue significando evaluación pendiente, no publicación terminada.

## Configuración y persistencia

La sesión requiere `FAMA_WEB_ORIGIN` (origen exacto HTTPS). Solo desarrollo loopback permite HTTP con `FAMA_ALLOW_INSECURE_LOOPBACK=1`. `FAMA_SESSION_MAX_AGE_SECONDS` tiene valor predeterminado 28800; `FAMA_SESSION_IDLE_SECONDS`, 1800. Se exige `1 <= idle <= lifetime <= 2678400`. Cookie segura `__Host-fama_session`; desarrollo HTTP, `fama_session_dev`; ambas `SameSite=Strict`, `HttpOnly`, `Path=/`.

El login conserva límites persistentes: `FAMA_RATE_LIMIT_KEY` debe contener al menos 32 bytes; `FAMA_ACCESS_LIMITS_JSON` permite los límites definidos por el servicio existente. Las cuotas consumen intentos de acceso; un login incorrecto registra un evento denegado. No se almacenan contraseñas ni cookies en auditoría.

**Conservar `JWT_SECRET_KEY`:** el arranque todavía exige esta configuración y ejecuta `ensure_authentication_configured()`. La clave debe contener al menos 32 bytes, no estar en blanco ni usar el valor histórico inseguro. El nombre se mantiene por compatibilidad de configuración; ya no existe emisión, validación ni expiración independiente de JWT en el servicio de autenticación.

El login canónico valida el esquema de sesión **antes** de reservar cuotas o comprobar credenciales. La ausencia o incompatibilidad devuelve 503 sin escribir cuotas, último acceso, auditoría ni sesiones, y sin emitir cookie. `validate_web_sessions(engine)` (`backend/app/services/web_session_schema.py`) es un preflight de solo lectura: no crea ni repara tablas. Las tablas de sesión, cuota y auditoría las crean las revisiones Alembic (`python -m app.schema upgrade --apply`); el script `scripts.migrate_web_sessions` fue retirado.

### Instalación existente

La entrada ligera `app.entrypoint.create_app` comprueba configuración y esquema antes de montar la API operacional. Conserva `/api/installation/status`, `/ready` y el router de instalación cuando existe `FAMA_CONFIG_DIR`; esta migración no elimina ni sustituye ese instalador. El estado de instalación, la autorización del operador y la preparación del esquema siguen sus procedimientos existentes. Un login no instala ni migra automáticamente una base existente.

**Operación real no autorizada por este documento:** respaldar, detener escritores, renovar identidad del destino y autorizar la migración antes de ejecutarla sobre una base existente. Solo SQLite en memoria forma parte de las comprobaciones de desarrollo; no se acredita aquí PostgreSQL operacional.

## Navegador y proxy

El navegador usa la API del mismo origen mediante el rewrite `/api/:path*` existente. `API_URL` selecciona el backend del proxy; una API pública de otro origen no es válida para la sesión web. No guardar credenciales en `localStorage` ni convertir la cookie en Bearer.

El workspace exige identidad confirmada; consulta [acceso web y recuperación](acceso-web.md). `SessionBoundary` no monta vistas privadas mientras comprueba la sesión. Los errores de comprobación y revocación conservan bloqueo, advertencia y reintento, sin afirmar un cierre no confirmado. La sesión y el cierre se presentan en el sidebar usando la misma operación de logout. Un 401 privado durante un cierre pendiente o fallido no sustituye la confirmación de revocación ni elimina su reintento. Las generaciones de sesión evitan que un 401 antiguo invalide una sesión nueva. La guardia de interfaz no sustituye los permisos de las APIs. La migración general de vistas con `fetch` directo queda fuera de esta etapa; no se garantiza invalidación automática para esos clientes.

## Verificación y límites

Desde `backend/`, usar el intérprete validado y `tests/run_isolated_training_checks.py` con los módulos afectados de autenticación e importados; conservar `PYTHONDONTWRITEBYTECODE=1`, `PYTHON_DOTENV_DISABLED=1`, `DATABASE_URL=sqlite://`, `CUDA_VISIBLE_DEVICES=''` y `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` según el [procedimiento de entrenamiento](integracion-flujo-entrenamiento.md).

Los recibos de `docs/receipts/auth-reconciliation-tdd/` son evidencia histórica, no resultados de esta migración. La presencia de comandos en este manual no acredita su ejecución. Estas comprobaciones no incluyen entrenamiento real, instalación real, datos existentes, GCS ni despliegue.
