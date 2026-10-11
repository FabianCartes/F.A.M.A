# Reevaluación explícita de modelos MAIN

Esta operación vuelve a medir un checkpoint MAIN existente en los snapshots
`val` y `test` ya preparados. No entrena, cambia selección, activa, publica ni
reemplaza el checkpoint o informes anteriores. Ejecuta el predictor publicado
`TrainedModelPredictor` desde la ruta local explícita, no desde el registro global.

## Requisitos y preflight

La base debe existir y contener el modelo, dataset y tabla `model_evaluation`; la
operación no crea esquemas ni migra. Proporcione explícitamente:

- `--database-url`: URL autorizada a una base ya preparada.
- `--model-id`: fila MAIN existente, no un componente de ensamble.
- `--checkpoint-root` y `--checkpoint`: raíz local confiable y ruta exacta contenida.
- `--expected-sha256`: hash esperado, que debe coincidir con la fila y los bytes.
- `--prepared-dir`, `--dataset` y ambos `--root raw=...` y
  `--root processed=...`.

La primera invocación es de solo lectura: carga el marcador y el trío CSV con
`load_prepared_dataset`, valida identidad de dataset, clases, IDs, paths y grupos,
resuelve referencias contra las raíces declaradas y decodifica/hash cada grabación de
`val` y `test`. También inspecciona el checkpoint con `weights_only=True`, exige
metadata MAIN explícita (job, dataset e ID, arquitectura, clases ordenadas y configs
persistidas), y reconstruye la misma configuración efectiva que usan el runtime y el
guard de publicación. Metadata legacy ausente o ambigua falla cerrada; no se deduce el
dataset desde una ruta. El preflight no carga el predictor, infiere, crea intentos ni
cambia filas.

Ejemplo de preflight, ejecutado desde `backend`:

```sh
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/reevaluate_model.py \
  --database-url '<URL explícita>' \
  --model-id '<ID>' \
  --checkpoint-root '<raíz local de checkpoints>' \
  --checkpoint '<ruta del checkpoint dentro de la raíz>' \
  --expected-sha256 '<64 caracteres hexadecimales>' \
  --prepared-dir '<directorio prepared completo>' \
  --dataset '<AvesChilenas o engine_diagnostics>' \
  --root 'raw=<raíz raw>' \
  --root 'processed=<raíz processed>'
```

Revise el JSON acotado de salida: identidad del modelo/dataset, clases, tamaño y hash
del checkpoint, conteos y hashes de manifiesto por split. No contiene credenciales ni
rutas absolutas. Preflight también requiere leer y decodificar los audios locales; no
es una operación sin acceso a datos.

## Ejecución autorizada explícitamente

Solo después de revisar el preflight, repita exactamente los argumentos con
`--execute`. Ese flag crea nuevos intentos independientes `val` y `test`, con digest
de pareja compartido, y comienza ambos antes de inferir. El checkpoint vuelve a
verificarse alrededor de la carga y de cada predicción; cada audio conserva las
comprobaciones de snapshot del evaluador. Un cambio de bytes nunca produce un informe
completado. Si `val` ya terminó y falla `test`, el resultado de `val` se conserva y
solo se falla el intento incompleto. Los reintentos crean IDs nuevos y preservan todos
los intentos previos.

El resumen no incluye traceback ni paths. Un fallo deja razón acotada en los intentos
pendientes/en curso que se puedan actualizar. La operación no cambia `activo`,
`estado`, alias/default, métricas históricas, historial por época ni pesos; no llama al
entrenamiento, registro global, descarga de modelos, migraciones ni creación de
esquemas. La CLI requiere una URL explícita y administra/cierra su propio engine y
sesión; no usa una sesión global para ejecutar la reevaluación. Importar los modelos
ORM reutiliza `Base` sin cargar dotenv ni crear el engine de runtime. La API existente
`DATABASE_URL`, `engine`, `SessionLocal` y `get_db` permanece; dotenv y la configuración
se cargan al acceder los atributos de conexión o invocar `get_db`, con la misma
normalización PostgreSQL.

Ejemplo: añada `--execute` al final del comando de preflight anterior. Si la tabla de
evaluaciones o una identidad MAIN necesaria no existe, la ejecución falla sin
completarlas automáticamente.

## Límite operacional

Las regresiones usan únicamente SQLite temporal, checkpoints pequeños y WAVs
sintéticos con constructor de red sustituido; comprueban los seams reales del
predictor, snapshot y persistencia, pero no calidad externa, PostgreSQL desplegado ni
los artefactos/datasets operacionales. No se evaluó el modelo #11 ni se verifican aquí
las afirmaciones de 1.208 filas, 15 clases o particiones 850/177/181. Una ejecución
operacional del #11 requiere autorización separada y sus rutas/hash/destino explícitos.
