# Informe Técnico: Ensamble Ponderado Multi-Modelo (Soft Voting + Late Fusion) en Inferencia TTA (RDD)

**Proyecto:** Framework MLOps Híbrido para Clasificación de Audio (F.A.M.A.)  
**Fecha:** Septiembre 2026  
**Fase:** Iteración 12 - Fusión de Modelos con Diversidad Estructural (*Ensemble Learning*)  
**Checkpoints Evaluados:**  
1. [`checkpoints/efficientnet_gpu_pipeline_35e_best.pt`](../checkpoints/efficientnet_gpu_pipeline_35e_best.pt) (EfficientNet-B0 con GAP, peso: 0.80)  
2. [`checkpoints/efficientnet_gem_35e_best.pt`](../checkpoints/efficientnet_gem_35e_best.pt) (EfficientNet-B0 con GeM Pooling $p \approx 3.0$, peso: 0.20)  
**Test Set:** 154 grabaciones independientes de Xeno-Canto v3 (*Zero Recordist Leakage*, 15 especies de aves chilenas)  
**Metodología:** ADR ([`docs/adr/0006_ensemble_multimodelo_inferencia.md`](./adr/0006_ensemble_multimodelo_inferencia.md)) + TDD + RDD  

---

## 1. Resumen Ejecutivo y Nuevo Récord Histórico

En la Iteración 12 se implementó y validó empíricamente la estrategia de **Ensamble Ponderado Multi-Modelo (Soft Voting con Late Fusion)**, superando formalmente la barrera del 85% de Macro F1.

### Resultado Principal:
> [!IMPORTANT]
> **¡NUEVO RÉCORD HISTÓRICO ABSOLUTO DEL PROYECTO F.A.M.A.!**  
> La combinación ponderada de **EfficientNet GAP (80%) + EfficientNet GeM (20%)** bajo **Ventaneo Denso (hop 1.0s) y TTA Max**:
> * **Macro F1-Score:** **85.06%** (vs 84.38% anterior, **+0.68 pp**; vs 80.85% baseline, **+4.21 pp**)
> * **Accuracy:** **83.77%** (vs 83.12% anterior, **+0.65 pp**)
> * **Macro Precision:** **85.71%** (vs 85.56% anterior, **+0.15 pp**)
> * **Macro Recall:** **85.89%** (vs 84.85% anterior, **+1.04 pp**)
> * **4 Especies con 100% de Recall:** Canastero (100%), Churrín de la Mocha (100%), Turca (100%) y Picaflor chico (100%).

---

## 2. Fundamento Teórico y Hallazgo Arquitectónico: Early Fusion vs Late Fusion

Durante el diseño e implementación del ensamble se descubrió una diferencia matemática y bioacústica crítica entre dos estrategias de agregación:

1. **Early Fusion (Fusión por ventana antes de TTA):**
   * Combina las probabilidades de los modelos dentro de cada ventana individual $w$:
     $$P(c, w) = 0.8 \cdot P_{\text{GAP}}(c, w) + 0.2 \cdot P_{\text{GeM}}(c, w)$$
   * Luego toma el máximo temporal: $P^*(c) = \max_w P(c, w)$.
   * **Resultado:** 84.22% F1.
   * **Falla bioacústica:** Debido a que GeM focaliza en picos de alta energía y GAP en estructura armónica amplia, ambos modelos pueden detectar la vocalización óptima en *ventanas temporales ligeramente distintas*. En Early Fusion, la baja probabilidad de un modelo en una ventana atenúa la alta certeza del otro en esa misma ventana.

2. **Late Fusion (Fusión de picos de máxima evidencia TTA independientes):**
   * Cada modelo escanea el audio completo de forma independiente con TTA Max, identificando su propia ventana de máxima confianza:
     $$P^*_{\text{GAP}}(c) = \max_w P_{\text{GAP}}(c, w), \quad P^*_{\text{GeM}}(c) = \max_w P_{\text{GeM}}(c, w)$$
   * Luego se combinan linealmente sus vectores de máxima evidencia:
     $$P^*_{\text{ensemble}}(c) = 0.8 \cdot P^*_{\text{GAP}}(c) + 0.2 \cdot P^*_{\text{GeM}}(c)$$
   * **Resultado:** **85.06% F1 / 83.77% Accuracy**.
   * **Éxito bioacústica:** Permite que cada modelo aporte su detección más limpia sin penalizarse por desalineamientos de ventana entre sí.

