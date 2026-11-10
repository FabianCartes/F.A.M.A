# Entrenamiento de fuentes importadas — contratos T3 y T4

**Estado:** implementación funcional T3 en commit `381d09a6922657d6a304b5d7d2d129ee2981376f`, con los límites de evidencia indicados abajo; no acredita despliegue. La pregunta S11 del verificador se reprodujo y corrigió mediante el probe SQLite en memoria autorizado en L30 del plan: el arranque excluye expresamente `imported_model_source`, también cuando el ORM se importa antes de `app.main`. Los órdenes normal/preimportado pasaron en procesos frescos y conservaron la inicialización legacy. La verificación independiente anterior pasó 38 pruebas con veredicto inconcluso; la resolución posterior es evidencia del padre, no una nueva aprobación independiente. No se ejecutó DDL de producción. Consultar el [plan y su Log](../arquitectura/entrenamiento-datasets-importados-plan.md) para el cierre efectivo; este manual no autoriza operaciones reales ni afirma que el despliegue incorpore estos cambios. T3 conecta catálogo, admisión, consumidor y persistencia local; T4 añade la UI/preparación explícita con cierre funcional en `e6ccade`. Evaluación/publicación/predictor siguen pendientes en T5.

## Requisitos previos

1. Colección WAV supervisada, con una etiqueta por archivo y propietario real. Una importación ZIP válida no basta para entrenar; no se modifica el importador para imponer requisitos ML.
2. [Snapshot local T1](snapshots-locales-entrenamiento.md) completo e íntegro, propiedad del mismo usuario.
3. [Preparación T2](preparacion-datasets-importados.md) seleccionada por versión inmutable: mapa explícito de grabaciones/grupos, procedencia de anotaciones, todas las clases en train/val/test y perfil efectivo de audio/arquitectura. No se deduce independencia de nombres ni hashes. Menos de diez grabaciones independientes por clase solo advierte.
4. Asociación de procedencia `imported_model_source` migrada explícitamente, con esquema compatible, además de los esquemas anteriores. No se crean filas legacy ficticias ni se transfieren colecciones del propietario de desarrollo `-1` a cuentas reales.
5. Configuración de almacenamiento en el servidor: `FAMA_IMPORT_ROOT`, `FAMA_TRAINING_SNAPSHOT_ROOT` y `FAMA_IMPORTED_PREPARED_ROOT`. Las tres rutas deben ser absolutas y corresponder a los almacenes utilizados por T1/T2. Se consultan al acceder a una fuente importada, sin defaults de otro dataset; no se aceptan rutas del cliente. El servidor necesita leer los snapshots y preparados conservados y escribir su directorio habitual de checkpoints.

T1/T2 conservan interfaces Python explícitas; T3 no añade su preparación automática ni una UI. Tampoco descarga pesos para validar elegibilidad. Que una arquitectura sea compatible no acredita disponibilidad de sus pesos preentrenados o recursos de ejecución; un fallo del constructor no debe convertirse en entrenamiento aleatorio silencioso.

## Preparación T4 en Entrenamiento — cierre funcional local

La implementación local incorpora el puente de preparación, cliente privado tipado y selección/preparación visual en TrainingView. Las comprobaciones propias están aprobadas: 389 pruebas backend, 413 frontend, tipos y compilación; lint sin errores y con una advertencia de hooks. La prueba en navegador real con HTTP completamente simulado verifica selección existente/nueva, parámetros, checkpoint pendiente y cierre de sesión. La verificación independiente acotada aprobó 11 pruebas backend y 13 frontend sin defectos severos confirmados. El usuario autorizó incluir la corrección local previa de parámetros individuales y sus pruebas como prerrequisito preservado, no como autoría nueva de T4; la unidad está registrada en el commit `e6ccade11d62868067de17fff2dc9f1db833b80c`; este manual no acredita despliegue ni autoriza operaciones reales. Resultados y límites en el [recibo T4](../receipts/imported-training-t4-verification.json).

### Uso de la interfaz

Con sesión activa, Entrenamiento abre por defecto la fuente importada: al volver tras confirmar una importación, consulte su colección y los requisitos pendientes sin cambiar la fuente. Legacy permanece como opción secundaria y una selección manual se conserva al refrescar la misma sesión. Sin una preparación propia válida seleccionada, el inicio permanece deshabilitado; importar no prepara ni entrena automáticamente.

