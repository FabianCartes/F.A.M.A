# Traspaso: evaluación conjunta de la tríada estándar (entrega B)

> Estado vigente: B implementada para entrenamientos nuevos (commits 78f90d6–3227b1e, [ADR 0081](../adr/0081-intentos-de-evaluacion-conjunta-de-triadas.md), [recibo](../receipts/triada-evaluacion-cierre-b.json)). Lo siguiente es el registro histórico del alcance investigado; la acción explícita para composiciones existentes o pesos revisados sigue fuera de alcance.

Este traspaso describe el alcance investigado de B, que permanece en pausa y no está implementada. A está cerrada dentro del alcance sintético/frontend: identificación, historial agrupado y ficha conjunta, con 139 pruebas backend previamente observadas, 662 pruebas frontend nuevas, tipos/lint/build y verificación independiente aprobados. Los dos fallos de sincronización de pruebas se conservan como cortes históricos; no modificaron producción. Estado en [el plan de A](triada-presentacion-plan.md), [recibo de cierre](../receipts/triada-presentacion-cierre-a.json) y [verificación histórica T1](../receipts/triada-presentacion-verificacion-a.json). Código A en commits locales 5e7417e, 7bff776 y 8e09e66; sin push/PR. No reanudar B automáticamente.

## Estado de partida

- Base investigada: `4e39664`. Rama de trabajo local: `feat/triad-presentation`.
- A modifica metadatos visuales en registro/selector y añade `compositions` al historial autorizado, conservando `history`. TrainingView agrupa por IDs explícitos y reutiliza los detalles individuales con pesos de composición en una ficha conjunta. No añade persistencia ni informes conjuntos.
- `dataset` es la etiqueta visual; `dataset_name` es el destino canónico de almacenamiento/autorización. No intercambiarlos.
- `TriadComposition` identifica tres componentes ordenados, pesos, dataset, partición, trabajo y versión. Revisar pesos crea una composición nueva, con `previous_id`; si la anterior estaba activa, se transfiere su activación.
- El catálogo publica solo la última composición de cada trabajo. No cambiar esa política como efecto lateral de B.

## Resultado requerido

Obtener exactitud y demás métricas por grabación de la salida combinada, no una media de las accuracies individuales. Un informe pertenece a una composición y a unos pesos concretos; nunca se hereda automáticamente al revisar pesos.

La disponibilidad para inferencia y el estado de evaluación deben permanecer separados. La propuesta conserva publicación y activación actuales, mostrando la falta de informe. Un bloqueo adicional de publicación por evaluación pendiente requiere alcance propio.

## Código comprobado durante la investigación

| Archivo | Contrato relevante |
| --- | --- |
| `backend/app/services/predictors/triad_predictor.py` | Alinea clases, fusiona vectores ponderados y decide `argmax`; valida los tres componentes, incluso pesos cero. Propaga rechazos explícitos. |
| `backend/app/services/recording_evaluator.py` | Evalúa por grabación mediante `classes` y `predict(path)`; calcula métricas y rechazos. Su procedencia actual exige un único hash de checkpoint. |
| `backend/app/services/evaluations.py`, `backend/app/evaluation_table.py`, `backend/app/schemas/evaluation.py` | Intentos e informes actuales ligados a un `id_modelo` y un checkpoint. No representan honestamente una composición estándar. |
| `backend/app/services/reevaluation.py` | Reevaluación explícita síncrona de un MAIN individual; rechaza componentes. No es una cola general de trabajos. |
| `backend/app/services/training.py` | Evalúa componentes individualmente y después registra la composición; no calcula un informe conjunto estándar. El mensaje de cierre aún afirma que el ensamble no se publicó: ajustar solo al integrar estados reales. |
| `backend/app/services/evaluation_catalogue.py`, `backend/app/main.py` | Lectura de informes en catálogo reconoce modelos individuales. Ampliación necesaria para composiciones. |
| `backend/app/services/triad_compositions.py`, `backend/app/routes/triad_compositions.py` | Creación, autorización por dataset, revisión y activación versionadas. |

Consultar ADR 0070 y ADR 0076. El segundo describe composiciones importadas; no prueba implementación estándar vigente.

## Secuencia de implementación recomendada

