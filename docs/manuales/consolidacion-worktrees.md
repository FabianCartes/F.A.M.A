# Consolidación local de worktrees — 15 de octubre de 2026

Se retiraron **los 58 worktrees secundarios** tras respaldar y comprobar sus
estados. Las mejoras seleccionadas, incluido `spawn`, están integradas en commits
locales de `feat/consistent-evaluation-publication`, a partir de `23ad406`. Solo queda registrado
el worktree principal. También se inventariaron, preservaron y retiraron las tres
rutas `.t*-verify` que no eran worktrees. La publicación sigue pendiente.

## Cambios incorporados

| Cambio | Verificación y garantía conservada |
| --- | --- |
| Runner autocontenido | Guarda local e inventario vigente; rechazo de rutas ausentes, escapes y Python optimizado. El recibo histórico no se modifica. |
| `f_max=None` interno | Conserva Nyquist implícito en contrato, checkpoint e informes val/test. No amplía el esquema HTTP de audio. |
| Semilla UI/API | Entero uint32 estricto, predeterminado 42; llega al hijo spawn. RNG aislados del proceso API; sin promesa de determinismo entre equipos. |
| Cancelación durante validación | Detiene el flujo antes de guardar/publicar el modelo incompleto. |
| Spawn supervisado | Cola acotada, consumo independiente de HTTP, código de salida obligatorio y recursos recogidos antes de confirmar finalización. |
| Recuperación del predictor | Pruebas de fallo de construcción/transferencia del frontend y reintento; se conserva el predictor actual con identidad de carga y concurrencia. |

Los cambios se trasladaron por comportamiento. No se reemplazaron completos el
servicio, predictor, registro ni guarda por sus variantes antiguas. Se conserva
el rechazo explícito del fallo de pesos preentrenados, las raíces externas de
lectura y la política actual de activación.

## Retirada y respaldo

Respaldo local independiente del checkout:

```text
/home/kevin/Work/fama-preservation/20261015T151502Z/
├── manifest.json
├── refs.bundle
├── <número>-<worktree>/
│   ├── registration.txt
│   ├── index
│   ├── staged.patch
│   ├── unstaged.patch
│   ├── manifest.json
│   └── local-files.tar.gz
├── removed-clean-worktrees.json
├── removed-preserved-snapshots.json
└── <comprobación>.{json,stdout,stderr}
```

Se verificaron los SHA-256 de los archivos archivados y la integridad del bundle.
El directorio padre del respaldo tiene modo `0700`. En este primer respaldo,
los entornos virtuales, `node_modules`, índices CodeGraph y cachés reconstruibles
quedaron excluidos. El respaldo adicional descrito abajo sí incluye los entornos
CUDA de los dos worktrees fuente.
El respaldo es local, no una copia remota.

| Grupo retirado | Cantidad | Tratamiento |
| --- | ---: | --- |
| `legacy-cleanup-split`, `r01`–`r22`, `r23-unit5-review-3541d40`, `r24`–`r27` | 28 | Limpios, integrados y preservados por refs; retirada sin forzar. |
| Restantes cortes R23 | 15 | Mejoras útiles trasladadas; variantes antiguas y documentos históricos archivados. No todos sus commits son ancestros del principal. |
| `.rdd-worktree-t1`, `t2`, `t3` | 3 | Contenido local ya presente en commits integrados; snapshot exacto respaldado. |

Antes de retirar los últimos 18 se volvió a comparar HEAD, estado, parches staged
y unstaged, conjunto de archivos y hashes del respaldo. Se utilizó retirada
forzada únicamente cuando había ese estado local preservado o cachés ignoradas.
No se borraron ramas, no se ejecutó un prune global y no se reinició el almacén
de revisiones. La inspección de procesos accesibles no encontró cwd o descriptores
de trabajo en esas rutas; no es una garantía sobre procesos inaccesibles.

### Recuperación

1. Consultar el `manifest.json` del worktree para localizar su HEAD y respaldo.
2. Verificar `refs.bundle` con `git bundle verify`. Recuperar su historial en
   otro checkout si las refs locales ya no estuvieran disponibles.
3. Crear un worktree en ese HEAD. Aplicar `staged.patch` con `git apply --index`
   y después `unstaged.patch` con `git apply`, cuando no estén vacíos.
4. Inspeccionar `local-files.tar.gz` y restaurar sus archivos locales en ese
   checkout; comparar sus hashes con el manifiesto. No copiar el índice binario
   directamente sobre otro checkout: se conserva como evidencia adicional.

## Verificación ejecutada