1. Con una sesión web real, compruebe que **Tipo de fuente** muestra **Importada**. El catálogo privado se carga por separado del catálogo/hardware/historial legacy; un fallo privado no se presenta como catálogo vacío exitoso.
2. Seleccione su colección por ID estable. Para reutilizar una preparación, elija explícitamente su par snapshot/versión en **Preparación existente**: no crea una nueva copia ni inicia entrenamiento.
3. Para preparar una cohorte nueva, pulse **Crear snapshot y obtener plantilla**. Espere el recurso completo; consulte los miembros verificados como JSON (ID, clase y ruta original de anotación, no una ruta del servidor). La plantilla deja recording_id/group_id vacíos deliberadamente.
4. Complete el mapa exacto, la procedencia JSON y el perfil completo compatible, además de la semilla. No se infieren grupos ni políticas por el nombre de la colección. Pulse **Preparar snapshot** y espere el resultado. Corrija los requisitos indicados si falla; las advertencias por cantidad reducida no deshabilitan una versión preparada válida.
5. Al seleccionar una preparación, audio/ventanas y arquitectura quedan fijados al perfil y solo se permite modelo individual. Épocas, learning rate y batch siguen siendo editables; sus valores visibles se envían tanto globalmente como en la configuración del modelo. Cambiar fuente/colección o cerrar sesión descarta la selección privada.
6. Inicie entrenamiento por separado con el botón habitual. La respuesta de inicio no acredita finalización. **Checkpoint persistido; evaluación pendiente** es terminal para el sondeo de ejecución, no éxito global, publicación ni activación. Evaluación/publicación/predictor siguen en T5.

No hay porcentajes de preparación inventados ni reintentos automáticos. Tras una desconexión vuelva a consultar/reseleccionar un recurso existente antes de solicitar otra preparación: cerrar el panel no demuestra cancelación del trabajo síncrono del servidor.

Todas las rutas siguientes exigen identidad real activa mediante la sesión web por cookie del mismo origen; se retiran `imported_identity` y la autenticación Bearer. Los recursos ajenos e inexistentes responden con el mismo 404. El preflight de esquema es de solo lectura: ausencia/incompatibilidad responde 503 y requiere intervención explícita del operador, nunca auto-DDL.

| Operación | Cuerpo / resultado |
| --- | --- |
| `POST /api/training/imported/snapshots` | `{ "dataset_id": "<ID propio>" }`; 201 con snapshot `state: ready` solo después de completar T1. |
| `GET /api/training/imported/snapshots/{id}` | Descriptor sin propietario interno; verifica manifiesto y audio antes de responder ready. |
| `GET /api/training/imported/snapshots/{id}/members` | Metadatos de todos los miembros tras verificar completamente el audio; máximo 20 000 miembros. |
| `POST /api/training/imported/snapshots/{id}/preparations` | `mapping`, `provenance`, `seed` y `profile` explícitos según T2; 201 tras publicación completa, sin iniciar entrenamiento. |
| `GET /api/training/imported/snapshots/{id}/preparations/{version}` | Perfil, clases ordenadas, semilla y advertencias de una versión exacta; verifica índices y audio antes de responder ready. |

El JSON de escritura está limitado a 8 MiB antes de analizarlo. No se aceptan campos adicionales de snapshot, propietarios ni rutas del cliente. El mapa cubre exactamente los `member_id` obtenidos e incluye `recording_id` y `group_id` por miembro; la procedencia describe la fuente de las anotaciones. No inventar grupos por nombre/hash. El perfil contiene todos los campos de audio y las políticas explícitas de T2; no adoptar defaults legacy por omisión. Los errores semánticos de T2 conservan su código/mensaje accionable; menos de diez grupos independientes por clase advierte y no bloquea por sí solo.

Estas rutas son síncronas en threadpool, no una cola ni una promesa de duración. No hay 202 ni reintento automático. Si se desconecta el cliente, no se puede afirmar cancelación del servidor: vuelva a consultar el catálogo y seleccione un recurso propio existente antes de solicitar otra preparación. La preparación nunca inicia automáticamente un entrenamiento. La publicación atómica de T1/T2 conserva la integridad; no se añade un bloqueo RAM con supuestas garantías multiworker.

