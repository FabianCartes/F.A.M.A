# Límites de login y recuperación — backend

**18 de octubre de 2026.** [ADR 0037](../adr/0037-cuotas-persistentes-de-login-y-recuperacion.md). Complementa [sesiones](sesiones_web_y_acceso_administrado.md) y [cuentas](gestion_cuentas_y_recuperacion.md). No se ha cambiado `.env`, credenciales, BD real, proxy ni servicios.

**Actualización posterior:** ya están implementadas la [auditoría mínima y limpieza explícita de expirados](auditoria_y_limpieza_seguridad.md). La limpieza no es automática ni se ha ejecutado sobre una BD real. Las menciones de pendientes de auditoría/purga al final corresponden al corte de esta unidad de cuotas; no implican que esté validado el despliegue.

**Ajuste del 23 de octubre de 2026:** por solicitud del operador, la ventana predeterminada por cuenta de login pasa de 900 a **120 segundos**, manteniendo cinco admisiones. Prueba HTTP roja con `Retry-After: 900`, luego verde con `120`, rechazo a los 119 segundos y nuevo acceso al segundo 120. Regresión: 78 pruebas backend y nueve del formulario aprobadas. El proceso real 8010 conserva el código anterior: su reinicio espera la migración `0003_autonomy`, porque la base sigue en `0002_access`. No se modificaron cuotas persistidas ni configuración privada. [Recibo del ajuste](../receipts/limite_login_120s_20261023.json).

## Políticas vigentes en código

**Activado posteriormente el mismo 23 de octubre:** migración `0003_autonomy` aplicada por el operador y backend 8010 reiniciado por Codex. Una identidad sintética inexistente recibió cinco 401 y después 429 con 111 segundos restantes. No se agotaron cuotas de cuentas reales ni se borraron presupuestos previos. [Activación real](../receipts/autonomia_activacion_real_20261023.json); el párrafo anterior conserva el corte previo al reinicio.

| Operación | Clave de política | Presupuesto |
| --- | --- | --- |
| `POST /api/auth/login` | `login_account` | 5 admisiones por cuenta normalizada cada 120 s |
| Misma operación | `login_peer` | 60 admisiones por dirección ASGI observada cada 60 s |
| `POST /api/users/{id}/password-reset` | `recovery_target` | 3 admisiones por cuenta destino cada 900 s |
| Misma operación | `recovery_issuer` | 10 admisiones por administrador autenticado cada 900 s, entre todos los destinos |
| `POST /api/auth/reset-password` | `recovery_peer` | 20 admisiones por dirección ASGI observada cada 900 s |

Se cuentan intentos **admitidos**, también los correctos y los que después fallan por credenciales, cuenta ausente o error de la operación. No son contadores exclusivamente de contraseñas incorrectas. No activan/suspenden cuentas ni revocan sesiones. Recuperar/cambiar contraseña no limpia el presupuesto: un usuario puede tener que esperar para volver a iniciar sesión.

Ventana fija por clave, anclada a la primera admisión. Al alcanzar su vencimiento exacto se reinicia en la siguiente admisión. No es una ventana deslizante: pueden existir ráfagas en el límite entre ventanas. Los rechazos no prolongan el vencimiento.

Si cualquiera de las cuotas aplicables está agotada, se devuelve **429**, `Retry-After` en segundos enteros positivos y `Cache-Control: no-store`, sin cookie nueva ni enlace de recuperación. Se informa el mayor plazo restante de las cuotas agotadas. Las reservas de otras cuotas de esa misma petición se revierten, para no gastar el presupuesto de otra cuenta por un peer ya bloqueado. Un rechazo no reemplaza el último token de recuperación emitido.

La reserva se confirma en una transacción anterior a la verificación de contraseña o modificación de recuperación. Su consumo persiste aunque esas operaciones fallen después. Configuración inválida: **503** genérico; fallo SQLAlchemy: **503** sanitizado. No hay fallback en memoria ni modo abierto por pérdida de BD.

## Configuración pendiente del operador

- **`FAMA_RATE_LIMIT_KEY` obligatoria:** clave secreta UTF-8 de al menos 32 bytes, no vacía. Generar material aleatorio por un canal seguro, distinto del JWT; no copiar las claves sintéticas de pruebas ni guardarla en Git/logs. Mantenerla estable y uniforme entre procesos. No fue generada ni aplicada a tu entorno real.
- **`FAMA_ACCESS_LIMITS_JSON` opcional:** objeto de overrides por política; las no incluidas conservan defaults. Cada entrada requiere exactamente `limit` y `window_seconds`, ambos enteros (no booleanos), con rangos 1–10000 y 1–86400 respectivamente. Claves desconocidas, campos extra, valores inválidos o JSON incorrecto producen 503, no desactivan controles.

