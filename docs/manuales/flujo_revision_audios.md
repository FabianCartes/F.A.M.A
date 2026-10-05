# Revisar e incorporar audios

El audio inferido solo entra al dataset después de una validación explícita y una aprobación en la cola de revisión. Confirmar o corregir una clase no incorpora la muestra ni inicia un entrenamiento. El destino se conserva automáticamente al ejecutar el modelo: no se elige otro dataset durante la revisión.

## Recorrido de uso

1. En **Inferencia**, cargar un WAV y seleccionar el modelo. Conservar el resultado y su identificador de predicción; **Dataset de inferencia** muestra el ID persistido con ese resultado.
2. Elegir uno de los botones grandes: **Correcta**, con marca verde, o **Incorrecta**, con X roja. No hay una opción seleccionada por defecto. Si es incorrecta, elegir la clase corregida del catálogo asociado a esa inferencia.
3. Pulsar explícitamente **Enviar a revisión**. Elegir acierto/error o una corrección no envía por sí solo el feedback.
4. En **Gestión de audios**, consultar los pendientes y revisar la clase propuesta y el **Dataset de inferencia**. La clase será la predicha si se confirmó el acierto, o la corregida si se indicó un error. El destino es informativo: no hay selector de dataset.
5. Pulsar **Incorporar al dataset** para escribir en GCS y en el dataset local, o **Descartar de la cola** para retirar el pendiente sin borrar físicamente la fuente ni modificar los datasets.

Antes de enviar la validación no hay un elemento en la cola. Después del envío queda pendiente, pero todavía no hay una copia de entrenamiento. La incorporación solo termina cuando se completan ambos destinos y se persiste el estado procesado.

## Destino persistido y contrato de aprobación

La predicción guarda una instantánea nullable en `prediccion.dataset_name`, tomada del **modelo realmente ejecutado**, no de una selección de dominio ni del modelo que esté activo cuando se revise. El resultado la expone en `detalles.dataset_name` y la cola en `dataset_name`.

- Los predictores estándar de aves tienen el destino explícito `AvesChilenas`.
- Para un modelo registrado, se valida la asociación persistida con `conjunto_datos`: su nombre debe ser un componente de ruta válido. Su `ruta_gcp` puede coincidir con `datasets/<nombre>` o `gs://<bucket configurado>/datasets/<nombre>`, o ser la URI `file://` canónica del directorio local `backend/data/raw/<nombre>`, obtenido por el resolver de rutas del backend (en el contenedor: `file:///app/data/raw/<nombre>`). Se admite la barra final.
- La ruta local debe corresponder exactamente al nombre registrado y a un directorio existente; su destino físico debe permanecer dentro de la raíz raw. Se rechazan rutas externas, traversal incluso codificado, autoridades en `file://`, rutas malformadas y symlinks que escapen de esa raíz. No basta con que cualquier ruta local exista.
- No se supone que todos los bundles pertenezcan a ese dataset. Una asociación desconocida o inválida queda como `NULL`, sin impedir por sí sola la inferencia.

La asociación local verificada se expone en el catálogo y en los predictores registrados para inferencias nuevas. Este soporte no implementa incorporación local previa a GCS ni sincronización durable en segundo plano: el flujo de aprobación descrito en este manual sigue requiriendo ambos destinos.

Las predicciones antiguas o sin asociación verificable permanecen en `NULL`: no se adivina ni se rellena retrospectivamente el destino, y no existe una selección manual para repararlo. La interfaz muestra la advertencia y deshabilita la incorporación; una aprobación por API devuelve un error explícito y conserva el pendiente. **Descartar de la cola** sigue disponible.

La llamada normal es `POST /api/feedback/<ID feedback>/approve`, sin cuerpo JSON ni consulta de destino: basta el ID del feedback. La consulta `dataset_name` sigue siendo opcional por compatibilidad con clientes antiguos, pero solo se acepta si coincide exactamente con el destino persistido. Un valor distinto devuelve HTTP 409; nunca reemplaza el destino ni completa un `NULL`.

