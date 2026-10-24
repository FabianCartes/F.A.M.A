# ADR 0053 — Asignaciones explícitas y propiedad de entrenamiento

**Estado:** aceptado. **Fecha:** 18 de octubre de 2026.

## Contexto y decisión

El usuario confirmó que los investigadores solo operarán sobre recursos asignados, con acceso exclusivamente web. Ocultar recursos en el frontend o reutilizar el cargador histórico no basta: los cargadores no son una lista de permisos y existen registros con `id_usuario=1`, nombres descriptivos o asociaciones desconocidas.

Se conserva la sesión de ADR 0052 como identidad y se agrega una asignación muchos-a-muchos explícita entre usuario y dataset. Los administradores conceden/revocan esa asignación por ID persistido. Modelos y audios heredan acceso de su FK de dataset; los modelos catalogados deben declarar un destino canónico y los publicados desde BD también deben conservar una FK autorizada vigente, aunque la metadata en memoria sea antigua. No se modifica la política de construcción/publicación del registro global.

Las predicciones nuevas con un dataset de origen verificable registran dataset y actor en una relación explícita dentro de la misma transacción que la predicción. La alternativa de autorizar predicciones históricas por coincidencia de `dataset_name` se rechaza: un texto sin relación verificable no prueba procedencia. Sin esa relación, las predicciones y su feedback permanecen disponibles solo al administrador, también cuando un adaptador usado por él carece de destino asociado. No hay backfill ni asignaciones por conjetura.

Las rutas funcionales requieren sesión por defecto. Los listados y agregaciones se filtran antes de limitar resultados o leer checkpoints del historial. Las operaciones individuales comprueban acceso antes de transferir o ejecutar inferencia. Un lote de sync se autoriza completo antes de iniciar la primera descarga. El inventario de investigadores usa registros BD asignados, no el recorrido global cloud/local del administrador; se identifica como observación de BD, no como salud GCS.

## Propiedad del entrenamiento

El trabajo captura el actor al admitir el inicio. Observar y cancelar requieren dueño y asignación vigente al dataset, o administrador. La comprobación y la operación se realizan bajo el mismo lock del trabajo, para no aplicar la autorización del trabajo anterior a uno nuevo. Una revocación de asignación no cancela el cómputo ya admitido; impide solicitudes posteriores del investigador y deja al administrador la cancelación global.

Los entrenamientos iniciados desde HTTP guardan el actor en el modelo, pero no activan automáticamente el resultado. La activación exige una acción administrativa separada. Los llamadores internos de confianza conservan las interfaces anteriores; no son una segunda entrada HTTP.

## Consecuencias y límites

- La autorización se evalúa con la sesión y asignaciones vigentes por solicitud; una concesión no se guarda en la cookie.
- Los recursos no encontrados/no asignados responden 404 sin inventariar recursos ajenos. Operaciones globales administrativas y trabajos de otros autores responden 403.
- No se permite sobrescribir el feedback de otro autor como investigador, aunque ambos compartan dataset. Sí se permite curación sobre recursos asignados; el destino congelado no puede reasignarse desde el query HTTP.
- Se agregan tablas `asignacion_dataset` y `acceso_prediccion`, además de `sesion_web` del bloque anterior. Preparar DDL/migraciones y validarlas contra PostgreSQL es requisito previo al despliegue; no se ha aplicado ninguna migración real.
- El entrenamiento sigue siendo un singleton por proceso. La propiedad no convierte este diseño en un scheduler durable/multiproceso ni acredita coordinación entre réplicas. Un estado legacy sin dueño no se entrega a investigadores. Después de reiniciar no se adopta un trabajo por suposición.
- El catálogo global sigue compartido y puede actualizar metadata internamente; filtrar su respuesta no equivale a aislamiento de procesos/archivos o de recursos de cómputo. Las credenciales GCS son institucionales del backend, no se entregan al investigador.
- Persisten los pendientes de producción de ADR 0052: límites de intentos, auditoría, gestión de cuentas, UI, setup, proxy/CORS, Cloud SQL y validación operacional.

Contrato y verificación: [permisos sobre recursos asignados](../manuales/permisos_recursos_asignados.md).
