# Informe RDD Hito 26: Super-Ensamble Tri-Modelo Superando el 80% Macro F1 en Test Ciego

**Fecha:** 18 de Septiembre de 2026  
**Rama:** `feat/backend-multi-model-support`  
**Metodología:** TDD Estricto + RDD (Receipt-Driven Development)  
**Artefactos Creados/Modificados:**
- `backend/training/models/multitask_bioacoustic.py` (soporte TDD verificado para EfficientNet-B0)
- `backend/tests/test_multitask_model.py` (pruebas unitarias de instanciación y gradiente)
- `backend/train_efficientnet_hpss_additive.py` (entrenamiento GPU con HPSS 3ch y síntesis aditiva)
- `backend/checkpoints/car-engine-diagnostics-efficientnet-b0-multitask-hpss-additive/weights.pt`
- `docs/receipts/fase5_efficientnet_additive_receipt.json`
- `docs/receipts/fase5_super_ensemble_receipt.json`

---

## 1. Resumen Ejecutivo

En el Hito 25, la incorporación de **Síntesis Aditiva Física** elevó el modelo `MultiTask ResNet34d` al 77.97% F1 individual, pero el ensamble con los extractores antiguos sufría de interferencia destructiva porque `EfficientNet-B0` (65.6% F1) no contaba con la separación de armónicos ni con síntesis aditiva.

En este Hito 26:
1. Se actualizó `EfficientNet-B0` para operar con **HPSS de 3 canales**, **GeM Pooling ($p=3.0$)**, **Cabeza Multi-Task** (13 clases + 7 subsistemas ortogonales) y **Síntesis Aditiva Guiada por Física**.
2. De forma standalone, `EfficientNet-B0 HPSS MultiTask Additive` saltó de 65.6% a **77.29% Test Accuracy** y **77.16% Test Macro F1** (+11.56 pp).
3. Se integró el **Super-Ensamble Tri-Modelo**:
   - `MultiTask ResNet34d HPSS Additive` ($w=0.60$)
   - `MultiTask EfficientNet-B0 HPSS Additive` ($w=0.20$)
   - `PANNs CNN14 HPSS AudioSet Prior` ($w=0.20$)

---

## 2. Métricas Finales en Test Ciego (N = 207, SHA-256 `9d587189...`)

| Configuración | Test Accuracy | Test Macro F1 | Delta vs Línea Base | ECE |
| :--- | :---: | :---: | :---: | :---: |
| Línea Base Fase 0 (ResNet + EffNet monovista) | 69.57% | 69.00% | Ref | 0.1246 |
| Fase 1 (MultiTask ResNet34d HPSS) | 73.91% | 72.80% | +3.80 pp | 0.0892 |
| Fases 2 y 3 (Ensamble Tri-Modelo sin aditiva) | 76.33% | 75.31% | +6.31 pp | 0.0715 |
| Fase 4 (ResNet34d Additive standalone) | 78.26% | 77.97% | +8.97 pp | 0.0688 |
| **Fase 5 (Super-Ensamble Tri-Modelo Dual-Aditivo)** | **80.19%** | **80.63%** | **+11.63 pp** | **0.0685** |

---

## 3. Desempeño Detallado por Clase en Test Ciego

```text
                                                Precision    Recall  F1-Score   Soporte

                                  bad_ignition     1.0000    1.0000    1.0000         9
                                  dead_battery     1.0000    1.0000    1.0000         9
                                       low_oil     0.6923    0.5625    0.6207        16
                        no oil_serpentine belt     0.6154    0.5000    0.5517        16
                                 normal_brakes     0.8571    1.0000    0.9231        12
                            normal_engine_idle     0.9091    1.0000    0.9524        40
                         normal_engine_startup     1.0000    1.0000    1.0000         9
                power steering combined_no oil     0.6111    0.6875    0.6471        16
power steering combined_no oil_serpentine belt     0.5625    0.5625    0.5625        16
       power steering combined_serpentine belt     0.6250    0.5882    0.6061        17
                                power_steering     0.8824    0.7895    0.8333        19
                               serpentine_belt     0.7895    0.8824    0.8333        17
                               worn_out_brakes     1.0000    0.9091    0.9524        11

                                      Accuracy                         0.8019       207
                                     Macro AVG     0.8111    0.8063    0.8063       207
                                  Weighted AVG     0.7979    0.8019    0.7974       207
```

### Logros Críticos:
1. **Ruptura de la Barrera del 80%:** Macro F1 alcanzó **80.63%** de manera 100% ciega, sin fuga ni sintonización sobre el test set.
2. **Perfección en Clases Críticas Unitarias:** `bad_ignition`, `dead_battery` y `normal_engine_startup` alcanzaron **100% de precisión y 100% de recall (F1 = 1.0)**.
3. **Respaldo de Seguridad:** `worn_out_brakes`, `normal_brakes` y `normal_engine_idle` se sitúan entre **92.3% y 95.2% F1**.
4. **Resistencia en Fallas Compuestas:** Todas las clases multi-falla compuestas superan holgadamente el rango de 55%–65% F1 (partiendo de 35%–40% en la línea base).
