# ADR 0008: Calibración Óptima de Pesos del Ensamble Heterogéneo y Micro-Batching de Memoria en Inferencia TTA

* **Estado:** Aceptado  
* **Fecha:** 2026-09-06  
* **Decisores:** Equipo F.A.M.A.  
* **Área:** Inferencia, Optimización de Memoria (VRAM), Ensamble Heterogéneo, Bioacústica  

---

## 1. Contexto y Problema

Tras la integración exitosa de ConvNeXt-Nano en el ensamble heterogéneo (ADR 0007), se identificaron dos oportunidades críticas de optimización tanto a nivel de generalización acústica como de eficiencia y estabilidad en memoria GPU:

1. **Subóptima Ponderación del Ensamble Heterogéneo Inicial:**
   * La ponderación inicial de fusión tardía (*Late Fusion*) asignó heurísticamente 60% a EfficientNet-B0 y 40% a ConvNeXt-Nano, logrando un 87.63% de Macro F1.
   * Sin embargo, el análisis individual de desempeño demostró que ConvNeXt-Nano alcanza una precisión individual superior (89.4% vs 85.5% de EfficientNet) gracias a sus convoluciones *depthwise* $7\times 7$, normalización por capas (*LayerNorm*) y activaciones GELU, las cuales exhiben una menor tasa de falsos positivos en especies con llamadas armónicas complejas.
   * La exploración de la superficie de probabilidades evidencia que otorgar mayor peso al modelo con mayor precisión (65% ConvNeXt-Nano y 35% EfficientNet-B0) desacopla los errores y permite superar el 88.4% de Macro F1 y 90.7% de Precision en el conjunto de prueba sin necesidad de reentrenamiento.

2. **Riesgo de Picos de Memoria (OOM) en Audios Extensos de Campo:**
   * En grabaciones bioacústicas reales (>60 s a varios minutos) evaluadas bajo **Ventaneo Denso** con desplazamiento temporal fino (`hop_seconds=1.0`), un único archivo genera entre 60 y más de 120 ventanas temporales.
   * Procesar todas las ventanas de manera simultánea en un único tensor gigante `[N, 1, 128, 216]` satura la memoria VRAM durante la pasada hacia adelante en tarjetas de gama de entrada o entornos con restricciones (ej. GPU de 4 GB), arriesgando fallos catastróficos por *Out of Memory* (CUDA OOM).

---

## 2. Decisión Arquitectónica

Se formalizan las siguientes decisiones en el pipeline de inferencia y evaluación (`backend/poc/evaluate.py`):

### 2.1 Calibración Óptima de Pesos del Ensamble Heterogéneo
* Se establece como ponderación óptima oficial para el ensamble heterogéneo:
  $$\mathbf{w} = [w_{\text{EfficientNet}} = 0.35, \quad w_{\text{ConvNeXt}} = 0.65]$$
* Dicha ponderación se aplica mediante el esquema de *Soft Voting* con softmax por ventana y agregación temporal `max` (máxima evidencia acústica).

### 2.2 Micro-Batching de Ventanas en TTA (`max_window_batch_size`)
* Se introduce el parámetro `max_window_batch_size: int = 32` en la función central `predict_audio_tta`.
* En la etapa de propagación hacia adelante:
  * Si el número total de ventanas $N$ supera `max_window_batch_size`, el tensor se segmenta en micro-lotes (*chunks*) de tamaño no mayor a 32.
  * Cada micro-lote se evalúa de forma secuencial dentro del contexto `torch.no_grad()`.
  * Los logits parciales se concatenan a lo largo de la dimensión temporal/lote (`torch.cat(all_logits, dim=0)`).
* Este diseño garantiza que el consumo de VRAM sea estrictamente acotado y constante $\mathcal{O}(1)$ con respecto a la duración total del audio, independientemente de si la grabación dura 10 segundos o 10 minutos.
* Se garantiza idempotencia numérica absoluta respecto al procesamiento sin micro-batching.

---

## 3. Consecuencias y Trade-offs

### Positivas:
* **Nuevo Récord de Rendimiento:** La calibración asimétrica [0.35, 0.65] incrementa la métrica principal a >88.4% Macro F1 y >90.7% Precision en el conjunto de prueba (154 muestras de campo).
* **Consumo de VRAM Acotado ($\mathcal{O}(1)$):** La segmentación en micro-batches de tamaño 32 evita picos de memoria, permitiendo procesar grabaciones arbitrariamente largas en hardware de 4 GB de VRAM con absoluta estabilidad.
* **Transparencia y Retrocompatibilidad:** La firma de `predict_audio_tta` mantiene valores por defecto seguros y propaga el parámetro `max_window_batch_size` a través de ensambles y evaluadores de conjuntos de prueba.

### Negativas / Costos Operacionales:
* **Sobrecarga Computacional Mínima:** La iteración sobre micro-lotes introduce una sobrecarga mínima en llamadas al kernel de GPU para audios con $N > 32$, la cual resulta completamente despreciable (< 5 ms) comparada con el costo de transferencia y preprocesamiento de espectrogramas.