Ejemplo de formato, no una configuración recomendada de producción:

```json
{"login_account": {"limit": 5, "window_seconds": 120}}
```

Una política modificada no borra contadores: el límite nuevo aplica a las reservas y el vencimiento existente se conserva hasta abrir la siguiente ventana. Rotar `FAMA_RATE_LIMIT_KEY` crea un espacio de claves distinto y reinicia de hecho los presupuestos; las filas anteriores quedan pendientes de limpieza. No rotar en cada arranque.

Faltan propagación/revisión de configuración de despliegue, migración explícita de `cuota_acceso` y validación PostgreSQL/Cloud SQL. La tabla está registrada en ORM para el `create_all` existente; esto no acredita una migración productiva. Sin la clave explícita, login y las operaciones de recuperación protegidas devuelven 503. Las sesiones ya vigentes y logout mantienen su contrato anterior.

El UPSERT utiliza `RETURNING`: SQLite requiere versión 3.35 o posterior; la observada en estas pruebas es **3.49.1**. Se compiló estáticamente el DDL de la tabla para el dialecto PostgreSQL, sin conectarse ni ejecutar SQL contra PostgreSQL.

## Proxy, privacidad y límites

La cuota usa `request.client.host` del scope ASGI, no lee directamente cabeceras reenviadas. Detrás de Next.js puede agrupar a muchos investigadores bajo la dirección del proxy. No presentarla como IP real certificada ni habilitar confianza indiscriminada en headers para evitar ese agrupamiento. Revisar la cadena proxy/Next.js/Uvicorn y su configuración de confianza antes de exposición. La prueba de headers simulados verifica la aplicación directa, no esa cadena real.

Las claves de la tabla son HMAC de política e identificador. Los emails/IP en claro no se guardan en **esa tabla**; los datos de usuario siguen existiendo en sus tablas propias. No registrar cuerpos de login/recuperación o respuestas con enlaces. HMAC seudonimiza; no elimina las obligaciones de retención y seguridad.

No se limita aquí el tamaño del cuerpo HTTP previo al parsing, ni se cubren todas las rutas autenticadas, abuso distribuido, cuentas atacadas para agotarlas temporalmente, o crecimiento global de identificadores distintos. La expiración es lógica, no purga física: limpiar expirados y limitar recursos de ingreso siguen pendientes. Mantener los relojes de workers sincronizados y validar tiempos de espera/carga de BD antes del despliegue.

## Evidencia

Pruebas HTTP en `backend/tests/test_access_limits.py`: normalización, cuotas por peer/destino/emisor, 429/Retry-After, configuración insegura, vencimiento exacto, no consumo parcial, origen no permitido, concurrencia y persistencia desde otro proceso Python. BD de archivo SQLite temporal con FKs, sin lifespan productivo, red externa ni activos reales. Los tests existentes de commits de credenciales se ajustan para fallar después de la reserva, no en lugar de la mutación que pretenden verificar.

Resultados de cierre en [KANBAN](../KANBAN.md). No son evidencia de concurrencia PostgreSQL/Cloud SQL, rendimiento hasta pantalla, navegador, proxy real ni seguridad integral de producción. Auditoría, limpieza y login/SlicedWaves siguen separados.

**Cierre observado:** 172 PASS en ocho archivos, tres avisos de deprecación (287,05 s), sin exclusiones en esta selección. Incluye 28 casos de cuotas y regresión de cuentas, sesiones, autenticación y permisos; no sustituye los fallos conocidos de otras selecciones ni acredita la suite global.

Desde `backend`, con entorno aislado antes de importar módulos:

```bash
DATABASE_URL=sqlite:// PYTHON_DOTENV_DISABLED=1 PYTHONDONTWRITEBYTECODE=1 python -m pytest tests/test_access_limits.py tests/test_account_management.py tests/test_web_sessions.py tests/test_auth_service.py tests/test_jwt_validation.py tests/test_auth_configuration.py tests/test_api_auth.py tests/test_resource_access.py -q -p no:cacheprovider
```

La clave y configuración de pruebas son explícitas y sintéticas en las fixtures. No usar esa clave en despliegue ni asumir que la prueba configura el entorno real.
