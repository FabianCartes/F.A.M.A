# Operar índices con referencias canónicas por etapa

Cada fila que consume el flujo nuevo declara `file_path` relativo POSIX y
`file_stage` (`raw` o `processed`). El operador configura raíces físicas por
etapa; el lector no busca alternativas por nombre, clase, extensión o enlace.
Esta guía describe el contrato disponible y la preparación de una transición
**futura, con autorización propia**; no acredita migración ni despliegue real.
La decisión está en el [ADR 0019](../adr/0019-referencias-canonicas-por-etapa.md).

## Ruta rápida: preparar, revisar y decidir

1. Identificar explícitamente índice de entrada, etapa y raíces físicas del dataset.
2. Preparar un plan offline: metadata sola **o** el trío completo train/val/test;
   declarar candidatos y snapshots nuevos, con padres físicos ya existentes.
3. Revisar el informe dry-run y comparar campos, orden y membresía con las entradas.
4. Solicitar autorización separada antes de publicar con `--apply`.
5. Planificar después la adopción por los consumidores: publicar candidatos no
   cambia sus bindings ni sustituye índices vivos.

Los ejemplos siguientes usan rutas ficticias `/synthetic/...`; **no ejecutarlos
sobre datos reales**. Tampoco crean directorios ni conceden permiso operativo.

## Fila persistida y raíces declaradas

```csv
nombre_archivo,clase,xc_id,file_path,file_stage
0042.mp3,Chucao,0042,chucao/0042.mp3,raw
```

Mapa ilustrativo, solo declaración (sin imports ni invocaciones):

```python
roots = {
    "raw": "/synthetic/data/raw/AvesChilenas",
    "processed": "/synthetic/data/processed/AvesChilenas/processed_wav",
}
```

| Concepto | Regla |
| --- | --- |
| `file_path` | Texto relativo POSIX no vacío dentro de la raíz de su etapa. |
| `file_stage` | Declaración explícita `raw` o `processed`; un WAV también puede ser raw. |
| Raíz física | Absoluta, canónica y sin symlinks en ningún ancestro; conservar la grafía original, sin pre-resolver aliases. |
| Etiqueta, carpeta, nombre original | `clase`, directorio de almacenamiento y `nombre_archivo` son conceptos distintos; no reconstruyen referencias. |
| Absoluta resuelta | Solo para uso transitorio en memoria, no para persistir en CSV. |

El [núcleo stdlib](../../backend/dataset_references.py) expone
`resolve_reference(file_path, file_stage, roots)` y
`reference_from_path(path, file_stage, roots)`. Rechaza absolutos en la fila,
URI, backslash, traversal, componentes vacíos/`.`/`..`, controles, etapas
inválidas, raíces alias, ancestros symlink, archivos ausentes o no regulares.
Solo verifica la raíz seleccionada; una raíz no utilizada puede estar ausente.
**No verifica contenido acústico, hash ni identidad semántica del dataset**,
ni congela el filesystem frente a carreras. Esas obligaciones son del llamador.

## Productores y consumidores: no confundir interfaces con defaults

El `metadata.csv` raw sigue siendo la fuente única de verdad de los originales.
El [saneador](../../backend/poc/sanitize.py) requiere `metadata_index` y `roots`
en su interfaz `sanitize_dataset(...)`: consume únicamente filas raw canónicas
indexadas, sin enrolar archivos descubiertos. Publica solo derivados verificados
en un índice separado, por defecto `metadata.csv` bajo la raíz processed física
(`processed_wav`). Cambia `file_path`/`file_stage`, preservando nombre original,
hash, hechos acústicos y procedencia. **El hash conservado identifica los bytes
originales, no el WAV derivado**; no se reemplaza por un hash del derivado.

