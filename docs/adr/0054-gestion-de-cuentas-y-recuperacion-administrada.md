# ADR 0054 — Gestión de cuentas y recuperación administrada

**Estado:** aceptado. **Fecha:** 18 de octubre de 2026.

## Decisión y alternativas

El acceso es exclusivamente web y las cuentas se crean por administradores. Se agrega gestión backend de nombre, rol y suspensión/reactivación, sin borrado físico ni reasignación de historia. Los cambios efectivos de rol/estado y los cambios de contraseña revocan todas las sesiones y recuperaciones pendientes de la cuenta dentro de la misma transacción. Cambiar solo el nombre o reiterar el mismo estado no revoca sesiones.

Como todavía no existe correo institucional configurado, la recuperación no será un formulario público que envíe contraseñas ni un servicio SMTP supuesto. El administrador verifica la identidad por un canal institucional, emite una capacidad aleatoria de 256 bits, de un solo uso y quince minutos de duración, y entrega el enlace por un canal seguro. La BD solo conserva SHA-256 del token. La respuesta administrativa es no cacheable; el token viaja en el fragmento del enlace, no en su query. Consumirlo cambia la contraseña, no activa cuentas ni inicia sesión automáticamente. Una nueva emisión reemplaza la anterior y revoca las sesiones existentes, sin invalidar la contraseña actual antes del consumo.

## Invariantes transaccionales

- Debe quedar al menos un administrador activo. Un lock local de Python no basta entre procesos: las mutaciones de cuentas se serializan mediante la fila única `control_cuentas`, con escritura transaccional compatible con PostgreSQL/SQLite. Después de adquirirla se revalidan sesión, estado y rol del actor. La creación administrada participa del mismo protocolo.
- La emisión/consumo de recuperación y los cambios de cuenta/contraseña comparten ese protocolo. Token consumido y contraseña/revocaciones se confirman o revierten juntos; no se consume el token si falla el commit.
- La comprobación de credenciales web y la creación de sesión comparten una transacción. Tras verificar la contraseña, una escritura condicional sobre usuario exige que siga activo y conserve el hash aceptado. Evita emitir una sesión con contraseña antigua después de un cambio concurrente. Se refresca el rol bajo esa protección, sin fiarse del objeto anterior.
- Suspender/reactivar o cambiar rol no rehabilita tokens ni cookies revocados. La revocación no cancela entrenamientos ya admitidos.

La alternativa de contar administradores sin serializar las mutaciones permite que dos administradores se degraden simultáneamente y ambos observen un sustituto que dejará de existir. Se rechaza. La serialización añade contención a operaciones administrativas poco frecuentes; el login utiliza la escritura condicional del usuario, no el gate global de cuentas.

## Consecuencias y límites

Se agregan `control_cuentas` y `recuperacion_cuenta`; es necesario preparar y validar migraciones antes de desplegar. No se modifican hashes/cuentas existentes salvo mediante las operaciones explícitas sobre la BD destino. En esta etapa solo se usan cuentas y BD sintéticas, sin DDL real ni servicios externos.

La recuperación depende de un administrador autenticado: no resuelve que todos los administradores pierdan sus credenciales. Un procedimiento de emergencia del operador queda pendiente, sin reabrir bootstrap ni crear una puerta pública de recuperación. No hay UI de cuentas ni pantalla `/reset-password` todavía; el enlace identifica el flujo futuro y el consumo actual es HTTP JSON.

Siguen pendientes límites de intentos/emisión, auditoría sin secretos, purga de sesiones/tokens expirados, HTTPS/proxy/CORS, integración visual y validación de concurrencia en PostgreSQL/Cloud SQL. Las pruebas concurrentes SQLite no acreditan disponibilidad ni aislamiento operacional en GCP. No exponer como producción cerrada.

Contrato y uso: [gestión de cuentas y recuperación](../manuales/gestion_cuentas_y_recuperacion.md).
