# ADR 0037 — Cuotas persistentes de login y recuperación

**Estado:** aceptado. **Fecha:** 18 de octubre de 2026.

## Decisión y alternativas

Antes de incorporar pantallas públicas, el usuario confirmó límites temporales configurables para login y recuperación, sin suspensión automática de cuentas. Los contadores en memoria se descartan porque reinicios y varios procesos permitirían multiplicar el presupuesto. No se incorpora Redis ni otro servicio real: las reservas se persisten en la misma BD mediante UPSERT condicional, compatible con PostgreSQL y SQLite con `RETURNING`.

Cada operación reserva todas sus cuotas en una transacción y ordena sus claves para evitar inversión de locks entre esas reservas. Si una cuota está agotada se revierten las reservas de las demás y se responde 429 con `Retry-After`; el rechazo no prolonga la ventana. Una admisión se confirma antes de verificar credenciales o modificar recuperación: los intentos admitidos correctos e incorrectos cuentan, y un error posterior no devuelve el presupuesto. El fallo de configuración/BD no habilita fallback local ni acceso abierto.

Se utilizan ventanas fijas ancladas a la primera admisión de cada clave, no una ventana deslizante. En el vencimiento exacto se abre una nueva ventana. Se acepta la posibilidad de ráfagas entre ventanas como trade-off inicial simple y verificable; no se promete protección integral contra abuso distribuido.

## Identidad y privacidad

`cuota_acceso` solo conserva clave HMAC-SHA256, contador y vencimiento; no guarda emails, direcciones observadas, contraseñas ni tokens en claro. Se exige `FAMA_RATE_LIMIT_KEY` explícita, distinta de la clave JWT, sin valor secreto predeterminado. Son datos seudonimizados, no garantía de anonimato. Rotar esa clave deja inaccesibles las cuotas anteriores hasta su purga y permite comenzar presupuestos nuevos: no rotarla por request/reinicio y usar configuración uniforme entre workers.

La identidad de login se normaliza igual que el usuario (`strip/lower`) y se valida contra la longitud del esquema/UTF-8 antes de calcular HMAC. La cuenta origen de emisión se obtiene de la sesión y el destino del ID de ruta validado. El token de recuperación no forma parte de ninguna clave de cuota.

No se leen directamente `Forwarded`/`X-Forwarded-For`. La dirección observada proviene del scope ASGI; puede representar al proxy y por ello su cuota es complementaria, no una identificación certificada del investigador. Deben validarse también las opciones de proxy de Uvicorn y la cadena de reescrituras: un servidor que reconstruya ese scope desde cabeceras no verificadas puede debilitar la política.

## Alcance y consecuencias

- Políticas iniciales: login 5/cuenta/900 s y 60/peer/60 s; emisión de recuperación 3/destino/900 s y 10/administrador/900 s; consumo 20/peer/900 s.
- Las solicitudes necesitan origen y payload válidos; las no autorizadas para emitir recuperación se rechazan antes de reservar. No es un límite global previo al parsing HTTP ni de RAM/CPU/concurrencia.
- Una cuenta o contraseña recuperada no reinicia cuotas; una sesión vigente no se revoca por un 429. Logout, consulta de perfil y cambio de contraseña autenticado conservan sus controles existentes, sin cuotas nuevas en esta unidad.
- Se añade una transacción de reserva antes de la operación protegida. Preparar DDL/configuración y medir impacto de latencia/carga contra PostgreSQL antes de desplegar; las pruebas SQLite, incluso concurrentes y desde otro proceso, no acreditan operación Cloud SQL.
- Siguen pendientes auditoría sin secretos, purga acotada de filas expiradas y controles de proxy/ingreso. La expiración lógica no elimina filas ni limita la cardinalidad global de identificadores admitidos.

Configuración, contrato y verificación: [límites de acceso](../manuales/limites_login_y_recuperacion.md).
