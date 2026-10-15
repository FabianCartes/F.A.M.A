# Recuperación del modelo 14 y retirada de modelos legacy

El 15 de octubre de 2026 se recuperó `fama_trained_model_14` y se eliminaron los
modelos 11, 12 y 13 con sus dependencias operativas exclusivas. El catálogo servido
por el frontend contiene únicamente el modelo 14, predeterminado, sin errores de
publicación; la vista de Predicción y una inferencia HTTP real fueron verificadas.

## Causa y corrección

Antes del cambio se comparó el runtime desplegado con los informes 5/6 del modelo
14: las únicas diferencias eran `implementation_sha256` y `model_loader_sha256`.
El checkpoint tenía el SHA y tamaño registrados correctos. No había diferencias
de parámetros de preprocesamiento ni de agregación.

El [ADR 0025](../adr/0025-compatibilidad-semantica-evaluacion.md) separa compatibilidad
semántica y huellas del código. Se reconstruyó la imagen del backend y se recreó
su contenedor; el SHA del guard desplegado coincide con el checkout. No se
reentrenó ni se modificó el checkpoint para recuperar disponibilidad.

## Reevaluación real

Se ejecutaron primero el preflight y después la [reevaluación explícita](reevaluacion-modelos.md)
con los siguientes argumentos, más una URL PostgreSQL explícita obtenida del entorno
del contenedor y normalizada sin imprimir credenciales:

```text
--model-id 14
--checkpoint-root /app/checkpoints
--checkpoint /app/checkpoints/fama_052049cd64b34997911b93eab0f7eef3_best.pt
--expected-sha256 d6ede3c7f343d8a2945209bd13d3fcbc0b497a2863dcd7e8afee18c0be7cbc4d
--prepared-dir /app/data/prepared/AvesChilenas
--dataset AvesChilenas
--root raw=/app/data/raw/AvesChilenas
--root processed=/app/data/processed/AvesChilenas/processed_wav
```

Solo la segunda ejecución añadió `--execute`. El runtime fue Python 3.12.15,
PyTorch 2.14.1+cu130 y CUDA en RTX 2050. Nuevos intentos: **7 val / 8 test**, ambos
completados bajo `gpu-audio-frontend-v2`; informes 5/6 conservados. El estado
`standard_eval_completed` y la selección activa de 14 permanecieron intactos.

| Split | Muestras | Accuracy | F1 macro | Rechazos |
| --- | ---: | ---: | ---: | ---: |
| Validación | 177 | 44,63 % | 47,56 % | 31 |
| Test | 181 | 44,75 % | 50,28 % | 63 |

Los reportes completos nuevos coinciden con los anteriores en métricas, matriz y
rechazos. La reparación restaura disponibilidad, no mejora calidad. Persisten
diagnósticos MPEG de algunos audios de origen; ambas evaluaciones finalizaron.
No se modificaron audios ni particiones para silenciarlos.

## Retirada autorizada de 11, 12 y 13

Se verificaron IDs, hashes, inactividad, claves foráneas, ausencia de archivos
compartidos con otros modelos y referencias de audio antes de aplicar la limpieza.
Se usó una transacción PostgreSQL con bloqueo de las tablas afectadas y
eliminaciones cloud por clave exacta y generación, sin borrar prefijos completos.

| Elementos eliminados | Cantidad |
| --- | ---: |
| Modelos | 3 |
| Evaluaciones | 4 |
| Métricas por época | 30 |
| Predicciones | 20 |
| Retroalimentaciones | 11 |
| Estados de sincronización | 3 |
| Checkpoints locales | 2 |
| Objetos GCS `raw_audios/` exclusivos | 20 |

El checkpoint de 13 ya estaba ausente. Tampoco existían objetos GCS en las tres
rutas `models/` registradas. Se verificó la ausencia de las filas y archivos
objetivo y de los objetos cloud actuales después de completar la operación. La
transacción DB no proporciona atomicidad distribuida con filesystem/GCS.

El dataset compartido `AvesChilenas`, sus filas `audio`, manifiestos y grabaciones
incorporadas —incluidas `feedback_9.wav`, `feedback_10.wav` y `feedback_13.wav`— se
conservaron: son recursos del dataset, no pesos exclusivos de los modelos retirados.
Los documentos y recibos históricos siguen describiendo sus ejecuciones originales.

## Verificación ejecutada

- TDD: la publicación falló al introducir un wrapper equivalente; después de la
  corrección pasan los casos de refactors y el rechazo de contratos incompatibles.
- Runner aislado: **240 aprobadas, 1 deseleccionada, 2 advertencias FFT** tanto en
  Python 3.14 del host como en Python 3.12 de la imagen. Suite: registro, catálogo
  HTTP, flujo, persistencia y reevaluación. SQLite en memoria, CPU sintética y red
  bloqueada. No se ejecutó la suite global.
- El wrapper de imports subprocess se deseleccionó; su payload original se verificó
  separadamente con `--ambient-import-probe`, exitoso en ambos intérpretes.
- En Python 3.12, el primer intento directo fue bloqueado antes de los tests porque
  `cuda.pathfinder` consulta `ldconfig` durante el import de PyTorch. La ejecución
  válida precargó únicamente `torch` antes de instalar la guarda original; no se
  ampliaron sus permisos. También se aplicó esa precarga al probe de imports.
- Preflight de publicación con audio real: `smoke_passed`, forward de red y SHA
  cargado esperado, sin escrituras de predicción.
- HTTP mediante `frontend:3000/api/predict`: `classified`, CUDA, `is_mock=false`,
  SHA cargado esperado, subida GCS y persistencia PostgreSQL confirmadas (ID 45).
- Chromium headless real: 14 como única opción seleccionable, pesos publicados,
  par admitido visible y mensaje de bloqueo ausente. No se hizo la carga de audio
  mediante la interfaz del navegador; la inferencia se comprobó por HTTP.
- Reinicio adicional del backend: catálogo del frontend sigue con total 1,
  default 14 y `publication_errors=[]`; los modelos antiguos no reaparecen.

Comando de las pruebas Python 3.12 (desde la raíz):

```sh
docker run --rm --network none --user "$(id -u):$(id -g)" \
  --mount type=bind,src="$PWD",dst=/workspace --workdir /workspace/backend \
  -e PYTHONDONTWRITEBYTECODE=1 -e PYTHON_DOTENV_DISABLED=1 \
  -e DATABASE_URL=sqlite:// -e CUDA_VISIBLE_DEVICES= \
  -e PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 fama-backend:latest \
  python -c 'import torch,runpy; runpy.run_path("tests/run_isolated_training_checks.py",run_name="__main__")' \
  tests/test_registry_db_sync.py tests/test_api_model_catalogue.py \
  tests/test_training_flow.py tests/test_training_persistence.py \
  tests/test_model_reevaluation.py \
  -k 'not test_cli_and_reevaluation_imports_do_not_initialize_ambient_database_runtime' \
  -o addopts=
```

Para el probe se conserva el mismo contenedor/comando Python y se sustituye la
lista de selectores y opciones pytest por `--ambient-import-probe`.

Evidencia acotada e identidades: [recibo de recuperación](../receipts/model14-recovery.json).
Entrega en commit local autorizada tras confirmar el funcionamiento del modelo,
sin publicación remota. El cambio preexistente en `AGENTS.md` se incluyó por
autorización explícita posterior.
