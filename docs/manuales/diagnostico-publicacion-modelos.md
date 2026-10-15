# Diagnóstico de publicación de modelos

`GET /api/models` devuelve los modelos que superaron la publicación. Cada entrada de `publication_errors` conserva su `code` existente; para `standard_evaluation_invalid` puede incluir además `reason`, una categoría acotada y segura para orientar el diagnóstico. La razón no contiene rutas, texto de excepciones, configuración privada ni secretos.

## Razones de evaluación estándar

| `reason` | Qué indica | Siguiente revisión |
| --- | --- | --- |
| `runtime_configuration_incompatible` | Hay informes completados para el artefacto, pero su configuración efectiva no coincide con la que describe el runtime del predictor actual. | Revisar la configuración e identidad del predictor y planificar una reevaluación explícita con el runtime previsto. |
| `evaluation_pair_incomplete` | No existe un par admisible de informes `val` y `test` completados para la identidad del checkpoint. Puede faltar un split o no corresponder a la identidad esperada. | Comprobar que ambos informes estén completados y asociados al checkpoint, dataset, clases y esquema esperados. |
| `checkpoint_invalid` | No se pudo validar el checkpoint o su identidad persistida: integridad, estructura estándar, configuración de preprocessing o relación con el modelo. | Revisar el artefacto y el hash registrado en un entorno operativo autorizado. |
| `pair_provenance_invalid` | Los informes individuales no acreditan el mismo par admitido de manifiestos `val/test`; por ejemplo, falta o no coincide su identidad conjunta. | Verificar la procedencia conjunta de ambos informes; no combinar informes de admisiones distintas. |
| `model_state_incomplete` | El modelo está en un estado estándar pendiente, fallido o de componente, no en estado finalizado. | Completar la evaluación estándar antes de solicitar publicación o activación. |

La guarda usa estas categorías tipadas, no interpreta mensajes de excepción. Una causa inesperada conserva el código `standard_evaluation_invalid` sin `reason`, y el cliente la presenta como un error genérico. El contrato no cambia el código de error existente ni permite publicar o activar un modelo que la guarda rechaza.

Otros códigos públicos de publicación, como `checkpoint_missing`, `checkpoint_too_small`, `checkpoint_invalid`, `checkpoint_unreadable` y `checkpoint_outside_root`, conservan su significado y no incluyen detalles internos. El campo `reason` es opcional y está reservado para `standard_evaluation_invalid`.

## Interpretación del catálogo

- Si hay modelos publicados junto con errores, la interfaz mantiene los modelos publicados seleccionables y muestra el diagnóstico de cada modelo rechazado.
- Si la consulta del catálogo termina correctamente y no devuelve modelos ni errores, el catálogo está vacío: no hay modelos seleccionables. No equivale a que queden modelos disponibles.
- Si la base de datos no está disponible, la API informa `database_unavailable` (habitualmente HTTP 503). La interfaz lo distingue de un catálogo vacío y conserva la última selección/catálogo que ya hubiera recibido.
- Un error inesperado de red o servidor tampoco debe interpretarse como catálogo vacío: la interfaz conserva el catálogo previo y muestra un aviso de actualización fallida.

## Límites operativos

El diagnóstico es de solo lectura. No vuelve a evaluar modelos, no cambia la selección ni activa, elimina, repara o publica artefactos automáticamente. Una reevaluación, modificación de runtime, cambio de checkpoint o acción sobre modelos concretos requiere autorización operativa y evidencia aislada propias. La razón pública orienta qué revisar; no prueba por sí sola la causa raíz ni autoriza una acción.
