# Seguimiento: frontend definitivo de entrenamiento

## Objetivo

Hacer que checkpoints estándar nuevos conserven el contrato efectivo/versionado del `GPUAudioFrontEnd`, y que predictor e informes de evaluación/reevaluación usen ese mismo preprocesamiento. Las augmentations continúan exclusivas del entrenamiento.

## Límites

- No reconstruir normalización de #11/#12, editar sus checkpoints/informes, cambiar activación, desplegar ni iniciar entrenamiento real.
- Checkpoints históricos sin contrato no reciben valores supuestos; toda evaluación que necesite parámetros ausentes se rechaza antes de inferir.
- El recorrido integral usa datos y checkpoint sintéticos. No hacer benchmark; una ejecución breve de rendimiento requiere autorización aparte.
- La ficha de un primer entrenamiento (recomendación inicial: EfficientNet-B0) es posterior a la corrección y no autoriza ejecutarlo.

## Tareas y evidencia

1. [x] **Alcance y seams:** fijar frontend definitivo, límites históricos/sintéticos y seams públicos confirmados por el usuario.
2. [x] **Contrato común:** contract v1 explícito y persistido desde los valores efectivos; pruebas focales de persistencia.
3. [x] **Inferencia:** predictor reconstruye `GPUAudioFrontEnd` desde metadata validada; RED/GREEN observado con equivalencia numérica determinista. Augmentations siguen solo en training.
4. [x] **Compatibilidad/guardas:** metadata ausente/inválida/no soportada se rechaza para checkpoints estándar; predictor legacy no estándar preservado; pruebas focales de reevaluación. No se relajaron controles de identidad/hash/splits.
5. [x] **Verificación integrada CPU:** cinco suites focales verificadas independientemente: 172 PASS / 4 SKIP. Incluyen checkpoint/predictor/reevaluación sintéticos y invariancia de dB por muestra con batch heterogéneo, silencio, padding y recorte.
6. **Cierre:** informar ficha técnica y estimación de costo para propuesta futura únicamente si los datos disponibles permiten estimarlas; si no, declarar incertidumbres y detenerse antes de cualquier ejecución.

## Estado

Implementación focal verificada en CPU. El contrato v1 exige `top_db_scope=per_sample`; ausencia o scope batch se rechaza. No está cerrado el proceso de revisión nativa ni la ficha del futuro entrenamiento.

## Decisiones

- El frontend definitivo es `GPUAudioFrontEnd`; no se elegirán o compararán rutas alternativas.
- La evaluación debe validar contrato antes de inferencia y no deducir valores históricos.
- Sin entrenamiento real ni benchmark dentro de esta autorización.

## Evidencia de cierre

Verificador independiente: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -rs -p no:cacheprovider backend/tests/test_trained_predictor.py backend/tests/test_model_reevaluation.py backend/tests/test_training_persistence.py backend/tests/test_training_service.py backend/tests/test_training_flow.py` → 172 PASS / 4 SKIP (13.71 s). Whitespace check focal PASS. Dos warnings librosa por FFT mayor que entrada corta. Los skips requieren checkpoint externo ausente; CUDA no disponible.

TDD: RED inicial 8 fallos antes de producción; batch heterogéneo reveló dependencia de dB con diferencia máxima 116.2178; corrección por muestra GREEN. Rechazo de scope ausente: RED DID NOT RAISE → GREEN. Fixture target_sr=16000 corregida con f_max=8000 (6 FAIL → 12 PASS parametrizados; archivo 86 PASS), sin relajar Nyquist.

Incidente de verificación: un punto final interpretado como argumento provocó suite global accidental: 26 FAIL / 1493 PASS / 5 SKIP. Se corrigieron y reverificaron los seis casos focales de training_flow; los restantes fallos globales no fueron diagnosticados ni se rerunió la suite global. No declarar regresión global limpia.

Revisión nativa: INSPECT requiere selección de untracked y detecta cambios ajenos en backend/frontend; no START, lineage ni aprobación. Pendiente aislar un candidato revisable sin tocar cambios ajenos. No se crean commits sin pedido explícito del usuario.

Incidente documental: el tablero fue sobrescrito inicialmente por error; se recuperó la versión HEAD y se agregó un bloque propio. No se dispone de snapshot previo del worktree para acreditar preservación de posibles ediciones no confirmadas que existieran antes de esa escritura.

Sin entrenamiento real, benchmark, activación, despliegue, commits ni modificaciones de checkpoints/informes históricos.
