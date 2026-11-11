# Preparación local de datasets importados (T2)

**Estado vigente — MVP d:** se retiró la entrada de entrenamiento por snapshots/preparaciones importadas. Las rutas `/api/training/imported/*` ya no están registradas; `imported_dataset_id`, `snapshot_id` e `imported_prepared_version` se rechazan al iniciar, incluso con `null`, sin entrenar el dataset predeterminado. Para trabajos nuevos use el ZIP publicado y `dataset_name` + `partition_version` del [flujo vigente](entrenamiento-datasets-importados.md).

**Los artefactos existentes se retienen:** `ImportedDatasetPreparation`, sus CSV/manifiestos, snapshots y asociaciones siguen siendo necesarios para leer y evaluar modelos importados históricos y revisar sus pesos. No se eliminan tablas, filas ni archivos. Los ejemplos de creación y resultados siguientes son documentación histórica de T2, no instrucciones para restaurar la entrada retirada ni autorización para operaciones reales.

## Alcance y estado históricos

Módulo callable independiente: `backend/training/imported_dataset_preparation.py`.
Implementa T2 del [plan](../arquitectura/entrenamiento-datasets-importados-plan.md)
y el contrato del [ADR 0071](../adr/0071-preparacion-local-de-datasets-importados.md).
No modifica ZIP, admisión, catálogo, loaders legacy, UI, base de datos ni entrenamiento.
T3 deberá integrar un consumidor de este formato; **estos CSV no son compatibles
por sí solos con `load_prepared_dataset`**. Preparar no inicia un job ni acredita
calidad, evaluación, publicación de un modelo o disponibilidad para inferencia.

## Interfaz pública

La aplicación configura una instancia real de `TrainingSnapshots` (T1) y una raíz
privada durable del servidor; ninguna ruta procede del cliente:

```python
preparations = ImportedDatasetPreparation(snapshots, server_prepared_root)
ready = preparations.create(
    owner_id, snapshot_id,
    mapping=[{"member_id": member_id, "recording_id": recording_id, "group_id": group_id}],
    provenance={"source": "anotaciones revisadas versión 1"},
    seed=42,
    profile=explicit_profile,
)
selected = preparations.get(owner_id, snapshot_id, ready["version_id"],
                            expected_profile=explicit_profile)
rows = preparations.read_split(owner_id, snapshot_id, ready["version_id"], "train")
```

El ejemplo de mapa ilustra una fila: debe contener **exactamente toda la membresía**
del snapshot, sin miembros faltantes, adicionales ni duplicados. Se usa una lista
para poder detectar duplicados. Cada fila exige los tres campos, strings no vacíos
sin controles y de hasta 512 caracteres. Una grabación puede tener varios miembros,
pero todos deben declarar el mismo grupo; un grupo puede abarcar varias clases.
`provenance` es un objeto JSON de hasta 64 KiB con `source` no vacío; se conserva
completo. No certifica que las anotaciones sean verdaderas. Ni hash ni filename
establecen independencia. `seed` es uint32 estricto (no bool).

`create` devuelve el descriptor persistido después de publicarlo y verificarlo.
`get` selecciona la versión exacta y comprueba autorización T1, hash de su manifiesto,
identidad del snapshot/propietario y hashes de los tres CSV. `expected_profile`
permite exigir compatibilidad exacta; `read_split` repite la comprobación del CSV
sobre los mismos bytes que entrega. Los campos CSV se devuelven como strings.
No hay selección de «última versión», regeneración automática ni bypass histórico.
Una identidad ajena (incluido propietario `-1`) obtiene el 404 de T1 sin revelar datos.

## Perfil explícito y audio original

Un perfil completo válido de ejemplo —no un default recomendado para todo dominio—:

```python
explicit_profile = {
    "architecture": "audio_cnn", "channels": 1, "preprocessing": "mono_mel",
    "windowing": "energy_peak_pad", "window_hop_seconds": 0.5,
    "audio": {
        "target_sr": 8000, "duration_seconds": 1.0, "n_mels": 32,
        "n_fft": 256, "hop_length": 64, "f_min": 0.0, "f_max": 4000.0,
        "use_gpu_frontend": False,
    },
}
```

Se exigen todos los campos de `AudioConfig`, además de los campos externos mostrados;
no se rellenan valores omitidos ni se infiere dominio por nombre. `f_max=None`
explícito se normaliza a Nyquist numérico. Se validan tipos, finitud, frecuencia
objetivo 1–384 kHz, duración positiva, FFT potencia de dos hasta 65536, salto FFT,
bandas Mel, `0 <= f_min < f_max <= Nyquist`, y cantidad de muestras entre FFT y
10 millones. El hop temporal debe producir al menos una muestra y no superar
la duración. El esquema actual admite solo salida mono/Mel y ventana
`energy_peak_pad`: mezcla mono, resampling, padding con ceros si falta duración,
o selección determinista de máxima energía (incluida cola) con el hop explícito.
**Esa transformación queda diferida al futuro consumidor T3; T2 no la ejecuta.**