Evidencia focal del candidato: `docs/receipts/imported-training-t4-tdd/`; consultar cada recibo JSON y sus streams crudos para distinguir RED intencionado, fallo de fixture y GREEN. Las pruebas DOM focales cubren preparación explícita y selección existente, payload efectivo/individual, descarte de respuesta tardía y cierre de sesión, y `checkpoint_persisted`. Por separado, el padre ejecutó tipos, lint, compilación y el flujo en navegador real usando una copia temporal sin `.env` y todas las respuestas API interceptadas. La corrección de `turbopack.root` se aplicó solo a esa copia; no cambia la configuración del proyecto. El primer intento de navegador se bloqueó por origen de API y el siguiente guion agotó su timeout por no abrir el menú responsive; esos fallos se conservan, y la ejecución corregida fue autorizada explícitamente. No se acredita con esta prueba el transporte de cookies contra un backend real, el proxy desplegado ni datos operacionales.

## Catálogo y selección HTTP

Los modelos importados permanecen privados e inactivos: el propietario puede consultar su catálogo, pero `POST /api/training/models/{id}/activate` devuelve HTTP 200 con `{"success": false, "error": "Los modelos importados no pueden activarse globalmente."}` sin cambiar activos ni el default global. El acceso anónimo conserva 401 y el propietario ajeno 404; esto no cambia la activación legacy ni acredita todavía predicción HTTP importada.

Los ejemplos describen contratos; no son instrucciones para iniciar trabajos sobre una instancia real sin la autorización operacional correspondiente.
Un predictor público ya registrado conserva la selección legacy sin un preflight DB adicional; esto no promete éxito offline: un fallo posterior al guardar la predicción sigue respondiendo 500 después de la subida confirmada y la inferencia.
Por decisión explícita, un registro frío cuya identidad no pueda verificarse no enumera ID, aliases ni rutas en errores del catálogo; si era activo, bloquea el default con un error genérico. Esto estrecha el diagnóstico legacy de identidades desconocidas, no sus permisos: los rechazos identificables se conservan cuando la identidad legacy está acreditada.

En la integración local T5, `POST /api/predict?model_id=<ID o alias exacto>` resuelve un importado desde su asociación persistida y exige su propietario activo mediante cookie de sesión, incluso con registro frío. Admite ID canónico, ID numérico, nombre y stem del checkpoint persistido; un recurso ajeno responde 404 sin enumerarlo y uno propio sin identidad exige autenticación. La publicación valida procedencia, informes y pesos antes de usarlo, no cambia el default y conserva la confirmación GCS obligatoria antes de inferir. Omitir el ID o usar `default` conserva la selección pública legacy. La prueba HTTP focal está pendiente: este contrato no acredita operación real ni cierre de T5.

- `GET /api/models`: conserva el catálogo público legacy, sin modelos importados ni autenticación global nueva.
- `GET /api/models?include_imported=true`: en la integración local T5 añade solo los modelos importados del usuario real activo, autenticado mediante la misma cookie de sesión de los recursos importados. No acepta un propietario elegido por el cliente ni cambia el default global. La aparición en este catálogo no acredita predicción HTTP ni el cierre de T5. La comprobación histórica del catálogo con Bearer, anterior a la migración a cookie, está registrada en `docs/receipts/imported-training-t5-tdd/19-green-private-http-catalogue.json`; no valida cookies ni el startup de la aplicación.
- `GET /api/training/datasets`: conserva el catálogo legacy y su acceso anterior.
- `GET /api/training/datasets?include_imported=true`: exige identidad real existente y activa mediante cookie web, según el [contrato de sesión](sesion-web-importados.md); añade solo las colecciones del propietario. Cada entrada importada tiene `source_type: "imported"`, `id`, `name`, `eligible`, `reasons` y `preparations`.
- Una opción preparada contiene `snapshot_id`, `prepared_version`, `eligible`, `reasons`, `profile` y `warnings`. Este `prepared_version` se envía como **`imported_prepared_version`** al iniciar, no como la opción homónima de preparados legacy.
- `preparation_required` indica que no hay una preparación seleccionable; `source_migration_required` que falta un esquema compatible; `source_unavailable` que la fuente no puede verificarse; `profile_conflict` que la arquitectura/audio/ventanas no coinciden. No confundir esos motivos con una importación inválida.
- El catálogo limita la consulta a 128 colecciones y 128 snapshots listos del propietario y a 512 versiones en el almacén preparado. Si excede el presupuesto responde 503 con `catalog_budget`; no representa el resultado truncado como completo. T3 no introduce paginación ni acredita escala máxima. Enumerar elegibilidad verifica bytes y puede ser costoso: no equivale a una comprobación operacional de latencia.

