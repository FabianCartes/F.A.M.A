# Auditoría y limpieza de seguridad — backend

**18 de octubre de 2026.** [ADR 0056](../adr/0056-auditoria-minima-y-limpieza-transaccional-acotada.md). Complementa [cuentas](gestion_cuentas_y_recuperacion.md), [cuotas](limites_login_y_recuperacion.md) y [permisos](permisos_recursos_asignados.md). Sin migración, limpieza, cuentas ni servicios reales operados.

## Lectura de auditoría

`GET /api/security/audit?limit=50&before_id=...`, solo administrador autenticado. Límite de 1–100; cursor opcional entero positivo de 64 bits. Devuelve:

```json
{"events": [], "next_before_id": null}
```

Si una lectura autenticada incluye `Origin`, debe coincidir con `FAMA_WEB_ORIGIN`; un origen explícito ajeno devuelve 403 incluso con cookie administrativa válida. GET sin `Origin` sigue permitido con sesión/rol adecuados. Las escrituras requieren el header. La cadena CORS/Next.js/Uvicorn real debe revisarse igualmente antes de exposición.

Los eventos se ordenan por ID descendente. Para continuar se utiliza el `next_before_id` devuelto; las inserciones nuevas no desplazan las páginas antiguas. No se calcula un total global. Campos públicos de cada evento:

No hay un snapshot transaccional entre peticiones: eventos que se confirmen tarde en otra transacción pueden requerir refrescar las primeras páginas. El ID indica orden de asignación, no un orden total certificado de commits o acciones humanas.

| Campo | Significado |
| --- | --- |
| `id` | Identificador monotónico de evento; admite huecos. |
| `occurred_at` | Segundos Unix UTC generados por el backend, no por el cliente. |
| `action` | Acción del vocabulario cerrado descrito abajo. |
| `outcome` | `success` o `denied`. |
| `actor_id` | Cuenta que actuó cuando la identidad fue validada; null en intentos anónimos, consumo por capacidad o recuperación local del operador. |
| `subject_user_id` | Cuenta afectada cuando hay identidad de destino verificada. |
| `dataset_id` | Dataset de una concesión/revocación, no su nombre o URI. |

Nunca se incluyen nombres personales, emails, IP, cuerpos, contraseñas, hashes de credenciales, tokens ni enlaces de recuperación. Los IDs no son anonimato: permiten correlación con las tablas de dominio y permanecen restringidos a administradores. No se audita la propia lectura, para no generar nuevas páginas mientras se consulta.

## Eventos actuales y atomicidad

| Acción | Cobertura |
| --- | --- |
| `session.login` | Éxito con actor/cuenta validados; rechazo admitido sin atribuir identidad a quien solo escribió un email. |
| `account.created` | Alta administrada efectiva. |
| `account.name_updated`, `account.role_changed` | Cambios efectivos, sin guardar valores del nombre/rol. Incluye denegación de degradación del último administrador. |
| `account.suspended`, `account.reactivated` | Cambios efectivos; incluye denegación de suspensión del último administrador. |
| `account.password_changed` | Éxito o contraseña actual incorrecta de un usuario autenticado; sin guardar ninguno de los valores. |
| `account.recovery_issued` | Emisión administrada exitosa o destino suspendido rechazado. |
| `account.password_reset` | Consumo exitoso con cuenta destino y actor null; token inválido/expirado/reutilizado admitido, sin token o identidad supuesta. |
| `account.operator_recovered` | Recuperación local de un administrador existente; cuenta destino validada y actor null, sin certificar una identidad personal del operador. Comparte transacción con hash, revocaciones y reactivación explícita cuando corresponda. |
| `assignment.granted`, `assignment.revoked` | Cambios efectivos con actor, cuenta y dataset. Una repetición idempotente no añade otra fila. |
| `security.cleanup` | Limpieza confirmada con administrador responsable. |

No hay una fila por rechazo 429. Tampoco se incorporan automáticamente rechazos de origen, formato, autenticación previa, destino inexistente, todas las denegaciones de roles/rutas, lecturas, logout, bootstrap, SQL manual de operadores ni todas las operaciones ML. La [CLI de recuperación local](recuperacion_emergencia_administrador.md) sí registra su operación definida; no convierte consultas SQL externas en eventos. Es auditoría de aplicación de alcance definido, no una captura completa del tráfico ni evidencia WORM/firmada.

Los eventos de éxito se confirman con el cambio. Si falla la auditoría, se revierte la creación/suspensión/cambio de contraseña/recuperación/asignación/limpieza o no se emite la nueva sesión. Se devuelve 503 sanitizado; no hay éxito fantasma ni fallback con cuerpos o secretos. No puede persistirse en esa misma BD un evento del propio fallo de almacenamiento. Los presupuestos de admisión de la unidad anterior ya confirmados siguen consumidos aunque falle después la operación/auditoría.

Estas pruebas reproducen fallos con rollback conocido. Una conexión remota puede perder el acuse después de un commit exitoso: en ese caso operación y evento pueden estar confirmados aunque el cliente reciba 503. No se promete exactamente una ejecución ni ausencia absoluta de efectos tras cualquier 503; comprobar estado y reintentar las operaciones idempotentes. `success` significa confirmación transaccional del servidor, no entrega garantizada al navegador. El registro tampoco conserva valores históricos de nombres/roles ni los conteos de una limpieza; esos conteos están en su respuesta.

