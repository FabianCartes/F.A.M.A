# ADR 0023: Identidad del checkpoint cargado por el predictor

La comparación entre el hash del archivo registrado y el del informe de evaluación no identifica por sí sola el checkpoint usado para construir una instancia en memoria. Se decide asociar a la instancia el SHA-256 de la misma instantánea de bytes usada para cargarla y conservar esa identidad en cada resultado. La interfaz distingue identidad registrada, procedencia de carga e identidad del informe; ninguna equivale a atestación continua de los tensores.

## Política estricta para modelos persistidos

El usuario eligió bloquear la predicción cuando el modelo persistido no tiene hash esperado, en lugar de conservar inferencia histórica con garantía limitada. Un registro sin `hash_binario` válido requiere regularización explícita; no se calcula ni persiste un valor automáticamente como parte de este cambio. Si la instancia cargada no corresponde a la identidad esperada, no puede usarse silenciosamente para ese registro.

## Consecuencias y límites

- El hash de carga es evidencia de procedencia del checkpoint, no un hash de los parámetros después de cargar, mover de dispositivo o ejecutar el modelo.
- Un archivo cambiado después de cargar A no puede cambiar retroactivamente la procedencia de la instancia A ni de sus resultados.
- La publicación principal de entrenamiento ya utiliza nombres únicos y publicación sin sobrescritura. Se conserva; no se migran checkpoints ni se modifican scripts experimentales.
- No se introduce una migración de esquema, regularización de registros, activación de modelos o despliegue automático.
- La implementación y su evidencia se siguen en [identidad-checkpoint-cargado](../arquitectura/identidad-checkpoint-cargado.md). No se afirma verificación completada hasta cerrar esas comprobaciones.
