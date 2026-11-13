# Predicciones: selector con búsqueda y detalle de evaluación simplificado

**Estado actual: implementado, verificado y aplicado al frontend local con autorización. Commit local autorizado; sin push.** El lint de `PredictionView.tsx` conserva diagnósticos preexistentes, detallados abajo; no hay aprobación global de lint.
Se conserva el catálogo, la disponibilidad y los efectos de selección. Las secciones siguientes registran la investigación y las comprobaciones de cada etapa; sus referencias a aplicación o commit pendientes describen ese momento, no el estado actual. No afecta al plan de tríada.

## Objetivo

Agregar en la vista de Predicciones el mismo selector con búsqueda presente al seleccionar la arquitectura en la vista de Entrenamiento, con todas sus funciones de búsqueda y resaltado de la opción al pasar el mouse. Investigación y, a partir de ella, plan de corrección.

Etapas, en orden: implementación, aplicación de los cambios a la aplicación local y commit de los cambios. Cubren implementación, aplicación al frontend local y commit de estas mejoras; no autorizan push, PR ni despliegue de backend.

## Hallazgo y referencia real

| Control | Implementación observada durante la investigación, antes del cambio | Consecuencia para el plan |
| --- | --- | --- |
| Arquitectura de Entrenamiento | `<select>` nativo en `frontend/components/views/TrainingView.tsx:1233–1260`. | No tiene una búsqueda ni hover implementados por la aplicación que puedan importarse. |
| Modelo de Predicciones | `<select>` nativo en `frontend/components/views/PredictionView.tsx:1185–1215`. | Se sustituye solo el control visual, no la lógica del catálogo o de inferencia. |
| Dataset de Entrenamiento | `frontend/components/training/TrainingDatasetSelector.tsx`. | Sí implementa búsqueda, lista desplegable, opción activa por mouse/teclado, Escape, cierre al salir y restauración de foco. Es el patrón funcional y visual reutilizable. |

`TrainingDatasetSelector` consulta sus propios catálogos y mantiene selección de datasets. No se debe insertar directamente en Predicciones ni reutilizar sus peticiones para listar modelos. La alternativa mínima es conservar su patrón de interacción en un selector de modelos puramente presentacional, sin refactorizar Entrenamiento ni añadir dependencias.

## Alcance implementado

1. Se creó `frontend/components/prediction/PredictionModelSelector.tsx` con opciones, ID seleccionado y callback de selección recibidos desde la vista. No consulta APIs ni activa modelos por su cuenta.
2. Se reemplazó solo el bloque de `model-select` en `PredictionView.tsx`, usando los mismos `availableModels` y `selectedModelId`.
3. Se conserva el efecto de elegir un modelo: actualizar su ID, cerrar el diálogo de evaluación y limpiar `evaluationDialogModelId`.
4. Se mantienen los nombres y el orden publicados, el grupo «Mis modelos», las claves por ID y los estados vacíos/no disponibles. Los nombres iguales no se usan como identidad de selección.
5. No se modifican las consultas al recuperar foco/visibilidad, las guardas de sesión/pesos, ficha técnica, carga de audio, historial ni payload de inferencia.

## Interacción

- Al abrir, mostrar un buscador y las opciones del catálogo ya cargado, sin peticiones nuevas.
- Filtrar por nombre con la misma comparación local básica del selector de datasets: ignorar mayúsculas/minúsculas y espacios en los extremos; no introducir búsqueda remota ni semántica.
- Resaltar la opción bajo el puntero con el patrón visual existente. Pasar el mouse o escribir no cambia el modelo seleccionado ni inicia inferencia.
- Seleccionar explícitamente con clic o teclado; conservar navegación por flechas, Enter y Escape, cierre al abandonar el control y retorno de foco apropiado.
- Mantener visibles las coincidencias sin pesos, atenuadas/deshabilitadas y con su indicación de no disponibilidad; ni clic ni teclado las pueden seleccionar.
- Mostrar un estado sin coincidencias sin borrar la selección vigente ni confundirlo con un error de catálogo.
- Al cerrar, limpiar el texto de búsqueda como en el patrón de entrenamiento; conservar el modelo elegido.
- Conservar una etiqueta accesible para el selector y nombres distintos para el control cerrado y el campo de búsqueda.

## Verificación

Se aplica RED/GREEN a las reglas nuevas y se comprueba la interfaz pública del control:

1. Abrir y buscar filtra nombres sin nuevas peticiones ni cambio de selección.
2. Hover resalta la opción y no modifica el modelo activo; clic selecciona el ID correcto y cierra.
3. Flechas/Enter/Escape y salida de foco conservan el comportamiento esperado y no seleccionan opciones deshabilitadas.
4. Modelos sin pesos siguen visibles/deshabilitados; catálogo vacío, búsqueda sin resultados y nombres repetidos mantienen sus identidades y estados correctos.
5. Seleccionar mantiene el cierre/limpieza del diálogo de evaluación y los efectos existentes de ficha e historial.

