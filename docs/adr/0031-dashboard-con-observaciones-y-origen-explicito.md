# ADR 0031: Dashboard con observaciones y origen explícito

**Estado:** Aceptado. **Fecha:** 15 de octubre de 2026.

El dashboard mezclaba datos de referencia con telemetría actual, convertía ceros/ausencias en cifras de ejemplo y podía buscar/cargar pesos al consultar métricas. El usuario confirmó probar módulo, GET `/api/dashboard/stats` y vista renderizada, y mantener métricas del último registro de entrenamiento sin atribuirle activación. Se elige una lectura pasiva con desconocidos explícitos, no añadir probes cloud ni cambiar catálogo/activación.

## Contrato

- Conteos proceden de filas consultadas: BD vacía da cero; sin sesión o antes de una consulta fallida quedan null. La media de confianza sin predicciones es null; una media observada de cero se conserva. Fallo SQL marca database `degraded` y hace rollback; las observaciones ya obtenidas pueden conservarse, no se promete snapshot distribuido.
- Accuracy, pérdida y curvas proceden del último `Modelo` por ID (último registro, no máximo score, activo ni necesariamente entrenamiento exitoso). `latest_model_name` y `metrics_source="latest_registered_model"` identifican ese origen. Se conserva `active_model_name` como alias de compatibilidad, sin semántica de activación, y se elimina su sustitución por nombre del ensamble.
- Null/ceros se conservan. Las curvas contienen solo filas reales, incluida una sola época; no se rellenan diez épocas de referencia. Un registro sin métricas no degrada la BD por redondear null. El evento dice modelo **registrado**, no entrenamiento exitoso.
- Actividad seleccionada contiene predicciones y último registro de modelo, sin evento de ingesta sintético. No es auditoría completa ni garantía de orden global cronológico. Dominio proviene de la asociación de dataset registrada; no se deduce por spelling del modelo ni se inventa ID. Confianza no se presenta como certeza diagnóstica.
- GET ya no invoca el estado de ensamble que dispara búsqueda/carga de checkpoints. Storage/inferencia no comprobados quedan `unknown`; ensamble sin observación, `ready=null` y modelos vacíos. `get_stats` conserva su argumento opcional de estado reportado, pero este no prueba salud del motor ni cambia métricas de entrenamiento. No se modifica `registry.py` ni se resuelve su política pendiente.
- Fallo de telemetría de hardware devuelve dispositivo desconocido sin perder las observaciones BD. No se promete ausencia total de I/O de hardware: se conserva la consulta pasiva existente, aislada con adaptadores externos en pruebas.

## Presentación y referencias

La vista muestra «No disponible» para desconocidos, conserva ceros y etiqueta métricas del último modelo registrado. Los conteos son **registros BD**, no inventario GCS. No presupone Focal Loss/AdamW, convergencia óptima, clases, muestras o física sin fuente actual.

Las fichas por dominio conservan valores de referencia ya existentes, ahora con `source="historical_reference"` y aviso visible de que no acreditan disponibilidad actual. Se corrigen nombres de campos que no coincidían entre backend/vista y se retiran fallbacks de precision/balanced F1 no suministrados por esa respuesta. No se recalcula ni reconcilia la evidencia experimental: ese cierre sigue en OE5.

Una actualización fallida advierte que se conserva la última lectura y deja de confirmar salud actual; la falta de respuesta de hardware no se convierte en CPU normal/cero observado. No añade parser exhaustivo, sincronización entre polls concurrentes, SLA de refresco, probes de servicios, timestamps de auditoría ni garantías de producción.

Se prefirió etiquetar las referencias antes que borrarlas como resultados históricos, pero se retiraron curvas/eventos ficticios porque aparentaban actividad observada. El manual y contraste de objetivos deben distinguir esta corrección de otras fuentes pendientes de estado/ensamble/inventario. Evidencia pública y límites operacionales: [KANBAN](../KANBAN.md).
