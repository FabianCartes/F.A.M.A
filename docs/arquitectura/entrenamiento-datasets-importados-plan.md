# Plan: entrenamiento de datasets importados
Traspaso para una nueva sesión: conectar colecciones importadas con preparación reproducible, entrenamiento y evaluación local.
Estado: T0 completada; T1 completada como base de snapshots locales (commit `36bf33806d4678246c76331b7abede7c2a81e8df`); T2 completada en commit `73526d6f4ab0c52bc9bc7a16d43994155692794a`, con limitación del recheck independiente aceptada; T3–T7 sin iniciar. Rama: `feat/imported-training-snapshots`. Runner: `backend/tests/run_isolated_training_checks.py` con `.venv/bin/python` (Python 3.14.8 host, no acredita imagen 3.12). Este documento no autoriza entrenamiento real, migraciones sobre datos existentes ni cambios del runtime.

## Specs

Solicitudes del usuario, conservadas literalmente; las recomendaciones del agente se distinguen en las secciones posteriores.

- S1: «Perfecto, ahora se requiere pasar al entrenamiento, verifica que se requiere para que cualquier dataset este disponible para entrenamiento para asi dejar el flujo definitivo».
- S2: «Con este nuevo flujo, cualquier dataset que pase la subida del zip podra ser entrenado? este cambio no modificaria el modulo de subida del zip?».
- S3: «Y en que parte se mencionaria que no puede ser entrenado? Abria que fijar un limite minimo de audios para entrenamiento cierto? Esta comprobacion se podria omitir de momento y dejarlo como trabajo futuro?».
- S4: «Cual seria tu propuesta de minima cantidad para tener una distribución?».
- S5: «Realiza el plan para solucionar el problema de entrenamiento con lo conversado anteriormente, lo ideal seria implementarlo en una nueva sesion».
- S6: «Require an explicit group map — recommended».
- S7: «Require all three — recommended».
- S8: «WAV, single-label, local — recommended».
- S9: «Require an explicit profile — recommended».

S6–S8 son las opciones seleccionadas por el usuario al cerrar T0; sus preguntas y consecuencias quedan registradas en L6. S9 se confirma para T2 y su consecuencia literal queda en L16.

## Lectura rápida y alcance

**Objetivo propuesto:** cualquier colección importada que cumpla un contrato de clasificación acústica debe poder prepararse y entrenarse sin agregar su nombre al código. Importar correctamente no acredita que se puedan construir particiones válidas ni que el modelo vaya a ser útil.

Primera versión confirmada en T0 (S8): WAV, clasificación supervisada con una etiqueta por archivo y preparación/entrenamiento locales sin dependencia de GCS. No incluye multilabel, detección de eventos, regresión ni cualquier modalidad/modelo. La predicción HTTP conserva su contrato GCS actual. Al iniciar la implementación, confirmar el alcance si el usuario solicita algo diferente; no interpretar «cualquier dataset» como compatibilidad universal.

| Decisión propuesta | Aplicación |
| --- | --- |
| Conservar el importador ZIP | No cambiar recepción, límites, clases por carpeta, validación contenida, confirmación, descarga ni sincronización para imponer requisitos ML. |
| Separar preparación de importación | La elegibilidad y sus razones aparecen en Entrenamiento y en el resultado de Preparación; no invalidan una importación correcta. |
| Cantidad como advertencia | Referencia operativa de 10 grabaciones independientes por clase; no rechazo automático del ZIP ni bloqueo por ese número. Es recomendación discutida, no suficiencia estadística demostrada. |
| Fallar ante imposibilidad estructural | No admitir entrenamiento sin fuente válida, etiquetas coherentes o particiones utilizables y sin fuga. |
| Mantener contratos existentes | Preservar `AvesChilenas`, `engine_diagnostics`, checkpoint/predictor y preparación histórica compatibles. No renombrar ESC-10 como un dataset legacy. |
| Local-first | Congelar y preparar con los archivos locales publicados; sincronizar con GCS no es requisito. |

No se han acordado umbrales de calidad, balance mínimo, folds definitivos ni resultados métricos exigibles. No inventarlos como requisitos del usuario.

## Tasks

T0 está completada únicamente como investigación y diseño; evidencia y decisiones más abajo y en el [ADR 0052](../adr/0052-preparacion-local-de-datasets-importados.md). T1 está implementada y verificada en estado sintético aislado, con límites de evidencia registrados; T2 está implementada con verificación funcional y limitación independiente aceptada; T3–T7 son tareas **futuras**, no resultados aprobados. Una tarea incluye su código, pruebas y documentación relacionados; no separar escritores de código/pruebas del mismo comportamiento. Los paths son candidatos que deben estrecharse tras T0, no permiso para editar directorios completos.

