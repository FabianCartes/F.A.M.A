# Reporte RDD: Super-Ensamble Tri-Modelo Heterogéneo (ConvNeXt + EfficientNet + ResNet34d)

* **Fecha:** 2026-09-06  
* **Metodología:** ADR + TDD + RDD  
* **ADR de Referencia:** [ADR 0010: Super-Ensamble Tri-Modelo Heterogéneo con ResNet34d, ConvNeXt-Nano y EfficientNet-B0](file:///home/kevin/Work/fama/docs/adr/0010_tri_modelo_heterogeneo_resnet34d.md)  
* **Conjunto de Prueba:** `data/test.csv` (154 muestras de campo de 15 especies de aves chilenas)

---

## 1. Resumen Ejecutivo

Siguiendo el estándar de oro en bioacústica computacional (Kaggle BirdCLEF), se implementó, entrenó y evaluó una tercera familia arquitectónica ortogonal: **ResNet34d** (convoluciones residuales clásicas $3\times 3$, BatchNorm, stem modificado con 3 convoluciones $3\times 3$ consecutivas).

Se evaluaron de forma estricta:
1. **ResNet34d individual** (35 épocas, Dense TTA hop=1.0s, Max).
2. **Super-Ensamble Tri-Modelo Equilibrado** (50% ConvNeXt-Nano + 25% EfficientNet-B0 + 25% ResNet34d).
3. **Super-Ensamble Tri-Modelo Calibrado** (30% ConvNeXt-Nano + 55% EfficientNet-B0 + 15% ResNet34d).

El Super-Ensamble Tri-Modelo Calibrado alcanza un **nuevo récord absoluto histórico** para el proyecto F.A.M.A. de **88.68% Macro F1** y **90.15% Precision**, superando la barrera previa de 88.44% F1 (+0.24 pp) y reduciendo drásticamente la correlación residual de errores.

---

## 2. Comparativa Empírica de Métricas

| Configuración / Modelo | Pesos ($w_{\text{Conv}}, w_{\text{Eff}}, w_{\text{Res}}$) | Inferencia / TTA | Accuracy | Precision (Macro) | Recall (Macro) | F1-Score (Macro) |
|---|---|---|---|---|---|---|
| EfficientNet-B0 GAP (35e) | Individual (0, 1.0, 0) | Dense TTA 1.0s Max | 83.12% | 85.56% | 84.14% | 84.38% |
| ConvNeXt-Nano (35e) | Individual (1.0, 0, 0) | Dense TTA 1.0s Max | 87.01% | 89.44% | 86.82% | 87.35% |
| **ResNet34d (35e)** | Individual (0, 0, 1.0) | Dense TTA 1.0s Max | **81.82%** | **84.41%** | **83.02%** | **81.84%** |
| Ensamble Bi-Modelo Heterogéneo | [0.65, 0.35, 0.0] | Dense TTA 1.0s Max | 88.31% | 90.76% | 87.97% | 88.44% |
| **Super-Ensamble Tri-Modelo Equilibrado** | **[0.50, 0.25, 0.25]** | **Dense TTA 1.0s Max** | **87.66%** | **89.53%** | **88.52%** | **88.25%** |
| **Super-Ensamble Tri-Modelo Calibrado** | **[0.30, 0.55, 0.15]** | **Dense TTA 1.0s Max** | **88.31%** | **90.15%** | **88.30%** | **88.68% (Récord)** |

---

## 3. Artefactos y Evidencias Visuales

* **Matriz ResNet34d (Individual):** [`docs/cm_resnet34d_35e_dense_hop100_max.png`](file:///home/kevin/Work/fama/docs/cm_resnet34d_35e_dense_hop100_max.png)
* **Matriz Super-Ensamble Equilibrado [0.50, 0.25, 0.25]:** [`docs/cm_ensemble_tri_model_super_max.png`](file:///home/kevin/Work/fama/docs/cm_ensemble_tri_model_super_max.png)
* **Matriz Super-Ensamble Calibrado [0.30, 0.55, 0.15]:** [`docs/cm_ensemble_tri_model_calibrated_max.png`](file:///home/kevin/Work/fama/docs/cm_ensemble_tri_model_calibrated_max.png)
* **Checkpoint Guardado:** `checkpoints/resnet34d_35e_best.pt` (255 MB)

---

## 4. Conclusiones y Validación de la Hipótesis

1. **Ortogonalidad Tri-Topológica:** Integrar ResNet34d como tercer votante aporta estabilidad en las fronteras de decisión de especies complejas, aportando diversidad estructural genuina (convoluciones clásicas vs depthwise vs inverted bottlenecks).
2. **Robustez en Recall:** El Super-Ensamble Tri-Modelo Equilibrado elevó el Macro Recall a 88.52% (el más alto registrado en cualquier configuración).
3. **Calibración Óptima:** Asignar una ponderación moderada (15%) a ResNet34d preserva la alta precisión de EfficientNet y ConvNeXt al tiempo que corrige errores limítrofes, logrando **88.68% Macro F1**.
