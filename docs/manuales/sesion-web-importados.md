# Sesión web para recursos importados

Esta integración reutiliza la sesión opaca de `aa53e09a9b935f752b01fe464cbc1a5bd10556c0` sin sustituir el contrato Bearer ni exigir login a los recursos legacy. No instala la aplicación, no crea usuarios y no habilita automáticamente el esquema en una base existente.

## Contratos HTTP

| Interfaz | Credencial y resultado |
| --- | --- |
| `POST /api/auth/login`, `GET /api/auth/me` | Contrato Bearer anterior, sin cambios. |
| `POST /api/auth/web/login` | JSON `email`, `password`; devuelve `user` y cookie opaca `HttpOnly`, nunca JWT. Requiere `Origin` exacto. |
| `GET /api/auth/web/me` | Confirma usuario activo y sesión vigente; 401 si falta, expira o se revoca. |
| `POST /api/auth/web/logout` | Revoca sesión del navegador; 204 sin cuerpo. Requiere `Origin` exacto. No revoca JWT independientes. |
| Importación y entrenamiento importado | Cookie o Bearer válidos y propiedad exacta. Si hay ambas credenciales, deben ser válidas y del mismo usuario. |
| Entrenamiento legacy | Conserva acceso previo; una credencial inválida no activa una nueva barrera global. |

No hay fallback desde Bearer inválido a cookie ni desde cookie presente a identidad local `-1`. La excepción local sin credenciales conserva sus restricciones anteriores y nunca habilita entrenamiento importado. El rol administrador no concede propiedad sobre importados ajenos.

El catálogo de entrenamiento, inicio, progreso, parada, historial y activación mantienen sus verificaciones T3; esta unidad únicamente añade el transporte de identidad web. `checkpoint_persisted` sigue significando evaluación pendiente, no publicación terminada.

## Configuración y persistencia

La sesión web requiere `FAMA_WEB_ORIGIN` (origen exacto HTTPS). Solo desarrollo loopback permite HTTP con `FAMA_ALLOW_INSECURE_LOOPBACK=1`. `FAMA_SESSION_MAX_AGE_SECONDS` tiene valor predeterminado 28800; `FAMA_SESSION_IDLE_SECONDS`, 1800. Se exige `1 <= idle <= lifetime <= 2678400`. Cookie segura `__Host-fama_session`; desarrollo HTTP, `fama_session_dev`; ambas `SameSite=Strict`, `HttpOnly`, `Path=/`.

El login web conserva límites persistentes: `FAMA_RATE_LIMIT_KEY` debe contener al menos 32 bytes; `FAMA_ACCESS_LIMITS_JSON` permite los límites definidos por el servicio existente. Las cuotas consumen intentos de acceso; un login incorrecto registra un evento denegado. No se almacenan contraseñas ni cookies en auditoría. Los JWT conservan su configuración `JWT_SECRET_KEY` y su expiración independiente.

Las tablas `sesion_web`, `cuota_acceso` y `evento_seguridad` se excluyen del bootstrap. El migrador público `scripts.migrate_web_sessions.migrate_web_sessions(engine, writers_stopped=True)` valida el esquema existente y crea solo tablas ausentes. No modifica tablas incompatibles ni migra propiedad de datasets. `validate_web_sessions(engine)` es un preflight de solo lectura. La ausencia o incompatibilidad produce 503 sin crear una cookie.

**Operación real no autorizada por este documento:** respaldar, detener escritores, renovar identidad del destino y autorizar la migración antes de usar ese migrador en una base existente. Solo SQLite en memoria forma parte de las comprobaciones de desarrollo; no se acredita aquí PostgreSQL operacional.

## Navegador y proxy

El navegador usa la API del mismo origen mediante el rewrite `/api/:path*` ya existente. `API_URL` selecciona el backend del proxy; una URL pública de API de otro origen no es válida para la sesión web. No guardar credenciales en `localStorage` ni convertir la cookie en Bearer.

La pantalla de acceso y los componentes se adaptan de la implementación existente, sin su instalador, recuperación de contraseñas ni política global de asignaciones. Los errores de configuración no redirigen a un instalador ausente. Para el MVP se ocultan el aviso «Acceso legacy disponible» y el enlace «Continuar con recursos legacy», sin eliminar su implementación. El inicio de sesión y sus comprobaciones se conservan. Este cambio es solo visual: no bloquea el acceso directo al workspace ni cambia los permisos de las rutas legacy; la política global de acceso queda como trabajo futuro.

## Verificación y límites

Comandos backend: desde `backend/`, usar el intérprete validado y `tests/run_isolated_training_checks.py` con `tests/test_web_session_integration.py` y `tests/test_web_imported_training.py`; conservar `PYTHONDONTWRITEBYTECODE=1`, `PYTHON_DOTENV_DISABLED=1`, `DATABASE_URL=sqlite://`, `CUDA_VISIBLE_DEVICES=''` y `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` según el [procedimiento de entrenamiento](integracion-flujo-entrenamiento.md).

Evidencia de los ciclos y regresiones: `docs/receipts/auth-reconciliation-tdd/`. El recibo de cierre documentará resultados y exclusiones observados; la presencia de comandos en este manual no acredita su ejecución. No incluye entrenamiento real, instalación, datos existentes, GCS ni despliegue.
