# Acceso web a F.A.M.A.

## Entrada y sesión

El workspace requiere una identidad confirmada por la sesión web. Al abrir la aplicación, `SessionBoundary` muestra la pantalla de acceso mientras comprueba la cookie; las vistas del workspace aún no se montan. Si el servidor confirma que no hay sesión, se reemplaza la ruta por `/login`, sin añadir una entrada al historial. No existe una excepción de acceso anónimo a recursos legacy.

En `/login`, introduce el correo electrónico y la contraseña de una cuenta habilitada. La aplicación confirma la cookie antes de abrir el workspace. Una visita a `/login` con sesión ya confirmada vuelve a la aplicación.

## Fallos y reintentos

- **Comprobación fallida:** el workspace permanece bloqueado. La pantalla de acceso conserva la advertencia y el botón **Reintentar comprobación**. Un fallo de red o de servidor no significa que el usuario sea anónimo; no se redirige mientras esa comprobación siga sin resolverse.
- **Cerrar sesión:** las vistas privadas desaparecen inmediatamente, antes de esperar la respuesta del servidor. Si no se confirma la revocación, la advertencia y **Reintentar cierre de sesión** permanecen en la pantalla de acceso. No se afirma que la sesión esté revocada ni se restaura el workspace al volver a enfocar la ventana. Un `401` tardío tampoco borra la advertencia ni el reintento mientras ese cierre siga pendiente. Tras un cierre confirmado, se vuelve a `/login`.
- **Sesión invalidada:** una respuesta no autorizada vigente oculta las vistas privadas y dirige al login. Las respuestas tardías de una generación anterior no deben restaurar el acceso.

La revalidación por foco o visibilidad conserva el estado de las vistas si se confirma el mismo propietario. Un cambio de propietario descarta el estado privado anterior.

## Alcance de la protección

Esta guardia central controla el montaje de la interfaz del workspace; no sustituye la autenticación y autorización de las APIs ni protege por sí sola entradas de servidor. No cambia contratos del backend, persistencia ni configuración de servicios.

Las pruebas automatizadas de autenticación usan UI y respuestas HTTP sintéticas; no acreditan una autenticación real contra servicios desplegados.
