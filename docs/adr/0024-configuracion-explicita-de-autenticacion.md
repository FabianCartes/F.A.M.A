# ADR 0024: Autenticación y alta inicial con configuración explícita

**Estado:** Aceptado; configuración implementada, gestión exclusiva por administradores pendiente. **Fecha:** 13 de octubre de 2026.

Se retiran la clave JWT y credenciales iniciales implícitas: una instancia no debe emitir sesiones ni crear administradores con valores compartidos públicamente. El operador proporciona una clave persistente y credenciales de alta inicial; la ausencia/configuración insegura se comunica como indisponibilidad, sin reescribir configuración ni cuentas existentes.

## Decisión y alternativas

- `JWT_SECRET_KEY` no tiene fallback. Se exige texto UTF-8 de al menos 32 bytes, no blanco ni igual a la antigua clave pública. El mínimo no certifica entropía: debe generarse una clave aleatoria y única por instancia.
- Emisión y validación de tokens fallan con `AuthenticationConfigurationError` cuando no hay configuración válida. Login la comprueba antes de verificar credenciales o escribir último acceso; login/perfil traducen ese error a HTTP 503 sanitizado, distinto del 401 por credenciales inválidas.
- `seed_initial_admin` solo crea una cuenta en una tabla sin usuarios, con email explícito plausible y contraseña explícita de al menos 12 caracteres distinta de la antigua contraseña pública. No genera, almacena ni imprime nuevos secretos; no promueve ni cambia cuentas existentes. Si hay usuarios pero no administrador, no inventa recuperación: requiere una intervención autorizada separada.
- Se descarta conservar defaults incluso en desarrollo y generar una clave efímera por arranque: los defaults son reutilizables por terceros; claves efímeras romperían sesiones al reiniciar o entre procesos. Tampoco se escribe automáticamente `.env` ni se resetean claves/contraseñas históricas.
- Se mantiene el arranque de los otros módulos durante esta transición, pero **no se certifica seguridad del servicio**: las rutas sensibles todavía no están protegidas en su totalidad.
- El usuario acordó que solo un administrador autenticado creará investigadores u otros administradores. Esa política aún no está aplicada a `/api/auth/register`; login web, autorización de rutas y configuración de contenedores son unidades posteriores, no garantías de esta entrega.

## Operación y límites

Las variables se leen en el proceso; la clave JWT se captura al importar el módulo. Aplicar valores reales/reiniciar servicios requiere autorización operativa propia. Cambiar de clave invalida sesiones anteriores; cuentas con contraseñas históricas inseguras no se reparan automáticamente.

La plantilla contiene campos vacíos, no credenciales listas para usar. La corrección posterior de [ADR 0025](0025-configuracion-runtime-y-contexto-sin-credenciales.md) propaga estas variables mediante Compose y excluye JSON del contexto backend; editar `backend/.env` no configura por sí solo un contenedor que no monta ese archivo. Sin build, despliegue ni cambios sobre datos/credenciales reales. Login y permisos permanecen pospuestos a la etapa de funcionalidades nuevas por decisión del usuario.

Evidencia por interfaces públicas en [KANBAN.md](../KANBAN.md): entorno de importación limpio sin dotenv, claves/credenciales sintéticas y SQLite temporal; no prueba configuración del despliegue real.
