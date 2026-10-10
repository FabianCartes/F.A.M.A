# ADR 0022: Contrato de evaluaciones finales estandarizadas

* **Estado:** Decisión aceptada. EVAL-1 (contrato/cálculo) y EVAL-2 (persistencia aislada) implementados con pruebas SQLite; integración de entrenamiento, bundles, API/UI y reevaluación son cortes posteriores.
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

## Identidad y procedencia: requisitos para integraciones

Los informes finales futuros deben asociarse explícitamente al artefacto evaluado: clases ordenadas, split, dataset, configuración efectiva de predictor/preprocesamiento/agregación, versión del evaluador y hashes de pesos y de membresía/manifiesto. Los consumidores deben distinguir identidad genérica de procedencia de evaluación de cualquier identidad persistida que requiera FK real; nunca fabricar identificadores. Los hashes identifican bytes declarados, no acreditan autenticidad, congelamiento de audios ni equivalencia del predictor. Una llamada por grabación con el predictor publicado debe ser responsabilidad de la integración, no una garantía de este cálculo puro.

## Alternativas y consecuencias

Se descarta inferir clases con una biblioteca de métricas: si una clase no aparece en las observaciones, cambia el conjunto de macro-promedio y se oculta cobertura. Se descarta reinterpretar métricas históricas por época: carecen de una semántica final/identidad inequívoca. Un contrato y cálculo puros mantienen el alcance acotado y no introducen dependencias nuevas; una matriz densa requiere O(clases²) espacio y el cálculo O(muestras + clases²). La evaluación del predictor, procedencia verificable, persistencia, publicación, catálogo/UI y reevaluación requieren decisiones y pruebas de integración propias.