| ID | Specs | Estado | Resultado y superficie candidata | Dependencias / comprobación de cierre |
| --- | --- | --- | --- | --- |
| T0 | S1-S8 | completada (diseño; sin implementación) | Reconciliar checkout y restricciones; resolver congelación local y selección registry→predictor. Confirmar contrato de primera versión, persistencia y política de grupos. | Lectura acotada de los dos contratos pendientes; mapa con evidencia y diseño mínimo. Sin datos reales ni servicios. |
| T1 | S1-S2,S8 | completada; delegado por context backstop; commit `36bf338` | Servicio público de snapshot local por propietario/ID, completo y verificable; copia privada y manifiesto persistido, sin endpoint ni admisión hasta T3. Tablas y migrador aditivo explícito, solo ejecutado sobre fixtures sintéticas. | T0; RED/GREEN por regla; ownership, hashes/tamaños, membresía completa, append concurrente, reinicio/lectura y fallos sin snapshot consumible. Regresión ZIP sin tocar importador. Risk: items 2 y 4 (ownership/confinamiento y captura concurrente). |
| T2 | S1,S3-S4,S6-S9 | completada; commit `73526d6`; 141 PASS/1 deselección y focal 6 PASS; recheck independiente unavailable aceptado | Módulo nuevo `backend/training/imported_dataset_preparation.py`, pruebas y manual; formato separado por snapshot/versión, mapa de grupos/procedencia y perfil audio/arquitectura explícitos, clases y splits, advertencias. Sin loader legacy/admisión/UI. | T1; RED/GREEN con logs crudos; reproducibilidad y selección exacta, cobertura por clase, grupos disjuntos, cantidad baja solo advierte, perfil compatible e integridad/fallos. Risk: item2 (ownership/confinamiento), item4 si publicación concurrente. |
| T3 | S1-S2 | pendiente | Catálogo/admisión de entrenamiento ligados a snapshot y preparación, conservando contrato legacy. `backend/app/services/training.py`, rutas/esquemas consumidores. | T1-T2; rechazo previo al job, procedencia estable y regresiones de los dos datasets anteriores. No aceptar rutas del cliente. |
| T4 | S1,S3-S4 | pendiente | UI de Entrenamiento: selección de importados, preparación explícita, motivos de indisponibilidad y advertencias. `frontend/components/views/TrainingView.tsx`, cliente/esquemas y pruebas relacionados. | T2-T3; UI refleja estados reales, parámetros visibles llegan al backend y ZIP permanece independiente. |
| T5 | S1 | pendiente | Integrar y comprobar val/test, persistencia, registro y carga del predictor con clases/procedencia de la nueva fuente. Servicios de evaluación/registro/predictores solo donde sea necesario. | T3; checkpoint sintético y predicción pública conservan etiquetas y fuente. No rediseñar activación ni sustituir fallback legacy sin alcance. |
| T6 | S1-S8 | pendiente | Regresión integrada, verificación independiente de riesgos y documentación de uso/arquitectura. | T1-T5; TDD observado, controles aplicables y límites informados. Cierre de código no implica despliegue ni entrenamiento real. |
| T7 | S1,S5 | pendiente, autorización operacional separada | Prueba manual con ESC-10 importado, solo después de preparar persistencia/entorno y acordar dataset, presupuesto, arquitectura y efectos. | T6 y autorización explícita; respaldo/preflight y evidencia por etapa. No ejecutar por el mero cierre de tareas anteriores. |

## Estado comprobado y límites del diagnóstico

Referencia del checkout al redactar: rama `dev`, HEAD `dd929cd45c894368c69f6fde3d4606c4381ce222`. Las líneas indicadas son referencias de esta lectura; revalidarlas si cambia el checkout.

| Hecho observado | Evidencia de código |
| --- | --- |
| UI consume catálogo de entrenamiento y endpoint de inicio | `frontend/lib/api/trainingApi.ts:119–155`. |
| Solo dos identidades en catálogo/admisión; exige un `ConjuntoDatos` exacto y único | `backend/app/services/training.py:62,269–314,464–473`. |
| Fuente preparada validada antes de admitir job: metadata, referencias, audio, clases y separación de grabaciones | `backend/app/services/training.py:355–424,460–487`. El padre contrastó directamente este tramo. |
| Preparación restringida por nombre; su identidad actual no congela por sí misma bytes originales de audio | `backend/training/prepare_data.py:33–37,97–110,126–192,243–265`. |
| Confirmación local publica objetos y miembros; revisión de miembro registra inserción, no snapshot histórico completo | `backend/app/services/dataset_import_execution.py:229–312`; `backend/app/models/dataset_import.py:7–15`. |
| Modelos de revisión completa tienen identidad de objetos remotos; manifiesto público observado exige revisión completa y lectura remota verificada | `backend/app/models/dataset_import_revision.py:7–52`; `backend/app/routes/dataset_imports.py:154–181`; `backend/app/services/dataset_import_storage.py:45–60`. |
| Evaluación posterior usa clases restauradas y evalúa val/test antes de completar/activar caso no ensemble | `backend/app/services/training.py:688–751`; `backend/app/services/recording_evaluator.py:67–139`. |
| Predictor entrenado admite clases dinámicas y dimensiona la arquitectura con `len(classes)` | `backend/app/services/predictors/trained_predictor.py:153–175,205–269,427–452`. Conserva fallback de aves para checkpoints sin clases: no extender ese fallback a fuentes nuevas. |

### Dos comprobaciones iniciales de T0 (cerradas; resultado más abajo)

1. **Freeze local sin GCS:** la lectura anterior no acreditó el cuerpo que crea la revisión completa en `dataset_import_manifests` ni si está disponible antes de sincronizar. Seguir su creación y consumidores en el código actual. Reutilizarlo solo si congela membresía completa sin dependencia remota; de lo contrario, diseñar el snapshot local mínimo. No usar `DatasetMember.dataset_revision` como si fuera un historial completo ni quitar la guarda de `complete` del manifiesto remoto.
2. **Registro → predictor:** no quedó trazada la selección ordinaria del predictor del modelo publicado frente al default/bundles/ensembles. Seguir `registry` y sus rutas/consumidores; demostrar que el nuevo modelo se carga y devuelve sus propias etiquetas. Evaluar un checkpoint no prueba todas las rutas de publicación/inferencia.

Estos límites no son fallos actuales reproducidos ni se resuelven suponiendo compatibilidad. No repetir una auditoría general; cerrar los dos contratos concretos antes de implementar sobre ellos.

## Resultado técnico de T0

Revisión sobre `dev`, HEAD `dd929cd45c894368c69f6fde3d4606c4381ce222`. Hallazgos de código, no prueba operacional. Cambios locales del frontend y documentos anteriores preservados. La instrucción «Termina T0» autoriza cerrar esta tarea, no iniciar T1–T7.