Arquitecturas canónicas reconocidas: `audio_cnn`, `panns_cnn14`, `efficientnet_b0`,
`convnext_nano`, `resnet34d`. Se exige al menos 32 bandas/frames espectrales; PANNs
requiere 64 por sus seis etapas de pooling. Esto valida el contrato estático del
perfil, no ejecuta un modelo ni demuestra compatibilidad del futuro adaptador,
pesos preentrenados, GPU o rendimiento. No se aceptan aliases, HPSS ni canales de
entrada alternativos en esta primera preparación.

Se agota `iter_verified` de T1 antes de publicar, incluso si falla tras el último
chunk. Cada WAV se procesa por chunks de hasta 1 MiB, con spool de hasta 1 MiB en
memoria y derrame temporal privado; nunca se conserva todo el audio de la colección
en RAM. Se leen todos los frames PCM para detectar truncamiento. Se admite WAV PCM
entero sin compresión, 8/16/24/32 bits, 1–8 canales originales, tasa 1–384000 Hz y
al menos un frame; float/comprimido no está soportado aquí. Los originales pueden
ser estéreo y tener otra tasa: permanecen idénticos en T1 y en el importador.
La preparación guarda únicamente referencias, sin audio transformado ni aumento.

## Distribución e identidad

`group-cover-v1` separa grupos completos **antes** de ventanas/aumento. Busca
cobertura de todas las clases en train/val/test mediante búsqueda exacta,
determinista y acotada a 250000 nodos/200 grupos. Un grupo mixto nunca se divide.
Menos de tres grupos por clase prueba imposibilidad; tres o más no garantizan
factibilidad conjunta. Si se agota el árbol se informa imposibilidad demostrada;
si se agota el presupuesto se informa **factibilidad no determinada**, nunca
«imposible». Los grupos restantes se asignan hacia objetivo 80/10/10 por grupos,
subordinado a cobertura: no se promete el óptimo ni proporciones exactas.

Menos de diez grupos independientes declarados por clase produce advertencia
`low_independent_groups` con clase/conteo/referencia 10. No bloquea: el caso de tres
grupos mixtos válidos prepara 1/1/1 por clase. No es garantía estadística.

Cada directorio `<raíz>/<version_id>/` contiene `manifest.json`, `train.csv`,
`val.csv`, `test.csv`. El SHA256 de JSON canónico (sin su propio `version_id`) fija
schema 1/formato importado, propietario, snapshot y hash de manifiesto T1, mapa y
procedencia completos, semilla, perfil efectivo, política, clases ordenadas por
nombre con índice estable, advertencias, cantidad y hashes de CSV. Los CSV fijan
snapshot/member ID, clase/índice, grabación/grupo, import de origen, nombre de objeto,
rutas original/relativa, hash y tamaño. Son referencias estables, **no rutas a abrir
sin T1**. Cambiar un input relevante crea otra versión; reordenar el mapa no cambia
identidad. Re-seleccionar una versión anterior no modifica sus bytes.

## Fallos, confinamiento y rollback

`PreparationError` expone `state="failed"`, `code` y mensaje accionable:
`invalid_mapping`, `invalid_seed`, `invalid_profile`, `invalid_audio`,
`invalid_metadata`, `source_unavailable`, `split_impossible`,
`split_search_unavailable`, `budget_exceeded`, `publication_busy`,
`invalid_identity`, `artifact_unavailable`, `profile_mismatch`, `invalid_split`.
No es un estado ready ni un job fallido en DB. El 404 de T1 conserva su tipo;
fallos operativos de filesystem y raíces inseguras pueden propagar `OSError` o
`SnapshotIntegrityError`: el llamador debe informar fallo, nunca éxito.
Etiquetas vacías, controles, separadores y reservadas `.`, `..`, `__unknown__`,
`__unlabeled__` son inválidas; las referencias deben ser relativas contenidas WAV.

Presupuestos v1: 20000 miembros, 16 GiB por snapshot, 512 MiB por miembro, manifiesto
16 MiB, cada CSV 32 MiB y reserva libre de 1 MiB para índices. El mapa y los índices
son metadata acotada en memoria. No se instala un solver ni dependencia nueva.
La búsqueda acotada puede no resolver una colección válida: se informa esa limitación.

