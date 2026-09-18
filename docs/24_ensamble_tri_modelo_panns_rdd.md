# Informe RDD Hito 24: Transfer Learning Acústico (PANNs CNN14) y Ensamble Tri-Modelo Superando el 75% F1

**Fecha:** 18 de Septiembre de 2026  
**Rama:** `feat/backend-multi-model-support`  
**Metodología:** TDD Estricto + RDD (Receipt-Driven Development)  
**Artefactos Creados:**
- `backend/training/models/panns_cnn14.py`
- `backend/train_panns_transfer.py`
- `backend/tests/test_panns_model.py`
- `backend/checkpoints/car-engine-diagnostics-panns-cnn14-hpss/weights.pt`
- `docs/fase2_panns_receipt.json`
- `docs/fase2_3_tri_ensemble_receipt.json`

---

## 1. Resumen Ejecutivo y Conclusión de Fases 2 y 3

Siguiendo la hoja de ruta incremental y rigurosa sin fuga metodológica (test set congelado bajo SHA-256 `9d587189...`):

1. **Fase 2 (Transfer Learning Acústico con PANNs CNN14):**
   - Se importaron y adaptaron los pesos oficiales preentrenados en AudioSet (2M de audios de YouTube con motores, vehículos y maquinaria) de `Cnn14_mAP=0.431.pth`.
   - Se congelaron las primeras 4 etapas convolucionales para preservar representaciones espectrales acústicas de bajo nivel y mitigar el sobreajuste con 972 muestras.
   - De forma standalone, CNN14 alcanzó **64.25% Accuracy** y **60.77% Macro F1**. Si bien fue inferior al modelo MultiTask ResNet34d individual (72.80%), sus representaciones capturan un espacio acústico complementario no basado en ImageNet.

2. **Fase 3 (Fusión Calibrada Tri-Modelo):**
   - Se combinaron los tres backbones heterogéneos:
     1. `MultiTask ResNet34d HPSS` ($w=0.42, T=0.9$): Extractor 3 canales armónico/percusivo con desacoplamiento multi-task.
     2. `EfficientNet-B0 GeM` ($w=0.43, T=1.0$): Convoluciones invertidas MBConv que aportan escala armónica complementaria.
     3. `PANNs CNN14 HPSS` ($w=0.15, T=1.1$): Regularizador con prior acústico preentrenado en AudioSet.

---

## 2. Métricas Finales en Test Set Ciego (N = 207)

| Configuración | Test Accuracy | Test Macro F1 | Delta vs Línea Base |
| :--- | :---: | :---: | :---: |
| Línea Base Fase 0 (ResNet + EffNet sin desacoplar) | 69.57% | 69.00% | Ref |
| Fase 1 (MultiTask ResNet34d HPSS standalone) | 73.91% | 72.80% | +3.80 pp |
| **Fase 2 y 3 (Ensamble Tri-Modelo Calibrado GANADOR)** | **76.33%** | **75.31%** | **+6.31 pp** |

---

## 3. Desempeño por Clase Diagnóstica en Test Set (N = 207)

```text
                                                Precision    Recall  F1-Score   Soporte

                                  bad_ignition     0.8889    0.8889    0.8889         9
                                  dead_battery     1.0000    0.8889    0.9412         9
                                       low_oil     0.4375    0.4375    0.4375        16
                        no oil_serpentine belt     0.7500    0.3750    0.5000        16
                                 normal_brakes     0.7500    1.0000    0.8571        12
                            normal_engine_idle     0.9512    0.9750    0.9630        40
                         normal_engine_startup     0.8000    0.8889    0.8421         9
                power steering combined_no oil     0.5263    0.6250    0.5714        16
power steering combined_no oil_serpentine belt     0.5882    0.6250    0.6061        16
       power steering combined_serpentine belt     0.7500    0.5294    0.6207        17
                                power_steering     0.7895    0.7895    0.7895        19
                               serpentine_belt     0.7273    0.9412    0.8205        17
                               worn_out_brakes     1.0000    0.9091    0.9524        11

                                      Accuracy                         0.7633       207
                                     Macro AVG     0.7661    0.7595    0.7531       207
                                  Weighted AVG     0.7691    0.7633    0.7569       207
```

### Logros Críticos:
- Todas las clases compuestas rompieron la barrera del 50%–62% de F1 (en la línea base oscilaban entre 35% y 40%).
- Las fallas críticas de seguridad (`worn_out_brakes`, `normal_engine_idle`, `dead_battery`) superan el 94%–96% de F1.
- Objetivo del sprint cumplido: **Macro F1 superó la meta del 75% alcanzando 75.31% de manera 100% ciega y verificable**.