### Congelación local: contrato actual y diseño mínimo propuesto

- `backend/app/services/dataset_import_manifests.py:53–85` crea la revisión al sincronizar, copiando toda la membresía mediante `INSERT … SELECT` bajo la misma compuerta de publicación utilizada para confirmar importaciones. No usar la revisión de inserción de un miembro como snapshot completo.
- `dataset_import_manifests.py:169–224` exige adaptador remoto, verifica/sube los objetos y el manifiesto y solo entonces asigna `complete`. El endpoint público exige ese estado y recupera el manifiesto remoto (`backend/app/routes/dataset_imports.py:161–181`). Por tanto, **no existe actualmente un snapshot completo local de entrenamiento independiente de GCS**.
- Propuesta para T1: identidad y ciclo de vida propios de snapshot local de entrenamiento, sin cambiar el significado de `DatasetRevision.complete`. Capturar propietario, dataset, revisión y membresía completa bajo la compuerta compartida; verificar objetos locales por lotes y publicar la identidad únicamente después de completar la validación.
- Propuesta de bytes estables: materializar una copia privada verificada en el almacenamiento de entrenamiento, con hash/tamaño y manifiesto canónico; no usar enlaces duros a originales mutables. Presupuestar espacio, limpiar únicamente staging fallido propio y publicar atómicamente el snapshot. Append concurrente no cambia su membresía. Toda lectura de preparación debe comprobar integridad y fallar sin admitir job ante discrepancias. Las garantías entre captura, copia y publicación se deben demostrar con pruebas sintéticas en T1, no se consideran implementadas por este diseño.
- Persistencia propuesta: metadatos e identidad en la persistencia de aplicación; audio y preparados en raíces configuradas durables. Ninguna ruta del cliente ni almacenamiento RAM del runtime temporal como garantía de durabilidad. Esquema nuevo solo en pruebas aisladas hasta autorizar migraciones reales. Ownership debe verificarse tanto al crear como al seleccionar snapshot/preparación; no ampliar acceso para la identidad de desarrollo `-1`.

### Registro y predictor: selección trazada

- `backend/app/services/registry.py:101–123`: ID explícito selecciona el predictor registrado; omitir ID o usar `default` selecciona el default. No hay fallback automático hacia un bundle.
- `registry.py:307–324`: publicación de modelos persistidos construye `TrainedModelPredictor`, registra `fama_trained_model_<id>` y aliases, sin cambiar el default. El arranque restaura modelos persistidos y el activo; discovery de bundles es una operación distinta (`registry.py:338–430,506–549`).
- `backend/app/main.py:604–644`: `POST /api/predict` recibe `model_id` y llama a `registry.get(model_id)`. Después exige pesos y validación de audio, y **confirma subida GCS antes de ejecutar inferencia** (`main.py:666–714`). Local-first para preparar/entrenar no acredita predicción HTTP sin GCS. En T5 la prueba HTTP debe usar un adaptador remoto sintético aislado, sin operaciones GCS reales; eliminar esa dependencia de producción sería otro alcance.
- `backend/app/services/predictors/trained_predictor.py:153–175` restaura `classes`, pero mantiene fallback de aves si faltan. Para fuente importada, T5 debe exigir clases explícitas y comprobar orden/índices por ID registrado, preservando default/legacy. La asociación de dataset verificada por el registro no se debe sustituir por un nombre inferido.
- Prueba futura necesaria: checkpoint CPU sintético → publicación → catálogo → selección HTTP por ID → etiquetas/procedencia, más regresión del default. La lectura de código cierra el mapa de selección, **no demuestra todavía carga o predicción correcta del nuevo modelo**.

### Contrato confirmado al cerrar T0

Primera versión confirmada (S8): WAV supervisado de etiqueta única, preparación/entrenamiento local; conservar ZIP y legacy. Preparación identifica snapshot, perfil efectivo de audio/arquitectura, semilla, mapa de clases y grupos.

`DatasetMember` conserva clase, ruta, import de origen, hash y tamaño, pero no identidad explícita de grabación/grupo (`backend/app/models/dataset_import_metadata.py:44–55`). El usuario eligió exigir mapa explícito de grabación/grupo validado y vinculado al snapshot (S6); si falta, indicar pendiente de metadatos y no preparar splits afirmando independencia. No deducir independencia del nombre ni del hash. La procedencia del mapa debe conservarse; su existencia no certifica la verdad de las anotaciones.

El usuario confirmó cobertura de todas las clases en train/val/test, con objetivo 80/10/10 por grupos (S7); si es inviable, explicar imposibilidad estructural. Menos de 10 grabaciones independientes sigue siendo solo advertencia. Decisión y alternativas en el [ADR 0052](../adr/0052-preparacion-local-de-datasets-importados.md).

T0 queda cerrada: checkout reconciliado, dos contratos trazados, diseño mínimo de persistencia/estabilidad definido y decisiones humanas recibidas. La frecuencia, canales, ventana y preprocesamiento efectivos se concretan en el perfil versionado compatible con la arquitectura en T2; no se inventa aquí un valor universal. Esquema, códigos de error y pruebas de carreras/retención siguen siendo implementación T1–T6, no brechas que esta lectura declare resueltas. No hay autorización para iniciarlas por cerrar T0.

## Contrato mínimo propuesto

### 1. Fuente, acceso e identidad

