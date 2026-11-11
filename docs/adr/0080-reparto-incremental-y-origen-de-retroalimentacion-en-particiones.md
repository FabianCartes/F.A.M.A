# ADR 0080: Reparto incremental y origen de la retroalimentación en las particiones

Fecha: 2026-11-11. Estado: aceptado en el [plan de mejoras de particiones](../arquitectura/particiones-mejoras-plan.md) (S1–S3, decisiones 1 y 2).

## Contexto

Una versión de particiones es un manifiesto inmutable que fija los audios y su reparto en entrenamiento, validación y prueba ([ADR 0062](0062-particiones-explicitas-y-manifiestos-inmutables.md)). El reparto `grouped-hash-v2` agrupa por hash, grupo de origen y grabador y asigna grupos completos con `sha256(semilla:grupo)` y metas por clase. Tenía dos límites:

- Agregar audios obligaba a recalcular todo; un grupo podía cambiar de split, y las métricas de prueba de una versión a otra dejaban de ser comparables.
- La retroalimentación aceptada se registra con `recordist=human_feedback` y sin `source_group`, así que quedaba excluida de toda versión nueva sin un aviso claro en el flujo de entrenamiento.

## Decisión

- **Origen de la retroalimentación.** Al preparar una partición, cada aporte toma un origen derivado de la base: `prediction:{id_prediccion}` (la predicción de la que salió) o, si corrige una grabación del dataset (`curation_source_id`), `recording:{xc_id}`, que también se asigna a esa grabación. El origen es una identidad más del agrupamiento, como `source_group`. No se reescribe `metadata.csv`, así que los aportes ya aceptados entran igual. Sigue excluido un aporte sin ningún origen trazable.
- **Reparto incremental.** Una versión puede prepararse sobre una versión base guardada (`base_version`). Los audios de la base que siguen registrados con el mismo hash y la misma clase conservan su split; los grupos nuevos se reparten con el mismo algoritmo, partiendo de los conteos ya fijados. Un audio nuevo que pertenece a un grupo de la base hereda su split. Si un audio nuevo une grupos que estaban en splits distintos, la preparación se rechaza y hay que crear una versión desde cero. Se exige la misma semilla y los mismos porcentajes de la base. El manifiesto registra `policy.algorithm = "grouped-incremental-v1"` y `policy.base_version`.
- **Versiones desactualizadas.** La lista de versiones informa, por versión, cuántos audios registrados no incluye (`freshness.new`, sin contar los que ya figuraban como excluidos) y cuántos de sus audios cambiaron o desaparecieron (`freshness.changed`).

## Alternativas descartadas

- **Escribir `source_group` al aceptar la retroalimentación.** Deja la información junto al audio, pero obliga a reescribir filas existentes de `metadata.csv` para los aportes anteriores.
- **Recalcular desde cero con la misma semilla.** Más simple, pero puede mover audios entre splits y romper la comparabilidad que pide S3.

## Consecuencias

- Las versiones nuevas sin base se calculan igual que antes: una comparación diferencial de `_split` contra la implementación anterior dio el mismo reparto en 300 casos aleatorios. Las versiones guardadas no cambian.
- Las versiones nuevas pueden incluir más audios que antes (la retroalimentación), y sus entradas pueden traer el campo `origin`.
- Un reparto incremental repetido puede alejar los porcentajes reales de los objetivos, porque nunca mueve lo ya asignado; cuando importe el equilibrio, conviene una versión desde cero.
