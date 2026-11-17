# ADR 0083: Retiro del Super-Ensamble fijo y de su estado legacy

Fecha: 2026-11-17. Estado: aceptado. Sustituye la parte de lectura pasiva de `GET /api/model-info` de [ADR 0051](0051-estado-legacy-pasivo-y-ejecucion-atribuida.md); la atribución de la ejecución (`modelo_id`, `modelo`, `modelos_ejecutados`, `modelos_activos`) sigue vigente.

## Contexto

`backend/app/main.py` definía `SuperEnsembleService`, un Super-Ensamble de aves identificado por los nombres de archivo de tres checkpoints históricos (`efficientnet_gpu_pipeline_35e_best.pt`, `convnext_nano_35e_best.pt`, `resnet34d_35e_best.pt`) con pesos 0.55/0.30/0.15. El servicio se cargaba al arrancar y alimentaba solo `GET /api/model-info`, cuyo único consumidor era el panel «Estado observado del servicio bioacústico legacy» de Predicción. No formaba parte del catálogo de Predicción: las predicciones se ejecutan con los modelos y tríadas que publica el registro (`ModelRegistry`) y con los ensambles declarados en `FAMA_ENSEMBLES_JSON`.

Las filas `modelo` de esos checkpoints se retiraron el 16 de noviembre y sus pesos solo se conservan como respaldo en GCS. En la instalación oficial, el servicio ya no encontraba los archivos y arrancaba vacío. Una tríada reentrenada sobre AvesChilenas (composición 1, ADR 0081/0082) está publicada, evaluada en val/test y activa como modelo por defecto.

## Decisión

- Retirar `SuperEnsembleService`, sus constantes (`SPECIES_CLASSES`, `ENSEMBLE_WEIGHTS`), su carga en el ciclo de vida y la ruta `GET /api/model-info`, que ahora responde 404.
- Retirar de Predicción la consulta a esa ruta y el panel de estado legacy. Un ensamble declarado se describe con el mismo panel de especificaciones del catálogo que un modelo individual, con el encabezado «Especificaciones del Ensamble Seleccionado».
- El modelo por defecto sigue siendo una decisión explícita del administrador: el modelo o la tríada con `activo = True`.

## Alternativas descartadas

- **Mantener la ruta devolviendo un estado vacío:** conserva un contrato que no describe ningún predictor real.
- **Apuntar el servicio a la tríada reentrenada:** duplicaría la publicación de tríadas que ya realiza el registro, con otra fuente de verdad para pesos y checkpoints.

## Consecuencias

- Se elimina un contrato HTTP. Un cliente que consulte `/api/model-info` recibe 404; la información equivalente del modelo seleccionado está en `GET /api/models`.
- El arranque ya no intenta cargar checkpoints por nombre de archivo ni crea un dispositivo CUDA al importar `app.main`.
- Las pruebas del estado legacy se retiraron con su código; la atribución de la ejecución conserva su cobertura.
