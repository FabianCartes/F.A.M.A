# Identidad inmutable para composiciones de modelos importados

La procedencia de `ImportedModelSource` describe un checkpoint individual. Una tríada necesita una identidad propia que fije sus tres componentes y ponderaciones; copiar la identidad del primer componente ocultaría los otros contratos acústicos y no permitiría atribuir correctamente una revisión de pesos.

Se conserva la identidad individual y se incorpora un manifiesto JSON canónico, versionado y direccionado por SHA-256. Contiene tres referencias ordenadas a modelos distintos, sus hashes registrados, cada identidad importada completa, los pesos exactos y la cohorte común. Un cambio de pesos produce otra identidad sin sobrescribir la composición anterior. La raíz es privada y física; las lecturas validan de nuevo propietario, formato, confinamiento e integridad. La publicación del descriptor no sobrescribe un archivo existente.

## Alternativas

- **Usar solo tres filas de componentes:** no identifica una combinación concreta ni conserva su historial de ponderaciones.
- **Reutilizar la procedencia del primer checkpoint:** confunde identidad individual y composición y omite los contratos de los otros componentes.
- **Introducir una tabla nueva como primer paso:** acoplaría el formato de identidad a una migración antes de resolver la integración con evaluaciones y registro. Esta decisión no descarta una asociación relacional posterior si sus contratos la necesitan.

## Consecuencias y límites

Un manifiesto consistente **no acredita** propiedad en la base de datos, disponibilidad de pesos, evaluación conjunta ni admisión al catálogo. El consumidor debe vincular cada referencia con su asociación de procedencia persistida, verificar los artefactos bajo la raíz de checkpoints y evaluar la composición exacta antes de publicarla. No puede inferir esas garantías del JSON ni convertir un descriptor válido en un modelo disponible.

Cambiar solo los pesos permite reutilizar componentes, pero exige una nueva evaluación de la combinación. Las métricas individuales no sustituyen ese informe. Se mantienen los contratos de entrenamiento e inferencia individuales y no se reorganizan los ensambles legacy.

Implementación y evidencia por cortes: [plan de tríada](../arquitectura/triad-training-inference-plan.md). La vinculación autoritativa, la evaluación conjunta, la persistencia de los informes, la publicación privada en el registro, la inferencia, el cierre automático del entrenamiento y la revisión de pesos están integrados y verificados con pruebas sintéticas (CPU, SQLite en memoria). Se conservan dos advertencias operacionales: las entradas de staging del almacén no se eliminan, y una evaluación fallida puede dejar un manifiesto o un registro pendiente no admisibles que requieren limpieza operativa futura. No se han ejecutado migraciones, entrenamiento real ni cambios en el entorno activo.
