# ADR 0003: Pipeline de Datos en Ondas Crudas, Extracción Espectral en GPU y Portabilidad Acelerada Agnóstica

* **Estado:** Aceptado / Implementado  
* **Fecha:** 2026-09-06  
* **Decisores:** Equipo F.A.M.A.  
* **Área:** Arquitectura de Datos, Aceleración por Hardware y Rendimiento MLOps  

---

## 1. Contexto y Problema

Durante el entrenamiento en régimen extendido (35 épocas) de `BioacousticEfficientNet` implementado en la Iteración 7, se evidenció una degradación severa del rendimiento computacional:
1. **Inanición Crítica de GPU (*GPU Starvation*):** El uso de CPU se mantuvo permanentemente en 100% mientras la GPU dedicada (`NVIDIA GeForce RTX 2050 Mobile`) permanecía ociosa más del 75% del tiempo.
2. **Latencia Inaceptable en el Bucle de Entrenamiento:** Cada época tomó ~33.8 segundos, sumando **19 minutos y 46 segundos** para completar 35 épocas.
3. **Causa Raíz Arquitectónica:** `AudioDataset.__getitem__` ejecutaba `extract_mel_spectrogram` (Transformada de Fourier de Tiempo Corto y banco de filtros Mel mediante `librosa` en CPU) de forma síncrona para cada una de las muestras en cada época a través de los workers de `multiprocessing`. Mientras que la inferencia y retropropagación de `BioacousticEfficientNet` en la GPU tomaba ~12–15 ms por lote de 16 muestras, la preparación en CPU tomaba entre 300 y 450 ms.
4. **Riesgo de Incompatibilidad en Hardware Heterogéneo:** El sistema requería funcionar tanto en estaciones de trabajo y notebooks con GPU dedicada NVIDIA como en notebooks portátiles con gráficos integrados (Intel/AMD) sin obligar al usuario a modificar código fuente.

---

## 2. Decisión Arquitectónica

Se aprueba la reestructuración completa del pipeline de ingesta de datos bajo el patrón **Productor Ligero / Consumidor Paralelo en Dispositivo**:

### 2.1. Vectorización de Ondas Crudas en `AudioDataset` (`return_raw_waveform=True`)
* La CPU se descarga de todo procesamiento de señales de Fourier.
* Los workers de CPU ejecutan exclusivamente:
  1. I/O en disco para cargar las ventanas activas precalculadas o aplicar VAD.
  2. Data augmentation estocástico en el dominio del tiempo (*waveform*): desplazamiento temporal (`time_shift`), ganancia aleatoria (`gain`) y ruido gaussiano (`noise`).
* El dataset entrega tensores 1D contiguos de tamaño fijo `[110250]` (5 segundos a 22.050 Hz) en `float32`.
* Se preserva el modo `return_raw_waveform=False` por defecto para garantizar 100% de retrocompatibilidad con tests unitarios legados.

### 2.2. Extracción Espectral en Dispositivo (`GPUAudioFrontEnd`)
* El lote completo de ondas `[B, 110250]` se transfiere al dispositivo (`CUDA` o `CPU`) mediante memoria fijada (`pin_memory=True`, `non_blocking=True`).
* `GPUAudioFrontEnd` (módulo PyTorch basado en `torchaudio.transforms.MelSpectrogram` y `AmplitudeToDB`) computa la STFT, el banco de filtros Mel de 128 bandas (`f_min=800.0 Hz`, `f_max=10000.0 Hz`), la escala logarítmica en decibelios y la normalización Z-score por instancia en VRAM en un único kernel vectorizado:
  $$\mathbf{X}_{\text{norm}} = \frac{\mathbf{X}_{\text{dB}} - \mu}{\sigma + 10^{-6}}$$
* Latencia medida en GPU: **<0.05 ms por lote de 16 audios**.

### 2.3. Data Augmentation Espectral en GPU (`GPUSpecAugment`)
* Se traslada SpecAugment (`FrequencyMasking` y `TimeMasking`) desde la CPU hacia la GPU.
* Se activan máscaras independientes por lote (`iid_masks=True`), eliminando bucles secuenciales en Python y garantizando que cada muestra reciba perturbaciones espectrales únicas.

### 2.4. Portabilidad Agnóstica de Hardware
* La resolución del dispositivo de cálculo se formaliza como:
  ```python
  device_obj = torch.device(device if device is not None else ("cuda" if torch.cuda.is_available() else "cpu"))
  ```
* En entornos sin GPU NVIDIA (`device='cpu'`), `torchaudio` ejecuta operaciones STFT y Mel compiladas nativamente en C++ con vectorización AVX2, corriendo 2 a 3 veces más rápido que `librosa` sin requerir adaptaciones condicionales en el código.

### 2.5. Unificación en Inferencia y Test-Time Augmentation (TTA)
* Se alinea `predict_audio_tta` y `evaluate_test_set` en `backend/poc/evaluate.py` para utilizar exactamente el mismo `GPUAudioFrontEnd`.
* La inferencia TTA apila las $N$ ventanas activas de cada audio en un mini-lote `[N, 110250]` y las proyecta a espectrogramas Mel en paralelo en GPU, acelerando drásticamente el tiempo de evaluación.

---

## 3. Consecuencias y Trade-offs

### Positivas:
* **Aceleración Extrema de Entrenamiento:** El tiempo total de 35 épocas colapsa de **19m 46s** a **04m 45s** (**aceleración de 4.2x**, ~8.0s por época).
* **Eliminación del Cuello de Botella:** La GPU opera de manera continua sin periodos de espera ociosa; el uso de CPU desciende drásticamente permitiendo un sistema receptivo.
* **Superación del Techo de Rendimiento (RDD):** La consistencia en el espacio espectral de 800 a 10.000 Hz entre entrenamiento y prueba impulsó las métricas en el conjunto de prueba independiente (154 muestras con *Zero Recordist Leakage*) a su máximo histórico:
  * **Accuracy:** **83.12%** (+1.30 pp vs Iteración 7).
  * **Macro F1-Score:** **83.76%** (+1.69 pp vs Iteración 7).
  * **Macro Precision:** **85.13%** (alta confiabilidad de predicción).
* **Portabilidad Total:** Ejecución transparente en notebooks educativos sin GPU dedicada.

### Negativas / Riesgos Mitigados:
* **Mayor consumo de VRAM:** Transferir tensores de audio crudo `[B, 110250]` previo a la extracción Mel incrementa temporalmente la memoria de video en ~15 MB por lote, lo cual es despreciable frente a los 4.096 MB disponibles en la GPU.
* **Dependencia de `torchaudio`:** El proyecto asume `torchaudio >= 2.0.0` en `backend/requirements.txt`.
