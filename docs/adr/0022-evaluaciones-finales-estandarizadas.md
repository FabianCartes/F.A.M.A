# ADR 0022: Contrato de evaluaciones finales estandarizadas

* **Estado:** Decisión aceptada. EVAL-1 implementa el contrato y cálculo puro. Persistencia, entrenamiento, bundles, API/UI y reevaluación son decisiones/integraciones posteriores y no se atribuyen a este corte.
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

## Identidad y procedencia: requisitos para integraciones

Los informes finales futuros deben asociarse explícitamente al artefacto evaluado: clases ordenadas, split, dataset, configuración efectiva de predictor/preprocesamiento/agregación, versión del evaluador y hashes de pesos y de membresía/manifiesto. Los consumidores deben distinguir identidad genérica de procedencia de evaluación de cualquier identidad persistida que requiera FK real; nunca fabricar identificadores. Los hashes identifican bytes declarados, no acreditan autenticidad, congelamiento de audios ni equivalencia del predictor. Una llamada por grabación con el predictor publicado debe ser responsabilidad de la integración, no una garantía de este cálculo puro.

## Alternativas y consecuencias

Se descarta inferir clases con una biblioteca de métricas: si una clase no aparece en las observaciones, cambia el conjunto de macro-promedio y se oculta cobertura. Se descarta reinterpretar métricas históricas por época: carecen de una semántica final/identidad inequívoca. Un contrato y cálculo puros mantienen el alcance acotado y no introducen dependencias nuevas; una matriz densa requiere O(clases²) espacio y el cálculo O(muestras + clases²). La evaluación del predictor, procedencia verificable, persistencia, publicación, catálogo/UI y reevaluación requieren decisiones y pruebas de integración propias.
