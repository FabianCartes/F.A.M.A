# Preparar y seleccionar una versión identificada del dataset

DATA-6 convierte la frescura del origen en un requisito de admisión del entrenamiento. Un trío preparado con checksum válido todavía puede estar desfasado. Los manifiestos `.complete` schema2 nuevos registran el SHA-256 del índice de origen, los hashes de las particiones, los parámetros de reparto, la política de agrupación y un `version_id` determinista.

## Preparación explícita

Lo siguiente es una **plantilla de comando de operación**, no una operación ejecutada durante la implementación. La preparación sobre datos reales requiere autorización propia. El almacén de versiones y las raíces de audio deben existir ya como directorios físicos absolutos, sin antecesores symlink. No coloque el almacén dentro de una raíz de audio ni a la inversa.

Desde `backend/`, con el intérprete validado del proyecto:

```bash
python -m training.prepare_dataset --help
python -m training.prepare_dataset \
  --dataset AvesChilenas \
  --index-csv /absolute/raw/AvesChilenas/metadata.csv \
  --raw-root /absolute/raw/AvesChilenas \
  --versions-dir /absolute/prepared/AvesChilenas \
  --seed 42
```

Use `--processed-root` cuando el índice explícito referencie audio procesado; se pueden admitir ambas raíces por etapa. `engine_diagnostics` también está soportado, sin equiparar sus clases o identidades con las del dataset de aves. Los ratios se mantienen en 70/15/15 con recuentos aproximados y cobertura global de clases estricta.

El éxito imprime un JSON con `version_id`, `output_dir`, recuentos y ratios reales. El directorio hijo se nombra por el identificador de versión. Repetir la misma preparación rechaza el destino existente; nunca lo sobrescribe ni lo adopta en silencio. Un origen modificado puede crear un hijo distinto conservando las versiones previas. Las salidas parciales sin marcador de completado válido no son admisibles. Ningún entrenamiento, promoción, registro en base de datos o subida a la nube se ejecuta automáticamente.

## Selección en entrenamiento

`POST /api/training/start` acepta campos opcionales:

```json
{
  "dataset_name": "AvesChilenas",
  "prepared_version": "<64 caracteres hexadecimales en minúsculas>",
  "allow_historical_preparation": false
}
```

El servicio resuelve un hijo coincidente bajo su directorio de preparados configurado, o fija por identidad la preparación única configurada. No se aceptan rutas, recorridos de directorio ni nombres de directorio arbitrarios como identificadores de versión. Para AvesChilenas, el `FAMA_TRAINING_AVESCHILENAS_PREPARED_READ_DIR` existente puede nombrar el almacén o una versión única. Sigue siendo un directorio físico de lectura; ningún override se modifica automáticamente. Los demás datasets conservan su ubicación canónica actual.

Por compatibilidad, omitir el anclaje usa solo la preparación única configurada, siempre que sea schema2 y esté vigente. No elige un último hijo. La admisión correcta declara `preparation.version_id` y `preparation.historical`; el checkpoint guarda `preparation.manifest` y `preparation.historical` de esa misma instantánea admitida. Iniciar un trabajo no acredita terminación ni persistencia del checkpoint.

La admisión ordinaria rechaza un desfase del índice de origen con `Stale prepared dataset`. Prepare una versión nueva explícitamente y selecciónela; no edite los checksums para silenciar el error. El uso histórico deliberado exige a la vez un anclaje de versión y `allow_historical_preparation: true`. Omite únicamente la frescura: siguen aplicándose la integridad de las particiones, las raíces, las comprobaciones de códec, la agrupación y la validación de clases. La ejecución histórica no puede volver disponible un artefacto de audio que no lo esté.

El esquema1 heredado sigue soportado por `load_prepared_dataset` para los flujos existentes de lectura y evaluación. El entrenamiento a través de `load_prepared_version` lo rechaza con `Legacy preparation`; no se asigna retroactivamente un hash del índice vigente a particiones antiguas. Por tanto, el despliegue real exige una versión recién preparada antes de que los datos antiguos puedan entrenar bajo este contrato.

## Procedencia curada de grabaciones

Sin evidencia, mantenga el feedback histórico en su grupo conservador actual. No sustituya `recordist` por un identificador de feedback ni trate hashes diferentes como grabaciones independientes.

Cuando alguien haya verificado que un audio de feedback nuevo deriva de una grabación indexada original, la aprobación puede incluir el parámetro de consulta opcional:

```text
POST /api/feedback/<feedback-id>/approve?curation_source_id=<xc-id-original>
```

Esta es una declaración de procedencia humana. El servidor verifica que la referencia identifique de forma única a una grabación canónica original, no procedente de feedback, en el destino AvesChilenas persistido; no analiza si el audio es un recorte o una transformación de esa grabación. Nunca proporcione una referencia solo para obtener una partición preferente. Las referencias ausentes, de feedback a feedback y de dominios no soportados fallan de forma explícita.

La intención de aprobación persiste y fija la referencia; los reintentos pueden omitirla pero no cambiarla. La fila canónica de feedback conserva `recordist="human_feedback"` y añade `curation_source_id`. La preparación, la admisión de entrenamiento y la reevaluación derivan el mismo grupo efectivo a partir del `recordist` de la grabación original. Los grupos ordinarios de grabador permanecen indivisibles. El feedback desconocido mantiene su grupo común. Una cantidad insuficiente de grupos o una cobertura de clases inviable rechazan la preparación antes de reservar el destino.

Este cambio no rellena la procedencia histórica. Cualquier corrección de registros existentes exige una operación de curación auditable y autorizada por separado. Las pruebas sintéticas demuestran pertenencia curada en las tres particiones solo cuando existen grupos originales independientes y cobertura suficiente; no prometen redistribución de los cinco registros actuales.

## Límites de verificación y reversión

Las comprobaciones usan audio y CSV sintéticos privados y SQLite en memoria a través del [runner aislado](integracion-flujo-entrenamiento.md#reproducir-comprobaciones-aisladas). No acreditan el comportamiento en GPU, el funcionamiento con PostgreSQL, la calidad del modelo, el despliegue ni la pertenencia en datos reales.

Revierta el código de DATA-6 como un cambio de contrato coherente, no solo como su escritor de manifiestos. Conserve los directorios de versiones y los checkpoints; la reversión no autoriza borrar datos. Los consumidores más antiguos rechazan los marcadores schema2, por lo que restaurar una aplicación anterior también exige seleccionar explícitamente una preparación legacy compatible. No existe degradación ni reescritura automática de formato.