| Entrada inspeccionada | Configuración disponible |
| --- | --- |
| [Localizadores](../../backend/training/paths.py) | `get_dataset_roots(dataset_name)` declara raw y processed/`processed_wav`; no ofrece fallback de audio por existencia. |
| [Descarga](../../backend/poc/download.py) | `run_download_pipeline(..., metadata_index=None)` admite índice explícito; `data_dir` declara raw. CLI: `--raw-dir` (alias `--data-dir`) y `--metadata-index`, con defaults Aves. |
| Saneamiento | CLI: `--raw-dir`, `--output-dir`, `--metadata-index`, `--output-index`; si se omiten, raíces e índice de entrada usan defaults Aves. |
| [PoC train](../../backend/poc/train.py), [evaluate](../../backend/poc/evaluate.py), [benchmark](../../backend/poc/benchmark.py) | Sus interfaces reciben `roots` explícitas; sus CLIs vinculan raíces/índices Aves y no exponen overrides por raíz/índice. |
| [Entrenamiento de aplicación](../../backend/app/services/training.py) | Vincula el dataset admitido a sus raíces configuradas; véase [§5.5](manual_usuario_plataforma.md#55-requisitos-de-la-fuente-local-y-procedencia). |

No extrapolar estos flags a todos los scripts del repositorio. El modo productor
PAM `input_mode='pam_filename'` del [ingestor local](../../backend/training/datasets/local_folder.py)
es explícito y exige coincidencia única; no es fallback legacy de los lectores.
En el pipeline PoC, el trío existente se valida y reutiliza conservando strings,
membresía y orden; un trío parcial falla antes de outputs. Solo si faltan las
tres particiones se generan nuevas desde el índice canónico explícito.
El conversor siguiente **no llama al particionador**.

Saneamiento usa creación exclusiva por archivo, no atomicidad de lote: un fallo
puede dejar derivados huérfanos sin índice. La descarga publica CSV progresivo,
no protegido contra escritores concurrentes, y maneja audio en memoria.
Estas garantías no son los locks/publicaciones atómicas propios del
[flujo de feedback](flujo_revision_audios.md).

## Conversión offline: dry-run por defecto

La interfaz pública del [conversor](../../backend/scripts/convert_dataset_index.py) es:

```python
convert_indices(inputs, candidates, snapshots, *, stage, roots,
                legacy_suffix=None, apply=False)
```

Los tres mapas son `ROLE -> ruta absoluta`, con claves idénticas:
`metadata` sola o `train`, `val` y `test` completos. La CLI repite
`--index ROLE INPUT CANDIDATE SNAPSHOT` y exige `--stage raw|processed`,
`--raw-root ABS` y `--processed-root ABS`. Sin `--apply` devuelve un informe
JSON (`apply`, `indices`, conteos, filas y destinos), **sin escribir**.
No crea padres, temporales ni backups por defecto.

Metadata sola, desde la raíz del repositorio, como ejemplo dry-run:

```bash
python backend/scripts/convert_dataset_index.py \
  --index metadata /synthetic/indices/metadata.csv /synthetic/candidates/metadata.csv /synthetic/snapshots/metadata.csv \
  --stage raw \
  --raw-root /synthetic/data/raw/AvesChilenas \
  --processed-root /synthetic/data/processed/AvesChilenas/processed_wav
```

Trío completo, desde `backend`, ruta de módulo sin instalación:

```bash
python -m scripts.convert_dataset_index \
  --index train /synthetic/indices/train.csv /synthetic/candidates/train.csv /synthetic/snapshots/train.csv \
  --index val /synthetic/indices/val.csv /synthetic/candidates/val.csv /synthetic/snapshots/val.csv \
  --index test /synthetic/indices/test.csv /synthetic/candidates/test.csv /synthetic/snapshots/test.csv \
  --stage processed \
  --raw-root /synthetic/data/raw/AvesChilenas \
  --processed-root /synthetic/data/processed/AvesChilenas/processed_wav
```

### Regla de búsqueda y preservación

- Por defecto, para filas sin columna `file_path`, exige `nombre_archivo` explícito
  como basename seguro y coincidencia física **única** en la raíz seleccionada.
  `xc_id` solo no basta; no inventa filename ni extensión. No prefiere clase,
  slug, grafía o mayúsculas, ni prueba otra raíz o enlaces de compatibilidad.
- Opcionalmente `--legacy-suffix .mp3 .wav` (`legacy_suffix=(".mp3", ".wav")`)
  cambia solo la consulta legacy de nombres terminados en `.mp3`. No cambia
  `nombre_archivo`, hash ni etapa; nunca rescata un `file_path` inválido.
- Una columna `file_path` existente, incluso en blanco, se valida sin reemplazarla.
  Si falta `file_stage`, añade la etapa del operador tras validar la referencia.
  Una etapa existente inválida/en blanco rechaza; las válidas se conservan,
  incluso en filas canónicas de etapas mixtas.
- Añade **solo columnas de referencia ausentes**. Conserva texto original de
  campos, orden de cabecera/filas, cantidad, membresía, ceros iniciales, `NA`
  textual, grupos, grabadores y procedencia. El snapshot conserva bytes exactos
  del CSV de entrada, incluido BOM; el candidato puede diferir en comillas o BOM,
  no en los textos decodificados originales.
- No recalcula hashes, modifica audios ni fuentes, ordena, re-enrola, decodifica,
  reconstruye splits o actualiza pendientes/historial de modelos.

### Publicación y fallos

Entradas, raíces y destinos deben ser absolutos físicos canónicos, sin aliases;
los inputs deben ser archivos regulares, no symlinks. Candidatos/snapshots deben
ser nuevos y distintos, sin colisiones de ancestros, entradas o hardlinks.
No hay overwrite, adopción de existentes, reset ni reescritura idempotente.

**Solo con autorización separada**, añadir `--apply` publica snapshots y
candidatos después del preflight de todas las filas, entradas y destinos del
grupo y de revalidar bytes/referencias. Usa `xb` exclusivo por archivo frente a
competidores tardíos; **no tiene locks, no es inmune a carreras ni atómico como
lote**. Un fallo tras escribir puede dejar snapshots/candidatos parciales propios.
El operador debe inspeccionar entradas, snapshots y salidas bajo su plan y elegir
nuevos destinos explícitos para reintentar: no borrar, adoptar ni sobrescribir
competidores, resetear pendientes o reparticionar para ocultar el fallo.

## Corte operativo y recuperación: decisiones futuras

- [ ] Comparar candidatos contra entradas y snapshots: campos originales, cantidad,
  orden y membresía exactos; comprobar referencias en las raíces aprobadas.
- [ ] Congelar bindings de índices y escritores según el plan del operador antes
  del corte. `--apply` no adopta candidatos ni reescribe índices vivos originales.
- [ ] Preservar originales raw/processed, CSV, modelos/checkpoints,
  `feedback.pending`, `.feedback*`, intenciones y outbox. Los snapshots del
  conversor respaldan **solo CSV de entrada**, no BD, audio ni modelos completos.
- [ ] Definir rollback mediante bindings a entradas preservadas y verificadas,
  únicamente si el código elegido las admite. No prometer que el lector nuevo
  estricto acepte legacy ni ofrecer reescritura automática con pérdida de datos.
- [ ] No depender del enlace legacy aunque permanezca. Su creador no está
  identificado; cualquier retirada requiere inventario y autorización propios.

## Qué demuestra la evidencia disponible

El [tablero](../KANBAN.md) registra 557 pruebas aisladas integradas aprobadas,
con cobertura de dos dominios; no son toda la suite ni prueba de datos operativos,
dependencias desplegadas o aprobación nativa integral. El tablero identifica
cada revisión nativa consumida y su rango exacto: un recibo no cubre otros archivos
ni acredita el conjunto de la feature. Las revisiones/commits restantes y las
operaciones reales siguen separados y pendientes.

[`test_cli_paths.py`](../../backend/tests/test_cli_paths.py), líneas 65–87,
exige metadata/splits Aves, enlace de compatibilidad y ausencia de `data/` raíz
reales. Es histórico/no aislado, quedó fuera de esa suite y no se ejecutó aquí;
no es un test omitido por el runner. Modernizar sus fixtures requiere otro alcance.
El inventario estático de 55 callers de `resolve_reference` incluye pruebas:
no demuestra migración universal. Esta guía se limita a las fuentes enlazadas;
no ejecutó pruebas, conversión, entrenamiento, servicios ni inspección de datos.