## Qué conserva cada operación

| Operación | Resultado |
| --- | --- |
| Inferir | Conserva una fuente única `raw_audios/<UUID>.wav` en GCS y registra su vínculo con la predicción y su destino verificable, si existe. |
| Validar/corregir | Registra feedback pendiente; no copia al dataset. |
| Incorporar | Descarga los bytes de esa fuente y los escribe en GCS y en el dataset local. Solo finaliza cuando ambas escrituras y la persistencia del estado terminan. |
| Descartar | Marca el feedback como procesado y lo retira de pendientes. No borra físicamente la fuente ni modifica los datasets. |

Los destinos de incorporación son:

- GCS: `datasets/<ID canónico del dataset>/<directorio real de clase>/<slug_clase>_fb_<ID feedback>.wav`.
- Local: `backend/data/raw/<ID canónico del dataset>/<directorio real de clase>/<slug_clase>_fb_<ID feedback>.wav`.

Ambos contienen los mismos bytes de la fuente. El directorio se resuelve contra el catálogo real de almacenamiento del dataset: primero se busca la clase exacta; si no existe, se exige una coincidencia única tras normalización Unicode **NFC** y `casefold`. Así, la etiqueta semántica `Rayadito` usa el directorio existente `rayadito` sin crear una carpeta paralela. Los metadatos conservan `Rayadito`, no la convierten en el nombre físico del directorio.

Una coincidencia normalizada ambigua o un catálogo ausente/no verificable producen error; un fallo al consultar el catálogo tampoco permite una alternativa inventada. Si el catálogo se obtuvo válidamente y la clase es genuinamente nueva, se permite crear su directorio con la etiqueta normalizada NFC, siempre que sea un componente de ruta válido. Esta resolución no depende de que el inventario de clases del predictor coincida exactamente con los directorios.

Si existe `metadata.csv`, la aprobación agrega una fila identificada por el nombre canónico del archivo; no crea ese CSV si falta. Conserva la clase semántica y la procedencia `feedback_<ID>` / `human_feedback`, junto con el hash de los bytes. La incorporación no incluye preprocesamiento, reentrenamiento ni comprobación de calidad del modelo.

## Reintentos, concurrencia y resolución de problemas

El primer intento de incorporación fija **dataset, clase, fuente y directorio físico** mediante una intención persistida bajo el directorio raw. Un reintento reutiliza ese directorio aunque cambie el catálogo. El nombre determinista evita nuevos objetos/archivos y la actualización de metadatos evita filas duplicadas. No borrar ni editar los archivos de intención para cambiar el destino.

El backend usa bloqueo de fila al procesar feedback y bloqueos `flock` para la intención y los metadatos; estos últimos se reemplazan de forma atómica. La protección exige escritores cooperantes. No convierte GCS, filesystem y base de datos en una transacción única: un fallo puede dejar una copia parcial, que debe completarse reintentando con la misma intención. Una vez iniciada la incorporación no se puede cambiar la validación mediante reenvíos; una vez procesado el feedback, volver a aprobarlo devuelve conflicto.

