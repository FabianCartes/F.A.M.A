# ADR 0056 — Auditoría mínima y limpieza transaccional acotada

**Estado:** aceptado. **Fecha:** 18 de octubre de 2026.

## Decisión y alternativas

El usuario confirmó auditoría administrativa sin secretos y limpieza explícita de expirados, con retención inicial de noventa días configurable y lotes de quinientos registros por tabla, máximo mil. Se incorpora un registro de aplicación en BD, no un archivo de cuerpos HTTP, un servicio externo ni un log universal de todas las rutas.

Los eventos usan un vocabulario cerrado, fecha UTC en segundos Unix, resultado e IDs de actor/cuenta/dataset. No admiten texto libre, mensajes de error, emails, IP, contraseñas, hashes de credenciales, tokens, enlaces ni cuerpos de petición. Los IDs siguen siendo información identificable y requieren controles de acceso/retención. El actor se obtiene de la sesión validada; el consumo de recuperación usa el token como capacidad y no atribuye al consumidor la identidad del administrador que lo emitió.

Los eventos de éxito de login, cambios efectivos de cuenta/asignación, recuperación y limpieza participan de la misma transacción que la operación. Si no se puede escribir auditoría, no se confirma el cambio ni se emite una sesión nueva. La alternativa de confirmar primero y escribir después permitiría cambios sin rastro o éxitos fantasma; se rechaza. El helper de creación de usuarios permite flush sin commit a su llamador transaccional, manteniendo su default anterior para consumidores internos.

Los rechazos admitidos de login/recuperación y ciertas denegaciones de negocio se registran sin el texto de entrada. No se crea una fila por cada 429 ni por cada petición rechazada antes de autenticación/validación/admisión, para no convertir la auditoría en un amplificador de saturación. Las lecturas de auditoría no generan eventos nuevos.

Las lecturas autenticadas con un `Origin` explícito ajeno también se rechazan, aunque lleven cookie administrativa. Las lecturas sin ese header conservan el contrato para navegación/consumidores HTTP autorizados; las escrituras siguen exigiéndolo. Esta comprobación se centraliza con la validación de sesión/origen existente y no sustituye la revisión de CORS/proxies de producción.

## Limpieza

Solo un administrador puede solicitar limpieza por HTTP con origen válido; no se agrega tarea automática. Se eliminan sesiones vencidas por duración absoluta o inactividad, recuperaciones/cuotas expiradas y eventos que alcanzaron la antigüedad de retención. La expiración lógica de credenciales sigue funcionando aunque nunca se ejecute la limpieza. La retención de eventos se aplica al ejecutar mantenimiento: no garantiza borrado automático a los noventa días.

Cada DELETE limita candidatos por PK y vuelve a exigir expiración en el predicado exterior. Así una cuota o recuperación renovada no se elimina únicamente por haber aparecido antes como candidata. Los cuatro grupos y el evento de limpieza se confirman juntos. Un fallo revierte las eliminaciones y permite reintentar. La comprobación del administrador se revalida bajo el gate de cuentas; ese gate también se usa para mutaciones de asignaciones auditadas.

## Consecuencias y límites

- Se añade `evento_seguridad`, ID monotónico y un índice temporal de retención; se declaran índices de inactividad de sesión y expiración de recuperación. El DDL/índices se deben migrar explícitamente en BD existentes: `create_all` no los añade por sí solo a tablas ya presentes.
- El endpoint de lectura usa cursor por ID y límite de cien; no calcula conteos globales. La limpieza informa conteos y `has_more`, no garantiza un snapshot estable ante cambios posteriores.
- El lote limita filas eliminadas, no duración, IO, locks o coste del plan de ejecución. Faltan mediciones/planes/timeout en PostgreSQL/Cloud SQL y validación con volumen. Los relojes de workers deben estar sincronizados.
- El registro no es WORM, firmado ni resistente a un administrador de BD que lo modifique. No audita automáticamente SQL externo, bootstrap o todas las operaciones ML/feedback; el alcance HTTP está descrito en el manual.
- Las operaciones cuyo commit o almacenamiento de auditoría falla no pueden dejar allí un evento durable de ese fallo. Devuelven 503 sanitizado; no se recurre a logs con secretos ni se declara éxito.
- Si se pierde la confirmación de un commit remoto, el cliente puede recibir 503 aunque la BD haya confirmado operación y evento. La atomicidad no es garantía de entrega de respuesta ni de exactamente una ejecución por petición; consultar estado y reintentar operaciones idempotentes con esa posibilidad presente.
- No se borran usuarios, datasets, audios, predicciones, asignaciones, pesos, CSV, archivos locales ni objetos GCS. No se ejecuta mantenimiento sobre activos reales en esta unidad.

Contrato, eventos y evidencia: [auditoría y limpieza](../manuales/auditoria_y_limpieza_seguridad.md).