Cuerpo de `POST /api/training/start` para un perfil T2 `audio_cnn` ya existente (IDs ilustrativos que deben reemplazarse por los propios):

```json
{
  "imported_dataset_id": "0123456789abcdef0123456789abcdef",
  "snapshot_id": "abcdef0123456789abcdef0123456789",
  "imported_prepared_version": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
  "architecture": "AudioCNN",
  "epochs": 1,
  "batch_size": 2,
  "seed": 42
}
```

Esta selección es alternativa a `dataset_name`, `prepared_version`, `allow_historical_preparation` y `is_tri_model`; no mezclar esas opciones ni enviar `owner_id` u otros campos adicionales. Dataset/snapshot son IDs hexadecimales de 32 caracteres; la versión preparada tiene 64. La selección incompleta o incompatible con el esquema HTTP responde 422, antes de admitir un trabajo.

Arquitecturas: `audio_cnn` → `AudioCNN`, `panns_cnn14` → `PANNs-CNN14`, `efficientnet_b0` → `EfficientNet-B0`, `convnext_nano` → `ConvNeXt-Nano`, `resnet34d` → `ResNet-34d`. T3 admite una única arquitectura que coincida con el perfil preparado; no genera un ensamble/trío a partir de él. Los hiperparámetros de ejecución no cambian ese perfil.

El audio efectivo y el salto de ventana proceden del perfil T2 explícito/versionado. Omitir `audio_config` y `windowing_config` en la petición no adopta defaults legacy. Si se envían, sus valores efectivos validados deben coincidir; los defaults del DTO también cuentan. La política de selección es `energy_peak_pad`; las opciones de ventana aceptadas son el salto preparado, `aggregation_mode: "max"`, `gem_p: 3.0`, `vad_threshold: 0.0`. No modificar estas opciones para aparentar otra preparación.

## Autorización y errores

- No hay bypass `-1`, compartición ni propiedad elegida por el cuerpo. La autenticación usa el usuario real activo, no el principal de desarrollo del importador.
- Falta de token, sujeto inválido, cuenta inexistente/inactiva o token inválido se rechazan con 401 según el contrato vigente de autenticación; configuración de autenticación ausente puede producir 503.
- Una fuente inexistente, ajena, incompleta, corrupta o no registrable se rechaza antes del job con 404 y `detail: {"code": "source_unavailable", "message": "Fuente importada no disponible."}`. Ajena e inexistente no se distinguen. Los conflictos propios de perfil también usan 404, con `profile_conflict` y un mensaje sin rutas internas.
- No se asignan job, proceso ni estado nuevo por esos rechazos. El preflight de esquema es solo lectura: no migra, repara ni rellena tablas durante una petición.
- `GET /api/training/progress` y `POST /api/training/stop` requieren el propietario activo cuando el trabajo actual es importado. Otro usuario obtiene 404, sin observar ni cancelar el trabajo. Cuando es legacy se conserva el acceso anterior.
- `GET /api/training/history` conserva el historial legacy y excluye modelos importados. `?include_imported=true` requiere autenticación y añade únicamente los modelos importados del propietario, con `imported_source`. Un ID importado no concede acceso por conocerlo.
- La ruta de activación exige autenticación/propiedad para un modelo importado y conserva la guarda de evaluaciones: T3 no autoriza ni permite activarlo por guardar el checkpoint.

## Qué acredita cada estado

