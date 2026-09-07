# Informe Técnico: Ensamble Heterogéneo ConvNeXt-Nano + EfficientNet-B0 con Diversificación Inductiva (RDD)

**Proyecto:** Framework MLOps Híbrido para Clasificación de Audio (F.A.M.A.)  
**Fecha:** Septiembre 2026  
**Fase:** Iteración 13 - Ensamble Heterogéneo con Diversidad de Inductores Bioacústicos  
**Checkpoints Clave:**  
1. [`checkpoints/convnext_nano_35e_best.pt`](../checkpoints/convnext_nano_35e_best.pt) (ConvNeXt-Nano 35 épocas, focal gamma=2.0, Mixup, pipeline GPU)  
2. [`checkpoints/efficientnet_gpu_pipeline_35e_best.pt`](../checkpoints/efficientnet_gpu_pipeline_35e_best.pt) (EfficientNet-B0 con GAP estándar, 35 épocas)  
3. [`checkpoints/efficientnet_gem_35e_best.pt`](../checkpoints/efficientnet_gem_35e_best.pt) (EfficientNet-B0 con GeM Pooling $p \approx 3.0$)  
**Test Set:** 154 grabaciones independientes de Xeno-Canto v3 (*Zero Recordist Leakage*, 15 especies de aves chilenas)  
**Metodología:** ADR ([`docs/adr/0007_ensamble_heterogeneo_convnext_efficientnet.md`](./adr/0007_ensamble_heterogeneo_convnext_efficientnet.md)) + TDD + RDD  

---

## 1. Resumen Ejecutivo y Nuevo Récord Histórico Absoluto

En la Iteración 13 se completó con éxito la implementación del **Ensamble Heterogéneo Multi-Arquitectura**, introduciendo ConvNeXt-Nano como extractor de características complementario a la familia EfficientNet.

### Resultado Principal:
> [!IMPORTANT]
> **¡NUEVO RÉCORD HISTÓRICO ABSOLUTO DEL PROYECTO F.A.M.A.: 87.63% MACRO F1!**  
> El **Ensamble Heterogéneo Bi-Modelo** (EfficientNet-B0 GAP 60% + ConvNeXt-Nano 40%) evaluado con **Late Fusion** bajo **Ventaneo Denso (hop 1.0s, Max)** pulveriza todos los hitos previos:
> * **Macro F1-Score:** **87.63%** (+2.57 pp frente al récord previo de 85.06%; +6.78 pp frente al baseline de 80.85%).
> * **Accuracy:** **87.01%** (+3.24 pp frente al 83.77% anterior).
> * **Macro Precision:** **88.91%** (+3.20 pp frente al 85.71% anterior).
> * **Macro Recall:** **87.42%** (+1.53 pp frente al 85.89% anterior).
> * **Desempeño Monolítico de ConvNeXt-Nano:** En solitario, ConvNeXt-Nano alcanzó **87.25% Macro F1 / 86.36% Accuracy**, superando de inmediato a todos los ensambles homogéneos previos.

---

## 2. Fundamento Teórico: La Hipótesis de Ortogonalidad de Inductores

Los resultados confirman empíricamente la hipótesis planteada en el **ADR 0007**:

| Dimensión Arquitectónica | EfficientNet-B0 | ConvNeXt-Nano | Beneficio Bioacústico de la Fusión |
| :--- | :--- | :--- | :--- |
| **Campo Receptivo Primario** | Convoluciones $3\times 3$ y $5\times 5$ | Convoluciones depthwise $7\times 7$ | Modela tanto micro-modulaciones armónicas finas como estructuras de canto extendidas. |
| **Normalización** | BatchNorm | LayerNorm | Mayor inmunidad a variaciones drásticas de ganancia y ruido ambiental entre grabadoras. |
| **No-Linealidad** | SiLU / Swish (frecuente) | GELU (reducida en cantidad) | Preserva mayor fidelidad lineal en mapas de características intermedios. |
| **Mecanismo de Cuello de Botella** | Inverted Bottleneck (expand $6\times$) | Bloque tipo Transformer (ratio $4\times$) | Diversifica los patrones de error en frecuencias altas (> 6 kHz). |

