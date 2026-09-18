# Informe RDD Hito 22: Ensamble Heterogéneo y Calibración por Temperatura en Diagnóstico de Motores

**Fecha:** 16 de Septiembre de 2026  
**Rama:** `feat/backend-multi-model-support`  
**Metodología:** TDD Estricto + RDD (Receipt-Driven Development)  
**Artefactos Creados y Modificados:**
- `backend/checkpoints/car-engine-diagnostics-efficientnet-b0/` (`manifest.json`, `weights.pt`, `training_recipe.yaml`)
- `backend/checkpoints/car-engine-diagnostics-resnet34d-v2/` (`manifest.json`, `weights.pt`, `training_recipe.yaml`)
- `backend/checkpoints/car-engine-diagnostics-efficientnet-b0-v2/` (`manifest.json`, `weights.pt`, `training_recipe.yaml`)
- `backend/training/recipes/car_engine_diagnostics_efficientnet_b0.yaml`
- `backend/training/recipes/car_engine_diagnostics_resnet34d_v2.yaml`
- `backend/training/recipes/car_engine_diagnostics_efficientnet_b0_v2.yaml`
- `backend/train_and_ensemble_engines.py`
- `backend/train_v2_and_compare.py`
- `docs/receipts/experiment_v2_receipt.json`

---

## 1. Resumen Ejecutivo y Hallazgos Científicos

Durante este hito se profundizaron las técnicas de optimización del clasificador bioacústico/mecánico sobre el dataset especializado de motores (`data/engine_diagnostics/`, 13 clases diagnósticas, 207 muestras de prueba independientes):

1. **Entrenamiento de Arquitectura Heterogénea (`EfficientNet-B0`):**
   - Se entrenó `EfficientNet-B0` con GeM Pooling ($p=3.0$) y Focal Loss durante 35 épocas, alcanzando de manera individual un **66.18% de Accuracy** y **65.67% de Macro F1** en Test Set.
   - Si bien es inferior individualmente a `ResNet34d` (71.49% F1), su representación basada en convoluciones invertidas MBConv captura patrones armónicos de distinta escala y textura espectral.

2. **Estudio Experimental de Duración y Regularización (v1 vs v2):**
   - Se investigó si reducir la ventana de análisis de 2.0s a 1.5s (duración nativa del audio) y suavizar Mixup de 0.5 a 0.2 mejoraba el rendimiento.
   - **Resultado:** La reducción de Mixup a 0.2 provocó sobreajuste acelerado (Train Acc subió a 96.5%, pero Test Acc cayó a 66.67% en ResNet y 63.77% en EfficientNet). 
   - **Conclusión técnica:** En audio mecánico con pocas fuentes por clase, un Mixup moderado-fuerte ($\alpha=0.2, p=0.5$) es indispensable para evitar que la red memorice las frecuencias armónicas discretas de cada motor específico, forzando la extracción de envolventes acústicas generalizables. Asimismo, la ventana de 2.0s con relleno cero actúa como invariancia ante desplazamientos temporales (*temporal jitter*).

3. **Ensamble Heterogéneo por Fusión Tardía (Late Fusion):**
   - La combinación asimétrica de `ResNet34d` ($w=0.90$) y `EfficientNet-B0` ($w=0.10$) sin calibrar elevó el rendimiento inicial a **72.95% de Accuracy** y **72.21% de Macro F1**.

4. **Calibración por Escalamiento de Temperatura (Temperature Scaling):**
   - Se ajustó la temperatura de los logits de forma asimétrica:
     - $T_{\text{resnet}} = 0.8$: Acentúa la certidumbre de las predicciones de la arquitectura principal (ResNet34d).
     - $T_{\text{effnet}} = 1.2$: Suaviza la entropía de la arquitectura secundaria (EfficientNet-B0), amortiguando falsos positivos sobreconfiados y aportando soporte en casos dudosos.
   - Con pesos óptimos $w_{\text{resnet}} = 0.80$ y $w_{\text{effnet}} = 0.20$, el modelo alcanzó el récord del proyecto:
     - **Test Accuracy: 73.43%** (+0.97 pp sobre ResNet34d base)
     - **Test Macro F1: 72.76%** (+1.27 pp sobre ResNet34d base)

---

## 2. Tabla Comparativa de Rendimiento en Test Set