Se añadieron pruebas focales en `frontend/components/prediction/__tests__/PredictionModelSelector.test.tsx` y una prueba de búsqueda sin nuevas peticiones en `PredictionView.catalogue.test.tsx`. Las suites de catálogo, vista, identidad cargada, historial, catálogo privado y revalidación de sesión se adaptaron a abrir y elegir opciones mediante roles accesibles, en lugar de `fireEvent.change` de un `<select>`. Se conservan sus comprobaciones de negocio; el selector de clase de feedback sigue siendo nativo.

La verificación final comprende suite frontend completa, TypeScript sin caché incremental, lint de las superficies tocadas y build Webpack en copia aislada con dependencias existentes, sin copiar archivos `.env` ni conectar con la API activa. La comprobación DOM/clases no prueba píxeles ni apariencia final: la aceptación visual pertenece al usuario; no usar navegador automatizado ni ejecutar inferencia real para este cambio.

## Resultados de verificación del selector, antes del ajuste de disposición

Las comprobaciones se ejecutaron sobre una copia aislada con dependencias existentes. Los hashes del candidato final coinciden con las fuentes; no se modificó la aplicación activa.

| Comprobación | Resultado observado |
| --- | --- |
| RED/GREEN de búsqueda, hover, teclado y Escape | Fallos esperados observados antes de implementar cada interacción; corregidos. La regresión del grupo «Mis modelos» también se comprobó antes de restaurarlo. |
| Suite final `npm test` | **575 pruebas aprobadas en 67 archivos**, sin fallos ni deselecciones. Incluye las 122 pruebas focales de selector, vista, catálogo, identidad, historial y sesión. |
| `npm run build -- --webpack` | **Aprobado**, sin salida de error; compilación y generación de páginas completadas. |
| TypeScript `--noEmit --incremental false` | **Aprobado**. |
| ESLint del nuevo componente, helper y pruebas modificadas | **Aprobado**, sin advertencias. |
| ESLint de `PredictionView.tsx` | **No aprobado: 2 errores y 1 advertencia**, idénticos a `HEAD` en una comparación separada. |

Los diagnósticos preexistentes de la vista son `react-hooks/refs` (asignación a `historySelectedModel.current` durante render), `react-hooks/set-state-in-effect` (reinicio del historial) y `react-hooks/exhaustive-deps` (captura de `historyRequest.current` en cleanup). Se retiró la variable que quedó sin uso al sustituir el selector; no se alteraron esos hooks fuera del alcance.

Durante la adaptación de pruebas hubo fallos de interacción nativa, dos errores de edición y una lectura truncada que afectó la cola de una prueba. Se corrigieron sin eliminar casos: la cola se recuperó desde `HEAD` y las aserciones de negocio permanecen. La primera suite tuvo 569 aprobadas y 6 fallidas; las seis dependían de consultar opciones nativas sin abrir el nuevo menú. La suite final de 575 pruebas cubre las interacciones corregidas.

La evaluación nativa de revisión no estuvo disponible: devolvió `untracked files require an explicit declaration`. No se inició una revisión ni se emitió aprobación nativa. La verificación visual manual queda pendiente de aplicar el cambio al entorno activo con autorización; DOM y clases CSS no prueban píxeles.

Los logs, códigos de salida, comandos exactos y manifiestos privados están en `.private-local-delete-work/prediction-selector-checks/`: `results-verified.json`, `candidate-validated-manifest.json`, `verified-suite.*`, `verified-build.*`, `verified-types.*`, `verified-lint-component-tests.*` y `view-lint-baseline-comparison.json`. No son artefactos de producto ni se incluyen en commits.

## Ajuste posterior de la tarjeta de modelo seleccionado

Ajuste solicitado, acompañado de captura: la disposición del bloque de modelo seleccionado deja el nombre cortado hacia la izquierda.

La cabecera distribuía nombre/descripción y etiquetas de dispositivo/versión en una misma fila. El bloque de etiquetas usaba `shrink-0`, comprimiendo el texto en una columna estrecha. Se cambian únicamente clases de disposición en `PredictionView.tsx`: nombre y descripción ocupan una fila completa con `min-w-0`, `w-full` y `break-words`; las etiquetas quedan debajo en una fila con `flex-wrap`. La tarjeta y su primera fila también admiten ancho reducido y ajuste de línea. No se cambian textos, selección, métricas, checkpoint, consultas ni inferencia.

