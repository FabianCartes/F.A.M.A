# Catálogo, pesos y arranque del nodo oficial

**Actualización oficial aplicada, 25 de octubre:** `fama_oficial` está en `0004_integration` y la carpeta habitual ejecuta `fix/afinamiento-integral` (`54bdaaf`). Login real, permisos, GCS, datasets, dashboard y catálogo de seis modelos comprobados; cinco hashes históricos completados tras contrastarlos con GCS. Respaldos anterior/posterior restaurados y verificados en laboratorio aislado. Perfil, contraseñas e índices conservados. [Operación y límites](actualizacion_oficial_0004_20261025.md), [recibo](../receipts/actualizacion_oficial_0004_20261025.json).

**Actualización: 24 de octubre de 2026. Rama: `fix/afinamiento-integral`.** El perfil nativo oficial quedó completado y arrancado en `http://localhost:3010`, con PostgreSQL `fama_oficial` y bucket `fama-audio-records-2026`. Inicio de sesión, selección de modelo e inventario comprobados en el navegador; los cortes anteriores permanecen en sus recibos.

## Decisiones y ejecución

El operador confirmó usar el Super-Ensamble de aves como predeterminado y conservar tanto las cinco versiones remotas como las cinco históricas de audios diferentes. Codex publicó los cinco históricos con nombres `_historico_<sha16>.mp3`, precondición de generación cero y descarga posterior con SHA-256 idéntico. Son 149569020 bytes añadidos; no se reemplazó ni borró ningún objeto anterior.

Los 1205 audios indexados se copiaron al runtime oficial y verificaron por SHA-256. Su `metadata.csv` conserva orden y catorce campos originales, incluidos etiquetas, licencias y origen; añade `file_path` y `file_stage` para referencias canónicas. No se añadieron los seis audios locales ajenos al índice histórico. Huella del índice activo: `64f258de5c3b35853c09eb6b3b18c029ed22567f735d1edcd36db6275c8fc768`.

Existe una copia inmutable del índice bajo `dataset_indices/AvesChilenas/sha256/<huella>.csv`. Queda fuera de `datasets/` para que la descarga de audios no lo interprete como otro audio. Los datos completos de grabadores permanecen en los archivos operativos privados, no en este informe.

## Archivos físicos y conjunto de entrenamiento

| Dataset | Audios registrados desde GCS | Bytes | Preparación local |
| --- | ---: | ---: | --- |
| AvesChilenas | 1220 | 5478671962 | 1205 audios del índice histórico verificados |
| engine_diagnostics | 1386 | 185674284 | Disponibles en GCS; sin descarga local masiva |
| MaquinariaMinas | 1 | 220544 | Audio histórico local conservado y copia GCS verificada |

Los 1220 objetos de aves incluyen versiones y copias existentes; el índice de entrenamiento conserva 1205 filas. Registrar un objeto en el catálogo no lo incorpora automáticamente al índice o a una partición de entrenamiento. Se preservaron seis casos con copias remotas de los mismos bytes, sin deduplicación destructiva.

Se registraron `AvesChilenas` y `engine_diagnostics` en SQL con sus objetos físicos, rutas y tamaños observados; el cargador original permanece desconocido. Se completaron hash, frecuencia y duración solamente donde lo acredita el índice verificado. No se crearon asignaciones ni relaciones de entrenamiento de los modelos históricos. El registro previo de `MaquinariaMinas` se conservó sin reinterpretar su procedencia; su audio faltante se publicó en la ruta que ya guardaba SQL y se verificó descargándolo.

## Modelos y predeterminado

La instalación habilita expresamente `chilean-birds-ensemble` mediante `FAMA_ENSEMBLES_JSON`. Una base sin declaración y sin modelos SQL conserva el catálogo vacío. Una activación SQL posterior conserva su prioridad al reiniciar. [ADR 0068](../adr/0068-declaracion-explicita-de-ensambles-por-instalacion.md).

Se desactivaron únicamente los indicadores simultáneos de los cinco modelos heredados, IDs 2–6. Sus filas y pesos permanecen seleccionables. La coincidencia de etiquetas no se convirtió en vínculo de entrenamiento: sus datasets históricos siguen sin relación acreditada.

Los cinco checkpoints históricos cargan: EfficientNet-B0, ConvNeXt-Nano, ResNet34d y dos AudioCNN. Para los AudioCNN antiguos sin arquitectura declarada, el lector reconoce exclusivamente la estructura completa y formas esperadas de los pesos, usando tensores meta y carga estricta. También recupera `val_acc` cuando no hay `best_val_acc`; es una métrica guardada, no una evaluación nueva.

El Super-Ensamble ejecutó una inferencia real sobre un audio indexado de aproximadamente 3–5 segundos. Resultado observado: Zorzal patagónico, confianza 0,884, estado `classified_ensemble`, 3,563 segundos en esta ejecución. No se guardó una predicción SQL por esta comprobación directa. Esto acredita una ejecución, no exactitud general, un benchmark completo ni una nueva evaluación científica. No se encontraron los tres pesos del ensamble de motores; ese predictor sigue pendiente y no se añadió al catálogo inicial.

Los cinco pesos tienen copia por contenido en `operator_backups/checkpoints/sha256/<huella>.pt`, con generación cero al crear y descarga/SHA-256 verificados. Es un respaldo operativo de los archivos; no se añadió una procedencia de dataset falsa para satisfacer la API de copias de modelos. Su recuperación exige usar el manifiesto privado de esta operación y comprobar bytes antes de copiarlos al runtime.

