# ADR 0048: Recuperación local de administradores existentes

**Estado:** aceptado; implementado y comprobado con PostgreSQL/HTTP sintéticos e inspección real de solo lectura. **Fecha:** 23 de octubre de 2026.

La recuperación administrada requiere que otro administrador pueda entrar. Se incorpora una operación local del responsable del backend para restablecer una cuenta que ya sea administradora, sin reabrir instalación ni crear o ascender cuentas. La inspección es de solo lectura; aplicar exige confirmar la base, el correo y dos entradas ocultas de contraseña. Reactivar una cuenta suspendida requiere una opción explícita. Los administradores ausentes o degradados requieren investigación/restauración separada, no una promoción automática.

El cambio de hash, la reactivación solicitada, las revocaciones y la auditoría comparten la transacción y el gate de cuentas existente. La identidad y el rol se verifican nuevamente tras obtenerlo. Se conserva el historial, las asignaciones y las cuotas. El evento `account.operator_recovered` distingue el canal local; `actor_id` permanece nulo porque el operador no es una sesión web autenticada ni se pretende certificar su identidad personal.

La autoridad es el control del servidor y de su perfil privado con escritura SQL; no se añade una ruta HTTP ni una clave maestra. Las credenciales SQL ya permiten modificar cuentas: distribuirlas a personas que solo deben tener permisos web invalidaría esa frontera de confianza. El backend y sus secretos deben quedar bajo el operador autorizado. Se descarta una reparación automática al arrancar, que convertiría una incidencia de acceso o de servicios en permiso para alterar cuentas.

[Guía operativa](../manuales/recuperacion_emergencia_administrador.md) y [recibo](../receipts/recuperacion_emergencia_20261023.json).
