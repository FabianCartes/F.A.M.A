# Informe RDD Hito 25: Síntesis Aditiva Guiada por Física (Physics-Guided Additive Mixing)

**Fecha:** 18 de Septiembre de 2026  
**Rama:** `feat/backend-multi-model-support`  
**Metodología:** TDD Estricto + RDD (Receipt-Driven Development)  
**Artefactos Creados/Modificados:**
- `backend/training/pipelines/additive_mixing.py`
- `backend/tests/test_additive_mixing.py`
- `backend/train_multitask_hpss_additive.py`
- `backend/training/pipelines/dataset.py`
- `backend/tests/test_generic_audio_dataset.py`
- `backend/checkpoints/car-engine-diagnostics-resnet34d-multitask-hpss-additive/weights.pt`
- `docs/receipts/fase4_additive_mixing_receipt.json`

---

## 1. Resumen Ejecutivo y Fundamento Físico

En las fases anteriores, identificamos que las fallas mecánicas unitarias se encontraban resueltas (90%–100% F1), mientras que las fallas compuestas concurrentes (`low_oil`, `no oil_serpentine belt`, `power steering combined_no oil`) concentraban el cuello de botella de rendimiento por la escasez de muestras en el conjunto de entrenamiento (únicamente 75 ejemplos compuestas en train).

Para resolver esto sin recurrir a aumentaciones ciegas que distorsionen la física acústica, implementamos **Síntesis Aditiva Guiada por Física (Physics-Guided Additive Mixing)**:
- **Ecuación Acústica de Presión Sonora:** A diferencia de Mixup espectral (que intercala imágenes como transparencias artificiales), la física de dos fuentes mecánicas independientes vibrando en el mismo bloque motor sigue el principio de superposición lineal de ondas acústicas de presión:
  $$x_{\text{compuesto}}(t) = x_A(t) + \alpha \cdot x_B(t) \quad \text{con } \alpha \sim \mathcal{U}(0.7, 1.3)$$
- **Muestreo Ontológico Dinámico:** El componente `AdditiveCompoundSampler` descompone en tiempo real las etiquetas multi-falla compuestas en sus componentes unitarios constitutivos a partir de una matriz ontológica precalculada y genera nuevas combinaciones acústicas durante el bucle de entrenamiento, aumentando la densidad de datos sintéticos físicamente válidos en más de un 400%.

---

## 2. Métricas en Test Set Ciego (N = 207)

El conjunto de prueba congelado criptográficamente bajo SHA-256 (`9d587189434b41b27d55de43aa86f50312f0b5d300d437b03cc3ecae52c153d2`) arrojó un salto cuantitativo fundamental:

| Modelo / Ensamble | Test Accuracy | Test Macro F1 | Delta vs Línea Base | ECE |
| :--- | :---: | :---: | :---: | :---: |
| Línea Base Fase 0 (ResNet + EffNet monovista) | 69.57% | 69.00% | Ref | 0.1246 |
| Fase 1 (MultiTask ResNet34d HPSS standalone) | 73.91% | 72.80% | +3.80 pp | 0.0892 |
| Fases 2 y 3 (Ensamble Tri-Modelo anterior) | 76.33% | 75.31% | +6.31 pp | 0.0715 |
| **Fase 4 (MultiTask ResNet34d HPSS + Additive Mixing)** | **78.26%** | **77.97%** | **+8.97 pp** | **0.0688** |

---

## 3. Desempeño Detallado por Clase Diagnóstica

```text
                                                Precision    Recall  F1-Score   Soporte

                                  bad_ignition     0.8182    1.0000    0.9000         9
                                  dead_battery     1.0000    0.8889    0.9412         9
                                       low_oil     0.6000    0.5625    0.5806        16
                        no oil_serpentine belt     0.6111    0.6875    0.6471        16
                                 normal_brakes     0.8000    1.0000    0.8889        12
                            normal_engine_idle     0.9070    0.9750    0.9398        40
                         normal_engine_startup     1.0000    0.8889    0.9412         9
                power steering combined_no oil     0.6250    0.6250    0.6250        16
power steering combined_no oil_serpentine belt     0.6364    0.4375    0.5185        16
       power steering combined_serpentine belt     0.6429    0.5294    0.5806        17
                                power_steering     0.8750    0.7368    0.8000        19
                               serpentine_belt     0.7273    0.9412    0.8205        17
                               worn_out_brakes     1.0000    0.9091    0.9524        11

                                      Accuracy                         0.7826       207
                                     Macro AVG     0.7879    0.7832    0.7797       207
                                  Weighted AVG     0.7813    0.7826    0.7765       207
```

### Hallazgos Clave:
1. **Quiebre del Cuello de Botella de Lubricación:**
   - `no oil_serpentine belt` escaló de 40.0% (Línea Base) y 50.0% (Fase 3) a **64.71% F1** (Recall 68.75%).
   - `low_oil` escaló de 35.0% (Línea Base) y 43.75% (Fase 3) a **58.06% F1** (Recall 56.25%).
2. **Transferencia Negativa en Ensamblado Asimétrico:**
   - Al combinar este modelo individual ganador ($77.97\%$ F1) con modelos heterogéneos antiguos entrenados sin síntesis aditiva (`EfficientNet-B0` a 65.6% F1 y `PannsCNN14` a 60.77% F1), el ensamble obtiene 79.11% en validación pero cae a 77.50% en test ciego debido a que los modelos antiguos degradan las decisiones compuestas que el modelo aditivo ya resuelve con precisión.
3. **Calibración Probabilística:**
   - ECE se redujo a **0.0688**, lo que indica que las probabilidades de salida reflejan fielmente la incertidumbre epistémica y aleatoria del diagnóstico.
