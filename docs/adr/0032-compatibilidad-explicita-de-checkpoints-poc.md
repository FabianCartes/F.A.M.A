# ADR 0032: Compatibilidad explícita de checkpoints PoC

**Estado:** Aceptado. **Fecha:** 16 de octubre de 2026.

Un benchmark local autorizado encontró un checkpoint que no cargaba en `TrainedModelPredictor`: se construía GeM pese a que el artefacto no tenía ese parámetro. La corrección respeta metadatos explícitos y el contrato del formato PoC existente, no elimina claves ni inventa pesos. Resultados experimentales y fallos conservados: [informe CPU](../modelos/benchmark_local_cpu_20261016.md).

## Decisión

- Si existe `architecture`, conserva prioridad. En su ausencia, se lee `model_type`, como en `poc.evaluate.load_checkpoint_model`. El alias histórico `cnn` instancia `AudioCNN`, no un backbone timm.
- `pool_type` explícito admite avg/gem; null conserva la convención de promedio de `BioacousticModel`. Valores no soportados fallan en carga. No se reduce la verificación estricta de `state_dict` ni se completan parámetros faltantes.
- El formato PoC identificado por `model_type` sin `architecture` conserva el default avg que ya define su lector de evaluación. El formato actual con `architecture` mantiene el default GeM si omite el campo: no se reinterpreta como promedio por detectar una clave ausente. No es una heurística por nombre de archivo/tamaño/tensores faltantes.
- En el recorrido legacy sin `audio_config`, un `n_mels` explícito se usa en vez de ignorarlo y fijar 64. Se valida estrictamente mediante `AudioConfigSchema` (32–256 bandas). Campo ausente conserva 64; malformado/fuera de rango falla, no se sustituye silenciosamente. El contrato completo `audio_config` existente mantiene prioridad.
- La salida clasificada agrega `mel_bands` observado del tensor. Si el filtro devuelve silencio/ruido antes de extraer Mel/ejecutar la red, no se afirma que haya ocurrido ese forward.

## Límites

El modo sin perfil completo sigue identificado como `legacy_librosa`. No se deduce normalización GPU, HPSS, TTA ni física de entrenamiento a partir de un filename o solo `n_mels`; tampoco se validan aquí todas las métricas históricas del catálogo. No se modifica ningún checkpoint, dataset, referencia canónica, estado de activación o política de `registry.py`.

La compatibilidad de carga no prueba exactitud ni garantiza una clasificación: el audio real autorizado terminó en el filtro de ruido sin forward neuronal. Las pruebas sintéticas sí ejercitan clasificación para avg, GeM, bandas declaradas y CNN, incluyendo incompatibilidades que deben seguir fallando. La deserialización del benchmark fue restringida; esta unidad no introduce un bypass inseguro ni una migración de los artefactos históricos.
