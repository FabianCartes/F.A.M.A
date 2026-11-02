# Primer bloque hacia dev: plazo explícito del worker
Objetivo: integrar únicamente la elección del plazo cooperativo en el CLI existente de dev, sin importar la base histórica completa.
Rama aislada `feat/zip-dev-first-block`, base `adecb01868940421fb44ca56194439908f10b585`; referencia funcional de origen `e65acc877ee80b39dcd90c6ec8e27a7aafe0673c`.

## Specs
S1. Usuario: "Vamos con tu recomendación". Recomendación aceptada: "avanzar con el primer bloque coherente de integración hacia dev, en una rama aislada, sin modificar todavía dev ni iniciar servicios".
S2. Usuario: "Review the delivered subagent output and continue." Contrastar el mapa con fuentes reales; no ampliar el alcance por negativos no corroborados. No merge, push, PR, cambio de dev/checkout original, servicios, activación, datos reales o GCS.
S3. Contrato técnico seleccionado tras corregir el mapa: añadir `--execution-seconds` al CLI existente. Aceptar valores finitos en `(0, 3600]`, incluido900 y3600; omisión conserva300s y la llamada al constructor sin ese kwarg. No cambiar lease60s, heartbeat20s, validador, proxy, límites ZIP, cuotas, esquema, auth o almacenamiento físico.
S4. Rechazar valores no finitos, ≤0 o >3600 con exit2/stdoutvacío y mensaje exacto `--execution-seconds requires a finite value greater than 0 and at most 3600`. Rechazar la opción con `--cleanup-only` mediante exit2/stdoutvacío y `--execution-seconds is not supported with --cleanup-only`. Argparse conserva su validación de números no interpretables. Rechazos antes de acceso a recursos; HTTP del import y contadores públicos no cambian.
S5. Mantener comportamiento/salidas de invocación normal, `--local-only`, `--watch`, `--poll-seconds`, `--cleanup-only`, errores sanitizados y omisión del plazo. Help/manual documentan opción, límites y naturaleza cooperativa. No matar hilos ni añadir cancelación/reintentos. No portar archivos completos desde origen ni introducir `dataset_storage_runtime`/`--storage-profile`/`--cleanup-diagnostics` en el destino.
S6. Comprobar el DESTINO con RED/GREEN por CLI `main()` y estado HTTP público, SQLite en memoria/CPU sintético/red bloqueada/temporales privados mediante runner existente. No inspección interna de esperas para simular prueba de plazo900s, no dormir900s ni afirmar trial real. La propagación exacta y los defaults se contrastan también en fuentes; los resultados del origen/S76 no prueban este candidato.

## Tasks
- T1 [S1-S6] done; route: padre; dos ciclos RED/GREEN del destino observados, focal10PASS/9deseleccionadas y suite7módulos85PASS/0deseleccionadas (job1exit0). Código mínimo, omisión300/lease60 intactos. Risk: item3 parser compartido. Commit: pendiente de T2, unidad de comportamiento propia.
- T2 [S3-S6] done; route: UNA verificación independiente de fuentes mvzarjk2-3-oprg, sin bloqueantes severos/S1-S6 calificadas según evidencia disponible; padre único ejecutor. Diferencial5casos/10invocaciones y13preservaciones aprobadas; exactamente7superficies autorizadas cambiadas, apphelpers intactos. Risk: item3. Commit: misma unidad que T1.
- T3 [S1-S6] in_progress; route: padre; docs/help/índices/recibo, ASSESS nativo según switch y plan exacto, commit local/lectura de bytes/cierre. No entrega a dev ni nuevas etapas. Commit: pendiente; cierre documental separado si hace falta registrar evidencia posterior.

## Surfaces and checks
- Allowed edit surfaces: `backend/scripts/run_dataset_import_worker.py`, `backend/tests/test_dataset_import_worker_cli.py`, `docs/manuales/trabajos-importacion-datasets.md`, `docs/manuales/integracion-dev-worker-plazo.md`, `docs/README.md`, `docs/KANBAN.md`, `docs/receipts/dev-worker-execution-bound.json`.
- Soportes sin cambios: `dataset_import_execution.py` ya acepta `**worker_options`; `dataset_import_worker.py` ya define ejecución300/lease60; queue/modelos/API y fixtures existentes. No nuevos helpers productivos ni adaptadores hipotéticos.
- Costuras: argumentos CLI/exit/stdout/stderr y estado HTTP de trabajos/imports; SQLAlchemy se vincula a la DB sintética existente en la frontera del driver. No snapshots de almacenamiento interno en nuevos tests ni mocks del ejecutor propio.
- Runner desde el backend de ESTE worktree: `PYTHONDONTWRITEBYTECODE=1 PYTHON_DOTENV_DISABLED=1 DATABASE_URL=sqlite:// CUDA_VISIBLE_DEVICES='' PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 /home/kevin/Work/fama/.venv/bin/python -B tests/run_isolated_training_checks.py <selectores>`.
- Prerrequisitos confirmados: Python3.14.8 local, pytest/sqlalchemy/fastapi/soundfile/matplotlib/torch/psycopg2 localizables, sin imports app/ML en preflight. No valida imagen Python3.12. Guard local no es sandbox OS. No instalar dependencias ni relajar guardas/fixtures.
- Suite pertinente: módulos CLI/localworker/worker/execution/jobs/API async y cuotas existentes; confirmar selectores presentes antes de ejecutar. Casos con reloj/callbacks controlados del worker existente preservan timeout/fencing; no extenderlos a operaciones reales.
- Forecast200–350líneas autorales; estrategia de entrega `auto-chain`/`feature-branch-chain` conservada como unidades locales, no PRs. Tests/docs del mismo comportamiento juntos; riesgo3 va en su propia unidad. No reconstrucción de58commits/459archivos ni cherry-pick de los commits del perfil.
- Rollback de código: retirar únicamente opción/validación/reenvío nuevos y sus tests/help de esta unidad; ningún formato de datos o migración que deshacer. No ejecutar rollback en este trabajo.

