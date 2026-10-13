# Interpretar la identidad del checkpoint en Predicción

La procedencia del checkpoint cargado permite identificar el archivo del que se construyó la instancia predictora. No equivale a comprobar continuamente los parámetros en memoria ni certifica la calidad del modelo. Implementación y comprobaciones en [el contrato de seguimiento](../arquitectura/identidad-checkpoint-cargado.md).

## Qué muestra cada identidad

| Dato | Qué demuestra | Qué no demuestra |
| --- | --- | --- |
| Checkpoint registrado (`checkpoint_sha256` del catálogo) | SHA-256 de los bytes del archivo consultado para el catálogo | Identidad de una instancia que ya estaba cargada |
| Checkpoint cargado por la instancia (`loaded_checkpoint_sha256`) | SHA-256 de la misma instantánea de bytes usada para cargar el predictor | Atestación continua de los tensores o de otros procesos |
| Checkpoint del informe (`provenance.checkpoint_sha256`) | Identidad de archivo declarada por la procedencia del informe | Que una predicción concreta usó ese archivo |
| Checkpoint del resultado (`detalles.loaded_checkpoint_sha256`) | Procedencia de carga de la instancia que produjo ese resultado | Que el catálogo actual siga apuntando a esa versión |

El hash esperado del modelo persistido es `Modelo.hash_binario`; el predictor valida la instantánea contra ese valor antes de deserializar. Es distinto del hash del archivo leído para presentar el catálogo.

La vista conserva la identidad registrada al iniciar la solicitud y el hash recibido en el resultado. Cambiar la selección o refrescar el catálogo no reinterpreta una predicción anterior. Un hash opcional ausente o inválido se muestra como no disponible/no verificable; no se infiere desde otro campo.

## Modelos persistidos bloqueados

Un modelo persistido sin hash esperado válido no se habilita para predicción. El registro tampoco admite un checkpoint cuyos bytes no coincidan con el hash esperado. Una consulta de un modelo bloqueado devuelve HTTP 503 con un mensaje de indisponibilidad; no se genera ni persiste una predicción para ese rechazo.

Regularizar un registro histórico requiere una operación explícita y evidencia de qué artefacto se está admitiendo. Este cambio no modifica la base de datos ni completa hashes automáticamente. No existe un nuevo comando de regularización y este manual no autoriza SQL directo ni activación de modelos.

## Si cambia un archivo después de cargar

Una instancia cargada desde A conserva la identidad A aunque el archivo de esa ruta cambie a B. Sus resultados nunca deben etiquetarse con B por volver a consultar el archivo. Si el registro pasa a esperar B, la instancia anterior no se reutiliza para esa identidad: se valida una nueva carga o se rechaza la operación. Para modelos estándar siguen aplicando además las validaciones de los informes del catálogo.

La publicación principal de entrenamiento ya usa nombres únicos y evita sobrescribir el destino. No se migran checkpoints existentes ni se cambian los scripts experimentales como parte de esta mitigación.

## Alcance operativo

Los cambios locales y las pruebas aisladas no acreditan reconstrucción de contenedores, despliegue, regularización de registros históricos o inferencia con checkpoints reales. Esas operaciones requieren su propia autorización.