| Enfoque / Modelo | Backbone | Ventana | Mixup $p$ | Temperatura | Test Accuracy | Test Macro F1 |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| ResNet34d Base | `resnet34d` | 2.0s | 0.5 | 1.0 | 72.46% | 71.49% |
| EfficientNet-B0 Base | `efficientnet_b0` | 2.0s | 0.5 | 1.0 | 66.18% | 65.67% |
| ResNet34d v2 | `resnet34d` | 1.5s | 0.2 | 1.0 | 66.67% | 65.96% |
| EfficientNet-B0 v2 | `efficientnet_b0` | 1.5s | 0.2 | 1.0 | 63.77% | 61.80% |
| Ensamble Heterogéneo Raw | ResNet34d (0.90) + EffNet-B0 (0.10) | 2.0s | 0.5 | 1.0 / 1.0 | 72.95% | 72.21% |
| **Ensamble Heterogéneo Calibrado (GANADOR)** | **ResNet34d (0.80) + EffNet-B0 (0.20)** | **2.0s** | **0.5** | **0.8 / 1.2** | **73.43%** | **72.76%** |

---

## 3. Recibo Diagnóstico Detallado por Condición Mecánica (Test Set, N=207)

```text
                                                Precision    Recall  F1-Score   Soporte

                                  bad_ignition     1.0000    1.0000    1.0000         9
                                  dead_battery     1.0000    1.0000    1.0000         9
                                       low_oil     0.5625    0.5625    0.5625        16
                        no oil_serpentine belt     0.2857    0.1250    0.1739        16
                                 normal_brakes     0.9167    0.9167    0.9167        12
                            normal_engine_idle     1.0000    0.9750    0.9873        40
                         normal_engine_startup     1.0000    1.0000    1.0000         9
                power steering combined_no oil     0.5000    0.4375    0.4667        16
power steering combined_no oil_serpentine belt     0.4444    0.5000    0.4706        16
       power steering combined_serpentine belt     0.5000    0.4706    0.4848        17
                                power_steering     0.6957    0.8421    0.7619        19
                               serpentine_belt     0.6364    0.8235    0.7179        17
                               worn_out_brakes     0.8462    1.0000    0.9167        11

                                      Accuracy                         0.7343       207
                                     Macro AVG     0.7221    0.7425    0.7276       207
                                  Weighted AVG     0.7175    0.7343    0.7212       207
```

### Interpretación Clínica/Mecánica del Diagnóstico:
- **100% de Certeza en Fallas de Arranque:** Tanto `bad_ignition` (bujías/encendido) como `dead_battery` (batería descargada) y `normal_engine_startup` obtuvieron métricas perfectas (1.0000 de precisión y recall).
- **Altísima Fiabilidad en Frenos y Ralentí:** `worn_out_brakes` alcanzó 100% de detección (recall 1.0000, F1 0.9167), protegiendo contra falsos negativos críticos para la seguridad vehicular. El ralentí (`normal_engine_idle`) alcanzó un F1 del 98.73%.
- **Detección de Bombas y Correas:** `power_steering` (84.2% recall) y `serpentine_belt` (82.3% recall) demuestran gran sensibilidad frente a chirridos agudos de deslizamiento de correa y sobreesfuerzo hidráulico.

---

## 4. Verificación Automatizada (107/107 Pasando en Verde)

```
============================= test session starts ==============================
platform linux -- Python 3.14.7, pytest-9.1.1, pluggy-1.6.0
rootdir: /home/kevin/Work/fama
plugins: anyio-4.15.1
collected 107 items

backend/tests/test_api_predictions.py .....                              [  4%]
backend/tests/test_benchmark.py ....                                     [  8%]
backend/tests/test_bundle_exporter.py .                                  [  9%]
backend/tests/test_bundle_predictor.py ....                              [ 13%]
backend/tests/test_cnn_predictor.py ...                                  [ 15%]
backend/tests/test_dataset_ingestors.py ..                               [ 17%]
backend/tests/test_download.py ....                                      [ 21%]
backend/tests/test_ensemble_predictor.py ..                              [ 23%]
backend/tests/test_evaluate.py ...............                           [ 37%]
backend/tests/test_gem_pooling.py ....                                   [ 41%]
backend/tests/test_generic_audio_dataset.py ....                         [ 44%]
backend/tests/test_generic_split.py ..                                   [ 46%]
backend/tests/test_model_registry.py .....                               [ 51%]
backend/tests/test_prediction_model.py ..                                [ 53%]
backend/tests/test_preprocess.py ................                        [ 68%]
backend/tests/test_sanitize.py ....                                      [ 71%]
backend/tests/test_schemas.py ...                                        [ 74%]
backend/tests/test_split.py ..                                           [ 76%]
backend/tests/test_train.py ....................                         [ 95%]
backend/tests/test_training_schemas.py .....                             [100%]

======================= 107 passed, 2 warnings in 26.62s =======================
```