- Resolver una colección por propietario/identidad autorizada e ID estable; el nombre es presentación, no selector de dominio o ruta.
- Fijar membresía completa, clase, hash y tamaño de cada objeto local publicado, más metadatos y procedencia usados para preparar. Vincular job, preparación y checkpoint a esa identidad.
- Mantener inalterada la cohorte admitida cuando el dataset reciba más archivos. Detectar bytes ausentes/modificados; no entrenar silenciosamente contra otra versión. Aplicar el diseño de copia privada verificada de T0 y demostrar sus garantías de carrera en T1.
- No confiar en hashes enviados por el cliente ni permitir escapes de raíz. No revelar datasets de otros propietarios.
- La identidad de desarrollo `-1` no se convierte en cuenta real ni habilita acceso global. Inspeccionar la autorización actual del entrenamiento y resolver ownership de extremo a extremo sin desactivar autenticación.
- Referencias y metadatos grandes deben procesarse con límites razonables y lectura incremental; no cargar toda una colección en RAM ni recalcular un manifiesto completo por cada fila sin necesidad.

### 2. Preparación y política de audio

- Mantener una interfaz pequeña de fuente/preparación; reutilizar implementaciones existentes donde cumplan el contrato. No introducir un framework de adaptadores o una nueva cola sin necesidad acreditada.
- Perfil explícito de tarea/audio y arquitectura compatible: frecuencia, canales, segmentación/ventanas y preprocesamiento efectivos. Nunca deducir dominio por el nombre de la colección.
- Índice de archivos etiquetados, mapa de clases ordenado y estable y metadatos de grabación/grupo. Rechazar etiquetas reservadas/inválidas y clases de evaluación ausentes en train.
- Separar grupos/grabaciones antes de segmentar o aumentar datos. Hash diferente no demuestra independencia; segmentos de una misma grabación permanecen juntos. No deducir agrupación fiable solo del nombre de archivo.
- Si faltan metadatos de origen/grupos, exponer preparación pendiente de metadatos y exigir el mapa explícito confirmado en S6; no inventar independencia ni introducir un bypass silencioso.
- Guardar identidad/versionado de preparación, snapshot, splits, semilla, política efectiva y mapa de clases. Nada de regeneración implícita que cambie la cohorte al iniciar entrenamiento.
- Permitir volver a seleccionar una preparación explícita compatible; no elevar una preparación histórica incompatible a fuente verificada ni usar `allow_historical_preparation` para sortear requisitos nuevos.

### 3. Distribución y cantidad

Propuesta inicial: objetivo **80/10/10**, con asignación que respete grupos y restricciones. No es obligación de alcanzar porcentajes exactos cuando eso viola independencia.

| Ejemplos independientes por clase, si son asignables | Train | Val | Test | Interpretación |
| --- | --- | --- | --- | --- |
| 3 | 1 | 1 | 1 | Piso matemático si se exige representar cada clase en las tres particiones; no recomendación de calidad ni garantía del algoritmo. |
| 10 | 8 | 1 | 1 | Referencia operativa propuesta, advertencia si no se alcanza. Un caso en val/test no produce métricas robustas. |
| 40 | 32 | 4 | 4 | Ejemplo orientativo para ESC-10; condicionado a grupos/folds y procedencia válidos. |

No imponer ahora un umbral estadístico duro por clase. Posponer recomendaciones de suficiencia, balance y tamaño para generalización. Conservar las restricciones estructurales del contrato adoptado: no admitir particiones vacías/inutilizables, clases incompatibles, datos ilegibles ni fuga. S7 confirma cobertura de todas las clases en cada split para la nueva preparación; no atribuir esta decisión a la admisión legacy actual.

### 4. Estados visibles y resultado

En Entrenamiento mostrar conceptos equivalentes a **pendiente de preparación**, **preparado para entrenar** y **no se pudo preparar**, junto con razones accionables. Son textos/estados propuestos, no enums existentes confirmados. Precisar esquema y códigos al implementar y actualizar ayuda/documentación si cambia la interfaz.

- Un dataset importado válido sigue importado aunque no sea apto para una preparación concreta.
- La advertencia de cantidad reducida no debe convertirse en un botón deshabilitado por ese único criterio.
- Una incompatibilidad real se muestra antes de admitir entrenamiento, indicando la fase y el requisito incumplido, sin rutas internas/secretos.
- Distinguir admisión, ejecución, checkpoint persistido, evaluación completa, disponibilidad en catálogo y activación. No mostrar éxito global porque respondió el endpoint de inicio.
- No cambiar políticas de activación/default/ensemble por arrastre; limitarse a integrar y comprobar la nueva fuente con las políticas vigentes.

## Verificación futura: interfaces públicas y TDD

No se ejecutaron estas pruebas al redactar el plan. Los archivos son candidatos, no una suite histórica aprobada para el futuro cambio.

| Regla | Prueba de aceptación requerida |
| --- | --- |
| Catálogo e identidad | Dataset importado autorizado visible por ID; nombre arbitrario no requiere editar lista. No revelar otro propietario; conservar comportamiento legacy. |
| Admisión segura | Fuente no autorizada, snapshot inexistente/incompleto, referencias inválidas o preparación no aplicable se rechazan antes del job. Verificar respuesta, estado, datos y contadores sin alteraciones indebidas. |
| Snapshot completo | Añadir archivos a la colección no cambia una cohorte admitida; incluir todos los miembros de la versión seleccionada, no solo los insertados en su última revisión. |
| Integridad y fallos | Audio ausente/cambiado o fallo de lectura no produce entrenamiento/publicación parcial presentada como correcta. Probar la carrera relevante con estado sintético aislado. |
| Preparación | Semilla/perfil/snapshot iguales conservan asignación e identidad; grupos no se cruzan; segmentación/aumentación no mezcla splits. |
| Cantidad | Caso pequeño con particiones factibles genera advertencia y permite continuar; caso imposible falla por partición, no por no llegar a 10. Comprobar mensajes y ausencia de job. |
| Clases y modelos | Checkpoint CPU sintético con clases nuevas conserva orden e índices; val/test, registro y predicción pública usan las mismas clases y procedencia, sin fallback de aves. |
| UI | Elegibilidad/motivos/advertencias/preparación y parámetros efectivos; selección por ID, sin presentar importación como entrenamiento terminado. |
| Regresión ZIP | Recibir/importar/consultar/descargar conserva su contrato. No introducir umbral ML en el importador ni cambios no solicitados en límites/autorización/confirmación. |
| Regresión legacy | Mantener `AvesChilenas` y `engine_diagnostics`, políticas específicas, semilla y preparación, individual/duo/trío y persistencia/evaluación aplicables. |