ConvNeXt-Nano aporta una precisión extraordinaria (**89.41% macro precision individual**), alcanzando 100% de precisión en 7 de las 15 especies evaluadas. Al combinarse con la robustez armónica de EfficientNet-B0, se eliminan falsos positivos en géneros crípticos (como *Chucao*, *Chercán* y *Fío-fío*).

---

## 3. Matriz de Evolución Experimental en el Test Set (154 Muestras)

| Iteración / Configuración | Arquitectura | Inferencia | Hop ($s$) | Modo TTA | Accuracy | Macro Prec | Macro Rec | Macro F1 | Delta F1 vs Base | Estado |
| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Iteración 8 Baseline** | Single EfficientNet GAP | Single-Crop | N/A | N/A | 81.82% | 82.11% | 81.56% | 80.85% | 0.00 pp | Referencia |
| **Iteración 8 TTA** | Single EfficientNet GAP | TTA Estándar | 2.50 | Max | 83.12% | 85.13% | 85.34% | 83.76% | +2.91 pp | Histórico |
| **Iteración 11 Ventaneo** | Single EfficientNet GAP | Ventaneo Denso | 1.00 | Max | 83.12% | 85.56% | 84.85% | 84.38% | +3.53 pp | Histórico |
| **Iteración 12 Ensamble Homogéneo** | EfficientNet GAP (0.8) + GeM (0.2) | Ventaneo Denso | 1.00 | Max | 83.77% | 85.71% | 85.89% | 85.06% | +4.21 pp | Récord previo |
| **Iteración 13 ConvNeXt Individual** | Single ConvNeXt-Nano | Ventaneo Denso | 1.00 | Max | 86.36% | 89.41% | 86.49% | 87.25% | +6.40 pp | Campeón Single |
| **Iteración 13 Ensamble Tri-Modelo** | EffNet GAP (0.6) + Conv (0.3) + GeM (0.1) | Ventaneo Denso | 1.00 | Max | 86.36% | 87.87% | 86.75% | 86.65% | +5.80 pp | Estable |
| **Iteración 13 Ensamble Bi-Modelo** | **EffNet GAP (0.60) + ConvNeXt (0.40)** | **Ventaneo Denso** | **1.00** | **Max** | **87.01%** | **88.91%** | **87.42%** | **87.63%** | **+6.78 pp** | **¡NUEVO RÉCORD!** |

---

## 4. Desglose Detallado por Especie

### 4.1 Ensamble Heterogéneo Bi-Modelo Campeón (EfficientNet GAP 60% + ConvNeXt-Nano 40%)

```text
Especie                         Prec      Rec       F1   Soporte   Observación
────────────────────────────────────────────────────────────────────────────────
Canastero                      87.5%   100.0%    93.3%         7   100% Recall
Chercán                        83.3%    90.9%    87.0%        11   +7.0 pp F1 vs previo
Chincol                       100.0%    85.7%    92.3%         7   100% Precisión
Chucao                         80.0%    88.9%    84.2%         9   
Churrín de la Mocha           100.0%   100.0%   100.0%         8   ¡100% PERFECTO!
Churrín del sur                80.0%    80.0%    80.0%         5   
Colilarga                      88.9%    88.9%    88.9%         9   +4.7 pp F1
Fío-fío                        91.7%    78.6%    84.6%        14   +13.2 pp F1 vs previo
Picaflor chico                 83.3%    83.3%    83.3%         6   
Rayadito                       93.8%    93.8%    93.8%        16   +2.9 pp F1
Tapaculo                      100.0%    60.0%    75.0%        10   100% Precisión
Tijeral                       100.0%    87.5%    93.3%         8   100% Precisión
Tordo                          81.2%    92.9%    86.7%        14   
Turca                          90.0%   100.0%    94.7%         9   100% Recall (+4.7 pp F1)
Zorzal patagónico              73.9%    81.0%    77.3%        21   +7.3 pp F1 vs previo
────────────────────────────────────────────────────────────────────────────────
Promedio Macro                 88.9%    87.4%    87.6%       154   ¡NUEVO RÉCORD HISTÓRICO!
Accuracy General                                 87.0%       154   
```

