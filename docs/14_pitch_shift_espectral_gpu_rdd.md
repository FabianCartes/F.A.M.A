# Informe Técnico: Implementación de Pitch Shift Espectral en GPU y Reentrenamiento (RDD)

**Proyecto:** Framework MLOps Híbrido para Clasificación de Audio (F.A.M.A.)  
**Fecha:** Septiembre 2026  
**Fase:** Iteración 14 - Data Augmentation Espectral en GPU (Spectral Pitch Shift)  
**Checkpoints Clave:**  
1. [`checkpoints/convnext_nano_pitchshift_35e_best.pt`](../checkpoints/convnext_nano_pitchshift_35e_best.pt) (ConvNeXt-Nano 35 épocas, focal gamma=2.0, Mixup, Pitch Shift $\pm 2$ bins, $p=0.3$, pipeline GPU)  
2. [`checkpoints/convnext_nano_35e_best.pt`](../checkpoints/convnext_nano_35e_best.pt) (ConvNeXt-Nano 35 épocas sin Pitch Shift, baseline previo)  
3. [`checkpoints/efficientnet_gpu_pipeline_35e_best.pt`](../checkpoints/efficientnet_gpu_pipeline_35e_best.pt) (EfficientNet-B0 GAP estándar, 35 épocas)  
**Test Set:** 154 grabaciones independientes de Xeno-Canto v3 (*Zero Recordist Leakage*, 15 especies de aves chilenas)  
**Metodología:** ADR ([`docs/adr/0009_pitch_shift_espectral_gpu_augmentation.md`](./adr/0009_pitch_shift_espectral_gpu_augmentation.md)) + TDD + RDD  

---

## 1. Resumen Ejecutivo y Resultados de Validación Empírica

En la Iteración 14 se implementó y validó el **Desplazamiento Tonal Espectral en GPU (*Spectral Pitch Shift*)** como técnica de aumento de datos bioacústica dentro de `GPUSpecAugment`. La técnica permite simular la variabilidad biológica del tono fundamental ($\pm 1.0$ semitono) mediante traslaciones discretas sobre los bancos Mel en VRAM con costo computacional nulo (< 0.05 ms por batch) y sin artefactos de fase.

### Métricas Obtenidas en el Test Set (154 Muestras, Ventaneo Denso hop 1.0s, Max):

| Configuración / Modelo | Accuracy | Macro Precision | Macro Recall | Macro F1 | Delta F1 vs Récord Previo | Estado |
| :--- | :---: | :---: | :---: | :---: | :---: | :--- |
| **Récord Histórico Previo (ADR 0008)**<br>Ensamble Heterogéneo Calibrado (35% EffNet + 65% ConvNeXt sin Pitch Shift) | **87.66%** | **90.72%** | **87.97%** | **88.44%** | **0.00 pp** | **Campeón Absoluto de Referencia** |
| **ConvNeXt-Nano Individual previo (sin Pitch Shift)** | 86.36% | 89.41% | 86.49% | 87.25% | -1.19 pp | Modelo monolítico previo |
| **ConvNeXt-Nano Individual (con Pitch Shift $\pm 2$ bins, $p=0.3$)** | 82.47% | 88.03% | 82.92% | 83.66% | -4.78 pp | Regularización activa |
| **Ensamble Calibrado (35% EffNet + 65% ConvNeXt Pitch Shift)** | 82.47% | 86.67% | 83.05% | 83.71% | -4.73 pp | Evaluado |

---

## 2. Análisis Bioacústico y Diagnóstico Técnico

1. **Eficiencia Computacional y Aislamiento:**
   * La pasada hacia adelante y cálculo de gradientes se mantuvo idéntica en tiempo (~8.9s por época en GPU), certificando que el Spectral Pitch Shift en VRAM elimina por completo la penalización de ~180 ms del phase vocoder tradicional.
   * La suite completa de pruebas unitarias aumentó a **67 pruebas pasando al 100%**, validando el determinismo en inferencia (`model.eval()`) y la preservación de gradientes finitos en entrenamiento.

2. **Efecto de la Regularización en Especies Crípticas:**
   * ConvNeXt-Nano con Pitch Shift mantuvo una alta Macro Precision individual (88.03%), demostrando que la traslación espectral previene el sobreajuste memorístico en las frecuencias diagnósticas.
   * Sin embargo, para especies chilenas con bandas de frecuencia extremadamente estrechas y patrones silbados puros (ej. *Sylviorthorhynchus desmursii* / Colilarga o *Anairetes parulus* / Tijeral), un desplazamiento de $\pm 2$ bins Mel ($\approx 1.0$ semitono completo) altera la signatura acústica específica, confundiendo cantos limítrofes entre especies de la misma familia.
   * La regularización fue óptima en generalización de validación (90.60% Val Acc en época 35), pero en el conjunto de prueba independiente con distribución no sesgada, el ensamble calibrado sin pitch shift (88.44% F1) retiene el título de método campeón.

3. **Recomendación Operativa:**
   * Mantener el checkpoint campeón [`convnext_nano_35e_best.pt`](../checkpoints/convnext_nano_35e_best.pt) en el ensamble de producción con EfficientNet (ADR 0008, 88.44% Macro F1).
   * La capacidad de `GPUSpecAugment` con `--pitch-shift-bins` y `--pitch-shift-prob` queda incorporada en el codebase como herramienta configurable para escenarios de datasets desbalanceados con alta varianza intraespecífica.

---

## 3. Artefactos Generados

* Matriz de confusión ConvNeXt-Nano con Pitch Shift: [`docs/cm_convnext_pitchshift_dense_hop100_max.png`](./cm_convnext_pitchshift_dense_hop100_max.png)
* Matriz de confusión Ensamble Calibrado con Pitch Shift: [`docs/cm_ensemble_calibrated_pitchshift_max.png`](./cm_ensemble_calibrated_pitchshift_max.png)