| Comprobación | Resultado |
| --- | --- |
| Flujo, servicio, persistencia, API, esquemas, identidad cargada, catálogo y registro | **312 PASS**, 2 advertencias FFT de fixtures |
| Predictor, reevaluación y preprocessing sintéticos | **56 PASS**, 5 casos deseleccionados explícitamente |
| Preflight de publicación CLI con SQLite temporal y procesos propios | **18 PASS** |
| CLI del runner, incluida prueba de imports tras la retirada | **4 PASS** |
| Formulario/cliente de entrenamiento y vistas de predicción/catálogo | **116 PASS** |
| TypeScript sin emisión ni incremental | Exit 0 |
| Build de producción frontend | Exit 0 |
| Lint de archivos frontend modificados | Exit 1: 25 errores `any` y una advertencia ya presentes en HEAD |

El lint se contrastó con las versiones de HEAD mediante `git show` y ESLint por
stdin: mismos 23 errores en la prueba de TrainingView, 2 en la prueba del cliente
y la advertencia de import no usado en la vista. No se presenta como aprobado.

Las 312 y 56 pruebas usan el runner con CPU, SQLite en memoria, red bloqueada y
temporales privados. El primer intento de incluir el preflight en ese runner
fue rechazado por requerir SQLite en archivo; sus 18 pruebas se ejecutaron
separadamente sobre fixtures temporales, sin ampliar la guarda. Las cinco
deselecciones del segundo grupo son cuatro casos con checkpoint/audio históricos
y el wrapper subprocess de imports, cuyo payload se comprobó mediante el modo
aislado del runner. No cuentan como pruebas aprobadas.

No se acredita con estos resultados entrenamiento real, CUDA, PostgreSQL de
despliegue, navegador ni suite global. Los comandos y salidas están en el respaldo;
el resumen versionable está en
[`worktree-consolidation.json`](../receipts/worktree-consolidation.json).

## Cierre de los doce worktrees restantes

### Entrenamiento mediante `spawn`

Se integró el candidato de `fama-frontend-contract` por comportamiento sobre el
principal, conservando sus raíces externas, rechazo de pesos ausentes y guardas.
El [ADR 0024](../adr/0024-entrenamiento-aislado-spawn.md) registra el diseño y sus
límites. Las pruebas reprodujeron la cancelación IPC ignorada, la evaluación tras
cancelar después del registro y el hijo huérfano al fallar el supervisor; los tres
recorridos quedaron corregidos.

La comparación de activación encontró una diferencia real con
`fama-review-new-model-flow`: esa variante exige activación explícita; el principal
autoactiva tras completar informes estándar válidos. Se preservó la variante como
evidencia histórica y se conservó el comportamiento probado del principal. No se
copiaron sus ADR 0023–0025, cuya numeración colisiona con los ADR vigentes y cuyo
texto sobre ausencia de selector de semilla ya no describe la UI actual.

### Respaldo adicional y entornos CUDA

```text
/home/kevin/Work/fama-preservation/20261015T163827Z-remaining/
```

Contiene un bundle de refs, inventario completo por ruta, parches staged/unstaged,
índices Git y archivos `files.tar.gz`. Se verificaron SHA-256 de cada miembro,
modos y symlinks, además del hash de cada archivo comprimido. Un clon bare temporal
del bundle confirmó la disponibilidad de los doce HEAD. Se repitió la comparación
de estado y archivos inmediatamente antes de retirar cada ruta.

Los dos `.venv-cuda` completos, checkpoints, pesos privados, recibos y claims están
incluidos. Solo se excluyeron `.codegraph`, `.atl`, `frontend/node_modules` y
`frontend/.next`. El primer intento comprimido de la segunda fuente excedió el
tiempo; ese archivo incompleto fue rechazado y reconstruido antes de retirar nada.

Para recuperar una fuente, crear un worktree en el HEAD del manifiesto, en su ruta
original, y restaurar el archivo correspondiente **sin sobrescribir su nuevo
`.git`**. El archivo completo ya contiene las modificaciones locales; no reaplicar
encima los parches del mismo snapshot. Los parches e índices son evidencia auxiliar.
Conservar modos y symlinks al restaurar el entorno. Los launchers y shebangs usan
rutas absolutas originales. Ambos entornos dependen de `/usr/bin/python3.14`, cuyo
hash está en el manifiesto; driver, CUDA y datasets externos siguen siendo
dependencias del host. Se verificó la integridad archivada, no una nueva ejecución
CUDA ni la portabilidad del venv a otra ruta.

### Candidate-views de gentle-ai