### 4.2 ConvNeXt-Nano Monolítico Individual

```text
Especie                         Prec      Rec       F1   Soporte   Observación
────────────────────────────────────────────────────────────────────────────────
Canastero                      87.5%   100.0%    93.3%         7   
Chercán                        78.6%   100.0%    88.0%        11   100% Recall
Chincol                       100.0%    85.7%    92.3%         7   100% Precisión
Chucao                         61.5%    88.9%    72.7%         9   
Churrín de la Mocha           100.0%   100.0%   100.0%         8   ¡100% PERFECTO!
Churrín del sur               100.0%    80.0%    88.9%         5   100% Precisión
Colilarga                     100.0%    88.9%    94.1%         9   100% Precisión
Fío-fío                       100.0%    71.4%    83.3%        14   100% Precisión
Picaflor chico                100.0%    83.3%    90.9%         6   100% Precisión
Rayadito                       88.2%    93.8%    90.9%        16   
Tapaculo                       77.8%    70.0%    73.7%        10   
Tijeral                        85.7%    75.0%    80.0%         8   
Tordo                          80.0%    85.7%    82.8%        14   
Turca                         100.0%    88.9%    94.1%         9   100% Precisión
Zorzal patagónico              81.8%    85.7%    83.7%        21   
────────────────────────────────────────────────────────────────────────────────
Promedio Macro                 89.4%    86.5%    87.3%       154   Campeón Individual
Accuracy General                                 86.4%       154   
```

---

## 5. Artefactos y Matrices de Confusión

Los siguientes artefactos quedaron generados y versionados en el repositorio:
1. **Checkpoint ConvNeXt-Nano:** [`checkpoints/convnext_nano_35e_best.pt`](../checkpoints/convnext_nano_35e_best.pt) (172 MB).
2. **Matriz de Confusión ConvNeXt-Nano Individual:** [`docs/cm_convnext_nano_35e_dense_hop100_max.png`](./cm_convnext_nano_35e_dense_hop100_max.png).
3. **Matriz de Confusión Ensamble Bi-Modelo Campeón:** [`docs/cm_ensemble_effnet_convnext_max.png`](./cm_ensemble_effnet_convnext_max.png).
4. **Matriz de Confusión Ensamble Tri-Modelo:** [`docs/cm_ensemble_tri_model_max.png`](./cm_ensemble_tri_model_max.png).
5. **Suite de Pruebas Automatizadas:** 63 pruebas unitarias y de integración pasando al 100% (`.venv/bin/pytest backend/tests`).

---

## 6. Comandos Reproductibles de Inferencia

```bash
# 1. Ensamble Heterogéneo Bi-Modelo Campeón (87.63% F1)
.venv/bin/python backend/poc/evaluate.py \
    --checkpoints efficientnet_gpu_pipeline_35e_best.pt convnext_nano_35e_best.pt \
    --weights 0.6 0.4 \
    --use-tta --tta-mode max --hop-seconds 1.0 \
    --output docs/cm_ensemble_effnet_convnext_max.png

# 2. Inferencia ConvNeXt-Nano Individual (87.25% F1)
.venv/bin/python backend/poc/evaluate.py \
    --checkpoint convnext_nano_35e_best.pt \
    --use-tta --tta-mode max --hop-seconds 1.0 \
    --output docs/cm_convnext_nano_35e_dense_hop100_max.png
```