| Resultado | Significado y límite |
| --- | --- |
| Respuesta `started` con `job_id` | Fuente validada y trabajo admitido; no acredita checkpoint, evaluación ni inferencia. |
| `training` | Hijo en ejecución; los lectores verifican cada muestra contra tamaño/hash admitidos antes de decodificar. No re-preparan por nombre ni rellenan audio corrupto con ceros. |
| `checkpoint_persisted` | Hijo terminado correctamente y recogido por el supervisor; checkpoint local, modelo, asociación y métricas registrados. Sigue pendiente evaluación/publicación T5. |
| Historial `standard_eval_pending`, `active: false` | La guarda estándar impide restauración/publicación y activación sin informes admitidos. No se ha subido el checkpoint a GCS. |
| `stopped` tras registro | Conserva el checkpoint ya registrado como pendiente; no inicia evaluación ni publicación. |
| `failed` | No se afirma éxito. Fallos previos a commit revierten registros y limpian solo el checkpoint nuevo probado como no registrado. Ante commit indeterminado se conserva el artefacto y se informa incertidumbre, según el contrato existente. |

`imported_source` vincula propietario, dataset, snapshot/hash del manifiesto, versión preparada, perfil, clases/índices y procedencia de anotaciones. La asociación y las métricas se guardan en la misma transacción del modelo, con FK legacy `NULL`; el checkpoint contiene la misma identidad. Conservar los almacenes T1/T2 referenciados: no existe GC automático ni traslado/transferencia de propiedad como parte de T3. Véase [ADR 0053](../adr/0053-procedencia-durable-de-entrenamiento-importado.md).

## Migración y mantenimiento explícitos

La API Python pública es `scripts.migrate_imported_training_source.migrate_imported_sources(engine, writers_stopped=True)`, desde el entorno backend adecuado. Solo un operador autorizado debe proporcionarle un engine de la instancia objetivo, después de respaldo y parada coordinada de escritores. No hay CLI nuevo, DDL al seleccionar una fuente, backfill ni ejecución automática de esta operación. El bootstrap de `app.main` excluye esta tabla por nombre antes de `create_all`; el indicador ORM `info` por sí solo no ofrece esa garantía. La exclusión no modifica el bootstrap de las tablas anteriores. Este cambio solo ejecutó migraciones en bases sintéticas de pruebas.

El migrador verifica dialecto SQLite/PostgreSQL, tablas requeridas, columnas/tipos y restricciones de la asociación; crea la tabla solo si está ausente y acepta repetirlo sobre un esquema compatible. Rechaza un esquema incompatible sin repararlo. `validate_imported_sources(engine)` comprueba el esquema existente sin DDL y se usa antes de admitir y para la elegibilidad. Las pruebas SQLite no certifican DDL/locks PostgreSQL reales.

No borrar la tabla para revertir código ni eliminar snapshots/checkpoints: se perdería trazabilidad. La reversión operacional requiere un plan aparte que preserve modelos, métricas, asociación y archivos y considere lectores/escritores; no se añade una orden destructiva de rollback.

## Evidencia y límites

Evidencia cruda por comando/exit/stdout/stderr en `docs/receipts/imported-training-t3-tdd/`; seguimiento de resultados nuevos y fallos conservados en el Log del plan. Las pruebas de cobertura añadidas a caminos ya implementados se identifican como comprobaciones ordinarias, no como RED retrospectivo.

- Suite guardada original: SQLite en memoria, datos/modelos CPU sintéticos, temporales/cachés privados, red bloqueada y hashes protegidos. `spawn` no pertenece a esa suite.
- Comprobación separada de `spawn`: autorizada en L27, con procesos reales y SQLite temporal en archivo; no usa ni acredita la guarda del runner. Comprueba el módulo `test_training_spawn.py`, incluidos casos importados; red bloqueada durante la ejecución del pipeline sintético hijo. Temporales/cachés privados y limpieza observada. No afirmar que esta prueba sea un sandbox OS.
- El [diferencial reproducible](../receipts/imported-training-t3-differential.py) copia base T3 y candidato a scratch privado, aplica el mismo probe temporal a ambos y compara respuestas HTTP/estado/exit/stderr legacy. Normaliza únicamente identidades volátiles de job/versión y tiempos declarados; no introduce tests permanentes dependientes del historial Git. Su resultado debe consultarse en el JSON de evidencia, no inferirse por existir el script.

No acredita Docker/Python 3.12, GPU, PostgreSQL, calidad ML, escala/latencia, recursos de pesos preentrenados, UI contra servicios reales, evaluación/predictor T5 ni entrenamiento operacional T7. `/api/predict` mantiene su requisito GCS; entrenar localmente no lo convierte en una ruta sin cloud.
