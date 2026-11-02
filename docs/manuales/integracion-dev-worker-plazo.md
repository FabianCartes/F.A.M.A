# Primer bloque hacia dev: plazo explícito del worker
Objetivo: integrar únicamente la elección del plazo cooperativo en el CLI existente de dev, sin importar la base histórica completa.
Rama aislada `feat/zip-dev-first-block`, base `adecb01868940421fb44ca56194439908f10b585`; referencia funcional de origen `e65acc877ee80b39dcd90c6ec8e27a7aafe0673c`.

## Actualización T6.3 (alcance posterior, no reescribe la evidencia histórica)

El builder compartido ahora permite `FAMA_IMPORT_STORAGE_PROFILE` opcional para
HTTP/worker; ver [contrato físico](presupuesto-fisico-importacion-dev.md). No se
modifican dominio `(0,3600]`, default300, flag explícito900, watch/local-only,
cleanup o señales. El perfil inválido rechaza antes de construir engine con la
salida genérica existente; help explica la variable sin alterar salidas normales.
Esta ampliación posterior no convierte los recibos de este primer bloque en
pruebas de almacenamiento físico, activación real o ZIP grande.

## Specs
S1. Usuario: "Vamos con tu recomendación". Recomendación aceptada: "avanzar con el primer bloque coherente de integración hacia dev, en una rama aislada, sin modificar todavía dev ni iniciar servicios".
S2. Usuario: "Review the delivered subagent output and continue." Contrastar el mapa con fuentes reales; no ampliar el alcance por negativos no corroborados. Durante la preparación no se autorizaban merge, push, PR, cambio de dev/checkout original, servicios, activación, datos reales o GCS. S7 permite después únicamente el avance rápido de dev local; las demás exclusiones permanecen.
S3. Contrato técnico seleccionado tras corregir el mapa: añadir `--execution-seconds` al CLI existente. Aceptar valores finitos en `(0, 3600]`, incluido900 y3600; omisión conserva300s y la llamada al constructor sin ese kwarg. No cambiar lease60s, heartbeat20s, validador, proxy, límites ZIP, cuotas, esquema, auth o almacenamiento físico.
S4. Rechazar valores no finitos, ≤0 o >3600 con exit2/stdoutvacío y mensaje exacto `--execution-seconds requires a finite value greater than 0 and at most 3600`. Rechazar la opción con `--cleanup-only` mediante exit2/stdoutvacío y `--execution-seconds is not supported with --cleanup-only`. Argparse conserva su validación de números no interpretables. Rechazos antes de acceso a recursos; HTTP del import y contadores públicos no cambian.
S5. Mantener comportamiento/salidas de invocación normal, `--local-only`, `--watch`, `--poll-seconds`, `--cleanup-only`, errores sanitizados y omisión del plazo. Help/manual documentan opción, límites y naturaleza cooperativa. No matar hilos ni añadir cancelación/reintentos. No portar archivos completos desde origen ni introducir `dataset_storage_runtime`/`--storage-profile`/`--cleanup-diagnostics` en el destino.
S6. Comprobar el DESTINO con RED/GREEN por CLI `main()` y estado HTTP público, SQLite en memoria/CPU sintético/red bloqueada/temporales privados mediante runner existente. No inspección interna de esperas para simular prueba de plazo900s, no dormir900s ni afirmar trial real. La propagación exacta y los defaults se contrastan también en fuentes; los resultados del origen/S76 no prueban este candidato.

S7. Entrega posterior solicitada: "Cerremos la entrega a dev". Alcance humano seleccionado: "Integrar en dev local", con efecto "Incorporar los dos commits a dev sin push ni PR, preservando el checkout original y sin iniciar servicios." Incorporar fuente5a7c79f y cierrec70540f más su registro documental pasivo, sin cambiar backend ni ejecutar servicios. Exigir ancestry/avance rápido, árbol limpio, identidad exacta de archivos probados y preservación del checkout original/origen/historia. No reescribir recibos históricos como evidencia nueva ni afirmar entrega remota.

## Tasks
- T1 [S1-S6] done; route: padre; dos ciclos RED/GREEN, focal10PASS/9deseleccionadas y suite7módulos85PASS/0deseleccionadas. Código mínimo/omisión300/lease60 intactos. Risk: item3 parser compartido. Commit: `5a7c79f82294bd33a8941496f564e06918602016` (unidad de332líneas).
- T2 [S3-S6] done; route: UNA verificación independiente source-only mvzarjk2-3-oprg sin severos, padre único ejecutor; diferencial5casos/10calls/13preservaciones y7checksreadback aprobados. Risk: item3. Commit: `5a7c79f82294bd33a8941496f564e06918602016`.
- T3 [S1-S6] done; route: padre; help/manual/índices/recibo yASSESS normalizado/commit local/7checksreadback de fuente completos. nativeRiskmedium/reviewDuefalse; no START ni aprobación nativa. Commit de unidad: `5a7c79f82294bd33a8941496f564e06918602016`; este cierre documental pasivo se encadena inmediatamente después, sin código nuevo, merge ni operación.
- T4 [S7] done; route: padre; fuente5a7c79f/c70540f incorporada a dev local por avance rápido,10checks de entrega/preservación aprobados. Código probado idéntico;85tests/diferencial/independiente son evidencia previa, no reejecutada. Registro documental pasivo en sucesor inmediato de c70540f, sin push/PR/servicios ni modificar el checkout original.

