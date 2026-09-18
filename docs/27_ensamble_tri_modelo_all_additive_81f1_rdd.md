# Informe RDD Hito 27: Homogeneización All-Additive Tri-Modelo y Nuevo Récord 81.21% F1

**Fecha:** 18 de Septiembre de 2026  
**Rama:** `feat/backend-multi-model-support`  
**Metodología:** TDD Estricto + RDD (Receipt-Driven Development)  
**Artefactos Creados/Modificados:**
- `backend/training/models/panns_cnn14.py` (soporte TDD para cabeza multi-task)
- `backend/tests/test_panns_model.py` (pruebas unitarias TDD añadidas)
- `backend/train_panns_hpss_additive.py` (entrenamiento GPU con HPSS 3ch, multi-task y síntesis aditiva)
- `backend/checkpoints/car-engine-diagnostics-panns-cnn14-hpss-additive/weights.pt`
- `docs/fase6_panns_additive_receipt.json`
- `docs/fase6_all_additive_super_ensemble_receipt.json`

---

## 1. Resumen Ejecutivo

En el Hito 26 se rompió la barrera del 80% combinando `MultiTask ResNet34d` y `MultiTask EfficientNet-B0` (ambos aditivos) con el PANNs antiguo no aditivo (60.77% F1). Identificamos que PANNs era el único extractor que aún sufría de escasez de muestras en clases compuestas.

En este Hito 27:
1. Se extendió la arquitectura `PannsCNN14` bajo TDD para incorporar una **cabeza multi-task desacoplada** (13 clases mecánicas + 7 subsistemas ortogonales).
2. Se reentrenó con **HPSS de 3 canales** y **Síntesis Aditiva Física (`AdditiveCompoundSampler`)**.
3. De forma individual, PANNs mejoró su calibración y representaciones compuestas (ECE 0.0518).
4. Al ensamblar los tres extractores homogéneamente entrenados con síntesis aditiva física (`ResNet34d 0.60 + EfficientNet-B0 0.20 + PANNs CNN14 0.20`), el rendimiento en el conjunto de prueba ciego escaló a **80.68% Accuracy** y **81.21% Macro F1**, con un ECE récord de **0.0547**.

---

## 2. Progresión Histórica en Test Ciego (N = 207, SHA-256 `9d587189...`)

| Hito / Configuración | Test Accuracy | Test Macro F1 | Delta vs Línea Base | ECE |
| :--- | :---: | :---: | :---: | :---: |
| Línea Base Fase 0 (ResNet + EffNet monovista) | 69.57% | 69.00% | Ref | 0.1246 |
| Fase 1 (MultiTask ResNet34d HPSS) | 73.91% | 72.80% | +3.80 pp | 0.0892 |
| Fases 2 y 3 (Tri-Ensamble sin aditiva) | 76.33% | 75.31% | +6.31 pp | 0.0715 |
| Fase 4 (ResNet34d Additive individual) | 78.26% | 77.97% | +8.97 pp | 0.0688 |
| Fase 5 (Super-Ensamble Tri-Modelo) | 80.19% | 80.63% | +11.63 pp | 0.0685 |
| **Fase 6 (Tri-Modelo All-Additive Ganador)** | **80.68%** | **81.21%** | **+12.21 pp** | **0.0547** |

---

## 3. Desempeño Detallado por Clase en Test Ciego

```text
                                                Precision    Recall  F1-Score   Soporte

                                  bad_ignition     1.0000    1.0000    1.0000         9
                                  dead_battery     1.0000    1.0000    1.0000         9
                         normal_engine_startup     1.0000    1.0000    1.0000         9
                            normal_engine_idle     0.9091    1.0000    0.9524        40
                               worn_out_brakes     1.0000    0.9091    0.9524        11
                                 normal_brakes     0.8571    1.0000    0.9231        12
                                power_steering     0.9375    0.7895    0.8571        19
                               serpentine_belt     0.8333    0.8824    0.8571        17
       power steering combined_serpentine belt     0.6471    0.6471    0.6471        17
                power steering combined_no oil     0.5882    0.6250    0.6061        16
                                       low_oil     0.6429    0.5625    0.6000        16
                        no oil_serpentine belt     0.6429    0.5625    0.6000        16
power steering combined_no oil_serpentine belt     0.5625    0.5625    0.5625        16

                                      Accuracy                         0.8068       207
                                     Macro AVG     0.8170    0.8108    0.8121       207
                                  Weighted AVG     0.8049    0.8068    0.8039       207
```

### Logros Críticos:
1. **Récord Histórico:** Macro F1 alcanzó **81.21%** (+12.21 pp sobre la línea base) y Accuracy alcanzó **80.68%** (+11.11 pp).
2. **Elevación de las Clases Compuestas:** `no oil_serpentine belt` alcanzó el **60.00% F1**, consolidando a todas las clases compuestas en el umbral 56%–65% F1.
3. **Calibración Óptima:** ECE cayó a **0.0547**, reduciendo el error de calibración en más del 56% respecto a la línea base (0.1246).