## Limpieza explícita

`POST /api/security/cleanup`, solo administrador con sesión vigente y `Origin` permitido. Cuerpo opcional:

```json
{"batch_size": 500}
```

`batch_size` es entero estricto de 1–1000, sin campos extra. Si se omite el cuerpo se usa 500. No es un límite total: aplica a **cada una** de estas cuatro familias, hasta 2000 eliminaciones por defecto o 4000 con el máximo:

1. `sessions`: duración absoluta o inactividad vencidas.
2. `recoveries`: recuperaciones cuyo token expiró.
3. `quotas`: ventanas de cuotas expiradas.
4. `audit`: eventos que alcanzaron la antigüedad de retención.

Respuesta:

```json
{"batch_size":500,"deleted":{"sessions":0,"recoveries":0,"quotas":0,"audit":0},"has_more":false}
```

Si `has_more` es true puede repetirse otro lote; no hay repetición automática. El indicador describe lo observado en esa petición, no evita que aparezcan nuevos expirados después. La operación añade un evento propio nuevo; no elimina eventos recientes para dejar artificialmente el registro vacío.

Se comprueba expiración tanto al seleccionar candidatos como en el DELETE, para no borrar una ventana renovada concurrentemente. No se limpian sesiones, tokens o cuotas vigentes; en particular, una cuota llena vigente sigue respondiendo 429 después. Las eliminaciones y el evento se confirman juntos; ante fallo se revierte todo y se puede reintentar.

No se borran usuarios, historia de negocio, datasets, audios, pesos, asignaciones, archivos ni objetos GCS. No hay nuevo scheduler, worker o cron, y el agente no ejecutó esta ruta sobre tu BD real.

## Retención, esquema y límites operacionales

`FAMA_AUDIT_RETENTION_DAYS`: default **90**, entero entre 1 y 3650. Valor inválido: 503 antes de limpiar. El límite temporal es exacto (`occurred_at <= ahora - días × 86400`). La lectura sigue disponible para diagnosticar configuración inválida.

Cambiar la retención afecta la siguiente limpieza, no migra ni borra por sí solo los eventos. Sin ejecutar mantenimiento pueden conservarse más de noventa días: esto es una política aplicada por acción explícita, no una garantía de borrado automático o cumplimiento legal. La organización debe validar su política institucional.

Se añade la tabla `evento_seguridad` y se declaran índices temporales de retención, inactividad de sesiones y vencimiento de recuperaciones. En una BD existente se necesitan migraciones e índices revisados; `create_all` no actualiza índices de tablas ya existentes. Se compilaron el DDL y los índices para PostgreSQL sin conexión ni ejecución real.

El lote acota filas y resultados, no tiempo, RAM total, IO o duración de locks. Antes del despliegue faltan planes/timeout/mediciones con PostgreSQL/Cloud SQL y volumen, validación de proxies/ingreso y relojes sincronizados. No se acredita por ello el requisito de 50 GB, la latencia hasta pantalla o seguridad integral.

## Evidencia y continuación

Pruebas públicas en `backend/tests/test_security_audit.py`: privacidad, roles/origen, paginación por cursor, eventos de negocio, no duplicación de idempotentes/429, fallos de persistencia y rollback, lotes repetibles, datos vigentes preservados, renovación concurrente de cuota y retención exacta. BD SQLite temporal con FKs, fuentes sintéticas y ningún lifespan productivo.

Focal observada: **32 PASS**, una deprecación (102,49 s). Regresión conjunta y límites de su alcance en [KANBAN](../KANBAN.md). Una prueba concurrente SQLite no reproduce ni certifica todos los intercalados de PostgreSQL; no se declara suite global verde ni se cierran los fallos anteriores de portabilidad/catálogo.

Tras esa focal se reprodujo un GET administrativo con `Origin` ajeno que respondía 200, y se corrigió a 403 mediante la validación compartida. La prueba nueva pasó y se lanzó un cierre conjunto posterior con esa protección incluida; no se suma como si fuera parte de la primera focal.

**Cierre final:** 205 PASS en nueve archivos, tres avisos de deprecación (391,80 s), incluidos 33 casos de auditoría/limpieza. Sin exclusiones en esta selección. Incluye cuotas, cuentas, sesiones, autenticación y recursos asignados; no es la suite global ni revalida los archivos con pendientes de portabilidad/catálogo de las unidades anteriores.

Desde `backend`, con entorno aislado antes de importar:

```bash
DATABASE_URL=sqlite:// PYTHON_DOTENV_DISABLED=1 PYTHONDONTWRITEBYTECODE=1 python -m pytest tests/test_security_audit.py tests/test_access_limits.py tests/test_account_management.py tests/test_web_sessions.py tests/test_auth_service.py tests/test_jwt_validation.py tests/test_auth_configuration.py tests/test_api_auth.py tests/test_resource_access.py -q -p no:cacheprovider
```

Siguiente bloque funcional previsto: pantallas de login centrado con SlicedWaves y navegación/administración, manteniendo la autoridad de permisos en el backend. Setup, recuperación de emergencia del operador, migraciones/configuración real y producción siguen pendientes.
