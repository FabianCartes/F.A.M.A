# ADR 0043: Configuración en runtime y contexto backend sin credenciales JSON

**Estado:** Aceptado. **Fecha:** 13 de octubre de 2026.

Compose no transmitía la configuración que la autenticación implementada necesitaba, y el contexto backend podía incluir la credencial JSON usada por el montaje GCS. Se corrige la configuración existente: variables de autenticación pasan al runtime y JSON del backend queda fuera del contexto, sin añadir login ni permisos por roles.

## Decisión y alternativas

- Compose propaga `JWT_SECRET_KEY`, `ADMIN_INITIAL_EMAIL`, `ADMIN_INITIAL_PASSWORD`, `ADMIN_INITIAL_NAME` y `ACCESS_TOKEN_EXPIRE_MINUTES`. Clave/email/password ausentes se mantienen vacíos, nunca se sustituyen por credenciales compartidas; el backend conserva su rechazo explícito de configuración inválida.
- `backend/.dockerignore` excluye JSON tanto en raíz como en subdirectorios. No basta bloquear el nombre de ejemplo de una cuenta de servicio: las credenciales pueden tener nombres arbitrarios. Se conserva código Python y recetas YAML.
- Los JSON localizados en el flujo actual son credenciales, índices/manifiestos/artefactos externos, no código requerido para empaquetar el backend. Manifiestos y datos necesarios deben estar disponibles en sus volúmenes/directorios runtime. Una futura dependencia pública JSON empaquetada requiere revisión y excepción explícitas, no retirar el bloqueo general.
- No se modifica el montaje de GCS ni se copia/configura una credencial real. No se generan claves, se editan `.env` reales ni se reconstruyen/reinician servicios.

## Evidencia y límites

Se probaron las interfaces públicas confirmadas: `docker compose config` sobre copias temporales con entorno sintético y contexto preparado por Docker CLI contra una API simulada en loopback. Esta última recibe el tar preparado por el cliente legacy (`DOCKER_BUILDKIT=0`); no ejecuta instrucciones ni construye imágenes. Config del cliente aislada y auth ficticia impiden leer credenciales Docker/almacenes del operador.

RED confirmó ausencia de variables runtime y envío del JSON sintético con el nombre usado en Compose. GREEN verificó exclusión del nombre legado, nombre arbitrario y archivo anidado, preservando Python/YAML. No se interpreta que una imagen histórica haya filtrado claves ni que un build real/BuildKit o despliegue completo esté probado. Docker Engine estaba inactivo y no se inició.

Por decisión posterior del usuario, funcionalidades nuevas de login, registro administrado y permisos quedan fuera de esta etapa. Seguimiento y resultados en [KANBAN.md](../KANBAN.md).
