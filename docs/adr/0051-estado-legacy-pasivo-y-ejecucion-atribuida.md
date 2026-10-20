# ADR 0051: Estado legacy pasivo y ejecución atribuida

**Integration note (2026-10-20):** `modelos_ejecutados` identifies the invoked predictor. The existing `dev` contract for `modelos_activos` is preserved: only result-level participant/weight evidence populates it; it is not an alias of the invoked predictor. A non-mock annotation does not erase an explicit fallback role.

**Estado:** Aceptado. **Fecha:** 17 de octubre de 2026.

El estado de ensambles cargaba pesos al consultarse, trataba registros BD como readiness y añadía métricas inventadas para modelos cargados. El usuario confirmó corregir `SuperEnsembleService.get_status`, la ruta real GET `/api/model-info` y su presentación, sin modificar `registry.py` ni activación. La ruta `/api/ensemble/status` mencionada inicialmente no existe y no se añade.

## Hechos separados, con alcance explícito

- La lectura es pasiva: no llama `load_models`, no deserializa pesos, no ejecuta inferencia ni activa nada. La carga explícita y el ciclo de vida existente quedan separados.
- `state_scope="legacy_bioacoustic_service"` acota la observación a esa instancia legacy. `domain_supported=false` para otros dominios no indica que su predictor del catálogo sea indisponible; no se reciclan componentes bioacústicos como motores. Las clases incluyen `classes_source` y referencias/listados/cachés se califican como no verificados.
- `is_registered` se refiere a un registro enlazado por FK al dataset solicitado y arquitectura de la ranura: true si se observa, false si la consulta no lo encuentra, null si no se pudo comprobar. Se retiran coincidencias por texto de clase y préstamos globales de registros de otro dataset. No se reparan asociaciones históricas ni se cambia su política canónica.
- `weights_available` es presencia local de archivo no vacío, **no contenido validado**. Se comprueban candidatos/`models/` y rutas locales dentro de las raíces configuradas; remotos, esquemas no cubiertos, rutas externas/errores quedan desconocidos. No se consulta GCS ni se abre el checkpoint para inspección. Se revisa pertenencia léxica antes de resolver absolutos externos y pertenencia resuelta antes de consultar presencia. No sustituye el resolver del catálogo ni cierra todo alias/UNC, carreras de enlaces o recepción hostil.
- `weights_source` distingue candidato configurado, referencia registrada y archivo del modelo cargado. `recorded_checkpoint`/`loaded_checkpoint` separan nombres que pueden corresponder a versiones distintas. Accuracy/loss son solo de la fila BD (`metrics_source=database_record`), no resultados del objeto en memoria. Sin fila no se inventan porcentajes/pérdidas; se conservan ceros.
- `is_loaded` observa módulos atribuidos en memoria por este servicio. `is_ready` queda como alias legado de esa carga, **no inferencia comprobada ni calidad/compatibilidad universal**. Pesos pueden desaparecer en disco y la instancia seguir en memoria. Pesos de mezcla se leen del ensamble cargado, normalizados, no del prior configurado.
- Modos observados: unavailable sin carga atribuida, individual con un componente, partial_ensemble con dos, ensemble con tres, fallback solo con flag y módulo fallback presentes. No se anuncia AudioCNN por ausencia de la tríada. `ensemble_ready` solo resume carga de las tres ranuras; `active_models` es un campo legado del estado de esa instancia, no activación global del registro.

## Respuesta de predicción y vista

POST `/api/predict` deja de consultar un ensamble legacy ajeno para adornar su resultado. `modelo_id`, `modelo` y `modelos_ejecutados` identifican al predictor invocado; `modelos_activos` se conserva como alias de compatibilidad sin pesos/componentes inferidos. El rol fallback del predictor no se borra por `is_mock=false`: computación real y rol de respaldo son conceptos distintos. Invocar un predictor puede terminar en filtro; no prueba un forward neuronal (como mostró el benchmark autorizado).

La vista no inventa tarjetas industriales/bioacústicas, estado operativo, «Activo 3/3», porcentajes, versiones o dispositivo de producción por default. El panel legacy requiere ámbito/dominio coincidentes, separa registro/archivo/carga y archivos registrados/cargados, y muestra un fallback observado sin atribuirlo al seleccionado. Selector/activación y preflight `has_weights` no cambian. Las métricas de catálogo se etiquetan declaradas; sin datos muestra desconocidos y no presume conjunto test/Balanced F1. Los tags de respuesta usan la lista ejecutada, no componentes legacy antiguos.

La latencia inicial ficticia 0.14s se retira. El contador existente pasa a «Última solicitud»: tiempo hasta respuesta HTTP medido por ese código, no forward, JSON/render completo ni RNF de ≤3 s. No se añade un benchmark real en esta unidad.

## Límites

No unifica los dos caminos de inferencia, no valida criptográficamente archivos/versiones, orden de etiquetas, compatibilidad semántica, calidad, atomicidad de reload o lecturas concurrentes. No cambia deserialización de cargas explícitas ni garantiza seguridad completa del filesystem. Listados de datasets/clases y política de catálogo conservan sus límites previos. No se reejecutan activos reales ni se modifican datos/servicios; evidencia e interfaces de pruebas sintéticas en [KANBAN](../KANBAN.md).