Candidatos backend: `test_training_flow.py`, `test_training_service.py`, `test_training_persistence.py`, `test_api_training.py`, `test_dataset_preparation.py`, `test_recording_evaluator.py`, `test_trained_predictor.py`, `test_dataset_import_execution.py`, `test_dataset_import_manifests.py` y regresiones de consumidores que realmente se modifiquen. Frontend: pruebas del cliente/esquemas y `TrainingView.test.tsx`, preservando la corrección local previa de parámetros individuales y el comportamiento duo/trío.

**Procedimiento:** leer [integración del flujo](../manuales/integracion-flujo-entrenamiento.md) y [consolidación](../manuales/consolidacion-worktrees.md); revisar fixtures y prerrequisitos del runner antes de seleccionar módulos. Usar el runner `backend/tests/run_isolated_training_checks.py` con SQLite en memoria, CPU/audio sintéticos, temporales privados y red bloqueada. No debilitar `training_host_guard.py` ni instalar por inercia. Un selector aceptado no acredita que su fixture sea hermética; no ejecutar una suite global a ciegas.

Forma de comando **futura, no ejecutada en esta planificación**, desde `backend/`:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHON_DOTENV_DISABLED=1 DATABASE_URL=sqlite:// \
CUDA_VISIBLE_DEVICES='' PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
/home/kevin/Work/fama/.venv/bin/python \
  tests/run_isolated_training_checks.py <selectores-revisados>
