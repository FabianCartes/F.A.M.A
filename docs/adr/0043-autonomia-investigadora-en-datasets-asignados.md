# ADR 0043: Autonomía investigadora en datasets asignados

**Estado:** decisión aceptada por el operador; implementada en código, pendiente activación y recorrido remoto.
**Fecha:** 22 de octubre de 2026.

El operador define que un investigador con un dataset asignado puede descargar, preprocesar, entrenar, predecir, subir audios, corregir predicciones e incorporar aportes al dataset validado sin aprobación administrativa. La asignación concede ese alcance completo; no se añade un permiso separado de curador ni otro rol global. El administrador decide las solicitudes de acceso y mantiene sus responsabilidades de cuentas e infraestructura.

La incorporación sigue siendo una decisión humana explícita y puede ejecutarla el mismo investigador que propuso la corrección. Se conserva la distinción entre proponer e incorporar de [ADR 0013](0013_bucle_retroalimentacion_curacion_semi_manual_mlops.md), junto al alcance por recursos de [ADR 0035](0035-asignaciones-explicitas-y-propiedad-de-entrenamiento.md). Ver metadatos en un catálogo no permite acceder a audios, modelos o predicciones sin asignación.

Se descartan para este alcance la revisión obligatoria de cada aporte por el administrador y la propuesta de un permiso adicional de validación por dataset. Se prioriza la autonomía del investigador como actor principal del ciclo MLOps; la calidad de clase depende de su revisión, no de una segunda persona obligatoria.

## Consecuencias

- El catálogo de descubrimiento debe separar los metadatos disponibles para solicitar acceso de los recursos operables del dataset.
- Una solicitud pendiente no concede permisos. Su aprobación administrativa debe conceder acceso de forma consistente y registrar la decisión.
- Cargas e incorporaciones requieren validación técnica y trazabilidad de autor, clase, origen y resultado de persistencia. Autonomía no equivale a sobrescribir originales silenciosamente ni a declarar completada una operación parcial.
- «Dataset validado» identifica aportes aceptados por una persona autorizada; no certifica que la etiqueta sea científicamente correcta.
- Los ajustes de inventario, subida, incorporación SQL y catálogo/solicitudes están implementados en código. La revisión `0003_autonomy` conserva desconocida la autoría de incorporaciones históricas y añade solicitudes con una identidad actual por persona/dataset; el historial de decisiones se conserva en auditoría. La aprobación y la asignación comparten la transacción serializada de cambios de cuentas/accesos. El paso remoto sigue controlado por el operador; véase el [plan de ajustes](../manuales/plan_autonomia_investigador_y_catalogo.md).
