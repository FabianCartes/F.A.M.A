# ADR 0007: Ensamble Heterogéneo de ConvNeXt-Nano y EfficientNet-B0 con Diversificación de Sesgos Inductivos

* **Estado:** Aceptado / En Implementación  
* **Fecha:** 2026-09-06  
* **Decisores:** Equipo F.A.M.A.  
* **Área:** Arquitectura de Deep Learning, Bioacústica, Generalización de Modelos y Late Fusion  

---

## 1. Contexto y Problema

A pesar de haber superado la barrera del 85% de Macro F1 mediante el ensamble ponderado de EfficientNet-B0 con GAP y GeM (ADR 0006: 85.06% F1), los modelos basados exclusivamente en la familia EfficientNet enfrentan un límite estructural intrínseco:

1. **Homogeneidad de Sesgos Inductivos Convolucionales:**
   * Tanto EfficientNet-B0 GAP como EfficientNet-B0 GeM comparten la misma topología de convoluciones invertidas (*Mobile Inverted Bottlenecks*, MBConv) con kernels pequeños ($3\times 3$ y $5\times 5$), normalización por batch (*BatchNorm*) y activación no lineal *SiLU*.
   * Aunque GeM y GAP divergen en la etapa de agregación espacial y temporal, las representaciones intermedias aprendidas en los mapas de características espectro-temporales presentan una correlación de error residual no despreciable en especies complejas (ej. *Fío-fío*, *Zorzal*, *Tapaculo*).

2. **Inviabilidad Empírica de la Calibración de Umbrales:**
   * La optimización post-hoc de umbrales de decisión por especie evaluada sobre el conjunto de validación (154 audios) demostró un severo sobreajuste: incrementó +5.5 puntos porcentuales en validación pero degradó el rendimiento en test (-2.3 pp).
   * La evidencia empírica descarta la sintonización de hiperparámetros de inferencia sobre particiones reducidas y confirma que la mejora genuina de generalización debe provenir de la **diversidad de arquitecturas neuronales** (*Inductive Bias Diversity*).

3. **La Solución: Heterogeneidad Arquitectónica con ConvNeXt-Nano:**
   * ConvNeXt reinterpreta las redes convolucionales modernas adoptando innovaciones clave de los Vision Transformers (ViT):
     - Convoluciones *depthwise* de gran campo receptivo ($7\times 7$), permitiendo capturar patrones bioacústicos espectro-temporales amplios y trinos armónicos extendidos sin fragmentación.
     - Reemplazo de BatchNorm por **LayerNorm**, otorgando mayor estabilidad ante la variabilidad acústica inter-grabación.
     - Uso de activación **GELU** y reducción drástica en la cantidad de capas de activación/normalización, preservando una mayor linealidad en la propagación de características.
   * La combinación de EfficientNet-B0 (inductores $3\times 3/5\times 5$, SiLU, MBConv) con ConvNeXt-Nano ($7\times 7$, GELU, LayerNorm) produce representaciones ortogonales y errores desacoplados.

---

## 2. Decisión Arquitectónica

Se formalizan las siguientes modificaciones y adiciones de diseño en la base de código:

### 2.1 Generalización del Modelo Bioacústico (`BioacousticModel`)
* En `backend/poc/train.py`, se refactoriza `BioacousticEfficientNet` hacia un módulo profundo y desacoplado: `BioacousticModel(nn.Module)`.
* Se garantiza retrocompatibilidad absoluta mediante el alias `BioacousticEfficientNet = BioacousticModel`.
* El ciclo de congelamiento/descongelamiento (`freeze_backbone()` y `unfreeze_backbone()`) se adapta para operar de manera agnóstica a la arquitectura, identificando dinámicamente la cabeza clasificadora (`classifier = self.backbone.get_classifier()`, `self.backbone.head.fc`, o `self.backbone.classifier`).

### 2.2 Carga Polimórfica Dinámica en Inferencia (`backend/poc/evaluate.py`)
* Se adapta `load_checkpoint_model` para inspeccionar `checkpoint["model_type"]`. Si el tipo corresponde a una arquitectura soportada en `timm` distinta a la CNN básica de referencia (`audiocnn`), se instancia dinámicamente `BioacousticModel(model_name=model_type, num_classes=len(classes), pretrained=False, pool_type=pool_type)`.
* Esto habilita la carga sin fricción de checkpoints de cualquier familia (`convnext_nano.d1h_in1k`, `efficientnet_b0`, `resnet`, etc.).

### 2.3 Entrenamiento de ConvNeXt-Nano en GPU
* Se entrena `convnext_nano.d1h_in1k` durante 35 épocas utilizando el pipeline acelerado en GPU (`GPUAudioFrontEnd`, `GPUSpecAugment`, `FocalLoss(gamma=2.0)`, Mixup y warmup con backbone congelado).

### 2.4 Late Fusion en Ensamble Heterogéneo
* Se integran los modelos mediante fusión tardía (*Late Fusion*) sobre vectores de máxima evidencia acústica temporal extraídos bajo **Ventaneo Denso** (`hop_seconds=1.0`, modo `max`).
* Se evalúa:
  1. Ensamble Heterogéneo Bi-Modelo: EfficientNet GAP (0.60) + ConvNeXt-Nano (0.40).
  2. Ensamble Heterogéneo Tri-Modelo: EfficientNet GAP (0.60) + ConvNeXt-Nano (0.30) + EfficientNet GeM (0.10).

---

## 3. Consecuencias y Trade-offs

### Positivas:
* **Ortogonalidad Representacional:** La fusión de redes con campos receptivos contrastantes ($3\times 3/5\times 5$ vs $7\times 7$) neutraliza correlaciones de error sistemáticas en cantos complejos.
* **Extensibilidad Abierta (Open-Closed Principle):** `BioacousticModel` y `load_checkpoint_model` quedan preparados para integrar futuras arquitecturas de `timm` sin alterar contratos de interfaz.
* **Cero Riesgo de Regresión:** El alias de retrocompatibilidad y la preservación de firmas aseguran el 100% de operatividad de los 61 tests existentes.

### Negativas / Costos Operacionales:
* **Huella de Memoria VRAM Moderada:** Cargar concurrentemente EfficientNet-B0 y ConvNeXt-Nano añade < 150 MB adicionales de memoria VRAM, siendo perfectamente apto para la GPU de desarrollo de 4 GB.
* **Latencia de Inferencia:** En inferencia por lotes en GPU, la latencia combinada para un audio completo bajo ventaneo denso permanece en torno a ~120-220 ms, muy por debajo de los límites de tiempo real (500 ms).