1. **Identidad e intentos propios.** Diseñar una persistencia aditiva de intentos de composición, sin inventar un registro `Modelo` ni usar el hash del primer componente como hash del ensamble. Incluir ID/versión de composición, IDs y hashes ordenados de los checkpoints, pesos, clases, configuraciones efectivas por componente, versión del evaluador, dataset y manifiesto del split. Preparar y probar la migración antes de aplicarla a instalaciones reales.
2. **Cálculo reutilizado.** Adaptar la procedencia del evaluador conservando su cálculo por grabación y el predictor de tríada. Verificar también identidad ante rechazos, porque esa respuesta del predictor actualmente no devuelve la lista de hashes cargados. No duplicar la lógica de fusión.
3. **Ejecución acotada.** Para entrenamientos nuevos, integrar evaluación conjunta en el flujo de trabajo existente fuera de la petición HTTP. Para composiciones existentes o pesos revisados, diseñar una acción explícita con admisión y ejecución separadas; comprobar el mecanismo disponible antes de introducir una cola nueva. Guardar estados `pending/running/completed/failed`, resultados previos y fallos saneados. Ninguna inferencia en GET, startup o reconciliación del registro.
4. **Lectura y presentación.** Exponer informes por identidad exacta de composición, con autorización existente. Conectar la futura fila/ficha de A: validación en tabla, val/test diferenciados en ficha, pendiente/fallo/ausencia sin precisión inventada.

Los informes actuales no conservan vectores de probabilidades por grabación. Evaluar composiciones ya entrenadas requiere nueva inferencia sobre datos admitidos, no reentrenamiento; no ejecutar esa operación sobre datos reales sin acordar alcance y recursos. No añadir cachés de probabilidades ni optimización de pesos para resolver la primera versión.

## Criterios de prueba

- Caso sintético donde `argmax(sum(w*p))` no coincide con una estimación basada en promedio de accuracies.
- Clases permutadas entre componentes, rechazos y peso cero conservan el contrato del predictor.
- Cambio de checkpoint, audio, manifiesto o configuración impide atribuir resultados al informe admitido.
- Pesos nuevos crean identidad nueva sin apropiarse de informes anteriores.
- Separación de grabaciones, grupos y rutas entre train/val/test; decisiones de pesos basadas en val, no en test.
- Estados, fallo parcial y reintentos preservan checkpoints, activación e informes completados anteriores.
- Consultas autorizadas correctas, denegación a datasets no asignados y ausencia de inferencia en lecturas/startup.
- Modelos individuales mantienen informes y comportamiento anteriores.

Usar TDD en interfaces públicas con CPU/datos sintéticos, SQLite en memoria y runner aislado. La investigación no ejecutó estas pruebas ni acreditó calidad ML, GPU, PostgreSQL, Docker o datos reales.

## Prerrequisito A y evidencia para retomar B

1. Leer el plan de A, la copia de memoria correspondiente y el diff local; reconciliar antes de escribir.
2. No repetir la preparación indiscriminada: el verificador sí inició y la copia incluyó 39 GiB de runtime oculto, con `tar: Cannot write: Disk quota exceeded`, seguida de caída `WriteStream`/EDQUOT. La nueva copia explícita de fuentes y fixtures (614 archivos/9,92 MB, límite 64 MiB, hashes verificados, sin datos ni `.venv`) permitió ejecutar el verificador. No se parcheó Pi ni se identificó la cuota exacta.
3. Conservar los fallos observados: suite histórica de cinco archivos con timeout de 30 segundos y suite nueva catálogo/predictor/historial con fallo de orden. El último se reprodujo igual en base `4e39664` y candidato. Predictor e historial por proceso sí pasaron; no llamar a eso suite combinada aprobada. Frontend completo (655 pruebas), tipos, lint focal y build webpack aislado aprobados. Detalle y límites en el recibo de A.
4. A está cerrada dentro del alcance documentado: historial devuelve `compositions` con id, version, job_id y tres pares ordenados id_modelo/weight; la ficha muestra «Sin evaluación conjunta» y métricas individuales. Suite final frontend 662/662 y tipos/lint/build aprobados tras dos correcciones test-only; backend 139 casos aprobados por archivo y verificación independiente conservados. Los metadatos de evaluación de B todavía no tienen un contrato definitivo en A; su implementación requiere retomar B explícitamente.

No incluye GCS real, subidas, evaluación real, despliegue, reinicios, publicación remota ni cambios de activación.
