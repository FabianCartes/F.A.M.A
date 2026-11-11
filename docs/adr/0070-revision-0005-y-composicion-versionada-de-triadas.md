# ADR 0070: Revisión 0005 y composición versionada de tríadas estándar

Fecha: 2026-11-11. Estado: aceptado en la etapa f de la integración `mvp` (decisiones 1–3). Verificado en SQLite en memoria; PostgreSQL no verificado.

## Contexto

Después de las etapas d y e, el ORM y el esquema congelado `0004_integration` no coincidían:

- El ORM tenía `training_snapshot`, `training_snapshot_member` e `imported_model_source`, y ningún flujo vivo las usaba.
- El ORM tenía `imported_dataset.archived`, y la guarda de esquema que la exigía respondía 503 en toda admisión ZIP sobre una base creada por las migraciones.

La tríada estándar se entrena como tres `Modelo` independientes. Su peso solo queda en cada checkpoint (`ensemble_weight`), así que no se puede predecir con la combinación ni revisar los pesos sin reentrenar.

## Decisión

- Crear `0005_triad_composition` como revisión aditiva y congelada (`migrations/schema_0005.py`), con downgrade que falla de forma explícita. Solo crea la tabla `triad_composition`.
- No crear las tres tablas sin uso y retirar del código sus modelos y servicios. Tampoco se agrega `imported_dataset.archived`: se retiran la columna del ORM, el archivado y sus guardas. Las tablas y filas existentes no se borran (decisión 11).
- La composición guarda el dataset, la `partition_version`, el `job_id`, los tres `id_modelo` ordenados con sus pesos, el autor, la fecha y la versión anterior.
  - Una revisión de pesos es una fila nueva: `version` + 1, con `previous_id` apuntando a la anterior. Nunca se edita una fila existente.
  - La restricción única `(job_id, version)` impide dos versiones iniciales o dos revisiones concurrentes que partan de la misma versión.
  - Las restricciones `CHECK` exigen pesos no negativos y tres modelos distintos. La suma igual a 1 la valida el servicio.
  - La columna booleana `activo` (por defecto falso) marca la composición activa como modelo por defecto: solo puede haber una entrada activa entre `modelo` y `triad_composition`, activarla exige un administrador y una revisión de pesos de la composición activa transfiere `activo` a la nueva versión en la misma transacción.
- El esquema de HEAD es igual al ORM más las cuatro tablas retiradas del código en la etapa b, que se conservan en la base. `tests/test_schema_head.py` lo comprueba.

## Alternativas consideradas

- **Crear en 0005 las tablas sin uso.** Daría paridad con un ORM que nadie usa, y quedarían permisos y mantenimiento sin propósito.
- **Agregar `archived` en 0005.** Contradice la decisión 11 tal como está escrita.
- **Derivar la composición de los checkpoints.** No necesita migración, pero las revisiones de pesos no quedan persistidas ni versionadas, y obliga a reescribir los checkpoints.

## Consecuencias

- Las bases en `0004_integration` se actualizan con `python -m app.schema upgrade --apply`. La instalación y la transferencia de historial usan el esquema 0005.
- Los scripts de permisos deben incluir `triad_composition` y aceptar la revisión 0005 (etapa f, T3).
- Las restricciones `CHECK` y los tipos en PostgreSQL 16 no se verificaron en esta etapa, porque la verificación se limitó a SQLite.
- Las tríadas importadas existentes no se recuperan; sus filas se conservan.
