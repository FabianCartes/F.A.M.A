# Documentación histórica

Esta carpeta conserva documentación retirada del conjunto vigente. Su contenido sirve como evidencia y contexto de decisiones pasadas; no describe necesariamente el comportamiento actual del código ni procedimientos ejecutables hoy.

## Criterio de retiro

Un documento se traslada aquí cuando corresponde a alguno de estos casos:

- Plan ya ejecutado, con todas sus tareas cerradas.
- Traspaso entre etapas de trabajo.
- Registro fechado de una integración, actualización o recuperación puntual.
- Procedimiento que depende de entornos, contenedores o scripts que ya no existen.
- Contenido reemplazado por otro documento o por un ADR posterior.

La documentación vigente permanece en `docs/arquitectura/`, `docs/manuales/` y el resto de carpetas descritas en [`docs/README.md`](../README.md). Los ADR no se trasladan: un ADR reemplazado conserva su ubicación y declara su estado.

## Estructura

| Carpeta | Contenido |
| --- | --- |
| [`arquitectura/`](arquitectura/) | Planes de implementación cerrados, traspasos e informes de diseño reemplazados. |
| [`manuales/`](manuales/) | Registros de integraciones fechadas, pruebas manuales puntuales y procedimientos retirados. |
| [`seguimiento/`](seguimiento/) | Tablero de tareas anterior (`KANBAN.md`) y listas de seguimiento cerradas. |

Los archivos conservan su nombre original y su historial de Git (`git log --follow <ruta>`). Los enlaces relativos se actualizaron al trasladarlos.