```

Confirmar primero el intérprete: la imagen backend usa Python 3.12; un resultado host con Python distinto no la valida. Informar exits/stdout/stderr, deselecciones y límites, no reutilizar conteos de documentos anteriores. Para cada comportamiento nuevo con runner aplicable: RED antes de producción, GREEN y regresión de consumidores tocados. Si se cambia un helper/parser compartido, comprobar diferencias no solicitadas frente al código base mediante el procedimiento acotado del harness; no comprometer pruebas que lean historial Git.

Desde `frontend/`, si se modifica: `npm test`, `npm run lint`, `npm run build` y comprobación de tipos según sus instrucciones locales. No repetir builds equivalentes por inercia; informar fallos ambientales y pruebas no ejecutadas. Verificación independiente para los riesgos concretos y revisión nativa únicamente según el switch/consentimiento del usuario, nunca como permiso de despliegue.

## Operación y preservación para la nueva sesión

### Git y cambios locales

Al redactar, hay modificaciones anteriores en `docs/README.md`, `frontend/components/views/TrainingView.tsx`, su test y manuales no rastreados. Esta planificación añade este documento y su enlace, sin commits ni cambios de producción. Comparar `git status` y diffs al retomar; no resetear, limpiar ni mezclar esas ediciones accidentalmente.

No se autoriza implementación por el mero contenido de este plan. Al recibir autorización, clasificar riesgos y mantener seguimiento de tareas/documentación bajo `docs/`, sin carpetas documentales paralelas. Elegir rama/commits conforme a las instrucciones vigentes y a las restricciones humanas, sin inferir permiso de push, PR, merge o despliegue. Si se adopta una decisión arquitectónica relevante, comprobar el último ADR y usar la numeración siguiente real; no reservar aquí un número.

### Runtime temporal: último estado observado, no comprobación actual

Consultar [prueba manual principal](../manuales/prueba-manual-principal-importacion.md), especialmente L45–L47. El usuario reportó importación, descarga por clase y reproducción correctas; no informó IDs/conteos/estado terminal exactos, no inventarlos.

Última preparación observada: main `localhost:3000`, API/ frontend inmutables de prueba en red interna `172.30.254.0/24`; DB conserva `172.30.253.30` y añade `.254.30`, mismo volumen/identidad. API con `--lifespan off`, solo import root físico persistente; data/checkpoints en RAM. **No es un entorno validado para entrenar.** Código nuevo en host no actualiza automáticamente esas imágenes.

Worker de importación job34 (PID histórico307099), relay principal job33 y privado3300/job9 quedaron activos al entregar la prueba anterior. PIDs/jobs/nombres pueden cambiar o dejar de existir en otra sesión: no usarlos sin renovar identidad ni intentar controlar jobs heredados como si pertenecieran al nuevo harness. No detener servicios o lanzar otro consumidor por inercia. Originales preservados detenidos y candidatos intermedios constan en el manual.

Restaurar originales puede reactivar tareas cloud; no hacerlo automáticamente. No `docker compose up/down` sobre este estado preservado: sus etiquetas no acreditan equivalencia con YAML. No leer `.env`, credenciales, claves cloud ni imprimir URLs/valores de entorno. Para desarrollo inicial usar pruebas aisladas, no los datos/DB reales del usuario.

Antes de una operación real futura: autorizar objetivo/efectos, renovar baseline/jobs/locks, comprobar persistencia de preparados y checkpoints, entorno/pesos necesarios, presupuesto de CPU/GPU/tiempo y almacenamiento, respaldos y reversión. Sin descargas de pesos, GCS, migraciones reales, cambio de volúmenes ni entrenamiento por defecto. Modelos CPU sintéticos no requieren descargar pesos.

### ESC-10 como aceptación posterior

ZIP preparado: `ESC10_dog_rain_sea_waves_120.zip`, 120 WAV, 3 clases, 40 archivos por clase, 52.939.882 bytes. SHA256 `4901586c10fe123fc8d9c554dfe7f2f8326a19b46df6507f2bc710bb79034afa`. Ubicación histórica autorizada: `/run/media/kevin/FAMA_P2/fama-p2/fama-manual-local/main-readiness/esc10-3classes-v1/`.

Los metadatos oficiales/folds y atribuciones están **fuera del ZIP**. No asumir que el catálogo importado contiene esa información. Asociarla y validarla explícitamente si se utiliza; no inferir independencia por filenames. El acceso a almacenamiento externo y datos reales en una nueva sesión requiere confirmar la autorización del objetivo; este plan no da permiso general para leer fuera del repositorio.

La prueba real posterior debe separar preparación, admisión, finalización, checkpoint persistido, informes val/test, disponibilidad/carga y predicción autorizada. No exige accuracy mínima ni garantiza generalización. Mantener IDs/hashes/clases/splits y errores como evidencia, nunca credenciales.

## Inicio sugerido original (histórico; T0 ya cerrada)

> Retoma `docs/arquitectura/entrenamiento-datasets-importados-plan.md`. Primero lee Specs, Tasks y los dos contratos pendientes de T0; después contrasta el Log y Git. Revisa la memoria del proyecto y sus observaciones completas, no reconstruyas requisitos desde resúmenes. Este es un plan, no implementación ni autorización de operaciones reales. Presenta el alcance de código y las decisiones pendientes antes de escribir. Si autorizo implementar, comienza por T0 y pruebas sintéticas aisladas; preserva la subida ZIP, los cambios locales y los dos flujos legacy. Referencia de cantidad: 10 grabaciones independientes por clase como advertencia, no bloqueo numérico; bloquear solo por imposibilidad estructural o incompatibilidad. Sin entrenamiento real, servicios, GCS, instalaciones ni migraciones sobre datos existentes sin autorización separada.

## Log

- L1: Solicitud original del puente de entrenamiento conservada íntegra en S1; seguimiento de preguntas sobre importación, elegibilidad y cantidad en S2–S4. El usuario reportó antes: «realice la importacion, descarge audios de cada clase y se escuchan correctamente. La prueba solo contemplaba esto sin entrenar aun?».
- L2: Diagnóstico de solo lectura con mapa acotado y una corrección. Hechos y límites en la tabla anterior; no se ejecutaron tests, entrenamiento, consultas DB ni cambios de servicios para este diagnóstico. El código leído no acredita el despliegue temporal ni el éxito de un modelo con ESC-10.
- L3: Recomendaciones discutidas: local-first, clasificación WAV supervisada de etiqueta única como primer alcance, estados de preparación en Entrenamiento, no modificar validación ZIP por criterios ML; 10 grabaciones independientes por clase y 80/10/10 como referencia, sin bloqueo estadístico duro. Son propuestas de diseño que el plan distingue de las citas del usuario; multilabel/otras tareas no aceptadas implícitamente.
- L4: «Realiza el plan para solucionar el problema de entrenamiento con lo conversado anteriormente, lo ideal seria implementarlo en una nueva sesion». Se redacta este documento de propuesta y su enlace; implementación y operación aplazadas a nueva autorización. No hay tareas T0–T7 completadas ni pruebas funcionales nuevas de código.
- L5: «Termina T0». Exploración acotada de solo lectura y contraste del padre: manifiesto completo depende de sincronización GCS; ruta HTTP selecciona registro por ID y exige subida GCS antes de inferir. Resultado técnico y diseño mínimo registrados. Sin producción, tests de código, servicios, datos reales, GCS ni commits.
- L6: Decisiones humanas recibidas en cuestionario:
  - Pregunta: «When imported files lack recording/group metadata, which policy should preparation use?». Selección literal: «Require an explicit group map — recommended». Consecuencia mostrada: «Keep the import valid; preparation waits for validated recording/group metadata. Never assume file independence.».
  - Pregunta: «Should each class be represented in train, validation and test?». Selección literal: «Require all three — recommended». Consecuencia mostrada: «Aim for 80/10/10 by groups; reject only when valid class-covered splits cannot be formed, not for having fewer than 10 recordings.».
  - Pregunta: «Confirm the first-version scope for the T0 design.». Selección literal: «WAV, single-label, local — recommended». Consecuencia mostrada: «Local preparation/training; preserve ZIP and legacy. Public prediction keeps its existing GCS contract; test it with synthetic storage.».
- L7: T0 cerrada como investigación/contrato; S6–S8 incorporan las decisiones, ADR 0052 registra límites y alternativas. T1–T7 siguen sin iniciar. Verificación documental: estructura Specs/Tasks/Log, rutas y enlaces locales de documentos afectados y `git diff --check`; no pruebas funcionales ni garantías runtime acreditadas. Cambios previos preservados y sin commits.

- L8: Usuario: «Procede». Autoriza la siguiente tarea anunciada, T1, no T2–T7. Se crea rama feat/imported-training-snapshots desde dd929cd conservando cambios locales. Seam de prueba: servicio público de creación/consulta/lectura verificada por propietario e ID, más migrador aditivo en SQLite sintético; no tablas internas como aserciones de resultado. T1 no expone HTTP ni modifica admisión (T3). Ruta delegada por context backstop, no por cantidad de archivos. Forecast T1: aproximadamente 600–900 líneas autoras incluyendo pruebas y manual; estrategia auto-chain, chain_strategy=feature-branch-chain, seleccionada explícitamente por el usuario antes del commit; no autoriza publicar ni tocar main. Sin instalaciones, servicios, entrenamiento real, migraciones existentes o GCS. Pruebas mediante runner original intacto, datos sintéticos, SQLite memoria y red bloqueada; Python host3.14.8 no acredita Docker3.12. Verificación independiente requerida por items2/4.

- L9: Usuario selecciona «Cadena sobre rama de integración — recomendada» (feature-branch-chain): cortes locales en rama feature, sin push/PR/merge. Worker mw1cpf7s-2-e1kn devuelve blocked antes de escribir/RED porque carece de bash_background. Se resuelve en el padre, sin cambiar límites: worker hace ciclos focales finitos con bash timeout<=30s; entrega suite completa pendiente y comando exacto al padre, quien la ejecuta con bash_background y su evento. No autorizar timeout/retry o foreground largo; no instalar herramientas ni repetir exploración.

- L10: Writer mw1crps0-3-mvv9 entrega candidato T1 en seis rutas (740 líneas), focales RED/GREEN descritas en manual; logs crudos focales solo transcript, no archivos exportados (límite de evidencia). Padre lee código/pruebas y ejecuta suite combinada exacta del manual: job-1 exit0, 66PASS16.30s, cero skips/deselecciones, 66SQLite memoria/30protegidos intactos/cleanupPASS/red bloqueada. Ocho hashes de cambios locales/runner/guard/inventario coinciden con baseline paterno. ASSESS nativeRiskunassessable por untracked; escalateitem2 exige independiente. Verifier mw1dc302-4-5q8f en curso, sin aprobación todavía. Sin cambios compartidos de producción: diferencial no aplica. No Docker3.12/PostgreSQL/GPU/GCS/entrenamiento real.

- L11: Independiente mw1dc302-4-5q8f ejecuta4PASS1.36s y no identifica blocker severo de código, pero el test de migración partía con tablas de snapshot ya creadas. Padre corrige solo fixture: dos tablas ausentes, rechazo público antes de migrar y éxito tras migración idempotente. Módulo3PASS0.54s/exit0/3SQLite-memoria/30protegidos/cleanupPASS. Se añade iteración verificada de audio/clase y se encarga al mismo verificador mw1dedld-5-z603 únicamente esa brecha, sin barrido/segundo modelo. Suite66PASS anterior corresponde al candidato antes de corregir fixture; fuente producción intacta. Logs crudos RED/GREEN focales históricos no exportados: no fabricarlos ni repetir RED retrospectivamente.

- L12: Recheck independiente aislado mw1dedld-5-z603 exit1/1FAIL0.67s: DROP de tabla ya ausente, no llegó al migrador. Corrección final de la misma fixture: checkfirst=True en ambos DROP, manteniendo asserts de ausencia; padre ejecuta selector exacto una vez exit0/1PASS0.47s,0deselected/1SQLite-memoria/30protegidos/cleanupPASS. Verifica create rechazado antes de migrar y create/get/iter_verified después. Sin defecto producción ni segundo verificador/barrido. La revisión independiente inicial de seguridad/concurrencia permanece4PASS; no se atribuye al verificador un veredicto global nuevo. Falta disposición humana sobre ausencia de archivos de logs crudos focales históricos, no funcionalidad de migración.

- L13: Usuario selecciona «Accept the documented evidence limitation» (accept-transcript-limitation). Autoriza continuar cierre con logs RED/GREEN focales en transcript y extractos, sin archivos crudos separados; no concede consentimiento nativo ni publicación. Recibo docs/receipts/imported-training-t1-verification.json vincula alcance, suite66PASS previa, independiente4PASS, fallo fixture aislado1FAIL y selector corregido1PASS. Siguiente: normalizar candidato de T1, ASSESS/revisión solo si la continuación nativa la requiere, luego commit local de unidad.

- L14: Commit de unidad T1:36bf33806d4678246c76331b7abede7c2a81e8df,11rutas/1120altas+1baja con diseñoT0 y evidencia incluidos; se conserva unidad coherente pese a heurística400, estrategia feature-branch-chain sin publicación. Cambios frontend y tres enlaces/manuales históricos excluidos. ASSESS del rango comprometido exacto contra dd929cd también unavailable por untracked ajenos; nativeRiskunassessable/escalateitem2high, independiente requerida ya ejecutada. No reviewDue/continuación, no inspect/START/lineage/aprobación nativa ni mutación de autoridad. T1 cerrada solo como base callable por servicio; T2–T7 no iniciadas. Este cierre documental no amplía operaciones autorizadas. Risk: items2y4 (ownership/confinamiento y captura concurrente); límites PostgreSQL/multiproceso/crash siguen explícitos.
- L15: Usuario: «Continua». Autoriza la siguiente tarea anunciada, T2; no T3–T7 ni operaciones reales. Base de la unidad: e1f3a31c0b216f300fd9fbb9f83cbc84832d264e; misma rama feature y estrategia auto-chain/feature-branch-chain. Memoria y archivo reconciliados (solo newline final difiere), Git conserva tres enlaces README, frontend y tres manuales ajenos. Mapeo acotado del contrato preparado delegado a mw1dpozt-6-20np; worker posterior por context backstop, sin delegar varias veces la misma lectura al padre. Forecast T2 aproximadamente 600–1000 líneas autoras con pruebas/manual; no dividir artificialmente ni omitir controles. Reutilizar runner original, SQLite memoria/audio sintético/red bloqueada y Python host3.14.8 sin acreditar Docker3.12. Padre ejecutará suites largas, worker solo focales con timeout<=30s y registros crudos durables desde RED. Perfil efectivo de audio y formato se concretan tras mapa; splits por grupos explícitos y cobertura de clases, sin inferir independencia. Sin fuentes reales, GCS, entrenamiento, servicios o migraciones existentes.
- L16: Mapa mw1dpozt-6-20np confirma que loader/preparación legacy están ligados por nombre/raíces; T2 tendrá módulo/formato independiente sin ampliar ese contrato, y T3 integrará admisión. AudioConfig vigente tiene defaults no neutrales (f_min800Hz), por lo que no se aplican silenciosamente. Pregunta: «How should T2 select the audio profile for an imported dataset?». Usuario selecciona «Require an explicit profile — recommended» (explicit-audio-architecture-profile). Consecuencia mostrada: «The caller supplies audio settings and an existing supported architecture; T2 validates and versions the effective profile. No silent defaults or inference from dataset names.». S9 incorpora esta decisión; no se elige valor universal ni se amplía soporte de arquitecturas. Seam de pruebas T2: crear/seleccionar preparación por propietario/snapshotID y leer manifiesto/particiones/índice por versión desde interfaz pública, con perfiles y grupos explícitos; fuente T1 verificada hasta agotar iteración, formato importado separado, sin jobs/endpoints/UI. Sin aserciones por tablas privadas. No implementación ni RED todavía. Evidencia nueva debe guardar comando/exit/stdout/stderr crudos desde cada RED/GREEN bajo docs/receipts/imported-training-t2-tdd/, no solo transcript.
- L17: Writer mw1dv96j-7-do6w entrega candidato T2 de tres rutas autorales (1073líneas) y 17 tríos crudos TDD. Padre lee módulo/tests/manual, comprueba17JSON/stdout/stderr con RED1/GREEN0, guard/cleanupPASS, y ocho hashes ajenos/protegidos sin cambios. Suite combinada job-2 exit0:138PASS/1deselected24.84s,96SQLite-memoria/30protegidos/cleanupPASS/red bloqueada. Caso CLI test_engine_cli_explicit_fixture deseleccionado por subprocess prohibido; no PASS ni fallo producción. Log crudo docs/receipts/imported-training-t2-combined.log. ASSESS unavailable por untracked/nativeRiskunassessable; escalateitem2 exige independiente. Verifier mw1ejmqx-8-94v6 en curso, no aprobado todavía. Búsqueda200grupos/250000nodos diferencia unavailable de imposible; perfil es contrato estático, ventanas/resampling difieren a T3. Ningún helper compartido modificado, diferencial no aplica.
- L18: Independiente mw1ejmqx-8-94v6 reproduce exit1/7PASS+1FAIL2.48s sin deselecciones: dos creadores iniciales compiten por mkdir de raíz antes del flock, FileExistsError envuelto como SnapshotIntegrityError. Fallo disponibilidad/contrato, sin corrupción observada. Se reabre T2; suite138PASS previa no refuta carrera. Padre autoriza una corrección acotada del helper compartido T1 _root_directory en training_snapshots.py para reabrir el directorio con O_NOFOLLOW tras creación concurrente segura, sin relajar confinamiento; más reproducción determinista por interfaz pública T2 y regresión T1 de creación/raíz insegura. No se editan otras funcionesT1 ni APIs/CLI; no hay comando existente afectado para diferencial CLI. Writer mismo se reanuda solo para esta corrección, logs crudos18+; tras GREEN, recheck del mismo verificador limitado al blocker, sin barrido nuevo/modelo. Sin autorización nueva de operaciones reales.
- L19: Correction writer mw1emvrc-9-6oex partial: helper cambia solo catchFileExistsError+reopenO_NOFOLLOW, RED18exit1/1FAIL0.76s y GREEN19exit0/1PASS0.71s; focal20exit1/1FAIL5.76s BrokenBarrierError de barrera interna, no timeout herramienta ni causa de participante ausente acreditada. Última corrección padre solo fixture: interleaving determinista de ganador mkdir sin barrera, conserva test2hilos. Focal21exit0/6PASS1.73s/0deselected/6SQLiteMem/30protegidos/cleanupPASS, incluye ganadores adversariales y regresionesT1. Suite final job3exit0/141PASS1deselected24.69s/99SQLiteMem/30protegidos/cleanupPASS, logdurable imported-training-t2-final-combined.log. Tríos01–21 auditados, fallos preservados. Recheck mismo independiente mw1euouo-a-9bvm falla a nivelagente assistant reported an error; result no aporta más, sin veredicto/prueba atribuible. No relanzar, cambiar modelo o nuevo barrido. Usuario: «Continua». Se continúa bookkeeping y se devuelve una Needs your decision por falta de cierre independiente: T2 no completada, sin commit. T3–T7 sin iniciar, sin operaciones reales.

- L20: Usuario: «Acepto». Acepta limitación documentada del recheck independiente unavailable para continuar cierre/commit localT2; no aprobación independiente/nativa, ni T3/publicación/operaciones reales. Recibo imported-training-t2-verification.json fija SHA candidato, suitefinal141PASS1deselected, focal6PASS, historial21tríosTDD e independiente inicial7PASS1FAIL corregido. Unidad coherente de preparación+tests+evidencia, supera heurística400 por controles de integridad/perfil/grupos y rawlogs; estrategia feature-branch-chain sin fragmentar artificialmente.

- L21: UnidadT2 commit73526d6f4ab0c52bc9bc7a16d43994155692794a,74archivos/1885altas8bajas incluyendo63archivos crudos/JSONTDD. Cortes feature-branch-chain, base exactae1f3a31 (no acumuladoorigin/main). Stageddiffcheckcompletoexit2 solo whitespaceoriginalpytestlogs, preservados; código/docs excluyéndolosPASSexit0. Ochohashes ajenos/protegidos coinciden. ASSESS de rango comprometido unavailable por untracked ajenos, nativeRiskunassessable/escalateitem2high; sin reviewDue/continuación, no inspect/START/lineage/aprobación nativa. Limitación recheck independiente aceptadaL20, no se relanza. T2cerrada; T3–T7 no iniciadas. Sin publicación/operaciones reales.