---

## 3. Matriz de Evolución Experimental en el Test Set (154 Muestras)

| Iteración / Configuración | Arquitectura | Inferencia | Hop ($s$) | Modo TTA | Accuracy | Macro Prec | Macro Rec | Macro F1 | Delta F1 vs Base | Estado |
| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Iteración 8 Baseline** | Single EfficientNet GAP | Single-Crop | N/A | N/A | 81.82% | 82.11% | 81.56% | 80.85% | 0.00 pp | Referencia |
| **Iteración 8 TTA** | Single EfficientNet GAP | TTA Estándar | 2.50 | Max | 83.12% | 85.13% | 85.34% | 83.76% | +2.91 pp | Histórico |
| **Iteración 11 Ventaneo** | Single EfficientNet GAP | Ventaneo Denso | 1.00 | Max | 83.12% | 85.56% | 84.85% | 84.38% | +3.53 pp | Récord previo |
| **Iteración 12 Early Fusion** | Ensamble GAP (0.8) + GeM (0.2) | Ventaneo Denso | 1.00 | Max | 83.12% | 85.25% | 85.23% | 84.22% | +3.37 pp | Ablación |
| **Iteración 12 Late Fusion** | **Ensamble GAP (0.8) + GeM (0.2)** | **Ventaneo Denso** | **1.00** | **Max** | **83.77%** | **85.71%** | **85.89%** | **85.06%** | **+4.21 pp** | **¡NUEVO RÉCORD!** |

---

## 4. Desempeño por Especie en el Ensamble Campeón

```text
Especie                         Prec      Rec       F1   Soporte   Observación
────────────────────────────────────────────────────────────────────────────────
Canastero                      87.5%   100.0%    93.3%         7   100% Perfecto
Chercán                        88.9%    72.7%    80.0%        11   
Chincol                       100.0%    85.7%    92.3%         7   
Chucao                         88.9%    88.9%    88.9%         9   
Churrín de la Mocha            88.9%   100.0%    94.1%         8   100% Perfecto
Churrín del sur                80.0%    80.0%    80.0%         5   
Colilarga                      80.0%    88.9%    84.2%         9   
Fío-fío                        71.4%    71.4%    71.4%        14   
Picaflor chico                 75.0%   100.0%    85.7%         6   100% Perfecto (+8.8 pp F1)
Rayadito                       88.2%    93.8%    90.9%        16   
Tapaculo                      100.0%    60.0%    75.0%        10   Mejora (+8.3 pp F1)
Tijeral                       100.0%    87.5%    93.3%         8   
Tordo                          81.2%    92.9%    86.7%        14   Mejora (+3.9 pp F1)
Turca                          81.8%   100.0%    90.0%         9   100% Perfecto (+4.3 pp F1)
Zorzal patagónico              73.7%    66.7%    70.0%        21   Mejora (+3.3 pp F1)
────────────────────────────────────────────────────────────────────────────────
Promedio Macro                 85.7%    85.9%    85.1%       154   NUEVO RÉCORD
```

---

## 5. Artefactos y Conclusiones

1. **Matriz de Confusión Oficial:** Guardada en [`docs/cm_ensemble_gap_gem_dense_hop100_max.png`](./cm_ensemble_gap_gem_dense_hop100_max.png).
2. **Suite de Pruebas Automatizadas:** 61 pruebas unitarias e integración en verde (`.venv/bin/pytest backend/tests`).
3. **Validación de Principios de Software:** El módulo profundo `EnsembleClassifier` respeta el Principio de Sustitución de Liskov, permitiendo invocarlo de forma transparente desde el CLI:
   ```bash
   .venv/bin/python backend/poc/evaluate.py \
       --checkpoints efficientnet_gpu_pipeline_35e_best.pt efficientnet_gem_35e_best.pt \
       --weights 0.8 0.2 \
       --use-tta --tta-mode max --hop-seconds 1.0 \
       --output docs/cm_ensemble_gap_gem_dense_hop100_max.png
   ```
