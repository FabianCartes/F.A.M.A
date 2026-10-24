# Acceso web y SlicedWaves

**19 de octubre de 2026.** [ADR 0039](../adr/0039-acceso-web-del-mismo-origen-y-fondo-aislado.md). Interfaz conectada a los contratos de [sesiones](sesiones_web_y_acceso_administrado.md), [cuentas](gestion_cuentas_y_recuperacion.md) y [cuotas](limites_login_y_recuperacion.md); validación automatizada sin servidor ni cuentas reales.

## Pantallas y comportamiento

- **`/login`:** formulario centrado de correo/contraseña, sin alta pública ni elección de rol. Primero comprueba la sesión; si ya es válida, vuelve a `/`. Ante error de verificación no carga vistas ni solicita otra contraseña sin aclarar el fallo.
- **`/`:** no monta Sidebar, vistas ni peticiones de datos/ML antes de confirmar `/api/auth/me`. Un anónimo se dirige a `/login`; un 503 no se trata como usuario anónimo ni permite acceso.
- **Sesión confirmada:** muestra nombre/email y rol reales con botón de cierre. El POST login debe confirmarse con GET me y el mismo ID, no solo con presencia de una cookie o una respuesta JSON de éxito.
- **Expiración:** los clientes de datos notifican 401 para cerrar las vistas. Un 403 de permisos no causa logout. Respuestas 401 de una generación anterior no invalidan una sesión confirmada después.
- **Foco/visibilidad:** revalida sin polling nuevo de sesión. Mantiene el trabajo del mismo usuario durante la consulta —recuperar foco también ocurre al cerrar un selector de archivos— y lo elimina si se verifica otra identidad. Error o sesión negativa cierran las vistas. El backend valida cada operación aunque la comprobación visual esté pendiente; no hay garantía de borrado instantáneo entre pestañas.
- **Logout:** oculta las vistas durante el intento y espera 204. Si falla, informa que no pudo confirmar la revocación y permite reintentar; no anuncia éxito ni detiene entrenamientos.
- **401 de login:** mensaje genérico y contraseña del formulario vaciada. **429:** espera visual basada en `Retry-After` y tiempo transcurrido, también al volver de una pestaña en segundo plano. **503:** avisa de disponibilidad/configuración. No hay reintentos automáticos de contraseñas ni eco de errores internos del servidor.

La identidad vive en memoria del módulo de sesión y la cookie HttpOnly la administra el navegador. No se escriben tokens ni credenciales en localStorage/sessionStorage; se preservan preferencias de interfaz existentes. Esta capa visual no sustituye asignaciones/RBAC del backend. Todavía no hay panel gráfico para administrar cuentas, asignaciones o auditoría.

## Recuperación

El enlace del administrador usa `ORIGEN/reset-password#token=...`. La pantalla extrae exactamente una capacidad válida del fragmento y retira el fragmento de la entrada actual del historial. No lo muestra, persiste ni acepta como query param; esto no borra copias anteriores del enlace, clipboard, historial ajeno o datos que otro software haya registrado antes.

Se piden nueva contraseña y confirmación, con 12–1024 caracteres y sin blancos exclusivos. Se vacían al enviarlas. El token se mantiene solo en memoria del flujo para permitir reintentar un fallo de transporte, hasta consumo exitoso/desmontaje. POST `/api/auth/reset-password` no inicia sesión ni atribuye al consumidor la identidad del administrador emisor. Enlaces inválidos/expirados/usados se remiten al administrador; no se inventa un registro o recuperación pública por email.

La pantalla no envía correo ni crea cuentas. Un error de red puede ocurrir después del commit: no se promete que la contraseña quede sin cambiar, ni que el token siga disponible tras cualquier fallo. Seguir el contrato de [cuentas y recuperación](gestion_cuentas_y_recuperacion.md).

## SlicedWaves y accesibilidad

Fuente local: `frontend/components/backgrounds/SlicedWaves.jsx` y CSS asociado. Se conserva la variante JavaScript, shaders y valores solicitados:

```text
color1=#cb49ff color2=#ff5fa2 color3=#424aff ribbons=5 spacing=12
perspective=0.8 blur=0.8 glow=1.65 position=0.69 mouseInteraction=true
barWidth=0.55 ribbonHeight=0.18 spread=0.12 curve=0.4 speed=0.35
brightness=1.05 rotation=-1 grain=0.09 fade=0.05
```

