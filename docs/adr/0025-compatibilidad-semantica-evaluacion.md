# ADR 0025: Compatibilidad semántica del predictor evaluado

Estado: aceptado, 15 de octubre de 2026.

La publicación comparaba hashes de `inspect.getsource()` de cinco funciones con
los informes val/test. Un refactor, comentario o cambio de telemetría podía retirar
un modelo válido del catálogo. El cambio de identidad del checkpoint cargado del
ADR 0023 expuso este acoplamiento; no implica corrupción de los pesos.

## Decisión

La configuración nueva usa el contrato explícito `gpu-audio-frontend-v2`, definido
por `PREDICTOR_COMPATIBILITY_VERSION` en `standard_evaluation_guard.py`. Los cinco
hashes se conservan dentro de `predictor_config.implementation_provenance` como
evidencia diagnóstica, excluida únicamente de la comparación contra el runtime.
El par val/test sigue exigiendo configuración y procedencia conjunta coherentes.

Permanecen estrictos SHA/tamaño/metadata del checkpoint, dataset, clases ordenadas,
manifiestos, versión del evaluador, versiones de dependencias, contrato frontend,
parámetros efectivos y agregación. No se ignoran otros campos arbitrarios.

Los informes anteriores no se reescriben ni reinterpretan como v2. El primer paso
al nuevo contrato exige reevaluación explícita append-only de ambos splits.
Versiones desconocidas continúan bloqueadas. No cambia activación ni entrenamiento.

## Mantenimiento y consecuencias

Cambios de comportamiento en carga/restauración, decodificación, resampling,
recorte/padding, frontend, umbrales/rechazos, forward, clases o agregación requieren
revisar los parámetros declarados y aumentar el contrato si su semántica cambió,
con pruebas de comportamiento y nuevas evaluaciones. Cambios exclusivamente de
formato, wrappers equivalentes o metadatos no requieren aumentar la versión.

Se descarta mantener los hashes textuales como condición de compatibilidad por sus
invalidaciones espurias. También se descarta ignorar toda diferencia de runtime,
porque admitiría métricas que no representan al predictor servido. El versionado
explícito exige disciplina de revisión: no prueba automáticamente equivalencia
numérica ni garantiza determinismo entre dispositivos.

Pruebas públicas: publicación tras refactors equivalentes en las cinco funciones,
rechazo de contratos antiguos/desconocidos y tras cambio de contrato semántico,
además de las regresiones existentes de integridad y configuración efectiva.
