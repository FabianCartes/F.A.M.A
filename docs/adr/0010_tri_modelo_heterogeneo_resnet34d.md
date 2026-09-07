# ADR 0010: Super-Ensamble Tri-Modelo Heterogéneo con ResNet34d, ConvNeXt-Nano y EfficientNet-B0 para Máxima Robustez Bioacústica

* **Estado:** Aceptado / En Implementación  
* **Fecha:** 2026-09-06  
* **Decisores:** Equipo F.A.M.A.  
* **Área:** Arquitectura de Deep Learning, Bioacústica, Fusión de Modelos y Ensamble Heterogéneo  

---

## 1. Contexto y Problema

El ensamble heterogéneo bi-modelo actual (ADR 0007 y ADR 0008) combina EfficientNet-B0 (35%) y ConvNeXt-Nano (65%) bajo ventaneo denso (`hop_seconds=1.0s`, modo `max`), estableciendo un desempeño de referencia de **88.44% Macro F1** y **90.72% Precision** sobre el conjunto de prueba independiente de 154 grabaciones.

No obstante, en bioacústica computacional de alta fidelidad y competiciones de referencia internacional (estándar Kaggle BirdCLEF), la literatura y la práctica empírica demuestran que limitar la combinación a dos arquitecturas aún deja margen para correlación de errores en escenarios de alta interferencia acústica (viento, solapamiento biológico y llamadas crípticas). Para alcanzar la máxima robustez y desacoplamiento estadístico de errores, se recomienda fusionar tres familias topológicamente ortogonales:

1. **Inverted Residuals con Convoluciones $3\times 3$ / $5\times 5$ y SiLU (EfficientNet-B0):**
   * Extrae patrones espectro-temporales compactos con compresión intermedia y reponderación adaptativa de canales (Squeeze-and-Excitation).
2. **Large-Kernel $7\times 7$ Depthwise Convolutions con LayerNorm y GELU (ConvNeXt-Nano):**
   * Emula la visión espacial de los Vision Transformers (ViTs) con gran campo receptivo, alta capacidad para modelar armónicos prolongados y estabilidad ante fluctuaciones de amplitud global.
3. **Convoluciones Residuales Clásicas $3\times 3$ con Batch Normalization y ReLU/SiLU (ResNet34d):**
   * La variante `resnet34d` introduce una modificación fundamental en el bloque *downsampling* (stem con 3 convoluciones $3\times 3$ en lugar de una de $7\times 7$, y pooling adaptativo con *stride* de convolución desacoplado), ofreciendo preservación rigurosa de gradientes y bordes de alta frecuencia en espectrogramas Mel.

---

## 2. Decisión Arquitectónica

Se aprueba y ejecuta la siguiente estrategia de extensión y evaluación empírica:

### 2.1 Soporte Integral de ResNet34d en `BioacousticModel`
* Incorporar formalmente `resnet34d` en la abstracción `BioacousticModel`, validando el ciclo de vida de congelamiento/descongelamiento de capas (`freeze_backbone()` / `unfreeze_backbone()`) mediante el identificador polimórfico de la capa clasificadora lineal (`model.backbone.get_classifier()` / `model.backbone.fc`).
* Garantizar que `load_checkpoint_model` en `backend/poc/evaluate.py` cargue e instancie checkpoints generados con `model_type="resnet34d"` de forma transparente.

### 2.2 Entrenamiento de ResNet34d en GPU Acelerada
* Entrenar `resnet34d` durante 35 épocas utilizando el pipeline completo acelerado en GPU:
  * Extracción directa de espectrogramas Mel en GPU (`n_mels=128`, `f_min=800`, `f_max=10000`).
  * Aumentación en GPU con `GPUSpecAugment` y Mixup Aditivo Espectral ($\alpha = 0.2$, $p = 0.5$).
  * Optimización con `FocalLoss` ($\gamma = 2.0$) para balancear clases difíciles.
  * Estrategia Warmup de 3 épocas con backbone congelado seguido de fine-tuning completo con AdamW.

### 2.3 Evaluación Individual y Super-Ensamble Tri-Modelo
* Evaluar `resnet34d` de forma individual sobre `data/test.csv` (154 audios) empleando **Dense TTA** (`hop_seconds=1.0`, agregación `max`).
* Evaluar el **Super-Ensamble Tri-Modelo Heterogéneo** (ConvNeXt-Nano + EfficientNet-B0 + ResNet34d) integrando Late Fusion y agregación de probabilidades por ventana temporal con pesos calibrados:
  $$\mathbf{w} = [w_{\text{ConvNeXt}} = 0.50, \quad w_{\text{EfficientNet}} = 0.25, \quad w_{\text{ResNet34d}} = 0.25]$$
* Contrastar empíricamente si la inclusión de una tercera familia ortogonal reduce los falsos positivos y supera el umbral de 88.44% Macro F1.

---

## 3. Consecuencias y Trade-offs

### Positivas:
* **Ortogonalidad Tri-Familiar de Errores:** Se desacoplan las representaciones convolucionales profundas entre tres inductores conceptualmente distintos (Inverted Residuals vs Large-Kernel Depthwise vs Deep Residuals Clásicos con stem modificado).
* **Cero Impacto en Regresiones:** El módulo `BioacousticModel` y `load_checkpoint_model` mantienen interfaces limpias y retrocompatibles, preservando el 100% de la suite de pruebas unitarias.
* **Consumo de Memoria VRAM Eficiente:** La carga combinada en GPU de los tres modelos (`convnext_nano`, `efficientnet_b0`, `resnet34d`) no supera los 200 MB de memoria de pesos, permitiendo inferencias fluidas incluso en hardware modesto.
* **Inferencia en Tiempo Real:** Bajo ventaneo denso y micro-batching (`max_window_batch_size=32`), la evaluación combinada de los tres modelos se ejecuta en < 150 ms por audio completo en GPU.

### Negativas / Consideraciones:
* **Tiempo de Entrenamiento Adicional:** Entrenar una red adicional de 34 capas requiere ~3-5 minutos en GPU, lo cual se realiza una única vez offline.
* **Coordinación de Checkpoints:** El pipeline de inferencia debe gestionar tres archivos de pesos en simultáneo para el super-ensamble.
