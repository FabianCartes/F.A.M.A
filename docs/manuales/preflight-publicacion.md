# Preflight de publicación de un modelo

El preflight comprueba si **un modelo exacto** puede publicarse en un runtime candidato, usando el registro de modelos y la guarda de evaluaciones estándar existentes. No vuelve a implementar compatibilidad, no activa modelos, no crea el esquema y no inicia la aplicación FastAPI.

## Preflight sin inferencia

Ejecutar desde la raíz del repositorio con valores del candidato revisado:

```bash
.venv/bin/python backend/scripts/preflight_publication.py \
  --database-url '<CANDIDATE_DATABASE_URL>' \
  --checkpoints-root '<CANDIDATE_CHECKPOINTS_ROOT>' \
  --model-id 'fama_trained_model_<MODEL_ID>' \
  --expected-sha256 '<EXPECTED_CHECKPOINT_SHA256>'
```

Todos los valores de runtime son explícitos. El comando no carga `.env` ni utiliza una URL, una raíz de checkpoints o un modelo por defecto. El ID debe ser el identificador persistido `fama_trained_model_<id>` y el SHA-256 esperado debe coincidir tanto con el valor persistido como con los bytes del checkpoint encontrado bajo la raíz indicada. Los errores de otros modelos no invalidan el resultado del modelo requerido.

La lectura SQL se fuerza en modo de solo lectura por conexión: `SET TRANSACTION READ ONLY` en PostgreSQL y URI nativa SQLite `mode=ro` al abrir la conexión, además de `PRAGMA query_only=ON`. SQLite solo admite archivos de base existentes; se rechazan bases en memoria y modos URI incompatibles antes de conectarse. Así, una ruta inexistente no crea archivos. Al terminar, la sesión se revierte/cierra y la conexión y el engine se cierran.

La salida estándar contiene un único objeto JSON acotado; los fallos operativos esperados también usan JSON en stdout y dejan stderr vacío. Código de salida `0` indica preflight satisfactorio, `1` un preflight o smoke no satisfactorio y `2` argumentos inválidos. La respuesta incluye el ID y hash esperados, un código y una razón saneada; no incluye URL de base de datos, secretos, excepciones ni rutas privadas.

Un resultado de preflight satisfactorio valida la publicación y la identidad del checkpoint con inicialización perezosa de metadata. **No demuestra que el modelo de red se haya construido ni que cargue e infiera correctamente.**

## Smoke opcional y separado

Solo después de revisar el preflight, se puede proporcionar un audio controlado para invocar el predictor público real:

```bash
.venv/bin/python backend/scripts/preflight_publication.py \
  --database-url '<CANDIDATE_DATABASE_URL>' \
  --checkpoints-root '<CANDIDATE_CHECKPOINTS_ROOT>' \
  --model-id 'fama_trained_model_<MODEL_ID>' \
  --expected-sha256 '<EXPECTED_CHECKPOINT_SHA256>' \
  --smoke-audio '<CONTROLLED_AUDIO_PATH>'
```

El smoke exige una salida clasificada que demuestre pasada de red y que la identidad del checkpoint efectivamente cargado coincida con el SHA-256 esperado. Silencio y ruido se informan como resultados acotados, pero no prueban el forward y por ello el smoke no pasa. El audio debe ser de prueba, controlado y autorizado para el candidato; el comando no evalúa conjuntos completos ni escribe audio, activa modelos o crea intentos de evaluación.

Este comando es un control previo de candidato. No reemplaza la publicación/release, el despliegue, la reversión ni una autorización operativa separada.
