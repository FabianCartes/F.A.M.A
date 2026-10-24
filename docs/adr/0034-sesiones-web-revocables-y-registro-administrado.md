# ADR 0034 — Sesiones web revocables y registro administrado

**Estado:** aceptado; implementación por etapas. **Fecha:** 18 de octubre de 2026.

## Contexto y alternativas

El usuario confirmó acceso exclusivamente web, investigadores limitados a recursos asignados y formulario centrado con SlicedWaves. PostgreSQL será Cloud SQL en producción, sin impedir desarrollar primero con PostgreSQL local. Mantener JWT en el navegador simplificaría la transición, pero complicaría revocación y agregaría un flujo Bearer innecesario para este producto.

## Decisión

La sesión web será opaca, persistida en la misma BD autoritativa que los usuarios y transportada mediante cookie HttpOnly. Solo se guarda SHA-256 del identificador aleatorio de 256 bits. En HTTPS se utiliza `__Host-fama_session`, Secure, SameSite=Strict y Path=/, sin Domain. Se exige origen explícito coincidente en escrituras, incluido login, para impedir CSRF. HTTP queda reservado a desarrollo loopback habilitado expresamente y utiliza otro nombre de cookie.

Duración absoluta inicial: ocho horas; inactividad: treinta minutos, configurables. Cada solicitud autenticada consulta usuario y rol vigentes. Logout revoca el identificador; login exitoso rota y revoca la sesión presentada por ese navegador. La suspensión deniega solicitudes mientras la cuenta esté inactiva. La futura gestión administrada debe revocar también las sesiones persistidas al suspender/cambiar contraseñas, sin cancelación implícita de entrenamientos.

`POST /api/auth/register` requiere administrador autenticado. `login` ya no emite JWT y `me` no acepta Bearer; las utilidades JWT legacy permanecen por compatibilidad interna y pruebas, no como segundo acceso web. Se preservan IDs y hashes de cuentas existentes. Esta decisión sustituye el transporte JWT del contrato HTTP de ADR 0024, no sus garantías de bootstrap explícito y conservación de cuentas.

## Consecuencias y límites

- La BD es necesaria para comprobar sesiones: error de persistencia produce 503 sanitizado, nunca acceso abierto, reapertura del setup ni cambio automático a BD local.
- Se agrega `sesion_web`; antes del despliegue se debe preparar y validar el cambio de esquema de forma controlada. No se ha migrado ninguna BD real ni provisionado Cloud SQL.
- Primer bloque implementado: login/me/logout/register. No equivale a autorización del resto del backend: siguen pendientes asignaciones, propiedad de trabajos y protección de rutas funcionales.
- También pendientes: límites persistentes de intentos y sesiones, purga de filas expiradas, recuperación de cuentas, auditoría, ajuste CORS/proxy, interfaz de acceso y asistente protegido. No exponer como plataforma segura todavía.
- Cloud SQL y conectividad deben estar disponibles antes de crear el primer administrador en producción. El asistente web no creará infraestructura GCP ni recibirá permisos IAM de administración para hacerlo.

Pruebas y configuración: [contrato de sesiones web](../manuales/sesiones_web_y_acceso_administrado.md).