Se retiraron los diez candidate-views, incluidos cinco con cambios locales
preservados. Sus owners se trasladaron al respaldo. Los snapshots eran de solo
lectura: Git retiró el registro, pero falló al borrar directorios. Se comprobaron
los bytes residuales contra el archivo verificado y se habilitó escritura solo
en los directorios exactos ya retirados para completar su eliminación.

Todos los archivos del store fuera de `candidate-views` y la salida completa de
`gentle-ai review status` son idénticos byte por byte antes y después. Sus veinte
lineages, incluidos dos `reviewing` y diagnósticos históricos, se conservaron.
Retirar vistas no equivale a aprobar, abandonar o reparar revisiones. No se usó
`store-reset`, prune global ni se retiró `REVIEW-MAINTENANCE.lock`.

### Rutas de verificación

| Ruta | Inventario previo | Tratamiento |
| --- | --- | --- |
| `.t1-verify.xFHiCl/` | 342 archivos, 7.192.874 bytes | Archivo completo verificado y retirada. |
| `.t3-verify-X0LRjz/` | 246 archivos, 2.215.728 bytes | Archivo completo verificado y retirada. |
| `.t3-verify-current` | Archivo regular de 40 bytes; puntero textual, no symlink | Archivado y retirado separadamente. |

Se preservaron también bytecode, cachés y gráficos locales de esas copias. No se
declararon redundantes por similitud de nombres ni se confundieron con worktrees.

## Verificación nueva tras integrar spawn

Los resultados de la tabla anterior corresponden a la consolidación previa.
Esta continuación ejecutó:

| Comprobación | Resultado nuevo |
| --- | --- |
| Suite aislada de flujo, servicio, persistencia, API, esquemas, identidad, catálogo y registro | 312 PASS, dos advertencias FFT de fixtures, sin deselecciones. |
| Spawn real y pipeline sintético completo | 9 PASS. SQLite temporal en archivo; CPU; red bloqueada en el pipeline hijo. |
| TrainingView, cliente API y tres vistas/contratos de PredictionView | 122 PASS en cinco archivos. |
| `npx tsc --noEmit --incremental false` | Exit 0. |
| `npm run build` | Exit 0. |
| Lint de los cuatro archivos frontend modificados | Exit 1: 25 errores `any` y una advertencia. Sigue sin aprobar. |

Desde `backend/`, con el intérprete local Python 3.14 validado:

```bash
PYTHON_DOTENV_DISABLED=1 DATABASE_URL=sqlite:// CUDA_VISIBLE_DEVICES= \
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONDONTWRITEBYTECODE=1 \
OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
/home/kevin/Work/fama/.venv/bin/python tests/run_isolated_training_checks.py \
  tests/test_training_flow.py tests/test_training_service.py \
  tests/test_training_persistence.py tests/test_api_training.py \
  tests/test_training_schemas.py tests/test_loaded_checkpoint_identity.py \
  tests/test_api_model_catalogue.py tests/test_registry_db_sync.py
```

Las pruebas spawn se ejecutan separadamente porque el runner anterior prohíbe
procesos y SQLite en archivo. Desde la raíz:

```bash
PYTHON_DOTENV_DISABLED=1 DATABASE_URL=sqlite:// CUDA_VISIBLE_DEVICES= \
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONDONTWRITEBYTECODE=1 NUMBA_DISABLE_JIT=1 \
OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
.venv/bin/python -m pytest -q backend/tests/test_training_spawn.py
```

La verificación no acredita Python 3.12/Docker, CUDA, PostgreSQL de despliegue,
entrenamiento con datos reales, calidad de modelos ni revisión nativa del candidato
nuevo. Los cambios están confirmados localmente, sin push. Los cambios concurrentes
en `AGENTS.md` se conservaron como trabajo ajeno.

## Commits de integración

| Commit | Unidad |
| --- | --- |
| `5e8609c` | Nyquist implícito en contratos, checkpoint e informes. |
| `c7b0199` | Selección y propagación de semilla desde UI/API. |
| `7c25b4a` | Ejecución spawn, supervisión y barreras de cancelación con pruebas y ADR. |
| `f006523` | Cobertura de recuperación del frontend del predictor. |
| `76760dc` | Runner autocontenido, guarda e inventario vigentes y pruebas CLI. |

El cierre documental se confirma en una unidad posterior. Los recibos conservan
el estado de sus snapshots de verificación
previos a estos commits; sus indicadores `changes_committed: false` o
`locally_verified_uncommitted` son históricos, no el estado actual de Git.