Se reutilizan las aperturas T1 con descriptores y `O_NOFOLLOW` en todos los ancestros;
raíz privada 0700, archivos nuevos 0400 y staging exclusivo. Se sincronizan archivos
y directorio, y un rename publica solo el conjunto completo. `flock` Linux no
bloqueante sobre la raíz serializa publicación entre escritores cooperantes;
una colisión concurrente puede dar `publication_busy`, sin espera/reintento implícito.
Cualquier entrada preexistente se conserva, incluso directorio vacío o symlink:
solo se re-selecciona si su integridad es válida. No hay overwrite ni GC.
Solo se limpia staging propio de un intento fallido; staging ajeno se preserva.
Una caída tras rename puede dejar una versión completa, o staging huérfano antes;
no se promete transacción con DB, recuperación de crash ni borrado automático.
`get` comprueba el manifiesto T1, **no relee todo su audio**: T3 deberá consumir
T1 verificado otra vez, no interpretar el descriptor como garantía eterna de bytes.
El confinamiento no protege contra un administrador que controle filesystem/proceso.

## Evidencia reproducible y pendientes

Host Python 3.14.8, SQLite en memoria, WAV sintéticos, red bloqueada, scratch/cachés
privados, runner/guard/inventario originales sin editar. No acredita Docker 3.12,
PostgreSQL, entrenamiento real, calidad ML, GPU ni datos existentes.
Cada ejecución tiene JSON con comando exacto/exit y stdout/stderr crudos separados
en [`imported-training-t2-tdd/`](../receipts/imported-training-t2-tdd/).

| Evidencia | RED observado (exit 1) | GREEN observado (exit 0) |
| --- | --- | --- |
| 01/02: creación/selección | módulo ausente, 1 FAIL | 1 PASS, 0.54 s |
| 03/04: mapa exacto | KeyError ante miembro faltante, 1 FAIL | 6 PASS, 1.77 s |
| 05/06: perfil | perfil omitido aceptado, 1 FAIL | 20 PASS, 4.69 s |
| 07/08: WAV | audio ilegible aceptado, 1 FAIL | 3 PASS, 1.16 s |
| 09/10: semilla | bool aceptado, 1 FAIL | 5 PASS, 1.38 s |
| 11/12: retención | directorio vacío sobrescrito, 1 FAIL | 1 PASS, 0.67 s |
| 16/17: limpieza ante fallo de apertura | staging propio residual, 1 FAIL | 4 PASS, 1.28 s |

Triangulación 13: 16 PASS/3.75 s; 14: 15 PASS/3.67 s (exit 0). Incluye imposibilidad
conjunta con tres grupos/clase, fuente corrupta/ausente/symlink, fallo tardío T1,
ownership, traversal, perfiles/versiones previas, disco/rename/lock, concurrentes,
80/10/10 factible, arquitecturas alternativas y WAV multichunk estéreo a otra tasa.
No se inventaron RED para comportamientos ya cubiertos por la implementación.
Triangulación 15: 2 PASS/2.40 s (exit 0), reselección tras los cambios y límite de
201 grupos con factibilidad no determinada. La autorrevisión detectó la brecha de
limpieza entre mkdir y open; el ciclo 16/17 la corrigió sin ampliar superficies.
En total se ejercitaron los 69 casos nuevos mediante focales, en revisiones sucesivas;
esto no equivale a ejecutar la suite combinada sobre el candidato final.
Todos estos stderr están vacíos; cero skips/deselecciones; runner confirma limpieza,
SQLite memoria, red bloqueada y hashes de sus 30 rutas protegidas.

**Suite combinada ejecutada por el padre** mediante `bash_background`, job-2: **exit 0, 138 passed, 1 deselected in 24.84s**. La deselección corresponde exactamente al caso CLI indicado abajo y no cuenta como PASS. Runner: 96 conexiones SQLite memoria, red bloqueada, 30 rutas protegidas intactas y limpieza del scratch PASS. El diagnóstico argparse de destino existente observado en la salida pertenece a una prueba negativa esperada del legacy, no a un fallo de suite. Log crudo combinado stdout/stderr: [T2 combined](../receipts/imported-training-t2-combined.log).