El fondo ocupa la superficie de acceso/recuperación; el formulario se centra y puede desplazarse verticalmente en pantallas pequeñas. El canvas es decorativo, `aria-hidden` y no intercepta clics. Los inputs tienen etiquetas, autocompletado y foco visible; los errores se anuncian por `alert`. No hay equivalencia de píxeles ni medición de contraste acreditada todavía.

Se respeta `prefers-reduced-motion`, incluidos cambios mientras la pantalla está abierta. El botón de pausa desmonta el renderer y deja fondo estático. El módulo no se mantiene detrás de las vistas de trabajo; cancela frames y libera programas/buffers/texturas/framebuffers/VAOs al desmontar o perder contexto. Se corrigió liberación parcial ante fallos de shaders y asignación de buffers. Esto no mide memoria o GPU reales ni certifica todos los fallos de drivers; un entrenamiento del nodo puede continuar tras logout y debe supervisarse por separado.

Licencia upstream observada: [MIT + Commons Clause License Condition v1.0](https://github.com/DavidHDev/react-bits/blob/main/LICENSE.md). Se conserva copyright/condiciones junto al código como aviso `@license`. No describirlo como MIT sin restricciones ni revender el módulo/exports de forma independiente. No se instalaron dependencias adicionales.

## Configuración antes de una prueba manual

La interfaz exige **mismo origen**. Se recomienda `NEXT_PUBLIC_API_URL` vacío, usando `/api` y el rewrite existente; `API_URL` del proceso Next.js apunta al backend interno. No colocar secretos en variables `NEXT_PUBLIC_*`. Una API de otro origen se rechaza antes de enviar credenciales; no hay fallback Bearer, CORS abierto ni `localStorage` como solución alternativa.

En el backend deben estar configurados el origen público `FAMA_WEB_ORIGIN`, la clave `FAMA_RATE_LIMIT_KEY`, tablas/migraciones y el administrador autorizado. HTTP solo está contemplado para loopback de desarrollo mediante el opt-in ya documentado. Ninguna de esas variables, credenciales o BD reales fue aplicada por esta unidad.

No iniciar el backend productivo solo para mirar el diseño: su lifespan existente puede cargar pesos y workers. Preparar primero un entorno aislado y acordar el arranque/prueba manual. No se ejecutó servidor Next.js, build, navegador real, despliegue ni solicitud a PostgreSQL/GCS reales. Antes de producción faltan revisión HTTPS/proxy/CORS, migraciones/índices, usuarios/activos de prueba y validación E2E autorizada.

## Pruebas y pendientes

Pruebas renderizadas en `frontend/components/auth/__tests__/` y `frontend/app/__tests__/session*.test.tsx`, con HTTP/router/WebGL/media query simulados. Se prueban gate inicial, cookie confirmada, identidad discordante, 401/403/429/503, tiempo de espera, foco/cambio de identidad, logout, extracción de capacidad y liberación gráfica. No es una captura visual ni una conexión real entre Next y FastAPI.

TypeScript sin emisión/incremental y ESLint focal sin diagnósticos. Focal de acceso: **30 PASS/cinco archivos**; cierre completo en [KANBAN](../KANBAN.md). Node observado **22.20.0** sigue fuera del requisito del jsdom instalado; no se cambió runtime ni se relajaron versiones para ocultarlo.

**Cierre observado:** frontend completo **279 PASS/28 archivos** (85,04 s), sin exclusiones. Incluye las 30 pruebas de acceso, no se suman como si fueran adicionales a ese total. La regresión inicial detectó una expectativa de HTTP que no incluía las nuevas opciones de seguridad; ahora exige `credentials=same-origin`, `cache=no-store`, `redirect=error`, método GET y señal de abort. No se repitieron suites backend ni benchmarks reales para este bloque; sus recibos y resultados conservan su alcance histórico.

Comandos desde `frontend`:

```text
node node_modules/vitest/vitest.mjs run --maxWorkers=1
node node_modules/typescript/bin/tsc --noEmit --incremental false
node node_modules/eslint/bin/eslint.js app/page.tsx app/login/page.tsx app/reset-password/page.tsx app/__tests__/session.test.tsx app/__tests__/session-configuration.test.tsx components/auth components/backgrounds/SlicedWaves.jsx lib/auth.ts lib/api.ts
```

Siguientes unidades: pantallas administrativas (cuentas/asignaciones/auditoría y mantenimiento), setup protegido, recuperación de emergencia y validación operacional. No se declara lista la plataforma para producción ni acreditados los objetivos operativos por estas pruebas.