| Síntoma | Comprobación o acción |
| --- | --- |
| Sin dataset de inferencia asociado | La incorporación no está disponible; HTTP 409 por API. Mantener pendiente o descartar; no adivinar el destino ni usar un override manual. |
| Error GCS al inferir | Comprobar bucket, configuración y permisos de escritura en el entorno autorizado. Sin confirmación de carga no hay resultado exitoso persistido. |
| HTTP 503 al incorporar | La incorporación no finalizó. Revisar catálogo, acceso a la fuente, permisos GCS y escritura local; puede existir una copia parcial. Reintentar con la misma intención. |
| Fuente histórica ausente o ruta antigua | Solo se admite la fuente administrada `raw_audios/<UUID>.wav`. No se recuperan automáticamente audios históricos por nombre ni se fabrican sustitutos. La aprobación falla y el elemento permanece pendiente. |
| HTTP 409 al reenviar feedback o aprobar | El elemento ya terminó, inició su incorporación, carece de destino verificable o la consulta legacy intenta cambiarlo. Consultar el detalle; no cambiar clase/destino mediante reenvíos. |
| HTTP 422 al incorporar | Revisar componentes de ruta válidos (no vacíos, hasta 100 caracteres, sin separadores ni controles) y ambigüedad o ausencia del catálogo. `dataset_name` no es obligatorio; si se envía por compatibilidad, debe ser válido y coincidir con el persistido. |
| Reintento incompatible con la intención | No cambiar dataset, clase, fuente ni directorio. Conservar la intención original y diagnosticar el error sin editarla. |

## Migración antes de actualizar el backend

Una base existente requiere la migración explícita de [`migrate_prediction_dataset.py`](../../backend/scripts/migrate_prediction_dataset.py). `create_all` crea tablas nuevas, pero **no altera una tabla existente**. La migración no se ejecuta automáticamente al iniciar el backend.

Procedimiento para un operador autorizado; este manual no concede autorización ni acredita que se haya ejecutado:

1. Obtener y verificar un respaldo recuperable de la base de datos, según el procedimiento del operador.
2. Pausar los escritores de **inferencia y curación** para evitar operaciones concurrentes durante el cambio.
3. Suministrar explícitamente en el entorno la `DATABASE_URL` aprobada para la base objetivo, sin imprimir su valor ni exponer secretos. El script no carga `.env` ni usa una URL por defecto.
4. Desde la **raíz del repositorio**, con el intérprete Python del entorno de dependencias existente, ejecutar **antes de actualizar el backend**:

   ```bash
   python backend/scripts/migrate_prediction_dataset.py --apply
   ```

5. Verificar el resultado: `dataset_name added` si agregó la columna, o `dataset_name already present` si ya existía. Solo después de comprobar el éxito, continuar la actualización y la reanudación de escritores conforme al procedimiento autorizado de despliegue.

El script soporta **SQLite y PostgreSQL** y agrega `dataset_name VARCHAR(100) NULL` a `prediccion`. Es idempotente si la columna ya existe; no hace backfill: las filas antiguas conservan `NULL`. No exige instalar dependencias nuevas ni se debe sustituir la URL aprobada por una base elegida automáticamente.

## Prerrequisitos y límites de verificación

Se necesita un bucket GCS accesible, credenciales válidas configuradas por el operador y permisos para leer la fuente, consultar el catálogo y escribir el dataset. El backend requiere acceso de escritura al dataset local y un sistema Linux/FS con soporte de `flock`; la protección de metadatos supone escritores cooperantes.

Las pruebas en [`test_audio_review_flow.py`](../../backend/tests/test_audio_review_flow.py) conectan los endpoints con `TestClient`, SQLite aislado, predictor/registro controlados y GCS falso que conserva bytes. Las pruebas de [almacenamiento](../../backend/tests/test_storage.py), [incorporación](../../backend/tests/test_feedback_storage.py) y [migración](../../backend/tests/test_prediction_dataset_migration.py) protegen la resolución de clase, los reintentos y el cambio de esquema. No acreditan acceso a GCS real, despliegue, interacción de navegador ni calidad acústica. La integración del registro con PostgreSQL y la prueba optativa de calidad real de Chucao requieren sus entornos y artefactos propios y quedan fuera de esta verificación; Chucao se omite sin `FAMA_QUALITY_MODEL_ID`, `FAMA_QUALITY_CHECKPOINT` y `FAMA_QUALITY_AUDIO`.

Para la operación general, consultar el [manual de usuario](manual_usuario_plataforma.md) y la [guía de despliegue](guia_despliegue_operativo_docker.md). El cierre del flujo y sus verificaciones pendientes se siguen en el [tablero del proyecto](../KANBAN.md).