Comando exacto, desde `backend/`:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHON_DOTENV_DISABLED=1 DATABASE_URL=sqlite:// CUDA_VISIBLE_DEVICES='' PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 /workspace/fama/.venv/bin/python tests/run_isolated_training_checks.py tests/test_imported_dataset_preparation.py tests/test_dataset_preparation.py tests/test_training_snapshots.py -k 'not test_engine_cli_explicit_fixture'
```

Se rechaza expresamente `test_dataset_preparation.py::test_engine_cli_explicit_fixture`
para este runner: lanza subprocesses, prohibidos por la guarda. La deselección
esperada es una, no cuenta como PASS; no se sustituye con un mock de éxito.
El resto de fixtures revisadas usa filesystem privado y SQLite memoria; no se
requieren artefactos históricos ni servicios. El padre comprobó además los 17 tríos
JSON/stdout/stderr, exits RED/GREEN y pruebas de guarda/cleanup, y ocho hashes de
rutas locales/runner/guard/inventario preservadas. Verificación independiente de
riesgos 2/4 ejecutada: **exit 1, 7 passed, 1 failed in 2.48s**, cero deselecciones. El fallo público de creadores concurrentes reproduce una carrera de `mkdir` de la raíz antes del flock: `FileExistsError` se convierte en `SnapshotIntegrityError`. Es fallo de disponibilidad/contrato, no corrupción observada. La suite combinada anterior aprobada no descarta una carrera intermitente. T2 está reabierta para una corrección acotada, con reproducción determinista y recheck del mismo verificador; sin nuevo barrido ni cierre todavía. Plan/índices/commits son del padre.

### Intento acotado de corrección de creación concurrente de raíz

El padre autorizó modificar únicamente `_root_directory` del servicio T1: ahora
se tolera solo `FileExistsError` de mkdir y se reabre con
`O_DIRECTORY|O_NOFOLLOW`, conservando la comprobación final de permisos privados.
No cambia el protocolo de publicación. Se añadieron pruebas públicas T2 con
sincronización en mkdir y con un ganador adversarial symlink/no privado;
estas últimas **aún no tienen ejecución observada**.

Evidencia nueva, sin reemplazar 01–17:

- 18-red: selector de dos creadores con raíz ausente, exit1/1 FAIL/0.76 s;
  `FileExistsError` envuelto en `SnapshotIntegrityError`.
- 19-green: el mismo selector después del cambio, exit0/1 PASS/0.71 s.
- 20-focused: exit1/1 FAIL/5.76 s. El mismo test falló con `BrokenBarrierError`
  al expirar su barrera interna de 5 s; no se estableció la causa de que faltara
  el segundo participante. El runner paró antes de las pruebas adversariales,
  el concurrente original y las dos regresiones T1 seleccionadas. **No están
  aprobadas por esta ejecución.** No se repitió ni amplió el timeout.

Los tres comandos/resultados y stdout/stderr crudos están en los tríos numerados;
stderr vacío, cero deselecciones y guardas/30 hashes/limpieza aprobados en los tres.
El padre sustituyó únicamente la barrera dependiente de scheduling por un interleaving determinista en la llamada de filesystem: otro creador crea el directorio antes del segundo mkdir real, que devuelve FileExistsError. El test público comprueba creación, reselección e integridad; se conserva además el test original de dos hilos. No se atribuye una causa no acreditada al segundo participante ausente del intento 20.

- 21-focused: **exit 0, 6 passed in 1.73s**, stderr vacío, cero deselecciones, seis conexiones SQLite memoria, 30 rutas protegidas intactas y cleanup PASS. Incluye el caso determinista, el test original de dos hilos, ambos ganadores adversariales y las dos regresiones T1. Sus resultados reemplazan el pendiente de ejecución de los casos adversariales, no borran el fallo 20.
- Suite final poscorrección job-3: **exit 0, 141 passed, 1 deselected in 24.69s**; 99 conexiones SQLite memoria, 30 rutas protegidas intactas y cleanup PASS. Mismo comando combinado anterior y misma exclusión CLI explícita. [Log final](../receipts/imported-training-t2-final-combined.log). La suite 138 PASS anterior corresponde al código previo al fix.
- Recheck independiente limitado del mismo verificador, tarea `mw1euouo-a-9bvm`: **unavailable**, error del agente `assistant reported an error`; consulta de resultado no recuperó más evidencia. No hay nuevo veredicto independiente ni resultado de tests atribuible a ese recheck. No se relanza, no se cambia de modelo y no se interpreta el fallo del agente como defecto de código ni aprobación.

**Disposición:** se continúa con el cierre y el commit local con la limitación del recheck independiente documentada. T2 se cierra como módulo callable probado en estado sintético; no como aprobación independiente posterior al fix ni como review nativa. No se inicia más verificación, T3 ni operaciones reales por este cierre. Evidencia consolidada: [recibo T2](../receipts/imported-training-t2-verification.json). Commit de unidad: `73526d6f4ab0c52bc9bc7a16d43994155692794a`.

ASSESS del rango comprometido exacto contra `e1f3a31c0b216f300fd9fbb9f83cbc84832d264e` quedó unavailable por archivos no rastreados ajenos; nativeRisk unassessable, escalación item2high y sin `reviewDue` ni continuación de revisión. No se inició review ni hubo aprobación nativa. El `diff --cached --check` completo devolvió exit2 por espacios finales originales en logs crudos de pytest; se conservaron sin alteración. La comprobación de código/documentación excluyendo esos logs aprobó con exit0. Ocho rutas ajenas/protegidas coinciden con baseline.