## Surfaces and checks
- Allowed edit surfaces: `backend/scripts/run_dataset_import_worker.py`, `backend/tests/test_dataset_import_worker_cli.py`, `docs/manuales/trabajos-importacion-datasets.md`, `docs/manuales/integracion-dev-worker-plazo.md`, `docs/README.md`, `docs/KANBAN.md`, `docs/receipts/dev-worker-execution-bound.json`; para S7, también `docs/receipts/dev-worker-local-delivery.json` (manifiesto documental, no autoridad de rama en tiempo real).
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
L8. ASSESS inicial: precondición explícita de no rastreados, nativeRiskunassessable/sin candidato. Una normalización delimitada stageó exactamente7archivos autorizados; ASSESS nuevo nativeRiskmedium/riskhigh solo por agenteitem3,7paths332líneas, reviewDuefalse/under_budget/candidateconsumedfalse/outcomeunknown. Plan writerSelfVerification+independentVerifier satisfecho. No INSPECT/START/linaje/acuse/aprobación nativa de este candidato. No reutilizar el review del perfil. El estado fuente no cambió entre ambas evaluaciones.
L9. Unidad fuente `5a7c79f82294bd33a8941496f564e06918602016`, árbol `44d855174e4eb340d0796a0cbd084820107cac1d`, padreadecb018,7archivos331+/1-=332líneas. Lectura Git posterior:7checks aprobados, todos7blobs exactos, árbol limpio, hashes iguales a fuentes probadas. Recibo enlazado desde índice; este cierre actualiza solo documentación/evidencia. Ninguna suite/observación/S76 se repite sin cambio de fuente.
L10. Estrategia `auto-chain`/`feature-branch-chain`: corte de fuente EXACTO `adecb018..5a7c79f` (332líneas); corte siguiente solo cierre pasivo de documentación/recibo sobre5a7c79f. Cada unidad revisable menor que400. El aviso del hook139commits/52606líneas comparó conorigin/main:138commits YA estaban en dev, no se autoriza ni entrega ese rango. Padre confirmó1commitreal desde dev antes del cierre; no fetch/reescritura/PR/ampliación del alcance por el aviso.
L11. Resultado: primer bloque disponible en rama aislada; dev/original/origen/historia/recibos y servicios preservados, todaslasgates operativas siguenpausadas. No habilita ZIP6/10GiB ni el perfil local completo. Límite: ejecución900s demostrada como propagación literal y trabajo público válido, no ensayo de duración real; Python3.14.8 no acredita imagen3.12. Futuro producto fuera de este encargo: seleccionar próximo bloque coherente o decidir integración/publicación; no iniciar ninguno implícitamente.
L12. Usuario: "Cerremos la entrega a dev". Pregunta de alcance: "Los dos commits están listos y dev sigue intacto. ¿Quieres cerrar la entrega solo en dev local o publicarla para integrarla mediante un PR?" Respuesta humana: "Integrar en dev local"; descripción aceptada: "Incorporar los dos commits a dev sin push ni PR, preservando el checkout original y sin iniciar servicios." Preflight actual: devadecb018, fuente/cierre5a7c79f/c70540f, worktree limpio, dev ancestro y exactamente2commits pendientes; no dev checkout en worktrees registrados. Solo Git/documentación, sin nuevos comportamientos o instalaciones.
L13. Entrega fuente observada: nuevo worktree registrado `.git/agent-worktrees/dev-local-delivery` sobre devadecb018, `git merge --ff-only c70540f812db3d8961299611b627a6e504b5f1ef` completado sin conflictos; devlocal=c70540f,2commits exactos.10checks aprobados: dev limpio/correcto, hashes fuente yrecibo histórico iguales en ambosworktrees, rama/statusNUL/index originales intactos ysin nuevo backenddiff. Se usó worktree separado para preservar también la rama de preparación con su seguimiento; no stash/reset/cambio de rama del checkout original. Manifiesto `dev-worker-local-delivery.json` distingue integración fuente real de registro documental posterior; el estado final de refs se acredita por Git/readback.
