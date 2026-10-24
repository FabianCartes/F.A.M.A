# Nombres de modelos en entrenamiento y predicción

Los modelos persistidos comparten el rótulo `Dataset · Arquitectura (vN)` en el historial de entrenamiento, catálogo, activación, resultado y registro de sesión de predicción. Seguimiento: [issue #2](https://github.com/FabianCartes/F.A.M.A/issues/2) y [KANBAN](../KANBAN.md#nombres-coherentes-de-modelos--issue-2).

## Interpretación

- El dataset procede de la relación persistida; `AvesChilenas` se presenta como “Aves Chilenas” y `engine_diagnostics` como “Motores”. Sin relación se muestra “Dataset no verificado”, aunque `clase_objetivo` sugiera un dominio.
- `vN` es la versión visual del historial: sufijo `_vN.pt` explícito o contador cronológico por dataset/arquitectura, con desempate por ID. Las versiones explícitas no avanzan ese contador, conservando la regla anterior.
- Se consideran también filas no publicables. El contador puede cambiar al incorporar registros antiguos o corregir sus datos; no constituye una versión persistida inmutable.
- El ID técnico `fama_trained_model_<id>`, rutas, hashes y selección de inferencia conservan su función. La etiqueta `dataset` no sustituye `dataset_name`, que mantiene su validación independiente para almacenamiento.
- Los predictores predefinidos conservan sus nombres; no se les asignan versiones ni datasets inventados. La UI conserva “Versión no publicada” si falta ese metadato.

## Comprobación local

Desde `backend/`, utilizar el [runner aislado](integracion-flujo-entrenamiento.md#reproducir-comprobaciones-aisladas) con estos selectores:

```text
tests/test_api_model_catalogue.py tests/test_model_registry.py tests/test_training_service.py tests/test_training_persistence.py tests/test_loaded_checkpoint_identity.py -q
```

Desde `frontend/`:

```bash
npm test -- components/views/__tests__/PredictionView.catalogue.test.tsx components/views/__tests__/PredictionView.loaded-identity.test.tsx components/views/__tests__/PredictionView.test.tsx components/views/__tests__/TrainingView.test.tsx lib/api/__tests__/trainingApi.test.ts
npx tsc --noEmit --incremental false
```

Evidencia y límites en el [recibo](../receipts/model-names.json). Las pruebas focales usan SQLite en memoria, adaptadores ML/GCS sintéticos y jsdom; por sí solas no acreditan el despliegue o calidad ML. La reproducción histórica de `main` evalúa sus expresiones fuente inmutables.

La integración posterior del commit `89590d0` en `dev` se comprobó desde `/home/kevin/Work/fama`: reconstrucción con `./iniciar_fama.sh --build`, API directa/proxy y Chromium real. El modelo #14 muestra `Aves Chilenas · EfficientNet-B0 (v1)` en ambas vistas y `Versión v1` en predicción. Se preservaron ID, relación de dataset, hash de checkpoint y contenedor/volumen PostgreSQL. Esta comprobación visual no ejecutó inferencia ni entrenamiento y no acredita calidad ML.

## Reversión

Revertir el commit `89590d0` (módulo de nombres, consumidores, campos opcionales, presentación y pruebas) y reconstruir desde la carpeta principal. No hay migración ni cambios en pesos/datasets que revertir. Se conservó la imagen backend anterior como `fama-backend:rollback-model-names-ea25565df94e`; la imagen frontend antigua ya no estaba disponible en Docker y su reversión requiere reconstruir el código anterior. Conservar los montajes operativos y el volumen PostgreSQL.
