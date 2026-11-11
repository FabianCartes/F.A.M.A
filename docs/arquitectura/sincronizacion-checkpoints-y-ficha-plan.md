# Modelos: sincronización de checkpoints con GCS y ficha técnica completa

Objetivo: reemplazar «Copias del checkpoint» de la ficha técnica por un botón «Sincronizar» por modelo en el historial, con el resultado en una ventana modal, y completar la ficha técnica con toda la física del audio y los hiperparámetros. Rama `mvp`, sin push ni PR; commits locales por unidad. Runner backend: `backend/tests/run_isolated_training_checks.py`; frontend: Vitest, `tsc`, ESLint y build.

## Specs
- S1 — Kevin, 2026-11-11: «agregar el boton de sincronizar, una vez este sincronizado el boton debera decir "Sincronizado" y la comprobacion de copias debera hacerse al presionar el boton de sincronizar y despues sincroniza el audio.» («audio» = el checkpoint del modelo.)
- S2 — «Se podria colocar una ventana modal para decir si el audio fue sincronizado con exito o fallo y dar la razon.»
- S3 — «De esta manera sacar las copias del checkpoint de la ficha tecnica.»
- S4 — «Ademas en la ficha tecnica faltan opciones de la fisica de audio y hiperparametros. Deberian estar todos.»
- S5 — Kevin, 2026-11-11: «tambien las epocas y perdida sacalas de la tabla principal y dejalas en la ficha tecnica».

## Estado verificado al planificar (`0f29bdd`, solo lectura)
- `CheckpointCopies` (`backend/app/services/checkpoints.py`) ya ofrece `status`, `backup` y `restore` con verificación de tamaño y SHA-256; el objeto en GCS es `models/checkpoints/sha256/{hash}.pt`. Endpoints: `GET/POST /api/training/models/{id}/checkpoint[/backup|/restore]` (`backend/app/routes/checkpoints.py`). No hay estado de respaldo persistido: cada `status` consulta GCS.
- `CheckpointBackup.tsx` vive dentro de la ficha técnica (`TrainingView.tsx`, modal `modal-ficha-tecnica`) con «Comprobar copias», «Respaldar en GCS» y «Recuperar en este equipo».
- El historial (`backend/app/services/training.py:1490-1560`) expone `learning_rate`, `batch_size`, `optimizer`, `loss_type` y 7 campos de audio. El checkpoint guarda además `windowing_config` (`hop_seconds`, `aggregation_mode`, `gem_p`, `vad_threshold`), `regularization_config` (`loss_type`, `focal_gamma`, `mixup_enabled`, `mixup_alpha`, `pitch_shift_enabled`), `seed`, `epochs`, `initialization_mode`, `checkpoint_epoch`, `ensemble_weight`. No guarda `weight_decay` ni `early_stopping` (están en la configuración, `training.py:638-640`).
- La ficha técnica no muestra épocas, pérdida ni `hop_length`; la tabla principal muestra épocas, precisión y pérdida.

## Decisiones (aprobadas por Kevin el 2026-11-11, L2)
1. «Sincronizar» cubre las dos direcciones: comprueba; si falta en GCS, respalda; si falta en este equipo, recupera; si ambas copias están, informa que ya estaba sincronizado; ante un conflicto falla con el motivo. Reutiliza `backup`/`restore` verificados.
2. El rótulo «Sincronizado» sale de una consulta por lotes (una lectura del prefijo `models/checkpoints/sha256/` y un chequeo de tamaño del archivo local, sin hashear), separada del historial. Si GCS no responde, el botón queda como «Sincronizar» sin afirmar nada; la verificación por bytes ocurre al presionar.
3. Los modelos ya entrenados muestran «No registrado» en `weight_decay` y early stopping; los nuevos los guardan en el checkpoint.

## Tasks
- T1 | S1,S2 | pending | inline | Backend: `POST …/checkpoint/sync` (acción tomada: `already_synced`, `uploaded`, `restored`; conflictos con motivo) y `GET /api/training/models/checkpoints/sync-status` por lotes, con el mismo filtro de acceso que el historial; pruebas con GCS simulado. Risk: item 3 (endpoints nuevos, aditivos).
- T2 | S1-S3,S5 | pending | inline | Frontend: botón «Sincronizar»/«Sincronizado» por fila, modal de éxito o fallo con motivo (`DatasetConfirmationDialog`), quitar «Copias del checkpoint» de la ficha y las columnas «Épocas» y «Pérdida» de la tabla.
- T3 | S4,S5 | pending | inline | Backend: el historial expone todos los parámetros guardados (ventaneo, regularización, semilla, épocas, inicialización, época del checkpoint, peso en la tríada) y el checkpoint de modelos nuevos guarda `weight_decay` y `early_stopping`; frontend: ficha con física del audio completa (incluido `hop_length`), hiperparámetros completos, épocas, precisión y pérdida. Risk: item 1 (campos nuevos en el checkpoint, aditivos).
- T4 | S1-S5 | pending | inline | Verificación: suites de checkpoints, historial y entrenamiento; Vitest/`tsc`/lint/build; prueba manual en `fama_pruebas` con el modelo 1 (ya respaldado en L14 de la etapa g).

## Log
- L1 — Kevin, 2026-11-11: «Se debe refactorizar la manera en la que se suben los modelos a GCS, mi plan seria agregar el boton de sincronizar, una vez este sincronizado el boton debera decir "Sincronizado" y la comprobacion de copias debera hacerse al presionar el boton de sincronizar y despues sincroniza el audio. Se podria colocar una ventana modal para decir si el audio fue sincronizado con exito o fallo y dar la razon. De esta manera sacar las copias del checkpoint de la ficha tecnica. Ademas en la ficha tecnica faltan opciones de la fisica de audio y hiperparametros. Deberian estar todos. Comprueba que tan factible es hacer esto».
- L2 — Kevin, 2026-11-11: «Arma el plan con las recomendaciones, aunque tambien las epocas y perdida sacalas de la tabla principal y dejalas en la ficha tecnica». Decisiones 1–3 aprobadas.
