# Evaluación local del Super-Ensamble de motores servido

Esta operación calcula informes independientes de validación y test para el predictor
servido `EngineEnsemblePredictor` (ResNet34d + EfficientNet-B0 + PANNs CNN14). Llama a
la predicción combinada una vez por grabación; no promedia métricas de los componentes.

## Alcance y precauciones

- Requiere un conjunto preparado existente y sus raíces físicas raw/processed explícitas.
  Verifica marcador, hashes CSV, referencias, clases, separación de grupos y hashes de
  los audios antes de cargar los modelos; vuelve a comparar bytes al cerrar cada split.
- Los tres checkpoints deben suministrarse por nombre y en orden resnet, efficientnet,
  panns. El código carga esos bytes antes de calcular predicciones y comprueba sus
  SHA-256 al final de cada split y antes de escribir el resultado.
- La identidad compuesta no es un checkpoint único: `composite_checkpoint_sha256` es
  SHA-256 del JSON canónico/versionado con el orden, SHA-256 de cada checkpoint,
  pesos, clases y configuración efectiva del predictor. No acredita autenticidad de
  los checkpoints ni congela los audios frente a cambios maliciosos.
- La salida es un informe JSON local, no un bundle ni una publicación oficial. No usa
  BD, entrenamiento, activación, servicios, nube, búsqueda de checkpoints ni tuning.
  Test no selecciona ni ajusta pesos. Un destino existente se rechaza sin sobrescribir.
- No se aceptan modelos inyectados como procedencia checkpoint-backed para esta
  operación. Pueden usarse en pruebas de predicción, pero no generan identidad oficial
  ni se etiquetan como bytes cargados.

## Ejecución explícita

Desde la raíz del repositorio, indicar todas las rutas; adaptar únicamente a los
artefactos ya preparados y checkpoint que el operador decidió evaluar:

```bash
.venv/bin/python backend/scripts/evaluate_engine_ensemble.py \
  --prepared-dir /ruta/prepared/engine_diagnostics \
  --dataset engine_diagnostics \
  --raw-root /ruta/raw/engine_diagnostics \
  --processed-root /ruta/processed/engine_diagnostics \
  --resnet-checkpoint /ruta/resnet/weights.pt \
  --efficientnet-checkpoint /ruta/efficientnet/weights.pt \
  --panns-checkpoint /ruta/panns/weights.pt \
  --output /ruta/nueva-salida/engine-ensemble-evaluation.json
```

El directorio padre de salida debe existir y no ser symlink; el archivo objetivo no
puede existir. La herramienta no crea rutas de salida ni selecciona artefactos por
nombre. Usa los CSV `train_metadata.csv`, `val_metadata.csv` y `test_metadata.csv` y
el marcador `.complete` del formato `engine_diagnostics` de `load_prepared_dataset`.

## Contenido y límites del resultado

`reports.val` y `reports.test` contienen provenance genérica sin `id_modelo`, el hash
canónico de membresía/audio del split y un informe de grabaciones schema v2. Ambas
identidades comparten dataset, clases ordenadas, hash compuesto, pesos y configuración;
split, manifiesto de audios y cantidad pueden diferir. Silence/noise son rechazos del
predictor; un status/clase desconocido o logits no finitos falla la operación. El
informe solo se escribe después de ambas evaluaciones y la última comprobación de
identidad. Un fallo no produce un JSON de éxito.

La configuración describe los literales efectivos de `EngineEnsemblePredictor`:
resampling/RMS-VAD y selección de ventana, filtros RMS/planitud, frontend HPSS de tres
canales y combinación lineal de probabilidades softmax con pesos servidos. No es una
reevaluación histórica ni prueba de runtime desplegado, disponibilidad de checkpoints,
calibración de ensamble ni calidad en datos reales. No modifica ni reemplaza el flujo
experimental de entrenamiento/calibración de dos modelos.
