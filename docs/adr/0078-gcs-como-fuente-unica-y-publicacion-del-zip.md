# ADR 0078: GCS como fuente única y publicación del ZIP en el catálogo compartido

Fecha: 2026-11-11. Estado: aceptado en el plan de integración de `origin/fix/afinamiento-integral` en `mvp` (decisiones 2, 4, 8, 9 y 10); implementado en las etapas a–f de `mvp`. Sustituye el ADR [0027](0027-importaciones-zip-privadas-locales.md) (catálogo privado y su copia en `private-imports/`) y el ADR [0073](0073-sesion-web-compatible-con-bearer-importados.md) (sesión compatible con Bearer). El ADR [0044](0044-sincronizacion-por-contenido-y-publicacion-local.md) sigue vigente: describe la sincronización GCS→local (`sync_dataset_to_local`) que este ADR mantiene.

## Contexto

Al integrar la rama existente en `mvp` convivían dos catálogos de datasets:

- **Privado, local-first (mvp):** el ZIP confirmado quedaba en disco local con dueño (`owner_id`) y se copiaba a GCS bajo `private-imports/{owner}/{ds}/`. Tenía revisiones, manifiestos, exportación ZIP, una reserva de disco opcional (`dataset_storage_*`) y una vía de identidad por Bearer (`imported_identity.py`).
- **Compartido (compañero):** GCS es el original en `datasets/{ds}/{clase}/`, con filas `conjunto_datos` y `audio`, copia local por sincronización GCS→local, acceso por rol y asignación (`ResourceAccess`, ADR [0061](0061-autonomia-investigadora-en-datasets-asignados.md)) y particiones inmutables con `partition_version` (ADR [0062](0062-particiones-explicitas-y-manifiestos-inmutables.md)).

Mantener ambos duplicaba permisos, inventario, entrenamiento y predicción, y el catálogo privado no tenía control de rol.

## Decisión

- GCS es la fuente única de datasets. No hay catálogo privado por dueño.
- Confirmar un ZIP lo publica en `datasets/{ds}/{clase}/` (objetos creados con `if_generation_match=0`) y en `conjunto_datos`/`audio`, reutilizando la subida existente. El nombre del dataset es único global (409 si existe). La copia local queda en `raw_data_dir/{ds}/{clase}/` como copia ya sincronizada. Si la publicación falla, la importación sigue local y el trabajo se reintenta sin duplicar (etapa c, [plan](../arquitectura/integracion-mvp-c-publicacion-plan.md)).
- Pueden importar administradores e investigadores (decisión 10). El importador queda asignado al dataset (decisión 2); el administrador lo asigna a los demás. El acceso es por rol y asignación, sin excepciones por dueño de importación.
- El entrenamiento de un ZIP publicado usa el catálogo estándar con `partition_version` (etapa d, [plan](../arquitectura/integracion-mvp-d-snapshots-plan.md)). El plan original preveía snapshots sobre la copia sincronizada; en d se retiró la entrada importada y en f se retiraron del código las tablas de snapshots ([ADR 0070](0070-revision-0005-y-composicion-versionada-de-triadas.md)).
- La sesión es solo por cookie; se elimina la vía Bearer (decisión 4, etapa a, [plan](../arquitectura/integracion-mvp-sesion-cookie-plan.md)).

## Alternativas descartadas

- **Mantener solo el catálogo privado.** Conserva la privacidad por dueño, pero deja fuera las asignaciones, las particiones y el inventario existente, y no controla roles.
- **Mantener ambos catálogos.** Duplica permisos, inventario y flujos de entrenamiento y predicción, con dos fuentes de verdad para un mismo audio.

## Consecuencias

- Se pierde la privacidad por dueño: un dataset importado es visible para quien tenga asignación o rol de administrador.
- Se retiran la sincronización privada a `private-imports/`, las revisiones y manifiestos privados, la reserva de disco `dataset_storage_*` (decisión 8) y la exportación ZIP (decisión 9). La exportación queda pendiente en `docs/KANBAN.md` como función posterior sobre `datasets/` y `conjunto_datos`.
- Las tablas sin uso del catálogo privado no se borran de la base (decisión 11); un borrado destructivo iría en una migración separada acordada con el compañero.
- El plan original proponía sustituir también las partes de GCS del ADR 0044; al revisarlo en la etapa h se comprobó que solo trata la sincronización GCS→local, que sigue en uso, por lo que no se marca como sustituido.
- Los manuales del catálogo privado quedan como registro histórico con nota de sustitución.
- Se relaciona con los ADR 0061, 0062, [0063](0063-respaldo-explicito-de-checkpoints-por-contenido.md), [0064](0064-almacenamiento-persistente-vinculado-al-entorno.md) y [0069](0069-integracion-de-acceso-evaluacion-y-datasets.md) existente y con el 0070.
