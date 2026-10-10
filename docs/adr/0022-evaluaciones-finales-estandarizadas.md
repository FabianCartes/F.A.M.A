# ADR 0022: Contrato de evaluaciones finales estandarizadas

* **Estado:** Decisión aceptada. EVAL-1 a EVAL-4A implementados; EVAL-4B verifica sintéticamente la evaluación local del ensamble servido. API/UI, publicación oficial del ensamble, artefactos/datos reales y PostgreSQL/runtime real pendientes.
* **Área:** Informes finales reproducibles de clasificación multiclase.

## Contexto y decisión

Las métricas por época describen el proceso de optimización, no un informe final con identidad estable. Además, defaults de bibliotecas y clases ausentes pueden alterar las macros o esconder cobertura. Se define un cálculo puro compartido, con clases objetivo explícitas y orden conservado:

`calculate_classification_report(y_true, y_pred, classes, *, rejection_label=None)`.

El módulo calcula informes; no realiza inferencia, acceso a archivos, persistencia ni selección de modelo.

## Contrato v1

Las tres entradas son secuencias no vacías. Las etiquetas deben ser `str` no blancos o `int` nativos homogéneos; no se convierten implícitamente booleanos, nulos, flotantes ni tipos numéricos externos. Las listas real/predicha deben tener el mismo largo, cada etiqueta observada debe estar declarada y las clases deben ser únicas. Se conserva exactamente el orden de clases. Una entrada inválida produce `ValueError`, no un resultado parcial.

| Campo | Significado |
| --- | --- |
| `schema_version` | Entero `1`; cambios incompatibles requieren otra versión. |
| `classes`, `sample_count` | Orden de clases objetivo y cantidad de observaciones. |
| `confusion_matrix` | Conteos enteros: filas reales, columnas predichas, orden de `classes`. |
| `support` | Soporte real por clase, alineado con el orden declarado. |
| `per_class` | Precision, recall, F1, soporte e indicadores de denominador cero. |
| `coverage` | Clases sin soporte real (`absent_classes`) e indicador `complete`. |
| `metrics` | Accuracy, precision/recall/F1 macro, F1 ponderado y balanced accuracy. |

Todas las tasas son fracciones sin redondeo ni porcentajes persistidos. Denominador cero produce `0.0` y un indicador booleano explícito. Las macros promedian todas las clases declaradas; F1 ponderado usa soporte real; balanced accuracy promedia solo clases con soporte. Cobertura incompleta se informa y no se convierte en cero observado ni falla automática. El informe debe ser JSON estricto y finito.

## Rechazo explícito v2

`rejection_label=None` conserva el contrato v1. Una etiqueta de rechazo explícita y distinta, no blanca y del mismo tipo nativo habilita schema v2, incluso cuando no hubo rechazos. La matriz añade una columna final para rechazo; las clases objetivo siguen siendo las únicas clases reales y las únicas incluidas en macros. Cada rechazo cuenta como error/abstención, incluido en soporte real y falsos negativos; la tasa y cantidad de rechazos se informan separadamente. Etiquetas reales desconocidas y predicciones no declaradas siguen rechazándose. No se cambian umbrales ni se decide qué predictor genera un rechazo.

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

### Operación explícita de migración (pendiente)

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
de migración construye una tabla real temporal con agrupación CHECK alterada y
verifica rechazo y preservación; el esquema esperado sigue siendo idempotente.
Las representaciones PostgreSQL se prueban con fixtures escritos explícitamente:
es evidencia estructural, no salida observada de un servidor ni prueba de idempotencia
PostgreSQL. Variantes de deparser no enumeradas pueden fallar cerradas y necesitan
verificación aislada antes de ampliar el conjunto permitido. PostgreSQL
real/aislado, respaldo/restauración y aplicación operacional siguen pendientes;
no se ha tocado la BD activa. Retirar código y pruebas de EVAL-2 antes de aplicar
la migración no afecta datos existentes. Después de aplicarla, el rollback de código
no elimina la tabla ni intentos: cualquier reversión de datos requiere una operación
separada autorizada. No se promete atomicidad entre filesystem y BD.

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
conocidos entre train/val/test; el llamador debe invocarla antes de comenzar entrenamiento.

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

## Identidad y procedencia: requisitos para integraciones

Los informes finales futuros deben asociarse explícitamente al artefacto evaluado: clases ordenadas, split, dataset, configuración efectiva de predictor/preprocesamiento/agregación, versión del evaluador y hashes de pesos y de membresía/manifiesto. Los consumidores deben distinguir identidad genérica de procedencia de evaluación de cualquier identidad persistida que requiera FK real; nunca fabricar identificadores. Los hashes identifican bytes declarados, no acreditan autenticidad, congelamiento de audios ni equivalencia del predictor. Una llamada por grabación con el predictor publicado debe ser responsabilidad de la integración, no una garantía de este cálculo puro.

## Alternativas y consecuencias

Se descarta inferir clases con una biblioteca de métricas: si una clase no aparece en las observaciones, cambia el conjunto de macro-promedio y se oculta cobertura. Se descarta reinterpretar métricas históricas por época: carecen de una semántica final/identidad inequívoca. Un contrato y cálculo puros mantienen el alcance acotado y no introducen dependencias nuevas; una matriz densa requiere O(clases²) espacio y el cálculo O(muestras + clases²). La evaluación del predictor, procedencia verificable, persistencia, publicación, catálogo/UI y reevaluación requieren decisiones y pruebas de integración propias.

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
con artefactos reales. EVAL-5, EVAL-6 y validación en PostgreSQL/runtime real siguen
pendientes.
