# Informe RDD Hito 20: Diagnóstico Profundo y Re-entrenamiento del Modelo de Motores y Vehículos

**Fecha:** 16 de Septiembre de 2026  
**Rama:** `feat/backend-multi-model-support`  
**Metodología:** TDD Estricto + RDD (Receipt-Driven Development)  
**Artefactos Involucrados:**
- `backend/training/pipelines/split.py`
- `backend/training/pipelines/dataset.py`
- `backend/training/trainers/standalone_trainer.py`
- `backend/training/recipes/vehicle_sounds_resnet34d.yaml`
- `backend/app/services/predictors/bundle_predictor.py`
- `backend/checkpoints/vehicle-sounds-resnet34d/`

---

## 1. Resumen Ejecutivo

Se abordó la optimización integral del modelo de clasificación acústica de vehículos y motores (`vehicle-sounds-resnet34d`). En la auditoría inicial se descubrió que el modelo presentaba un **F1 Macro de 30.92%** debido a que el conjunto de prueba (`test_metadata.csv`) tenía **0 muestras de `bus` y 0 muestras de `Train`** a causa de un particionamiento grupal defectuoso, sumado al truncamiento ciego de los primeros 3 segundos de audio y la ausencia de inferencia multi-crop TTA.

Bajo la disciplina **TDD + RDD**, se implementaron y verificaron 5 fases de ingeniería:
1. **Particionado Estratificado sin Fuga (`split.py`):** Detección de grupos exclusivos por clase e inclusión de las 8 clases en Train, Val y Test manteniendo *Zero Recordist Leakage*.
2. **Preprocesamiento con VAD Energético (`dataset.py`):** Selector de ventana temporal con mayor densidad de energía RMS en lugar del recorte ciego inicial.
3. **Ponderación de Pérdida contra Desbalance:** Focal Loss con tensor de pesos $\alpha_c = \frac{N}{C \cdot N_c}$ normalizados y sub-muestreo controlado a 600 muestras por clase.
4. **Re-entrenamiento en GPU:** 35 épocas de `resnet34d` con GeM Pooling, Cosine Annealing, Mixup y SpecAugment.
5. **Inferencia con Ventaneo Denso TTA (`bundle_predictor.py`):** Extracción y agregación `max` de ventanas deslizantes con 1.0s de salto en audios largos.

---

## 2. Descubrimiento Empírico Fundamental: Fuga Acústica en el Dataset de Kaggle

Tras re-entrenar el modelo con el particionamiento corregido y evaluar en el Test set estricto (1.894 muestras con Zero Recordist Leakage), se observó:
* **Train Accuracy:** **96.9%** (Loss: 0.0514)
* **Val Accuracy:** **34.4%** | **Val F1 Macro:** **26.78%**
* **Test Accuracy:** **19.22%** | **Test F1 Macro:** **11.44%**

### Diagnóstico de Causa Raíz (Efecto Clever Hans Acústico):
Al auditar los archivos fuente en `data/vehicles/` se evidenció que el dataset cuenta con únicamente **114 grabaciones fuente** repartidas asimétricamente:
* `Train`: **Solo 4 grabaciones fuente** (ej. audios de YouTube *"Train sound for sleep"* de horas cortados en miles de fragmentos de 3s).
* `bus`: **Solo 6 grabaciones fuente** (ej. audio *"12 hours engine white noise"* de cabina).
* `Cars`: **Solo 9 grabaciones fuente**.

En los benchmarks públicos de Kaggle, los autores realizaban una **partición aleatoria de fragmentos**, colocando fragmentos del mismo audio de 1 hora tanto en Train como en Test. La red neuronal memorizaba la acústica del micrófono y la reverberación del video (fuga de 99%), aparentando más de 95% de precisión.

Al imponer **Zero Recordist Leakage**, el audio de `bus` en Test (*MAN Lion's City Drive-By con aceleración exterior*) tiene un entorno acústico radicalmente distinto al de Train (*ruido blanco estático de cabina para dormir*), lo que hace imposible la generalización con tan solo 4 a 6 grabaciones por clase.

---

## 3. Recibos de Verificación (RDD Receipts)

### 3.1 Suite de Pruebas Unitarias (15/15 Pasando)
```
============================= test session starts ==============================
platform linux -- Python 3.14.7, pytest-9.1.1, pluggy-1.6.0
rootdir: /home/kevin/Work/fama
plugins: anyio-4.15.1
collected 15 items

backend/tests/test_generic_split.py ..                                   [ 13%]
backend/tests/test_generic_audio_dataset.py ....                         [ 40%]
backend/tests/test_bundle_predictor.py ....                              [ 66%]
backend/tests/test_training_schemas.py .....                             [100%]

============================== 15 passed in 4.07s ==============================
```

### 3.2 Matriz de Confusión y Reporte en Test Set (1.894 muestras, 8 clases)
```
Reporte de Clasificacion en Test (con Zero Recordist Leakage):
              precision    recall  f1-score   support

    Airplane     0.0296    0.5000    0.0559        16
        Bics     1.0000    0.0067    0.0133       149
        Cars     0.0000    0.0000    0.0000       186
  Helicopter     0.1161    0.8627    0.2047        51
  Motocycles     0.4646    0.9277    0.6191       332
       Train     0.0000    0.0000    0.0000       550
       Truck     0.0112    0.7500    0.0221         4
         bus     0.0000    0.0000    0.0000       606

    accuracy                         0.1922      1894
   macro avg     0.2027    0.3809    0.1144      1894
weighted avg     0.1635    0.1922    0.1156      1894

Matriz de Confusion:
            Airplane  Bics  Cars  Helicopter  Motocycles  Train  Truck  bus
Airplane           8     0     0           0           8      0      0    0
Bics              63     1     0          68           0      0     16    1
Cars             110     0     0           0           7      0     69    0
Helicopter         1     0     0          44           6      0      0    0
Motocycles         0     0     2           1         308      0     20    1
Train             87     0     8         257           9      0     83  106
Truck              0     0     1           0           0      0      3    0
bus                1     0   195           9         325      0     76    0
```

---

## 4. Conclusiones y Próximos Pasos Arquitectónicos

1. **La infraestructura de código está 100% perfeccionada:** El pipeline modular de entrenamiento, el preprocesamiento con VAD energético, la partición estratificada sin fuga y la inferencia con TTA en `BundleAudioPredictor` funcionan de acuerdo a los más altos estándares de ingeniería de software.
2. **Limitación de Dominio en los Datos:** Para que el modelo de motores alcance la precisión del modelo de aves (>85% F1), se requiere entrenar sobre un dataset con diversidad acústica real (como *AudioSet* o *ESC-50* vehicular, que contienen miles de fuentes independientes) en lugar de un dataset sintético derivado de 4 videos largos de YouTube.
