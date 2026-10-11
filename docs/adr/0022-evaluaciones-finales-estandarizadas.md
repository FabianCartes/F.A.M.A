# ADR 0022: Evaluaciones finales estandarizadas

* **Estado:** EVAL-1 a EVAL-6B cerrados en los alcances documentados. EVAL-6B reevaluó #11 en `fama_db` de desarrollo; la calidad resultó baja y no está aprobada. La tabla nueva se verificó en solo lectura, no se probó upgrade de tabla v1. API/browser desplegados y suite backend global (12 FAIL/5 SKIP) siguen pendientes.
* **Área:** Informes finales de clasificación multiclase de aves y motores.

## Decisión y alcance actual

Separar el informe final del historial por época y compartir un cálculo puro con
clases explícitas. Esto evita que defaults de bibliotecas, clases ausentes o métricas
históricas ambiguas cambien el significado del resultado. EVAL-1 implementa solamente
`calculate_classification_report(y_true, y_pred, classes)` en
[`classification_metrics.py`](../../backend/ml_core/classification_metrics.py), con
biblioteca estándar y sin inferencia, agregación de ventanas, BD ni archivos.
El [tablero](../KANBAN.md#evaluaciones-finales-estandarizadas) gobierna la continuación.

## Contrato del informe v1

Las tres entradas son secuencias no vacías. Las etiquetas son `str` no blancos o
`int` nativos, del mismo tipo en todas las entradas; no se convierten implícitamente
booleanos, nulos, flotantes ni tipos numéricos de bibliotecas. El consumidor deberá
normalizar explícitamente esos tipos. Las clases son únicas y conservan su orden;
las etiquetas observadas deben pertenecer a ellas y ambas listas tener igual longitud.
Entradas inválidas producen `ValueError`, no informes parciales.

| Campo | Significado |
| --- | --- |
| `schema_version` | Entero `1`; cambios incompatibles exigirán otra versión. |
| `classes`, `sample_count` | Clases ordenadas y cantidad entera de pares evaluados. |
| `confusion_matrix` | Conteos enteros: filas reales, columnas predichas, mismo orden que `classes`. |
| `support` | Conteo real por clase, alineado con `classes`. |
| `per_class` | Lista ordenada de `label`, `precision`, `recall`, `f1`, `support` y `zero_denominator`. |
| `zero_denominator` | Indicadores booleanos de denominador nulo para precision, recall y F1; no significan valores JSON nulos. |
| `coverage` | `absent_classes` sin soporte real y `complete`; incluye clases que solo fueron predichas. |
| `metrics` | accuracy, precision_macro, recall_macro, f1_macro, f1_weighted y balanced_accuracy. |

Todas las tasas son fracciones de precisión flotante completa, sin redondeo ni
porcentajes persistidos. Para cada clase, precision usa TP/(TP+FP), recall usa
TP/(TP+FN) y F1 usa 2TP/(2TP+FP+FN). Denominador cero devuelve `0.0` acompañado de
su indicador. Macros promedian **todas** las clases declaradas; weighted F1 pondera
por soporte real. Balanced accuracy promedia recall **solo** de clases con soporte.
Accuracy usa aciertos/total. El resultado es serializable con JSON estricto, sin NaN.
Cobertura incompleta se informa y no implica por sí sola fallo; ausencia de clase
no equivale a un cero observado con denominador válido.

## Extensión opt-in v2: abstenciones (primer corte EVAL-3)

La llamada de tres argumentos mantiene exactamente el contrato estricto v1.
`calculate_classification_report(..., rejection_label=etiqueta)` habilita v2;
`None` mantiene v1. La etiqueta debe ser del mismo tipo nativo que las clases,
no blanca y distinta de todas ellas. Solo se permite en predicciones: etiquetas
reales desconocidas o predicciones arbitrarias siguen fallando.

V2 conserva clases objetivo y añade `prediction_columns = classes + [rejection_label]`
y `rejection = {label, count, rate}`. La matriz tiene N filas reales y N+1 columnas
predichas, incluida la última columna aun con cero rechazos. Count suma esa columna;
rate es count/total. Todas las grabaciones cuentan: los rechazos silencio/ruido son
abstenciones incorrectas, incluidas en soporte real y falsos negativos. Precision
usa solo predicciones de la clase objetivo; recall usa todo su soporte; F1 usa
2TP/(soporte real + predicciones objetivo). Accuracy y weighted F1 usan el total;
macros incluyen N objetivos, nunca la abstención; balanced accuracy mantiene solo
objetivos con soporte. No se cambian filtros, umbrales ni inferencia.

Persistencia admite identidades v1/v2 y exige coincidencia exacta de versión del
informe, columnas ordenadas, etiqueta de rechazo, conteos, tasas y álgebra. V1 no
admite los campos nuevos ni matrices rectangulares; sus informes siguen legibles.
Esta extensión de cálculo no ejecuta inferencia. Su integración MAIN se describe abajo.

### Compatibilidad de tabla y plan de upgrade separado

La definición para tablas nuevas permite `schema_version IN (1, 2)`. La migración
aditiva conserva comparación conservadora de agrupaciones CHECK. Una tabla instalada
con el CHECK antiguo `schema_version = 1` **no** se considera compatible: falla cerrada
y no se modifica. En #11 se creó la tabla nueva; el verificador corregido aceptó su
esquema en conexión PostgreSQL de solo lectura. Esto no acredita upgrade de un CHECK v1.

Si se descubre una tabla v1 instalada, hace falta autorización operacional separada:
respaldar/restaurar y verificar destino, drenar escritores, inventariar restricciones
y filas, y reemplazar únicamente el CHECK `evaluation_counts` por el de versiones
1/2 en PostgreSQL con transacción; verificar filas e informes v1 intactos y nueva
restricción antes de reanudar. SQLite requiere diseñar y aprobar por separado su
reconstrucción de tabla conservando datos/FK; este script no la hace. No existe aquí
un upgrade automático ni garantía operacional PostgreSQL.

## EVAL-2: persistencia e identidad implementadas

`model_evaluation` conserva intentos independientes, con FK obligatoria a
`modelo.id_modelo` y borrado restringido. No se inventa un registro paralelo de
ensambles: su identidad combinada queda pendiente de EVAL-4. Cada intento contiene
ID, versión de schema/evaluador, SHA-256 de checkpoint y manifiesto, dataset explícito,
split `val`/`test`, clases ordenadas, configuraciones de predictor/preprocesamiento/
agregación, cantidad esperada de muestras, informe JSON nullable, razón de fallo,
revisión de código opcional y fechas de creación/inicio/finalización UTC.

La interfaz pública es `EvaluationService(session)`, con `create(identity)`,
`start(id)`, `complete(id, report)`, `fail(id, reason)` y `read(id)`. Las mutaciones
hacen commit y rollback ante error: el llamador debe aportar una sesión dedicada,
sin trabajo ajeno pendiente. Devuelve diccionarios JSON separados de los objetos
persistidos; lectura ausente devuelve `None`. Identidad/informe/transición inválidos
producen `ValueError`; errores de BD se propagan tras rollback. No abre conexiones
ni crea sesiones propias. La importación ORM conserva el Base existente y, como los
otros modelos, importa la configuración de BD existente; no usarla en migraciones.

Los estados son `pending → running → completed` o `pending/running → failed`.
Los terminales no admiten cambios por esta interfaz; un reintento exige `create` y
un ID nuevo. La procedencia no tiene operación de actualización. Escrituras de estado
condicionadas al estado anterior evitan aceptar transiciones concurrentes obsoletas.
Las restricciones de BD aseguran FK, split, estados, conteo positivo y coherencia de
presencia de informe/error/fechas; no constituyen protección de inmutabilidad contra
SQL privilegiado directo. El uso soportado para evaluaciones es esta interfaz.

`complete` exige identidad válida, modelo existente e informe v1/v2 coherente con clases,
conteos, matriz, soporte, denominadores, cobertura y tasas fraccionales. No modifica
ni redondea el informe recibido; compara tasas con tolerancia flotante acotada
(relativa 1e-12, absoluta 1e-15). Configuraciones e informes deben ser JSON estricto
finito. Cobertura incompleta sigue siendo válida. Ausencia/fallo conserva `report=None`,
no fabrica ceros. No altera `Modelo.precision`, `perdida`, `activo` ni historial por época.
Los hashes son identidad declarada; este módulo no lee ni acredita archivos reales.

### Operación explícita de migración (historial de #11; upgrade v1 separado)

El operador debe respaldar, verificar destino y drenar escritores antes de ejecutar
`backend/scripts/migrate_model_evaluations.py --apply` con `DATABASE_URL` explícita.
No hay dotenv, URL por defecto, importación de app, `create_all` general ni migración
al arrancar el backend. El callable `migrate(engine)` admite SQLite/PostgreSQL y crea
solo la tabla nueva dentro de una transacción, exigiendo `modelo` preexistente.
Repetir devuelve sin cambios cuando estructura y restricciones coinciden; una tabla
incompatible falla cerrada, sin completarla, reemplazarla ni modificar históricos.
La definición de tabla compartida vive en el script libre de efectos de configuración.
La comparación de CHECK conserva todos los paréntesis, operadores, casts y literales;
solo ignora espacios fuera de literales. No intenta demostrar equivalencia SQL.
Acepta la expresión renderizada por el dialecto y, para PostgreSQL, un conjunto
explícito de seis representaciones de catálogo (counts actualizado para versiones 1/2). Representaciones desconocidas,
incluso wrappers redundantes no enumerados, se rechazan sin modificar la tabla.
Esto evita que una agrupación distinta de AND/OR pase como esquema compatible.

Las pruebas usan SQLite temporal, con FK habilitada para persistencia. La regresión
de migración construye una tabla temporal con CHECK alterado y verifica rechazo y
preservación. Las fixtures PostgreSQL siguen siendo evidencia estructural, no prueba
general de idempotencia: la migración real de #11 creó la tabla (exit 0), el segundo
intento falló en la comparación de CHECK (exit 1) y el recibo conserva ambos resultados.
La corrección `ab25519` amplió la allowlist exacta; obtuvo 102 PASS independientes y
`migrate(engine) -> False` aceptó el esquema existente en conexión solo lectura, sin
DDL nueva. La revisión nativa quedó APPROVED/ACK. No se verificó upgrade de un CHECK v1,
respaldo/restauración ni despliegue; un rollback de código no elimina tabla o intentos.
No se promete atomicidad entre filesystem y BD ni se atribuye RED histórico.

## EVAL-3B: evaluador por grabación

`LabelledRecording` es una entrada inmutable con identidad admitida, etiqueta,
path local, referencia canónica, etapa y grupo opcional. `RecordingEvaluator`
recibe la secuencia, el predictor y la procedencia/configuración; su construcción
valida clases/archivos, decodifica localmente con librosa y fija hashes de audio.
Expone `identity` para registrar un intento antes de inferencia; `evaluate()`
devuelve el informe v2 o propaga el error, sin persistir ni activar.

El manifiesto JSON canónico conserva el **orden admitido**, identidad, etiqueta,
referencia, etapa, grupo y SHA-256 de contenido de cada audio; su hash no incorpora
paths absolutos dependientes del host. La inferencia verifica contenido antes y
después de cada llamada. Esta política detecta mutaciones ordinarias, no un cambio
malicioso seguido de restauración ni garantiza un snapshot atómico de filesystem.
Cada grabación produce exactamente una llamada al mismo predictor, con clases en
su orden original. Solo estados `silence`/`noise` generan el sentinel reservado
`__recording_rejected__`; etiqueta o estado desconocido falla explícitamente.
`validate_recording_splits` rechaza cruces de identidades, paths resueltos y grupos
conocidos entre train/val/test; MAIN lo invoca antes de lanzar el worker.

**Límite de procedencia:** el llamador debe aportar configuraciones efectivas y el
hash del checkpoint realmente cargado; el helper no acredita esos campos por sí
solo. La prueba sintética restaura un checkpoint AudioCNN local usando el predictor
real y evalúa un tono, sin red ni datos reales. Las pruebas de persistencia usan
SQLite y la interfaz existente de intentos. No constituye evaluación de #11 ni del
runtime publicado.

### Integración MAIN: entrenamiento → evaluación → activación

`TrainingService.start_training` admite el mismo trío preparado y produce grabaciones
inmutables con referencias/etapas resueltas. Aves conserva `xc_id`; motores conserva
identidad `(clase, source_id)` cuando está declarada y usa etapa/referencia solo si
no existe ese ID, siguiendo el lector prepared. Ambos conservan el grupo canónico
`recordist`, no un nombre de columna supuesto. Val y test
no pueden introducir clases desconocidas; se rechazan etiquetas reservadas, archivos
sin metadata de codec válida y cruces de identidades/paths/grupos antes de scheduling.
El preflight usa `soundfile.info`: valida metadata, no acredita todos los frames; la
decodificación completa y hashes ocurren en el evaluador. No mide calidad de test ni
calibra. Las configuraciones DTO se separan a JSON antes de guardar el checkpoint.

La selección mantiene val accuracy y early stopping por val loss. Tanto actualización
como fallback del mejor snapshot usan `detach().cpu().clone()`, sin alias CPU. Las
pruebas controlan dos épocas y comprueban pesos restaurados y predicciones finales
del primer snapshot, incluido el caso de accuracy cero; no se reutilizan pesos vivos.

El checkpoint se registra primero con métricas históricas intactas, `activo=False`
y `estado=standard_eval_pending`. Luego el job entra en `evaluating`, que bloquea
otro entrenamiento. Se crea `TrainedModelPredictor` desde el archivo exacto, con
metadata lazy; el predictor restaura el modelo al inferir, en eval/no-grad. Antes
de construir los evaluadores se revalidan referencias/raíces con el lector canónico,
incluido rechazo de symlinks introducidos después de admisión. Se exige
orden de clases admitido y SHA-256 antes/después de restauración/inferencia. Val y
test tienen intentos independientes `pending → running → completed`, creados antes
de inferencia y persistidos mediante EvaluationService con sesión dedicada.

La procedencia registra constantes reales del predictor y defaults de las firmas de
Mel, resampling y flatness, más crop central/padding, máscaras/umbrales, agregación
por grabación, versiones de bibliotecas y hashes de implementación. Los literales
internos no expuestos por firma se describen bajo `published-fixed-crop-v1` y el hash
de su fuente. Training audio/windowing y defaults del frontend (incluida normalización) se guardan
**separadamente**; diferencias
emiten advertencia y nunca cambian el predictor ni convierten ventanas en muestras.
El frontend training y el Mel publicado pueden ser distintos incluso sin overrides.

Solo después de ambos commits y comprobación de identidad se pasa a
`standard_eval_completed` y se activa el modelo individual. La transición automática
preserva cualquier activo anterior hasta ese punto. `set_active_model` aplica el
mismo guard al marcador `standard_*`: revisa archivo/hash, dataset, job del checkpoint,
clases, versiones y coherencia de ambos informes/configs; pending/failed no son legacy.
Legacy sin marcador conserva activación con sesión; sin sesión ya no se anuncia un
éxito ficticio. No se reinterpretan campos históricos de precisión.

Los componentes de un entrenamiento múltiple sí reciben informes individuales,
quedan inactivos con `standard_component_evaluated` y el log declara explícitamente
que la combinación no está evaluada/publicada. Este marcador bloquea también la
activación manual: evaluación oficial del ensamble queda en EVAL-4.

Fallos de inferencia o persistencia marcan job failed y, cuando la BD lo permite,
`standard_eval_failed` e intentos pendientes/en curso fallidos, sin inventar informes.
Se conserva todo checkpoint registrado. Intentos ya completados permanecen intactos.
Si publicación pudo hacer commit antes de perder su acknowledgement, se intenta
compensar nuevo activo y restaurar IDs activos anteriores; fallo de recuperación se
registra explícitamente. No se promete atomicidad filesystem/BD, recuperación durante
una indisponibilidad permanente ni serialización global con activaciones concurrentes.
Fallos anteriores a construir una identidad válida pueden no producir intentos, pero
conservan estado fallido del modelo y bloquean activación. La operación pública de
reintento sin reentrenar sigue pendiente de EVAL-6; los artefactos quedan disponibles.

Rollback de MAIN: retirar sus cambios de worker/admisión/guard y pruebas conjuntamente;
no borrar checkpoints ni filas/intentos. Retirar el guard reabre la política legacy
anterior, por lo que exige decisión explícita de publicación. PostgreSQL, despliegue,
standalone y combinación de ensambles no están acreditados por las pruebas SQLite.

## Diseño objetivo para las integraciones restantes

Las siguientes reglas rigen EVAL-4 a EVAL-6; MAIN implementa el subconjunto anterior:

- Mantener informes independientes para validación y test del checkpoint seleccionado,
  no del último estado mutable. La identidad incluirá hash del checkpoint, configuración
  del predictor, orden de clases, split, manifiesto y procedencia del dataset. Un hash
  CSV no congela audios: documentar/verificar su política de integridad. El snapshot de
  pesos debe quedar aislado también en CPU, sin alias con pesos posteriores.
- Obtener una predicción por grabación con el preprocesamiento y agregación del predictor
  publicado, sin aumentos aleatorios ni gradientes. En ensambles evaluar la combinación
  real, no deducir calidad de sus miembros. Este calculador recibe las etiquetas ya
  obtenidas y no verifica por sí solo esa paridad.
- Test nunca selecciona, calibra ni ajusta. Conservar selección principal por val accuracy,
  early stopping por val loss y standalone por val Macro F1. El historial por época es
  seguimiento del entrenamiento, no el informe final del artefacto exacto.
- Separar estados de entrenamiento, evaluación y publicación. Una evaluación tendrá
  estados pendientes, en curso, completados o fallidos y procedencia de cada intento.
  Un fallo conserva el checkpoint, bloquea éxito/publicación y permite reintentar sin
  reentrenar. No prometer atomicidad entre filesystem y BD.
- Nuevas publicaciones oficiales requerirán informes completados de val/test del
  artefacto exacto. Legacy continúa legible y operativo: no reinterpretar su campo
  histórico `precision` como accuracy, macro precision ni otra métrica sin evidencia.
  Catálogo/UI distinguirán cero, ausencia, legacy y fallo. Reevaluar agregará informes
  sin reemplazar anteriores ni activar modelos.

Estas reglas complementan [ADR 0016](0016-procedencia-y-persistencia-entrenamiento.md)
y [ADR 0017](0017-disponibilidad-y-activacion-modelos.md), sin cambiar en EVAL-1/EVAL-2 sus
flujos actuales de persistencia, reconciliación o activación.

## Alternativas y consecuencias

Se descarta depender del conjunto de clases inferido por sklearn: omitir una clase
cambia las macros y oculta cobertura. También se descarta reutilizar métricas por
época o sobrescribir informes previos, porque pierden identidad y trazabilidad.
Una sola función concentra el contrato, sin adaptadores hipotéticos ni dependencias
nuevas. La matriz densa cuesta O(clases²) memoria; el cálculo cuesta O(muestras +
clases²). No es un evaluador de modelos ni acredita reproducibilidad de los audios.

## EVAL-4A: publicación standalone y bundle

El entrenamiento standalone conserva la selección por MacroF1 de validación y
captura un snapshot `detach().cpu().clone()` para evitar alias de tensores CPU. La
evaluación final convierte las filas admitidas de val/test en grabaciones únicas y
usa `BundleAudioPredictor.predict(Path)` sobre el bundle provisional real: filtros de
silencio/ruido, conversión de tasa, ventanas densas, Mel, temperatura y agregación
máxima no se sustituyen por el evaluador por lotes del entrenamiento. El test no
participa en selección.

El bundle manifiesta informes versionados por split, procedencia completa sin ID de
modelo de base de datos y SHA-256 de pesos independiente del hash del manifiesto de
grabaciones. `TrainingConfig.dataset_name` lo aporta explícitamente el caller (los
scripts de motores enlazan el nombre `engine_diagnostics`, ya declarado en su lector
prepared); el manifiesto guarda `dataset_name` opcional para mantener legacy legible,
pero un manifiesto oficial con informes lo requiere y liga ambos informes a ese valor.
No se infiere identidad desde rutas ni `model_id`.

`ModelManifest.effective_inference_config()` es la única representación canónica de
arquitectura, Mel/frontend, resampling/crop, filtros, temperatura y ventanas/agregación.
El predictor la expone sin cargar pesos; el evaluador la registra y el validador exige
coincidencia exacta con manifiesto/clases ordenadas/dataset, además de igualdad entre
las identidades val/test (salvo split, hash de membresía y conteo). Tanto la carga del
manifiesto como `publish_official` validan el contrato completo. `publish_official`
valida el slug y rutas locales, hash de pesos y manifiesto completo antes de mover el
provisional. Esto detecta inconsistencias accidentales o ediciones posteriores; no
acredita autenticidad criptográfica de datos o procedencia declarada.

El esquema comprueba split, coherencia del informe y que el checkpoint sea exactamente
el SHA-256 de los pesos staged. `EvaluationProvenance` permite identidad standalone;
`EvaluationIdentity` conserva el FK positivo obligatorio para `EvaluationService`.

El exportador de bajo nivel continúa permitiendo bundles legacy/experimentales sin
informes; solo `GenericModelTrainer.train_and_export` es ruta oficial obligatoria.
Esa ruta rechaza un destino oficial ya existente, exporta a una ubicación provisional,
evalúa y valida ambos splits y finalmente mueve el directorio completo al nombre
oficial. Si falla el preflight, inferencia o validación, no se publica ese nombre y
se conserva el provisional para diagnóstico/reintento manual. La separación no ofrece
transacción entre filesystem/BD ni una operación de reintento automática. Las métricas
históricas del loop se conservan etiquetadas como legado, no como informe final.

## EVAL-4B: evaluación sintética local del ensamble servido de motores

`backend/scripts/evaluate_engine_ensemble.py` es una operación explícita y separada del
script experimental de dos modelos. Solo admite el `EngineEnsemblePredictor` servido
(ResNet34d + EfficientNet-B0 + PANNs CNN14), pesos publicados 0.60/0.10/0.30 y clases
ordenadas del servicio. No modifica APIs, entrenamiento, bundles, servicios, catálogo,
activación o persistencia. No inserta en BD y usa `EvaluationProvenance` genérica sin
FK de modelo.

Antes de cargar componentes, la operación valida los CSV prepared y su marcador/hashes,
raíces y referencias raw/processed, labels de taxonomía servida, separación de
grabaciones/grupos train/val/test y hashes de audio antes de instanciar el predictor.
Luego exige los tres archivos regulares explícitos,
los carga mediante el predictor servido y vincula su identidad a SHA-256 por componente
en orden, configuración efectiva y pesos. El digest compuesto es una identidad
versionada del JSON canónico (no el hash de un archivo combinado ni una declaración de
autenticidad). Los bytes se vuelven a comprobar después de cada split y antes de
escribir el informe. Inyección arbitraria de módulos no se acepta como procedencia
checkpoint-backed.

Val y test se ejecutan una vez por grabación mediante `predict(Path)`, por lo que la
métrica corresponde a la combinación ponderada real de probabilidades. Se conserva el
rechazo silence/noise del predictor; solo `classified_super_ensemble` con clase conocida
se admite como predicción. Estados o clases desconocidos, salida no finita, mutación de
componente o identidad distinta fallan; no se genera informe de éxito. El destino JSON
se proporciona de forma explícita, debe tener padre existente y rechaza sobrescritura.
No hay calibración ni selección basada en test, publicación oficial, claims de runtime
ni conexión a BD.

La verificación usa únicamente WAVs y checkpoints pequeños sintéticos con los
constructores de redes sustituidos en test; no descarga pretrained ni accede a datos,
checkpoints privados, servicios u operaciones DB. EVAL-4B queda limitado a esa
verificación sintética local; no acredita rendimiento, integridad externa o despliegue
con artefactos reales. La evaluación real de #11 está documentada en EVAL-6B; no extiende
la evidencia sintética de EVAL-4B ni acredita API o despliegue.

## EVAL-5A: catálogo de informes existentes

`GET /api/models` expone `evaluations.val/test` únicamente para entradas del catálogo
cuyo ID siga el contrato emitido por el registro DB (`fama_trained_model_<id>`). Una
consulta batched ordenada por `id_evaluation DESC` devuelve por split el último intento
(incluidos pending/running/failed) y el último completado por separado; un fallo nuevo
no oculta el informe anterior. Informe v1/v2 y provenance pasan validación y conservan
conteos, cobertura, versiones y tasas completas. Ausencia de intentos se representa
como null, nunca como métricas cero; las métricas históricas del predictor permanecen
sin reinterpretar.

La respuesta distingue catálogo de evaluaciones `available` vacío de almacenamiento
`unavailable`/registro inválido, con códigos acotados y sin detalles internos. La
serialización de informes no crea intentos, calcula hashes, carga pesos ni ejecuta
predicción/evaluación. La reconciliación del registro durante la misma petición es una
operación separada y aplica el guard de integridad EVAL-5B a artefactos estándar.
Informes genéricos sin FK, como la identidad del ensamble EVAL-4B, no se atribuyen a
modelos del catálogo. Este slice se verificó con API en proceso y SQLite; la ejecución
real de reevaluación en PostgreSQL descrita en EVAL-6B no acredita despliegue ni
semántica operacional general del catálogo.

## EVAL-5B: guard canónico de publicación y activación

`standard_evaluation_guard.require_standard_reports` es el guard compartido por
activación y las dos rutas de registro DB: `ModelRegistry.publish_from_db` (catálogo)
y `register_from_db` (incluida la construcción startup de `build_default_registry`).
Todas lo ejecutan antes de instanciar/exponer predictores, escoger el default o añadir
alias. Un marcador `standard_*` solo admite publicación/activación si el estado del
modelo sigue en `standard_eval_completed`; pending, failed y
`standard_component_evaluated` fallan aunque existan informes antiguos. Los modelos
legacy no entran al guard.

La autorización se vincula al checkpoint confiable actual, no a que dos filas se
parezcan entre sí. El guard limita la ruta a la raíz local, comprueba tamaño, calcula
SHA-256 de los bytes y carga solo metadata en CPU con `torch.load(weights_only=True)`.
Valida contra el checkpoint y el modelo DB: hash, clases ordenadas, arquitectura,
dataset e ID, job, schema 2, versión de evaluador y configuración efectiva. El builder
único `build_evaluation_configuration` genera la procedencia tanto para el evaluador
MAIN como para el guard; `resolve_training_audio` es también la fuente común de los
defaults y overrides de audio usados por el worker y reconstruidos desde metadata del
checkpoint. El config liga arquitectura, job, audio/frontend/windowing de training,
versiones runtime, implementación del predictor y loader, transformaciones publicadas,
umbrales y defaults reales de resampling/flatness, además de agregación por grabación.
Los hashes de implementación apuntan a referencias estables del código predictor (no
al helper/guard), por lo que extraer el guard no crea un self-hash circular.

Entre intentos completed, solo cuentan informes que cada uno coincide exactamente con
ese config efectivo y con el checkpoint/dataset/clases/job/schema/evaluador actuales.
Ambos `predictor_config` contienen la identidad compartida versionada
`admitted_val_test_manifest_pair` (`version=1`, `sha256`): SHA-256 de JSON canónico
ordenado que incluye un dominio estable, versión 1 y los hashes de manifiesto val y
test en ese orden. MAIN construye ambas identidades admitidas tras validar las
particiones y antes de crear intentos o ejecutar inferencia; de sus hashes
individuales deriva y persiste el vínculo compartido. El guard reconstruye el digest
con los dos manifiestos concretos y exige que ambos informes contengan exactamente
el mismo valor reconstruido. Así no puede combinar val y test tomados de pares
admitidos distintos. Split, manifiesto
individual y cantidad de muestras pueden diferir, pues son propios de cada partición.
Intentos pending/failed más nuevos siguen visibles como `latest_attempt` en EVAL-5A,
pero no revocan una autorización completed previa del mismo artefacto/configuración:
el guard busca el par coherente entre todos los completados, no solo el intento más
reciente de cada split. Informes sin la identidad conjunta no autorizan publicación;
los informes estándar históricos no se actualizan ni migran automáticamente y
requieren reevaluación explícita. El digest acredita el emparejamiento de snapshots
admitidos, no que ambas inferencias ocurrieron en una única ejecución ni la autenticidad
de la procedencia. La comparación de `code_revision` sigue siendo igualdad exacta,
incluido `None`; no se deriva una revisión desde Git ni un commit invalida por sí solo
un par. Si cambia la identidad actual o no queda par completed coherente, se falla
cerrado.

Un error de integridad invalida una entrada DB cacheada y sus alias; el guard no cambia
filas `activo`, estado, intentos ni default del almacenamiento. `register_from_db`
valida antes del predictor/default/alias y solo selecciona como default una fila que
esté explícitamente activa y haya pasado el guard; un modelo inactive no se convierte
en fallback implícito. Un retry fallido del mismo artefacto/config no retira una
entrada previamente autorizada ni altera el default/activo DB.

Esta política no cambia la lectura lazy de modelos legacy ni les calcula hashes/carga
metadata en el guard. La serialización de informes EVAL-5A no lee checkpoints; la
reconciliación de un artefacto estándar sí hace lectura de integridad/metadata local,
pero no construye `TrainingService`, no predice ni evalúa. Las regresiones usan SQLite
y checkpoints sintéticos para configuración igual-e-incorrecta, rutas catálogo/startup,
cache/alias/default, retries fallidos y activación; PostgreSQL, runtime desplegado y
checkpoints o datasets reales no están acreditados.

## EVAL-5C: presentación de informes finales en Predicción

La vista `PredictionView` consume los informes incluidos en la respuesta existente de
`GET /api/models`; no agrega endpoints ni solicita ni ejecuta evaluaciones. Para el modelo
seleccionado presenta validación (`val`) y test por separado, con estado e identificador
del último intento y, de forma independiente, el identificador y el informe del último
intento completado. Así, un fallo nuevo no sustituye ni oculta un informe completado
anterior. Los informes v1/v2 muestran cantidad de muestras, accuracy, precision/recall/F1
macro, F1 ponderado, balanced accuracy, cobertura/clases ausentes, schema y versión del
evaluador. El rechazo v2 se muestra cuando sus campos opcionales están presentes; v1 no
requiere esos campos. Un valor válido de cero se representa como `0.00%`; métricas nulas,
ausentes o no finitas se muestran como no disponibles.

El catálogo `unavailable`, el catálogo disponible sin informes para el modelo y la
respuesta legacy sin `evaluation_catalogue_status` se distinguen explícitamente. Los
reintentos actualizan la selección desde la nueva respuesta y una respuesta unavailable
no deja visible un informe anterior como si siguiera vigente. La provenance visible se
limita a dataset, schema, versión de evaluador y SHA-256 de checkpoint validado; no se
renderizan configuraciones ni rutas. Cada informe se identifica como histórico y la UI
advierte que no garantiza correspondencia con los pesos cargados actualmente. Las
métricas legacy del catálogo siguen en una sección separada y rotulada como históricas;
no se recalculan ni reinterpretan como informes finales.

La verificación de UI usa fixtures públicos v1/v2 y Vitest con jsdom. No acredita
navegadores reales, PostgreSQL, modelos/datasets reales, ni cambios en publicación,
activación, pesos o ejecución de inferencia/evaluación.

## EVAL-6A: reevaluación explícita de checkpoints MAIN

`app.services.reevaluation.reevaluate_model(session, *, model_id, checkpoint_root,
checkpoint_path, expected_sha256, prepared_dir, dataset_name, roots, execute=False)`
usa sesión inyectada y es solo preflight por defecto. Exige identidad MAIN explícita,
metadata actual verificable y coincidencia entre DB, ruta confiable, tamaño/hash,
dataset, arquitectura, job, clases ordenadas y configuraciones. Comparte el inspector
seguro de checkpoint y el builder efectivo con `standard_evaluation_guard`; no intenta
reconstruir procedencia ausente ni inferir el dataset desde una ruta.

El preflight admite el trío completo con `load_prepared_dataset`, valida cobertura,
referencias y grupos/identidades disjuntas, y construye snapshots de manifiesto val/test
mediante `RecordingEvaluator` (hash y decodificación completos), sin instanciar predictor,
crear intentos, inferir ni modificar datos. `backend/scripts/reevaluate_model.py`
requiere URL, modelo, checkpoint/root/hash, prepared-dir, dataset y raíces explícitos.
Solo `--execute` crea dos intentos append-only con digest de pareja compartido; carga
`TrainedModelPredictor` desde el path exacto, y comprueba el checkpoint alrededor de la
carga y cada inferencia. Reintentos generan IDs nuevos; los informes previos y cualquier
split completado antes de un fallo permanecen intactos. No altera activo/estado,
precisión/pérdida histórica, alias/default, entrenamiento, registro global, checkpoint,
esquema ni migraciones. La CLI cierra su engine/sesión local y no usa una sesión global
para la operación. La metadata ORM `Base` puede importarse sin resolver dotenv ni crear
un engine: `DATABASE_URL`, `engine` y `SessionLocal` conservan sus nombres públicos y
se inicializan al accederlos. La normalización explícita del driver PostgreSQL no cambia.

La regresión automatizada de EVAL-6A es sintética: SQLite temporal, WAVs y checkpoint
pequeño, con constructor de red sustituido; no sustituye la evidencia operacional de
EVAL-6B. La ejecución real y sus límites de calidad se documentan por separado abajo.

## EVAL-6B: reevaluación real de #11 en desarrollo

Se ejecutó en `fama_db` fijada, con preflight e invariantes, sin alterar activación ni
métricas históricas. Los intentos inmutables son ID 1 (`val`, 177 muestras) e ID 2
(`test`, 181); 15 clases, informe schema v2 y evaluator recording v1; duración total
65.419 s. La identidad de fila #11 se verificó con hash `277d8523…`; el SHA esperado
del checkpoint comienza `070d…`.

Accuracy: val 6.779661%, test 3.867403%; macro F1: val 5.6262%, test 3.9644%.
Rechazos: 31/177 y 63/181. **Calidad no aprobada**; los resultados no habilitan ni
cambian activación y no reinterpretan la `precision` histórica. Diagnósticos
MPEG quedan para seguimiento de calidad exclusivamente de solo lectura; no se ejecuta
otra inferencia como parte de ese seguimiento.

El recibo `docs/receipts/model-11-real-evaluation.json` conserva los reportes originales.
La verificación independiente `mv3a8v51` cotejó snapshots/digests observados con el
recibo de origen y comprobó integridad del runtime por separado; no se afirma una
verificación offline adicional de archivos de manifiesto. La tabla de evaluaciones se
creó en la migración inicial y luego fue aceptada por el verificador corregido en modo
solo lectura; no hubo upgrade de un CHECK v1 ni despliegue de API/browser. El informe
inmutable no certifica calidad ni aprobación operacional.
