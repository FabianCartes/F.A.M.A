# ADR 0021: Preprocesamiento efectivo en checkpoints de entrenamiento web

**Estado:** Aceptado. **Fecha:** 11 de octubre de 2026.

El entrenamiento web calculaba Mel normalizado parametrizable, pero su predictor usaba constantes bioacústicas y Mel librosa sin esa normalización. Guardar la petición original tampoco conservaba los defaults efectivos. Los nuevos checkpoints guardan los siete campos acústicos efectivos y un perfil de preprocesamiento versionado; inferencia reproduce esa representación y el catálogo anuncia su frecuencia y duración.

## Decisión y alternativas

- `audio_config` contiene `target_sr`, `duration_seconds`, `n_mels`, `n_fft`, `hop_length`, `f_min` y `f_max`. Se guardan los valores usados, incluso cuando la petición omite campos.
- `preprocessing` versión 1 declara `frontend=gpu_mel_zscore`, con el mismo `GPUAudioFrontEnd` utilizado al entrenar. `window_selection=max_rms` reproduce `GenericAudioDataset`; `active_max_rms` reproduce la validación de `AudioDataset`, con hop 2,5 s y VAD relativo de 25 dB. No se cambia el muestreo del entrenamiento.
- El predictor rechaza configuración explícita incompleta/invalidada y perfiles no soportados mediante `ModelWeightsError`; no interpreta un perfil desconocido como una configuración bioacústica por defecto.
- Un checkpoint anterior con configuración completa y sin perfil conserva el recorrido genérico parametrizado. Uno sin configuración, o con `audio_config=null`, conserva el recorrido histórico de librosa a 22.050 Hz/5 s/64 bandas, identificado en el resultado como `preprocessing_mode=legacy_librosa`.
- Se descarta reinterpretar todos los pesos históricos con el nuevo frontend: no hay evidencia de que se entrenaran con esa representación. También se descarta inferir física por clases, ID o nombre de archivo. La compatibilidad legacy mantiene el comportamiento anterior, **no acredita coherencia con su entrenamiento ni calidad**.

## Consecuencias y límites

La configuración explícita puede cambiar predicciones previamente producidas con un frontend incorrecto. Pesos antiguos con configuración parcial requieren recuperar su procedencia, no completar el contrato por conjetura. No se modifica, migra ni reentrena ningún artefacto existente.

Este contrato corresponde a `TrainingService` y `TrainedModelPredictor`: no actualiza bundles, ensambles estáticos ni las fichas técnicas históricas de `get_history`. No incorpora HPSS, calibración, TTA configurable ni una nueva composición de ensambles.

Evidencia: pruebas de interfaces públicas con CPU, redes pequeñas en el adaptador externo timm, WAV sintéticos y SQLite temporal; ciclos RED/GREEN en metadatos, representación espectral, defaults, selección temporal y rechazos. Regresión final acotada: **84 aprobadas, cero fallos/omisiones/avisos**. No acredita calidad acústica, GPU, servicios reales ni despliegue. Seguimiento en [KANBAN.md](../KANBAN.md).
