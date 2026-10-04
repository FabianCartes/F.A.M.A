# ADR 0016: Procedencia y persistencia del entrenamiento

* **Estado:** Aceptado
* **Área:** Admisión de datasets, checkpoints locales y registro de modelos

## Contexto y decisión

El flujo podía entrenar con Aves aunque se solicitara otro dataset, registrar modelos sin asociación y anunciar éxito tras un fallo de BD. Los nombres basados en conteos también podían reutilizar destinos. Se decide vincular cada trabajo nuevo a una identidad exacta y una fuente local admitida, y reservar `completed` para el guardado confirmado de checkpoints, modelos y métricas. El [manual de entrenamiento](../manuales/manual_usuario_plataforma.md#5-módulo-3-entrenamiento-local-con-tríadas-de-ensambles) describe requisitos y comprobaciones operativas.

## Decisiones y alternativas

| Decisión | Alternativa descartada y motivo |
| --- | --- |
| Admitir solo `AvesChilenas` y `engine_diagnostics`, con registro único de nombre exacto y particiones/audio locales válidos | Aceptar cualquier nombre o sustituirlo silenciosamente por Aves atribuiría resultados a una fuente distinta; soporte universal requiere adaptación y evidencia propias. |
| Fijar ID, nombre, directorio y tablas/rutas al admitir; consumir esa fuente y revalidar ID/nombre bajo bloqueo de fila al registrar | Resolver nuevamente por nombre en el worker permite deriva de identidad. El snapshot es de metadatos y rutas, no una copia inmutable ni un hash del dataset. |
| Incluir dataset, trabajo y directorio de origen en el payload; persistir FK, tamaño y SHA-256 completo del artefacto | Deducir procedencia de etiquetas o nombres visibles no prueba origen. Los históricos NULL, incluido `fama_trained_model_7`, permanecen sin backfill por conjetura. |
| Publicar checkpoints UUID locales mediante temporal exclusivo, fsync de archivo/directorio y hard link sin reemplazo | `count + 1`, fallback `v1` o reemplazo de destino arriesgan sobrescritura en reintentos o concurrencia. La versión amigable del historial no determina el nombre del archivo. |
| Confirmar modelo y métricas del componente en un commit de BD antes de informar éxito | Tratar un rollback como advertencia y continuar hasta `completed` oculta pérdida de persistencia. Las métricas se guardan al finalizar el componente, no por commit incremental en cada época. |
| Mantener checkpoint local y BD con compensación limitada, sin afirmar transacción distribuida | Una garantía atómica entre filesystem, BD y GCS exigiría un protocolo y recuperación adicionales que este cambio no implementa. `models/<archivo>` en `ruta_binario_gcp` no acredita subida a GCS. |

## Consecuencias y límites aceptados

- `started` solo confirma admisión e inicio del worker; no acredita finalización. Una admisión inválida produce HTTP 400 y progreso `failed`. Los fallos de guardado o de identidad también quedan como `failed`, no como éxito aparente.
- La admisión comprueba estructura y existencia de archivos, no códecs, decodificación ni calidad acústica/modelo. Cambiar los bytes después de admitir puede alterar lo consumido; no existe congelación física del dataset.
- La publicación local es sin reemplazo; su durabilidad depende del soporte real de hard links y fsync. La BD usa `SELECT FOR UPDATE` para revalidar la identidad, pero su comportamiento en PostgreSQL desplegado no fue ejercitado por las pruebas aisladas.
- Si el registro falla, solo se limpia el checkpoint nuevo probado como no registrado. Si el commit pudo haber ocurrido y la consulta de comprobación falla, se conserva el artefacto: evitar perder pesos registrados prima sobre evitar un posible huérfano. El trabajo permanece `failed` ante esa incertidumbre.
- Una caída entre publicación y commit puede dejar un archivo sin fila; no se añadió reconciliación ni recuperación automática. Cada componente del ensamble tiene su commit: un fallo posterior no revierte componentes anteriores. Detener un trabajo tampoco garantiza guardar el componente en curso.
- El registro resuelve el basename del localizador contra checkpoints locales. Ni la ruta con prefijo `models/` ni el hash son evidencia de un objeto remoto. El historial expone asociación y métricas, pero su nombre amigable y ficha descriptiva no certifican procedencia histórica.

## Evidencia y continuación

ENTRENAMIENTO-1 (`09a7e22`) y ENTRENAMIENTO-2 (`b4ad280`, complemento documental `38fcd23`) cuentan con comprobaciones independientes de 64 y 84 pruebas respectivamente y revisiones nativas aprobadas/reconocidas, según el [tablero](../KANBAN.md). Esta documentación no reejecuta esas pruebas ni atribuye aprobación al candidato documental actual.

No acredita despliegue, entrenamiento real, calidad general, GPU, PostgreSQL real ni escrituras GCS. Tras autorización explícita, el siguiente paso es un smoke test de un modelo individual sin borrar históricos: comprobar FK, checkpoint/payload/hash, historial/métricas e inferencia. La curación GCS/local se valida por separado y requiere su propia autorización de escritura.

La unidad documental de rollback comprende este ADR, la sección de entrenamiento del manual y sus entradas de índice; revertir documentación no modifica modelos, archivos de pesos ni datos. No se ejecutó reversión.
