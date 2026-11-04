# ADR 0053: Procedencia durable de entrenamiento importado sin identidad legacy ficticia

**Estado:** Decisión aceptada para T3 (S10/S11); candidato local en verificación. No acredita despliegue, migración de datos existentes, evaluación ni publicación. Seguimiento y evidencia vigente: [plan](../arquitectura/entrenamiento-datasets-importados-plan.md), no este ADR.

## Contexto y decisión

`ImportedDataset.id` es una identidad privada de texto, mientras `ConjuntoDatos.id_conjunto_datos` es una identidad legacy entera. La FK de `Modelo` hacia esta última permite `NULL`, pero el registro de entrenamiento exige un dataset legacy exacto. Asignar un ID importado a esa FK o crear una fila legacy a partir del nombre confundiría propiedad y procedencia.

El usuario decidió adelantar desde T5 la asociación durable mínima necesaria para T3. `imported_model_source` vincula el modelo con propietario, dataset importado, snapshot y descripción inmutable de la preparación: hash del manifiesto de snapshot, versión preparada, perfil efectivo, clases/índices y procedencia de las anotaciones. Se registra en la misma transacción que el modelo y sus métricas; el modelo importado mantiene la FK legacy en `NULL` y `id_usuario` identifica a su propietario. No se modifica ni reasigna la procedencia de modelos existentes.

El checkpoint conserva la misma identidad; las filas de sus tres particiones y la preparación siguen en los almacenes inmutables de T1/T2. La fuente cruza `spawn` como datos serializables, sin sesión ni descriptores abiertos. El adaptador agota la verificación de T1 antes de admitir y vuelve a verificar los bytes que entrega al decoder, sin re-preparación por nombre ni sustitución del perfil o del orden de clases.

## Acceso y separación de etapas

S10 exige un usuario real activo y propietario exacto para seleccionar y consultar fuentes importadas, observar o detener su trabajo y consultar su historial. No se reutiliza el principal local `-1`, no hay transferencia automática ni compartición. Los recursos legacy conservan su acceso anterior.

T3 termina el trabajo importado en `checkpoint_persisted`, con el modelo inactivo en `standard_eval_pending`. El supervisor debe reconocer ese hito, recoger al hijo y comprobar su salida; no equivale a `completed`. Una cancelación posterior al registro conserva el artefacto ya registrado como pendiente, sin publicar. La guarda estándar vigente impide restauración y activación sin evaluaciones admitidas. Evaluación val/test, publicación y predictor importados siguen siendo T5: no se evita esa guarda ni se declara inferencia disponible.

## Alternativas y consecuencias

Se rechazó inventar una fila `ConjuntoDatos`: evitaría la asociación adicional a costa de mezclar dos espacios de identidad y aparentar un contrato legacy inexistente. También se rechazó admitir trabajos conocidos como incapaces de registrar su checkpoint y presentar un payload simulado como integración completa.

La asociación añade un esquema que requiere migración explícita, validación e idempotencia; no incluye backfill ni borrado. El arranque excluye expresamente `imported_model_source` de su lista de tablas para `create_all`, aunque un módulo de mantenimiento haya registrado antes el ORM. No se confía en un indicador `info` como mecanismo de exclusión. Un probe autorizado observó DDL real solo en SQLite en memoria: reprodujo el defecto y, tras la exclusión, verificó órdenes normal/preimportado con bootstrap legacy conservado; no es una migración operacional ni un segundo veredicto independiente. Deben conservarse snapshots/preparaciones referenciados. La persistencia local no implica subida a GCS; `/api/predict` conserva su requisito remoto. Las pruebas de T3 emplean exclusivamente estado sintético: el permiso para SQLite temporal en archivo y procesos reales se limita a la comprobación separada de `spawn` autorizada en L27 del plan.
