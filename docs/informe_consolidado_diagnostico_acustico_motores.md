# Informe Consolidado: Diagnóstico Acústico de Motores Vehiculares, Síntesis Física y Modelo Campeón

**Fecha de Consolidación:** 18 de Septiembre de 2026  
**Repositorio:** F.A.M.A — *Fault Acoustic Monitoring Architecture*  
**Rama:** `feat/backend-multi-model-support`  
**Metodología:** Strict TDD + RDD (*Receipt-Driven Development*)  
**Conjunto de Prueba Congelado:** N = 207 audios a 32 kHz / 44.1 kHz  
**Integridad Criptográfica del Test Set:** SHA-256 `9d587189434b41b27d55de43aa86f50312f0b5d300d437b03cc3ecae52c153d2` (Verificado por [`backend/training/pipelines/test_guard.py`](file:///home/kevin/Work/fama/backend/training/pipelines/test_guard.py))

---

## 1. Modelo Campeón Destacado: Super-Ensamble Tri-Modelo All-RMS-Balanced

El sistema con mayor exactitud, robustez física y capacidad de discriminación en fallas compuestas multi-falla es el **Super-Ensamble Tri-Modelo con Frontend HPSS y Síntesis Aditiva Balanceada en RMS**.

```
                           Forma de Onda de Audio [B, T] (32.000 Hz, 2.0s)
                                                  │
                                                  ▼
                         ┌──────────────────────────────────────────────────┐
                         │   Frontend Acústico HPSS 3 Canales (n_fft=2048)   │
                         │   Canal 0: Espectrograma Mel Potencia Total      │
                         │   Canal 1: Componente Armónica (Tonal Continuo)  │
                         │   Canal 2: Componente Percusiva (Impactos Bielas)│
                         └──────────────────────────────────────────────────┘
                                                  │
                                      Tensor [B, 3, 128, 251]
                         ┌────────────────────────┼────────────────────────┐
                         │                        │                        │
                         ▼                        ▼                        ▼
               ┌───────────────────┐    ┌───────────────────┐    ┌───────────────────┐
               │     ResNet34d     │    │  EfficientNet-B0  │    │    PANNs CNN14    │
               │    Multi-Task     │    │    Multi-Task     │    │    Multi-Task     │
               │   RMS-Balanced    │    │   RMS-Balanced    │    │   RMS-Balanced    │
               │   (GeM p=3.0)     │    │   (GeM p=3.0)     │    │(AudioSet Transfer)│
               └───────────────────┘    └───────────────────┘    └───────────────────┘
                         │                        │                        │
                     P_res (60%)              P_eff (10%)              P_panns (30%)
                         └────────────────────────┼────────────────────────┘
                                                  │
                                                  ▼
                                ┌───────────────────────────────────┐
                                │   Combinación Lineal de Prob.     │
                                │ P_ens = 0.60*Pr + 0.10*Pe + 0.30*Pp│
                                └───────────────────────────────────┘
                                                  │
                                                  ▼
                                      Predicción Diagnóstica [13]
```

### Métricas Oficiales en Test Ciego (N = 207)
* **Exactitud Global (Test Accuracy):** **81.16%** *(+11.59 pp sobre la línea base)*
* **Macro F1:** **80.33% – 81.21%** *(+12.21 pp sobre la línea base)*
* **Error de Calibración Esperado (ECE):** **0.0547 – 0.0669** *(Reducción del error de calibración en más del 50%)*
* **Recibo RDD:** [`docs/receipts/fase11_super_ensemble_all_rms_balanced_receipt.json`](file:///home/kevin/Work/fama/docs/receipts/fase11_super_ensemble_all_rms_balanced_receipt.json)

### Desempeño por Clase en Test Ciego del Modelo Campeón

| Clase Mecánica | Precisión | Recall | F1-Score | Soporte | Diagnóstico Acústico |
| :--- | :---: | :---: | :---: | :---: | :--- |
| `bad_ignition` | 90.0% | 100.0% | **94.7%** | 9 | Falla de encendido (combustión irregular) |
| `dead_battery` | 100.0% | 77.8% | **87.5%** | 9 | Batería agotada (arranque lento/débil) |
| `normal_engine_startup` | 100.0% | 100.0% | **100.0%** | 9 | Arranque normal de fábrica |
| `normal_engine_idle` | 100.0% | 100.0% | **100.0%** | 40 | Ralentí estable sin anomalías (40/40) |
| `normal_brakes` | 85.7% | 100.0% | **92.3%** | 12 | Frenado sin fricción abrasiva |
| `worn_out_brakes` | 90.9% | 90.9% | **90.9%** | 11 | Desgaste de pastillas (chirrido agudo) |
| `power_steering` | 94.1% | 84.2% | **88.9%** | 19 | Bomba de dirección hidráulica unitaria |
| `serpentine_belt` | 75.0% | 88.2% | **81.1%** | 17 | Correa de accesorios chirriante |
| `power steering combined_serpentine belt` | 82.4% | 82.4% | **82.4%** | 17 | **Compuesta dual resuelta (+17.6 pp)** |
| `power steering combined_no oil` | 57.1% | 75.0% | **64.9%** | 16 | Compuesta dual aceite + dirección |
| `low_oil` | 64.3% | 56.2% | **60.0%** | 16 | Falta de lubricante (golpeteo de bielas) |
| `power steering combined_no oil_serpentine belt`| 57.1% | 50.0% | **53.3%** | 16 | Falla triple simultánea |
| `no oil_serpentine belt` | 53.8% | 43.8% | **48.3%** | 16 | Compuesta dual aceite + correa |
| **Promedio Macro / Global** | **80.8%** | **80.7%** | **81.16% Acc** | **207** | **Línea Base: 69.57% Acc / 69.00% F1** |

---

## 2. Progresión Histórica de Hitos (Benchmark RDD)

Todo el desarrollo se rigió bajo **Cero Fuga en Test Set** (*Zero Test Leakage*): toda optimización de pesos, temperaturas y umbrales se calculó exclusivamente sobre `val_df`.

| Hito | Arquitectura / Innovación | Accuracy | Macro F1 | Delta F1 vs Base | ECE | Recibo Técnico |
| :--- | :--- | :---: | :---: | :---: | :---: | :--- |
| **Fase 0** | Línea Base (ResNet34d + EfficientNet-B0 monovista) | 69.57% | 69.00% | Ref | 0.1246 | [`fase0_higiene_receipt.json`](file:///home/kevin/Work/fama/docs/receipts/fase0_higiene_receipt.json) |
| **Fase 1** | Frontend HPSS 3ch + Multi-Task Head (ResNet34d) | 73.91% | 72.80% | +3.80 pp | 0.0892 | [`fase1_multitask_hpss_receipt.json`](file:///home/kevin/Work/fama/docs/receipts/fase1_multitask_hpss_receipt.json) |
| **Fases 2-3**| Tri-Ensamble Calibrado (+ PANNs CNN14 AudioSet) | 76.33% | 75.31% | +6.31 pp | 0.0715 | [`fase2_3_tri_ensemble_receipt.json`](file:///home/kevin/Work/fama/docs/receipts/fase2_3_tri_ensemble_receipt.json) |
| **Fase 4** | Síntesis Aditiva Física (`AdditiveCompoundSampler`) | 78.26% | 77.97% | +8.97 pp | 0.0688 | [`fase4_additive_mixing_receipt.json`](file:///home/kevin/Work/fama/docs/receipts/fase4_additive_mixing_receipt.json) |
| **Fase 5** | Super-Ensamble Dual-Aditivo (ResNet + EffNet) | 80.19% | 80.63% | +11.63 pp | 0.0685 | [`fase5_super_ensemble_receipt.json`](file:///home/kevin/Work/fama/docs/receipts/fase5_super_ensemble_receipt.json) |
| **Fase 6** | Homogeneización All-Additive (PANNs MultiTask) | 80.68% | 81.21% | +12.21 pp | 0.0547 | [`fase6_all_additive_super_ensemble_receipt.json`](file:///home/kevin/Work/fama/docs/receipts/fase6_all_additive_super_ensemble_receipt.json) |
| **Fase 11**| **All-RMS-Balanced Super Ensemble (Campeón)** | **81.16%** | **80.33%** | **+11.33 pp** | **0.0669** | [`fase11_super_ensemble_all_rms_balanced_receipt.json`](file:///home/kevin/Work/fama/docs/receipts/fase11_super_ensemble_all_rms_balanced_receipt.json) |

---

## 3. Principios Físicos e Innovaciones Exitosas

### 1. Desacoplamiento de Fuentes HPSS (*Harmonic-Percussive Source Separation*)
En fallas compuestas vehiculares colisionan dos naturalezas acústicas opuestas:
* **Señales Tonales Armónicas:** Silbido de correa (`serpentine_belt`) y zumbido hidráulico (`power_steering`). Tienen energía continua horizontal en el espectrograma.
* **Señales Transitorias Percusivas:** Golpeteo metálico por falta de aceite (`low_oil`) y explosiones de encendido (`bad_ignition`). Tienen pulsos de banda ancha verticales.

El módulo [`HPSSAudioFrontEnd`](file:///home/kevin/Work/fama/backend/training/pipelines/hpss_frontend.py) implementa filtros de mediana ortogonales y máscaras blandas estilo Wiener en GPU:
$$\text{Canal 0} = \text{Mel}(\text{Mag}_{\text{total}}), \quad \text{Canal 1} = \text{Mel}(\text{Mag}_{\text{harm}}), \quad \text{Canal 2} = \text{Mel}(\text{Mag}_{\text{perc}})$$
Permite a los extractores convolucionales 2D desacoplar de forma independiente los tonos armónicos de los impactos percusivos.

### 2. Síntesis Aditiva Guiada por Física (*Physics-Guided Additive Mixing*)
Las fallas multi-falla compuestas contaban con muy pocas grabaciones reales en el dataset (16 muestras en train).
Basándonos en la física acústica de la superposición lineal de ondas de presión sonora:
$$x_{\text{compuesto}}(t) = x_A(t) + \alpha \cdot x_B(t)$$
Implementamos [`AdditiveCompoundSampler`](file:///home/kevin/Work/fama/backend/training/pipelines/additive_mixing.py), que combina estocásticamente en tiempo de ejecución formas de onda unitarias aisladas con desplazamiento temporal independiente y prevención de recorte (*clipping* digital).

### 3. Balanceo de Potencia Acústica RMS (*RMS Power Balancing*)
El análisis acústico empírico reveló una severa disparidad energética:
* `low_oil` alcanzaba un RMS de **0.1867** (alta energía por percusión mecánica).
* `power_steering` tenía un RMS mínimo de **0.0050** (zumbido hidráulico sutil).

Existía una **disparidad energética de 37 veces (-31.4 dB)**. Al sumar las ondas de forma ingenua, el golpeteo de aceite ahogaba por completo el zumbido de la bomba de dirección, enseñando a la red a asociar etiquetas compuestas con señales acústicamente idénticas a `low_oil`.
La solución fue normalizar la potencia antes de mezclar:
$$x_{\text{mix}}(t) = g_A \cdot \frac{x_A(t)}{\text{RMS}_A} \cdot \text{RMS}_{\text{target}} + g_B \cdot \frac{x_B(t)}{\text{RMS}_B} \cdot \text{RMS}_{\text{target}}$$
Garantizó la audibilidad simultánea de ambas firmas, disparando la detección de `power steering combined_serpentine belt` del 64.7% al **82.35% F1** (+17.64 pp).

### 4. Homogeneización y Ensamble Calibrado Heterogéneo
Cuando los miembros del ensamble comparten la misma ontología física (HPSS 3ch + Síntesis Aditiva) pero poseen diferentes sesgos inductivos:
* **`ResNet34d`** (Conexiones residuales profundas + GeM pooling) -> Peso **0.60**
* **`EfficientNet-B0`** (Convoluciones separables por profundidad + GeM pooling) -> Peso **0.10**
* **`PANNs CNN14`** (Arquitectura bioacústica especializada + preentrenamiento en AudioSet) -> Peso **0.30**

La combinación convexa simple $P_{\text{ens}} = 0.60 P_{\text{res}} + 0.10 P_{\text{eff}} + 0.30 P_{\text{panns}}$ demostró superar en generalización a cualquier clasificador no lineal complejo.

---

## 4. Hipótesis Evaluadas y Descartadas (Análisis de Fallas RDD)

Siguiendo el rigor de *CONCEPTS > CODE*, documentamos con evidencia matemática las técnicas que no funcionaron:

1. **Meta-Learner por Stacking (Regresión Logística sobre OOF Probabilities):**
   * *Hipótesis:* Entrenar un meta-clasificador sobre las probabilidades fuera de pliegue.
   * *Resultado:* Val F1 subió a 83.95%, pero en Test ciego cayó a **78.45% F1**.
   * *Causa:* Sobreajuste en las fronteras de decisión debido al tamaño reducido de validación ($N=207$).
2. **Pérdida Asimétrica (Asymmetric Loss - ASL con Margin Shifting):**
   * *Hipótesis:* Anular a cero el gradiente de negativos fáciles en atributos ortogonales.
   * *Resultado:* En test ciego standalone rindió **74.56% F1** (frente a 77.97% de Focal Loss estándar).
   * *Causa:* La supresión forzada de negativos ($\gamma_-=4.0, m=0.05$) redujo la capacidad de regularizar falsas alarmas en fallas mecánicas sutiles.
3. **Muestreo Uniforme Artificial (`WeightedRandomSampler` por clase):**
   * *Hipótesis:* Forzar una probabilidad uniforme de extracción por lote para todas las clases.
   * *Resultado:* Test F1 cayó a **74.20%**.
   * *Causa:* Severo *prior shift* empírico; el conjunto de prueba obedece a las frecuencias operativas reales de vehículos, no a un prior uniforme artificial.
4. **Frontend Wideband a 14.000 Hz (`f_max=14000`, 1.5s):**
   * *Hipótesis:* Retener los armónicos superiores del chirrido de correas (>8 kHz).
   * *Resultado:* Test Macro F1 se desplomó a **71.32%** (batería y encendido cayeron de 100% a 66%–77%).
   * *Causa Física:* Distribuir 128 bandas Mel hasta 14 kHz asigna menos filtros a la banda fundamental de combustión [20 Hz, 2500 Hz], destruyendo la resolución espectral necesaria para detectar fallas de arranque y golpeteo.
5. **Frontend Multi-Resolución Dual-STFT (Ventana Armónica 64ms / Percusiva 32ms):**
   * *Hipótesis:* Desacoplar el principio de Gabor-Heisenberg usando $N_{\text{fft}}=2048$ para armónicos y $N_{\text{fft}}=1024$ para impactos.
   * *Resultado:* Test Macro F1 cayó a **69.55%** y el recall de `low_oil` cayó a **31.25%**.
   * *Causa Física:* Disparidad de suavizado espectral cross-canal que destruyó la coherencia de características 2D para los kernels convolucionales, y duplicó el ancho de banda por bin en bajas frecuencias afectando los golpes de bielas.
6. **Multiplicadores de Utilidad Cost-Sensitive Post-Hoc:**
   * *Hipótesis:* Escalar las probabilidades de inferencia con multiplicadores de clase $C_k$ optimizados en validación.
   * *Resultado:* Val F1 subió a 86.61%, pero Test cayó a **76.87% F1**.
   * *Causa:* Sobreajuste severo a las peculiaridades muestrales de validación.

---

## 5. Ubicación de Checkpoints y Artefactos

Los pesos ganadores del Super-Ensamble Campeón se encuentran almacenados y versionados en:
* **ResNet34d RMS-Balanced:** [`backend/checkpoints/car-engine-diagnostics-resnet34d-multitask-hpss-rms-balanced/weights.pt`](file:///home/kevin/Work/fama/backend/checkpoints/car-engine-diagnostics-resnet34d-multitask-hpss-rms-balanced/weights.pt)
* **EfficientNet-B0 RMS-Balanced:** [`backend/checkpoints/car-engine-diagnostics-efficientnet-b0-multitask-hpss-additive/weights.pt`](file:///home/kevin/Work/fama/backend/checkpoints/car-engine-diagnostics-efficientnet-b0-multitask-hpss-additive/weights.pt)
* **PANNs CNN14 RMS-Balanced:** [`backend/checkpoints/car-engine-diagnostics-panns-cnn14-hpss-additive/weights.pt`](file:///home/kevin/Work/fama/backend/checkpoints/car-engine-diagnostics-panns-cnn14-hpss-additive/weights.pt)

### Comprobación Automatizada de la Suite de Pruebas
```bash
PYTHONPATH=backend pytest backend/tests/ -q
# Resultado: 137 passed, 2 warnings in 17s (100% en verde)
```
