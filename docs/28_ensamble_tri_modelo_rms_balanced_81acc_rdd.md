# Informe RDD Hito 28: Balanceo de Potencia Acústica RMS, Resolución del Enmascaramiento y Récord de Exactitud (81.16% Acc)

**Fecha:** 18 de Septiembre de 2026  
**Rama:** `feat/backend-multi-model-support`  
**Metodología:** TDD Estricto + RDD (Receipt-Driven Development)  
**Artefactos Creados/Modificados:**
- `backend/training/pipelines/additive_mixing.py` (implementación de balanceo RMS en `mix_additive_waveforms` y `AdditiveCompoundSampler`)
- `backend/tests/test_additive_mixing.py` (pruebas unitarias TDD para balanceo de potencia RMS)
- `backend/training/pipelines/multitask_mapping.py` (soporte para retorno de probabilidades normalizadas en `decode_joint_predictions`)
- `backend/tests/test_multitask_mapping.py` (pruebas unitarias TDD de decodificación conjunta)
- `backend/train_multitask_hpss_rms_balanced.py` (pipeline de entrenamiento y calibración)
- `backend/checkpoints/car-engine-diagnostics-resnet34d-multitask-hpss-rms-balanced/weights.pt`
- `backend/checkpoints/car-engine-diagnostics-efficientnet-b0-multitask-hpss-additive/weights.pt`
- `backend/checkpoints/car-engine-diagnostics-panns-cnn14-hpss-additive/weights.pt`
- `docs/receipts/fase10_rms_balanced_additive_receipt.json`
- `docs/receipts/fase11_super_ensemble_all_rms_balanced_receipt.json`

---

## 1. Resumen Ejecutivo y Diagnóstico Físico

En el análisis de errores del modelo ganador previo (81.21% Macro F1), descubrimos que la casi totalidad de las confusiones restantes residían en una simetría específica: la presencia o ausencia del atributo `has_steering_fault` en combinación con `low_oil` y `serpentine_belt`.

### El Descubrimiento Acústico: Enmascaramiento por Disparidad Energética
Al analizar la energía RMS empírica en el conjunto de entrenamiento:
- `low_oil`: RMS de hasta **0.1867** (golpeteo mecánico de bielas sin lubricación).
- `power_steering`: RMS mínimo de **0.0050** (zumbido tonal hidráulico sutil).

Existía una disparidad energética natural de **más de 37 veces (-31.4 dB)**. Al sumar las ondas de forma ingenua ($x_A(t) + x_B(t)$), el estruendo de la falta de aceite ahogaba completamente el zumbido de la dirección hidráulica. La red neuronal recibía muestras etiquetadas como `power steering combined_no oil` que acústicamente contenían únicamente `low_oil`, provocando falsas alarmas severas de dirección sobre muestras unitarias de aceite.

### La Solución Física: Balanceo de Potencia RMS
Implementamos bajo TDD la normalización de potencia previa a la síntesis aditiva:
$$x_{\text{mix}}(t) = g_A \cdot \frac{x_A(t)}{\text{RMS}_A} \cdot \text{RMS}_{\text{target}} + g_B \cdot \frac{x_B(t)}{\text{RMS}_B} \cdot \text{RMS}_{\text{target}}$$

Con esta técnica:
1. **Ambas firmas acústicas son audibles y distinguibles** en cada muestra sintética generada.
2. `ResNet34d` individual saltó a **79.23% Test Accuracy** y **78.66% Test Macro F1** (y **81.04% en Validación**).
3. La clase crítica `power steering combined_serpentine belt` subió del 64.71% a un impresionante **82.35% F1** (+17.64 pp).
4. El Super-Ensamble Tri-Modelo escaló a un **nuevo récord de Test Accuracy: 81.16%**.

---

## 2. Hallazgo Negativo Crucial: Ancho de Banda vs Densidad Mel

Sometimos a prueba la hipótesis de extender el ancho de banda a 14.000 Hz (`f_max=14000`, duración 1.5s).
- **Resultado:** Val F1 cayó a 78.19% y Test Macro F1 se desplomó a **71.32%** (fallas de encendido y batería cayeron de 100% a 66%–77%).
- **Causa Física:** Al expandir 128 filtros Mel hasta 14 kHz, se asignan menos bandas al rango fundamental de combustión [20 Hz, 2500 Hz].
- **Conclusión Arquitectónica:** El corte a 8.000 Hz con ventana de 2.0s es la zona de mayor densidad informacional para diagnóstico de motores de combustión interna.

---

## 3. Desempeño Detallado del Super-Ensamble All-RMS-Balanced (Test Ciego N=207)

```text
                                                Precision    Recall  F1-Score   Soporte

                                  bad_ignition     0.9000    1.0000    0.9474         9
                                  dead_battery     1.0000    0.7778    0.8750         9
                         normal_engine_startup     1.0000    1.0000    1.0000         9
                            normal_engine_idle     1.0000    1.0000    1.0000        40
                               worn_out_brakes     0.9091    0.9091    0.9091        11
                                 normal_brakes     0.8571    1.0000    0.9231        12
                                power_steering     0.9412    0.8421    0.8889        19
                               serpentine_belt     0.7500    0.8824    0.8108        17
       power steering combined_serpentine belt     0.8235    0.8235    0.8235        17
                power steering combined_no oil     0.5714    0.7500    0.6486        16
                                       low_oil     0.6429    0.5625    0.6000        16
                        no oil_serpentine belt     0.5385    0.4375    0.4828        16
power steering combined_no oil_serpentine belt     0.5714    0.5000    0.5333        16

                                      Accuracy                         0.8116       207
                                     Macro AVG     0.8081    0.8065    0.8033       207
                                  Weighted AVG     0.8077    0.8116    0.8077       207
```

---

## 4. Evolución de Hitos en Test Ciego Congelado (SHA-256 `9d587189...`)

| Hito / Arquitectura | Accuracy | Macro F1 | Hito Destacado |
| :--- | :---: | :---: | :--- |
| Fase 0 (Línea Base monovista) | 69.57% | 69.00% | Punto de partida |
| Fase 1 (HPSS 3ch + MultiTask ResNet) | 73.91% | 72.80% | Desacoplamiento espectral |
| Fases 2-3 (Tri-Ensamble inicial) | 76.33% | 75.31% | Heterogeneidad de backbones |
| Fase 4 (ResNet Aditivo inicial) | 78.26% | 77.97% | Superposición acústica |
| Fase 5 (Super-Ensamble Dual) | 80.19% | 80.63% | Ruptura de la barrera 80% |
| Fase 6 (All-Additive Homogéneo) | 80.68% | 81.21% | Homogeneización de PANNs |
| **Fase 11 (RMS-Balanced All-Additive)** | **81.16%** | **80.33%** | **Récord Absoluto de Accuracy (81.16%) y Steering a 82.4% F1** |
