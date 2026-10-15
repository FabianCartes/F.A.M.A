# Reevaluación explícita de modelos MAIN

Esta operación vuelve a medir un checkpoint MAIN existente en los snapshots
`val` y `test` ya preparados. No entrena, cambia selección, activa, publica ni
reemplaza el checkpoint o informes anteriores. Ejecuta el predictor publicado
`TrainedModelPredictor` desde la ruta local explícita, no desde el registro global.

## Requisitos y preflight

Desde el [ADR 0025](../adr/0025-compatibilidad-semantica-evaluacion.md), la identidad
de publicación usa un contrato semántico explícito. Los hashes del código fuente
siguen como procedencia diagnóstica, pero un refactor equivalente no invalida los
informes nuevos. Los informes del contrato anterior requieren reevaluación explícita;
no se deben editar sus hashes ni versiones para hacerlos pasar por actuales.

La base debe existir y contener el modelo, dataset y tabla `model_evaluation`; la
operación no crea esquemas ni migra. Proporcione explícitamente:

- `--database-url`: URL autorizada a una base ya preparada.
- `--model-id`: fila MAIN existente, no un componente de ensamble.
- `--checkpoint-root` y `--checkpoint`: raíz local confiable y ruta exacta contenida.
- `--expected-sha256`: hash esperado, que debe coincidir con la fila y los bytes.
- `--prepared-dir`, `--dataset` y ambos `--root raw=...` y
  `--root processed=...`; las dos raíces físicas deben ser rutas absolutas existentes.

La primera invocación es de solo lectura: carga el marcador y el trío CSV con
`load_prepared_dataset`, valida identidad de dataset, clases, IDs, paths y grupos,
resuelve referencias contra las raíces declaradas y decodifica/hash cada grabación de
`val` y `test`. También inspecciona el checkpoint con `weights_only=True`, exige
metadata MAIN explícita (job, dataset e ID, arquitectura, clases ordenadas y configs
persistidas), y reconstruye la misma configuración efectiva que usan el runtime y el
guard de publicación. Metadata legacy ausente o ambigua falla cerrada; no se deduce el
dataset desde una ruta. El preflight no carga el predictor, infiere, crea intentos ni
cambia filas.

Ejemplo de preflight, ejecutado desde `backend` (el entorno virtual está en la raíz
del repositorio, por eso se usa `../.venv`, no `backend/.venv`):

```sh
PYTHONDONTWRITEBYTECODE=1 ../.venv/bin/python scripts/reevaluate_model.py \
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

Las regresiones automatizadas usan SQLite temporal, checkpoints pequeños y WAVs
sintéticos con constructor de red sustituido; no certifican calidad ni despliegue. La
reevaluación real de #11 en `fama_db` fijada se resume abajo por separado.

### EVAL-6B: ejecución real verificada

Intentos inmutables: ID 1 (`val`, 177 muestras) y 2 (`test`, 181), 15 clases, schema
informe v2 / evaluator recording v1. Preflight e invariantes incluidos; duración 65.419 s.
Hash de fila del modelo verificado `277d8523…`; SHA esperado del checkpoint `070d…`.
Accuracy val/test: 6.779661% / 3.867403%; macro F1: 5.6262% / 3.9644%; rechazos:
31/177 y 63/181. **Calidad no aprobada**; no reconstruir ni reinterpretar la métrica
histórica y no alterar activación.

El informe original es [`model-11-real-evaluation.json`](../receipts/model-11-real-evaluation.json).
La verificación independiente `mv3a8v51` cotejó snapshots/digests observados con el
recibo fuente y comprobó la integridad del runtime separadamente; no se afirma una
comprobación offline adicional de los archivos de manifiesto. Los diagnósticos MPEG
requieren seguimiento de calidad exclusivamente de solo lectura; ese diagnóstico no
se ejecutó como parte del cierre.

## Verificación de la migración

La migración de `model_evaluation` solo crea la tabla cuando falta; si ya existe,
verifica columnas y restricciones sin alterarla. PostgreSQL puede representar los seis
`CHECK` con una escritura de catálogo distinta a la compilada por SQLAlchemy. El
verificador añade una allowlist literal para esas seis formas observadas, sin normalizar
paréntesis ni cambiar condiciones; escrituras no contempladas siguen fallando cerradas.

El recibo [`model-11-evaluation-migration.json`](../receipts/model-11-evaluation-migration.json)
conserva el historial: primera creación exit 0 y segundo intento exit 1 al comparar
CHECK PostgreSQL. La corrección `ab25519` (102 PASS independientes; revisión nativa
APPROVED/ACK) reconoce las formas exactas y aceptó el esquema existente con
`migrate(engine) -> False` en conexión de solo lectura, sin DDL nueva. No reescribir el
recibo ni describir el segundo intento como éxito. No se verificó upgrade de una tabla
v1 ni se afirma RED histórico; la evaluación EVAL-6B y su límite de calidad constan
arriba.
