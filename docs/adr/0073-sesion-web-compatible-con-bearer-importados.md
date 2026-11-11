# Sesión web compatible con Bearer para recursos importados

**Estado:** Sustituido por [ADR 0078](0078-gcs-como-fuente-unica-y-publicacion-del-zip.md) (2026-11-11): la vía Bearer se eliminó y la sesión es solo por cookie.

Se reutiliza la sesión opaca revocable de `aa53e09a9b935f752b01fe464cbc1a5bd10556c0` mediante `/api/auth/web/*`, sin reemplazar `/api/auth/login` ni `/api/auth/me`: sus contratos Bearer ya tienen consumidores. Esta integración acotada se registra en L33 del [plan](../arquitectura/entrenamiento-datasets-importados-plan.md), manteniendo S10 y el acceso legacy.

## Decisión

La identidad para recursos importados puede proceder de cookie o Bearer. Authorization presente se valida sin fallback; si también existe cookie, ambas deben ser válidas y pertenecer al mismo usuario antes de renovar la sesión. El propietario exacto sigue siendo obligatorio incluso para administradores. Una cookie presente no se convierte en el principal local `-1`.

Las tablas de sesión, cuota y auditoría se crean mediante migración aditiva explícita, nunca por arranque. La configuración web y el esquema se verifican antes de cambiar estado de sesión. No se importa el instalador, administración de cuentas, recuperación de contraseñas ni asignaciones globales de la otra rama.

## Alternativas y consecuencias

- Copiar únicamente el login no conecta su cookie con las rutas Bearer actuales.
- Reemplazar las rutas existentes rompe consumidores; consolidar toda la rama cambia permisos legacy y amplía el alcance operacional.
- Una barrera global de sesión en el workspace impediría acceso legacy autorizado; la UI distingue estado privado sin imponerla.
- Logout revoca la cookie del navegador, no JWT independientes. La doble credencial discordante se rechaza: el cliente debe presentar una identidad coherente.
- No se transfieren datasets históricos ni se crea un administrador automáticamente. La migración y la creación operacional de usuarios requieren autorización independiente.

Implementación y evidencia se registran en el [manual](../manuales/sesion-web-importados.md); esta decisión no acredita despliegue, PostgreSQL real ni cierre de T4.