## Uso y límites de entrega

Desde `backend/`, en una futura operación autorizada con base migrada y raíces
privadas ya existentes, la opción se añade al comando normal, por ejemplo:

```bash
python -m scripts.run_dataset_import_worker --local-only \
  --database-url '<URL explícita autorizada>' \
  --import-root '<raíz privada compartida con la API>' \
  --staging-root '<raíz privada de intentos del mismo filesystem>' \
  --execution-seconds 900
```

Es documentación, no un servicio ejecutado en esta entrega. Omitir la opción
mantiene300s; no se lee una nueva variable implícita ni se seleccionan cuentas,
raíces o perfiles físicos. `--watch` sigue siendo una elección explícita previa.
El plazo es cooperativo: no interrumpe arbitrariamente Python ni evita efectos
externos de callbacks. Los límites ZIP conservadores del destino siguen iguales.
Este bloque no incluye el perfil6/10GiB ni prueba publicación/recepción grandes,
GCS, frontend, instalación, PostgreSQL real o aceptación S76 en dev. Tampoco
entrega el resto de la rama histórica; dev permanece en su commit original.

Rollback: revertir solo la unidad CLI/tests/help/documentación de esta rama;
no hay datos/esquemas nuevos que convertir. Es una frontera, no una instrucción
de ejecutar operaciones Git destructivas o borrar registros reales.

## Log
L1. Usuario: "Vamos con tu recomendación" y luego "Review the delivered subagent output and continue." Se prepara primer bloque en rama aislada desde dev; la integración/publicación/operación siguen fuera del alcance.
L2. Baseline padre: devadecb018, originalplan/large-zip-limits/statusNULSHAfb86d0e778f545c38d881d3569516530dff4f9ff0774c79595699c17f7852257/indexSHA855a904fdff33e10b5b436d276cf2a69b582ab9c0bc6ff728d6c9cbaed58478d; origenperfil e65acc8 limpio. Worktree nuevo registrado, sin editar fuente hasta documento/espejo/proyección.
L3. Mapper mvz9yfy2-1-4a2t declaró erróneamente ausentes CLI y ruta. Padre contrastó rutas literales y Git ls-tree: ambos archivos existen en ambos árboles. Una continuación delimitada mvza3bp1-2-zhck retiró falsos negativos (causa de lookup desconocida) y confirmó unidad CLI autocontenida mediante los constructores públicos existentes. No se acepta su expansión inicial a auth/esquema ni se fabrican pruebas del destino.
L4. Padre leyó CLI/test/guías vigentes del destino y skillTDD; no AGENTS adicionales backend/CONTEXT raíz rastreados. Dominio ya existente `(0,3600]`; conservar omisión de kwargs evita cambiar interfaces de los fixtures previos. Ninguna fuente, modelo, esquema, límite o helper del origen se traslada por proximidad.
L5. RED real del destino: opción900 desconocida,exit1/1PASS1FAIL9deseleccionadas; GREEN3PASS9deseleccionadas (omisión/900/3600). Segundo RED: valor0 llegaba al intento de conexión y dabaexit1no2; validación temprana mínima añadió rango/no finitos/cleanup. GREEN focal10PASS9deseleccionadas/2,25s, suite completa7módulos85PASS0deseleccionadas/15,52s (job1exit0/33s total incluye ambas invocaciones). 74SQLite en memoria/red bloqueada/CPU sintético/30rutas protegidas intactas/scratch limpiado. Ambas salidas stdout ystderr de RED/GREEN se guardan por separado en `.git/agent-scratch/dev-worker-{bound-red,bound-green,rejection-red,focused-green,suite}.{out,err}`. No se fabricó nueva prueba de origen ni se cambió ningún fixture existente.
L6. Diferencial en mktemp del proyecto `.git/agent-scratch/dev-worker-base-vg8dj33z`, baseCLI extraída deadecb018 y helpers productivos sin modificar: job2exit0,5casos/10invocaciones (normal/local/cleanup/watch conpoll3/raíz inválida), stdout/stderr/exit iguales yHTTP/contadores públicos intactos; sin operaciónGCS. Script efímero no entregado ni lectura de Git en tests comprometidos. Log `dev-worker-differential.{out,err}`. Help ampliado intencionalmente; no se exige identidad de su texto de uso nuevo.
L7. UNA verificación independiente de fuentes mvzarjk2-3-oprg: ningún bloqueante severo, S1/S2 coherentes con alcance, S3/S4 aprobadas en fuentes, S5/S6 calificadas por ejecución/diferencial del padre y sin trial900s. No comandos/tests/Git del verificador. Padre aprobó13checks de preservación antes del commit (dev/original/status/index/origen/historia/recibos/helpers),7superficies autorizadas exactas; recibo público registra hashes y límites. Los deselectores intermedios se cuentan, no se presentan como85aprobados; suite completa0deseleccionadas. Evidencia detallada stdout/stderr en logs, sin duplicar listas históricas en recibo. Próximo: ASSESS candidato, ruta nativa solo si corresponde, commit local/readback/cierre sin tocar dev.