Se añadió una regresión estructural al render público del catálogo con el nombre `motores · PANNs-CNN14 (v2)` y su descripción. El primer intento encontró una descripción repetida y se acotó la consulta a la cabecera; después se observó RED por la disposición horizontal anterior y GREEN tras el cambio. Es una comprobación DOM/clases, no una reproducción visual en un motor de navegador.

Comprobaciones nuevas sobre copia aislada: **56 pruebas focales y 576 pruebas completas en 67 archivos aprobadas**, build Webpack y TypeScript aprobados, lint de la prueba aprobado. El lint de la vista conserva los mismos 2 errores y 1 advertencia de base, sin diagnósticos nuevos; sigue sin aprobación global. La evaluación nativa continúa no disponible por archivos no rastreados y no se inicia revisión. Evidencia privada, sin sobrescribir la del selector: `.private-local-delete-work/selected-model-card-layout/{results.json,manifest.json,red-layout.*,focused.*,suite.*,lint-test.*,lint-view.*,build.*,types.*}`.

La comparación con la fuente previamente verificada confirma cambios de producción exclusivamente en atributos `className`; los hashes finales coinciden con la copia comprobada. No se modifica la copia activa, no se reinician servicios ni se hacen commits. La aceptación visual manual sigue pendiente de una actualización activa autorizada.

## Coste y exclusiones

Coste esperado **bajo y localizado**: un componente de presentación, una integración y pruebas. No requiere cambios backend, modelos ML, bases de datos, instalación de paquetes, refactorización del selector de entrenamiento ni modificaciones al flujo de tríada.

La implementación es local y no modifica backend ni componentes compartidos de Entrenamiento. No se instalan paquetes, no se ejecuta inferencia real y no se actualiza la copia activa. Commit, actualización de la aplicación activa y reinicio requieren autorización separada.

## Simplificación posterior del detalle de evaluación

La tarjeta ya no muestra el bloque «Checkpoint registrado y cargado». El modal omite hashes, schemas, identificadores de dataset, evaluador, split técnico duplicado, mensajes de denominador nulo y advertencias sobre parámetros internos. Se mantienen las métricas, clases, matriz, estados y la distinción entre evaluación aplicable e historial; no se modifican cálculos ni admisión backend. La identidad técnica de un resultado de inferencia es una sección diferente y no se altera en este ajuste.

Cada intento y cada informe muestra una sola fecha: finalización si es válida; en su defecto, inicio o solicitud con su etiqueta correspondiente. Se usa fecha larga en español, hora de 24 horas y zona UTC explícita; fechas inválidas no se muestran como si fueran válidas. La finalización es la referencia principal porque indica cuándo quedó disponible el resultado.

Se elimina la lista numérica sin nombres de «Soporte por clase». La tabla por clase conserva los recuentos bajo «Audios evaluados», con `InfoTooltip`, el mismo componente usado en Entrenamiento, para explicar que son cantidades de audios reales y no puntuaciones. Otro tooltip explica que cobertura completa significa presencia de todas las clases, no precisión perfecta. Los rechazos mantienen cantidad y porcentaje sin etiqueta interna; su columna en la matriz se presenta como «Rechazo».

El ajuste cubre presentación, no cambios de entrenamiento, datasets, cálculos, publicación ni credenciales. Comprobaciones y evidencia privada de este ajuste: `.private-local-delete-work/prediction-evaluation-summary/`. No se modifica el componente común de tooltip ni se instala ninguna dependencia.

Verificación observada del resumen: RED por presencia de bloque técnico; GREEN de 66 pruebas focales y 580 pruebas completas en 67 archivos. Lint de las pruebas aprobado; lint de la vista conserva exactamente 2 errores y 1 advertencia de base, sin aprobación global. El primer build detectó un tipo de entrada demasiado restrictivo del formateador de fechas: se corrigió la firma a `unknown` para validar los valores recibidos antes de formatearlos. Tras esa corrección exclusivamente de tipo y limpieza de espacios, build Webpack, TypeScript y las 66 pruebas focales volvieron a pasar; no se repitió la suite completa porque no cambió el comportamiento. No se ejecutó inferencia real ni navegador automatizado.

Aplicado a la copia activa con respaldo validado y hash de destino idéntico a la fuente comprobada. Se actualizó solo `PredictionView.tsx`, reutilizando el `InfoTooltip` ya presente sin modificarlo; sin reinicio de servicios. El frontend respondió HTTP 200. Evidencia en `active-apply.json`, `active-before.tsx`, `results.json`, `results-final.json` y `manifest-final.json` del directorio privado anterior. La revisión nativa sigue no disponible por archivos no rastreados y no se inició ninguna transacción; no hay aprobación nativa. La apariencia final y los tooltips siguen sujetos a comprobación manual del usuario.
