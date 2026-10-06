# ADR 0019: Referencias canónicas por etapa con raíces físicas declaradas

* **Estado:** Aceptado; contrato compartido implementado en CANON-1, migración pendiente
* **Área:** Índices de datasets, productores y lectores locales

Cada fila persistida debe incluir `file_path` relativo POSIX y `file_stage` obligatorio (`raw` o `processed`). El lector recibe las raíces físicas explícitas y valida la referencia sin reconstruir candidatos. Esta decisión conserva raw como fuente única de originales y processed como almacenamiento de derivados; no convierte índices históricos ni activa consumidores automáticamente.

## Contexto y alternativas

Feedback rechaza enlaces simbólicos en todos los ancestros de raw, mientras la admisión de entrenamiento todavía admite candidatos Aves reconstruidos por nombre, slug e identificador y llega a derivados mediante `raw/.../processed_wav`. Una ruta relativa sin etapa no identifica de forma inequívoca su raíz; un WAV también puede ser un original o una incorporación de feedback.

| Alternativa | Decisión y motivo |
| --- | --- |
| Inferir etapa por extensión, directorio o tanteo de archivos existentes | Descartada: mezcla originales y derivados y permite que una referencia explícita inválida caiga a otro archivo. |
| Persistir rutas absolutas | Descartada: vincula el índice al host o contenedor. Las absolutas solo se admiten como resultado en memoria o entrada del productor. |
| Añadir catálogo JSON o tabla de raíces por fila | Descartada: duplica configuración e identidad sin necesidad. La columna `file_stage` acompaña a `file_path` al copiar o dividir filas. |
| Columna de etapa y mapa explícito del llamador | Elegida: una interfaz pequeña concentra la validación para feedback y entrenamiento sin dependencias ML, BD o cloud. |

## Contrato e interfaz

El módulo [dataset_references.py](../../backend/dataset_references.py) expone dos funciones:

```python
resolve_reference(file_path: str, file_stage: str,
                  roots: Mapping[str, str | Path]) -> Path
reference_from_path(path: str | Path, file_stage: str,
                    roots: Mapping[str, str | Path]) -> dict[str, str]
```

El mapa es por dataset y por etapa. La raíz raw corresponde a `backend/data/raw/{dataset}`; para WAV saneados, processed corresponde a `backend/data/processed/{dataset}/processed_wav`, no al enlace de compatibilidad bajo raw. Otros productores declaran su raíz física de derivados; el resolver no descubre directorios ni adivina el mapa. Los localizadores de `training.paths` orientan esta configuración, pero sus llamadas actuales a `resolve()` no sustituyen la verificación de ancestros de la ruta original: el llamador no debe borrar evidencia de enlaces antes de pasarla al contrato.

Ejemplo ilustrativo (requiere archivos existentes; no es una operación de migración):

```python
from pathlib import Path
from dataset_references import reference_from_path, resolve_reference

roots = {"raw": Path("/app/data/raw/AvesChilenas"),
         "processed": Path("/app/data/processed/AvesChilenas/processed_wav")}
original = resolve_reference("chucao/42.mp3", "raw", roots)
feedback = resolve_reference("Chucao/feedback_6.wav", "raw", roots)
derivado = resolve_reference("chucao/42.wav", "processed", roots)
fields = reference_from_path(derivado, "processed", roots)
# Persistir fields: {"file_path": "chucao/42.wav", "file_stage": "processed"}.
# No persistir original, feedback ni derivado: son Path absolutos en memoria.
```

- `file_path` debe ser texto no vacío, relativo y sin normalizaciones pendientes. Se rechazan absolutos, unidades Windows, URI, backslash, dos puntos, controles Unicode Cc, componentes `.`/`..`/vacíos y separadores innecesarios. No se corrige silenciosamente una fila inválida.
- `file_stage` no tiene valor por defecto, aliases ni etapa desconocida diferida. Solo se verifica la raíz de la etapa solicitada; puede suministrarse un mapa parcial, pero esa etapa debe estar declarada.
- La raíz debe ser absoluta, canónica, existente y un directorio físico. Tanto raíz como candidato y todos sus ancestros se inspeccionan antes de resolver: ningún symlink es válido, tampoco interno, colgante o de compatibilidad. No se aceptan escapes ni destinos ausentes/no regulares.
- Los errores de campos, configuración y acceso físico son `ValueError` con mensajes sanitizados, traducibles por wrappers HTTP. No se exponen valores de entrada ni errores del sistema. El módulo no escribe archivos ni usa red.
- El productor puede descubrir archivos durante una importación legítima, pero luego debe declarar etapa y raíz y emitir la fila explícita. La conversión exige un archivo existente bajo esa raíz; no sirve para reservar una ruta futura.

## Responsabilidades y consecuencias

Extensiones permitidas, contenido no vacío, códec, hash, etiquetas, `source_group`, identidad outbox y reglas de incorporación siguen en productores/consumidores. Entrenamiento ya comprueba extensión y tamaño; feedback valida frames WAV e integridad. El módulo verifica referencias físicas, no contenido acústico: un archivo regular vacío o de otra extensión puede resolver y debe ser rechazado por el llamador cuando corresponda. Incorporación de feedback continúa siendo únicamente raw.

La etapa es una declaración, no una prueba deducida del archivo. El llamador es responsable de asignar correctamente raíces e identidad del dataset: el módulo no puede detectar un mapa físicamente válido pero semánticamente equivocado. Tampoco garantiza snapshot inmutable o ausencia de carreras entre validación y lectura; locks, publicación durable y revalidación de bytes siguen a cargo del flujo existente. No deben pasarse rutas previamente normalizadas/resueltas que oculten alias.

Al migrar consumidores, esta decisión sustituye la inferencia legacy de Aves asociada a la admisión de [ADR 0016](0016-procedencia-y-persistencia-entrenamiento.md) y la dependencia de lectura del enlace de compatibilidad de [ADR 0012](0012_unificacion_fuente_datos_raw.md). No sustituye sus invariantes de procedencia, persistencia o SSOT. El enlace histórico puede permanecer en disco, pero el flujo nuevo no debe utilizarlo.

## Alcance implementado y continuación

CANON-1 incorpora módulo, [pruebas públicas aisladas](../../backend/tests/test_dataset_references.py) e índice documental. Productores/base `AudioRecordingMetadata` (CANON-2), entrenamiento/mezcla/ingesta (CANON-3), feedback (CANON-4), conversión offline (CANON-5) y retirada integrada de dependencias legacy (CANON-6) siguen pendientes en el [tablero](../KANBAN.md). Los lectores actuales no han cambiado y los índices históricos todavía pueden carecer de etapa; no se declara resuelto el error real ni completado el flujo integral.

No se autoriza conversión real, reset, escritura BD/GCS, eliminación de enlaces, despliegue ni operación de servicios. El rollback de CANON-1 comprende solo módulo, pruebas, este ADR y su entrada/contador del índice documental; no revierte datos ni los cambios previos de feedback, Predicción o tablero.