## Historia, cuenta y corte

La historia se trasladó previamente con 41 filas y los siguientes valores de siete secuencias iguales. Antes del arranque se volvió a comprobar el origen: huella `922c811f8d90b01f58212613b2ebd913e43ea28555304af366c7e8b97a0afa64`, sin cambios y cero otros clientes en esa observación. Se compararon de nuevo todas las filas originales contra el destino; la única diferencia entonces era la activación de los modelos autorizada. El origen no quedó bloqueado permanentemente ni se alteró su configuración.

La cuenta histórica es `admin@fama.cl`, ID 1. La cuenta del correo personal del operador pertenecía a pruebas. `app.history_adoption` comprobó servicios, runtime y cuenta existente, registró la adopción y cerró la instalación sin repetir el alta. Después el operador pidió cambiar la contraseña olvidada de esa cuenta; se aplicó con la recuperación local auditada, revocando credenciales previas. No se guarda la contraseña en documentación, recibos o archivos operativos.

Se identificaron y detuvieron los cuatro procesos nativos de pruebas de 8010/3010 antes de iniciar los oficiales mediante `scripts/iniciar_nodo.ps1`. El preview antiguo de 8000 utiliza SQLite aislado y se conservó; no se identificó por error como escritor PostgreSQL histórico. Los demás servicios Docker y los perfiles/buckets de prueba permanecen separados. Los PID son observaciones puntuales, no identificadores permanentes.

Backend oficial: `127.0.0.1:8010/ready` responde 200 y `schema_current`. El proxy web de 3010 informa instalación `completed`. Las referencias privadas siguen usando el proxy oficial en 5434 y la identidad técnica oficial.

## Validación y pendientes

TDD de la declaración: primero falló la persistencia de la clave, después su validación y finalmente el catálogo real con ensamble no declarado. Selección inicial: **40 PASS / cinco deseleccionados / tres archivos** (configuración, reinicio con SQLite/pesos reales y catálogo HTTP). La selección final, tras corregir el recuento global, dio **66 PASS / cinco deseleccionados / siete archivos**, incluyendo ingesta, AudioCNN y pooling. Los cinco casos excluidos requieren privilegio de symlink Windows; no se presentan como aprobados. La discrepancia previa del catálogo vacío quedó resuelta y su prueba pasa. Las seis pruebas AudioCNN y catorce de pooling ya habían pasado en el corte anterior; no se sustituyen por pruebas globales.

Las predicciones históricas con nombre simple no se convierten en fuentes administradas `raw_audios/<uuid>.wav` por adivinar su nombre. Se conservan como historia, con las limitaciones de procedencia y reproducción que corresponden. Tampoco se convierten las correcciones históricas en permisos nuevos.

Quedan las condiciones del servidor universitario (sistema, dominio/HTTPS, recursos y acceso a GCP), respaldo SQL externo con destino/retención acordados y los pesos industriales faltantes. El entorno oficial inicial funciona en este PC y no expone puertos a otros equipos. El proceso nativo usa servidor de desarrollo frontend; el despliegue institucional requiere preparar su arranque de servicio.

[Recibo del corte previo](../receipts/traslado_historia_confirmado_y_pesos_20261024.json), [recibo de publicación y arranque](../receipts/catalogo_oficial_publicado_20261024.json), [preparación general](preparacion_entorno_oficial.md), [traslado/adopción](traslado_historia_y_adopcion.md).

## Cierre de la comprobación local

El navegador inició sesión correctamente con la cuenta recuperada, mostró el Super-Ensamble como selección inicial y los cinco modelos individuales. Gestión de audios mostró tres datasets y el bucket oficial. AvesChilenas presenta 1205 archivos locales y 1220 remotos; motores figura solo en GCS. Se conservan los avisos de contenido sin comparar: un contador igual por sí solo no prueba una sincronización física.

Durante esta revisión se detectó un límite de 2000 objetos en la cabecera del bucket. Una prueba con 2003 objetos reprodujo el fallo antes de cambiar producción. El cálculo ahora consume el iterador paginado completo sin almacenar todas las referencias en memoria; el navegador confirmó 2646 objetos y 5,82 GiB aproximados, incluidos índices, fuentes históricas y copias de pesos. Solo se reinició el backend oficial para activarlo; la sesión y el frontend permanecieron disponibles.

El respaldo final local de inicio, `backend/installation/cloud-oficial/backups/oficial-inicio-20261024/`, contiene 161105 bytes, SHA-256 `1bcc6c9c2593d09dffc27c77dce4980fb27ad8eb8d05e510710edf58f6f50818`. Se restauró mediante el módulo público en PostgreSQL 16 desechable: 17 tablas, nueve secuencias, huellas completas y `0003_autonomy` coincidentes. Incluye 2607 audios, tres datasets, cinco modelos, 31 predicciones históricas, cuenta recuperada y eventos de adopción/recuperación/login. La primera llamada del ensayo omitió argumentos del módulo; no ejecutó restauración y retiró su laboratorio. El segundo ensayo usó la interfaz correcta y verificó el respaldo. Ambos contenedores propios fueron retirados; los cuatro anteriores conservaron identidad y estado.

[Evidencia del bucket](../images/catalogo_oficial_20261024.png), [inventario visible](../images/datasets_oficiales_20261024.png).
