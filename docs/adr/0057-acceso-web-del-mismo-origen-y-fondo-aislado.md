# ADR 0057 — Acceso web del mismo origen y fondo aislado

**Estado:** aceptado. **Fecha:** 19 de octubre de 2026.

## Decisión

La interfaz utiliza las sesiones opacas del backend de ADR 0052, sin un segundo sistema de identidad Next.js ni tokens en storage. `/login` ofrece formulario centrado sin registro público ni selector de rol; `/` comprueba `/api/auth/me` antes de montar las vistas y sus peticiones. Tras POST login se confirma que la cookie funciona y corresponde al mismo ID antes de navegar a la aplicación.

Las peticiones de sesión y datos usan cookies de mismo origen, `no-store` y rechazo de redirects. Una configuración de API de otro origen se rechaza antes de transmitir credenciales. Se conserva el rewrite `/api` existente de Next.js hacia `API_URL`; no se agregan proveedores de identidad, servicios o dependencias. El backend sigue siendo autoridad de permisos: ocultar la aplicación no reemplaza sus controles.

Los clientes HTTP de datos comparten un wrapper que notifica 401. El límite visual descarta vistas ante expiración, no confunde 403 con falta de sesión y evita que respuestas antiguas revoquen una sesión verificada después. Se revalida al recuperar foco/visibilidad sin heartbeat adicional: se conserva el trabajo del mismo usuario durante la comprobación, para no destruir un selector de archivos o borrador; se descarta al comprobar otro ID, expirar o fallar la verificación. Cerrar sesión espera confirmación del servidor, sin cancelar entrenamiento ni afirmar revocación si falla la respuesta.

`/reset-password` consume la capacidad del fragmento, limpia la entrada actual de URL y solo la mantiene en memoria local hasta consumo/desmontaje. No se usa query, storage o campo oculto con token, ni se inicia sesión automáticamente. La interfaz respeta `Retry-After` por tiempo transcurrido y no reenvía credenciales automáticamente.

## Fondo y alternativas

Se integra SlicedWaves JavaScript + CSS de React Bits con los shaders y parámetros visuales proporcionados por el usuario. Se descartan librerías gráficas adicionales: el módulo utiliza WebGL2 nativo. El formulario permanece accesible con fondo estático ante ausencia de capacidades, compilación fallida, asignación fallida o pérdida de contexto. Movimiento reducido y pausa manual desmontan el renderer. No se mantiene en las vistas de trabajo; se liberan recursos y frames pendientes al salir del acceso.

Se conserva el aviso de licencia observado upstream el 19 de octubre de 2026: **MIT + Commons Clause License Condition v1.0**, no MIT simple. Permite incorporar el módulo en una aplicación, pero restringe redistribuir/vender los componentes o exports como producto independiente. El aviso completo queda junto al código; revisar la distribución institucional antes de publicar.

## Límites

La verificación actual usa DOM y adaptadores del navegador simulados: no acredita píxeles, contraste medido, compilación real de shaders, compatibilidad de todos los drivers, rendimiento GPU o navegación E2E con servicios reales. No se ejecutó Next build/dev ni se instaló tooling. Node 22.20.0 sigue fuera del requisito observado del jsdom instalado, aunque las pruebas pasan.

Siguen pendientes pantallas administrativas de cuentas/asignaciones/auditoría, setup inicial, recuperación de emergencia, migraciones/configuración de despliegue y validación real de proxy/HTTPS/PostgreSQL/GCS. No se modifican cuentas, secretos, datos ni servicios reales. Los resultados backend previos se conservan como evidencia histórica, no como una nueva medición de producción.

Uso, configuración y evidencia: [acceso web y SlicedWaves](../manuales/acceso_web_y_sliced_waves.md).
