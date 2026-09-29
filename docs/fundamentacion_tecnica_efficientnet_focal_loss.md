# Documento Técnico: Fundamentos de la Técnica de Transfer Learning, Front-End GPU y Focal Loss

**Proyecto:** Framework MLOps Híbrido para Clasificación de Audio (F.A.M.A.)  
**Fecha:** Septiembre 2026  
**Fase:** Iteración 5 - Especificación y Fundamentación Matemática de la Técnica  
**Dominio:** 15 Especies de Aves de Chile (Dataset Xeno-canto v3)  
**Módulos Afectados:** `backend/poc/preprocess.py`, `backend/poc/train.py`, `backend/poc/evaluate.py`, `backend/poc/benchmark.py`  
**Referencia Arquitectónica:** `docs/adr/0001_migracion_efficientnet_frontend_gpu.md`  

---

## 1. Motivación y Principio Arquitectónico (Concepts > Code)

En la Iteración anterior, el modelo convolucional plano (`AudioCNN`, 4 capas secuenciales) demostró un techo de aprendizaje asintótico en torno al **54.68% ± 2.67% de Accuracy**, sufriendo el fenómeno patológico denominado **"Efecto Flores"** (`docs/problemas_conocidos/01_solapamiento_de_clases_bioacusticas.md`). Dicho problema no era una anomalía estadística soluble con más épocas de entrenamiento, sino una **deficiencia estructural de representación**:

1. **Falta de Capacidad y Campo Receptivo Rígido:** Las convoluciones planas de 4 capas carecen del campo receptivo y la profundidad no lineal necesarios para desenredar especies biológicamente emparentadas que comparten formantes espectrales cercanos (*Furnariidae*, *Rhinocryptidae*).
2. **GPU Starvation:** La extracción espectral en CPU con `librosa` (~300 ms por audio) estrangulaba el flujo de datos hacia la GPU, limitando la exploración de arquitecturas más profundas.
3. **Pérdida No Focalizada:** La entropía cruzada estándar ponderaba por igual las muestras evidentes y las muestras confusas, convirtiendo a clases frecuentes en "sumideros" de falsos positivos (*Tordo*).

Para resolver estos problemas de raíz, la técnica de la **Iteración 5** implementa un pipeline bioacústico moderno fundamentado en cuatro pilares complementarios.

---

## 2. Pilar 1: Extracción Espectral Vectorizada en GPU (`GPUAudioFrontEnd`)

El primer cuello de botella erradicado fue la latencia del preprocesamiento. En lugar de procesar los audios en CPU con bibliotecas externas y enviar matrices resultantes a la memoria gráfica, el audio crudo entra a la GPU en forma de lote de ondas vectorizadas y se transforma en VRAM mediante kernels CUDA de `torchaudio`.

```text
  Lote de Audio Crudo: [B, 110250] (22.05 kHz, 5.0 s)
            │
            ▼  torchaudio.transforms.MelSpectrogram (CUDA)
  Espectrograma Lineal de Potencia: [B, 1, 513, 216]
            │
            ▼  Filtro Paso-Banda Triangular Mel [128 bandas, 800 Hz - 10000 Hz]
  Espectrograma de Mel: [B, 1, 128, 216]
            │
            ▼  torchaudio.transforms.AmplitudeToDB (top_db=80.0)
  Representación Decibelios Logarítmica: Tensor [B, 1, 128, 216]
```

### 2.1. Transformada de Fourier de Tiempo Reducido (STFT)
Dada una señal discreta en el tiempo $x[n]$, la STFT se define como:
$$X[m, \omega] = \sum_{n=-\infty}^{\infty} x[n] w[n - mH] e^{-j \omega n}$$
Donde:
* $w[n]$ es una ventana de Hann de longitud $N_{\text{fft}} = 1024$ muestras ($\approx 46.4\text{ ms}$ a $22.05\text{ kHz}$).
* $H = 512$ muestras es el salto temporal (*hop length*, $\approx 23.2\text{ ms}$), produciendo una tasa de 43.1 tramas por segundo.
* $m$ es el índice temporal y $\omega$ el índice de frecuencia angular discreta.

### 2.2. Banco de Filtros Mel y Acotamiento Bioacústico
La escala Mel modela la percepción de tono aproximada mediante:
$$m = 2595 \log_{10}\left(1 + \frac{f}{700}\right)$$
* **Resolución:** Se aumentaron los bancos de filtros a $N_{\text{mels}} = 128$ bandas (frente a las 64 anteriores), permitiendo discriminar micro-modulaciones armónicas.
* **Filtro Paso-Banda ($f_{\min} = 800\text{ Hz}, f_{\max} = 10.000\text{ Hz}$):** Elimina ruidos graves de fondo (viento, vehículos, manipulación de micrófonos $<800\text{ Hz}$) y altas frecuencias ultrasónicas sin señal biológica relevante para las 15 especies chilenas analizadas.
* **Escala Logarítmica:** Conversión a decibelios acotada con un rango dinámico relativo de $80\text{ dB}$:
  $$S_{\text{dB}} = 10 \log_{10}\left(\frac{S}{\max(S)}\right), \quad \text{clamp a } [-80, 0]$$

---

## 3. Pilar 2: Transfer Learning con `BioacousticEfficientNet`

En lugar de forzar a una red pequeña a descubrir filtros visuales de baja frecuencia desde cero con apenas ~1.000 grabaciones, la técnica aplica **Transfer Learning** sobre el backbone `efficientnet_b0` preentrenado en ImageNet-1k (1.2 millones de imágenes).

### 3.1. Adaptador de Canal Inicial ($1 \to 3$)
Las arquitecturas de visión computacional preentrenadas esperan tensores RGB de 3 canales ($[B, 3, H, W]$). En lugar de triplicar el tensor en memoria (lo cual triplica el consumo de ancho de banda en VRAM sin aportar información nueva), se implementó una convolución puntual $1 \times 1$:

$$\mathbf{X}_{\text{RGB}} = \text{Conv2d}_{1 \times 1}(\mathbf{X}_{\text{Mel}}), \quad \mathbf{X}_{\text{Mel}} \in \mathbb{R}^{B \times 1 \times 128 \times 216} \to \mathbf{X}_{\text{RGB}} \in \mathbb{R}^{B \times 3 \times 128 \times 216}$$

Esta capa actúa como un **adaptador paramétrico aprendible** que proyecta el espectrograma a combinaciones ponderadas de los canales que alimentan los primeros filtros convolucionales de ImageNet.

### 3.2. Bloques MBConv y Mecanismo Squeeze-and-Excitation (SE)
La estructura nuclear de EfficientNet está formada por bloques **Mobile Inverted Bottleneck (MBConv)**:

```text
 Entrada [B, C_in, H, W]
       │
       ▼  Convolución Puntual 1x1 (Expansión de Canales: C_in -> t * C_in)
       │  BatchNorm + Swish (SiLU)
       │
       ▼  Convolución en Profundidad (Depthwise 3x3 o 5x5)
       │  BatchNorm + Swish (SiLU)
       │
       ▼  Módulo Squeeze-and-Excitation (SE):
       │   ├─ Global Average Pooling: [B, C_exp, 1, 1]
       │   ├─ Linear(C_exp -> C_exp / r) + ReLU
       │   ├─ Linear(C_exp / r -> C_exp) + Sigmoid (Pesos de Canal: s)
       │   └─ Multiplicación elemento a elemento: X * s
       │
       ▼  Convolución Puntual 1x1 (Proyección Lineal: t * C_in -> C_out)
       │  BatchNorm (Sin activación no lineal para preservar información)
       │
       ▼  Residual Skip Connection: Entrada + Salida (si C_in == C_out y stride == 1)
```

**Ventaja Bioacústica:**
El mecanismo **SE** actúa como un filtro de atención por bandas de frecuencia y armónicos. Si una especie vocaliza en una banda estrecha ($2.5\text{ kHz} - 3.5\text{ kHz}$), el módulo SE suprime dinámicamente los canales correspondientes a frecuencias ajenas, aislando el canto de los ruidos ambientales concurrentes.

---

## 4. Pilar 3: Esquema de Fine-Tuning en Dos Fases con Warmup

Un error común en Transfer Learning bioacústico es entrenar todo el modelo desde la época 1. Dado que el clasificador lineal ($1280 \to 15$ clases) parte con pesos aleatorios, genera gradientes de magnitud masiva en los primeros pasos, destruyendo los pesos preentrenados del backbone (*Catastrophic Forgetting*).

Para garantizar una convergencia controlada, se formuló una estrategia en dos etapas:

```text
 Épocas 1 a 3: FASE DE WARMUP (Calentamiento)
 ┌─────────────────────────────────────────────────────────────┐
 │  Backbone EfficientNet-B0: CONGELADO (requires_grad = False)│
 │  Capa Adaptadora 1x1 y Cabeza Lineal: ENTRENABLES           │
 │  Optimizador: Adam (LR = 1e-3)                              │
 └─────────────────────────────────────────────────────────────┘
                               │
                               ▼ Época 4: Transición
 Épocas 4 a 15: FASE DE FINE-TUNING END-TO-END
 ┌─────────────────────────────────────────────────────────────┐
 │  Backbone EfficientNet-B0: DESCONGELADO (requires_grad = True)
 │  Optimizador: AdamW (LR = 1e-4, Weight Decay = 1e-2)        │
 │  Scheduler: Decaimiento Coseno (Cosine Annealing)           │
 └─────────────────────────────────────────────────────────────┘
```

1. **Fase 1 (Warmup - 3 épocas):** La cabeza de clasificación y el adaptador $1 \times 1$ se alinean con las características generales del espectrograma mientras el extractor de características permanece protegido.
2. **Fase 2 (Fine-Tuning - 12 épocas):** Se reduce la tasa de aprendizaje por un orden de magnitud ($\text{LR} = 10^{-4}$) y se habilita `AdamW`. El weight decay desacoplado ($10^{-2}$) regulariza la red contra el sobreajuste (*overfitting*) en las 5.3 millones de variables.

---

## 5. Pilar 4: Modulación de Pérdida con Focal Loss

En clasificación multiclase desbalanceada y solapada, la función estándar de entropía cruzada (`CrossEntropyLoss`) acumula gradientes provenientes de una gran cantidad de muestras fáciles, relegando a las clases complejas:

$$\text{CE}(p_t) = -\log(p_t)$$

Donde $p_t$ es la probabilidad estimada por el modelo para la clase verdadera ($p_t \in [0, 1]$).

### 5.1. Formulación de Focal Loss
Para forzar a la red a concentrarse en las muestras limítrofes (como la diferenciación sutil entre *Tijeral* y *Canastero* o *Chucao* y *Turca*), se introdujo `FocalLoss` con parámetro de modulación $\gamma = 2.0$:

$$\text{FL}(p_t) = -(1 - p_t)^\gamma \log(p_t)$$

```text
  Factor Modulador (1 - p_t)^gamma  con gamma = 2.0:
  
   p_t = 0.95 (Muestra Fácil)  ──> (1 - 0.95)^2 = 0.0025  (Pérdida atenuada en 400x)
   p_t = 0.50 (Muestra Dudosa) ──> (1 - 0.50)^2 = 0.2500  (Pérdida retenida en 25%)
   p_t = 0.15 (Muestra Difícil)──> (1 - 0.15)^2 = 0.7225  (Pérdida casi intacta)
```

### 5.2. Impacto en la Dinámica de Gradientes
El gradiente de $\text{FL}$ respecto a la activación pre-softmax $z$ se amortigua drásticamente para muestras con alta confianza, mientras que preserva el empuje de gradiente en los casos difíciles. Esto impidió que clases fáciles dominaran la actualización de pesos y desactivó el mecanismo de "clase sumidero" del *Tordo*.

---

## 6. Mapeo Arquitectónico en el Repositorio

La implementación sigue estrictamente principios de **Clean Code**, **Deep Modules** y **TDD**:

| Componente Técnico | Clase / Función | Archivo Fuente | Suite de Pruebas |
| :--- | :--- | :--- | :--- |
| **Front-End GPU** | `GPUAudioFrontEnd` | `backend/poc/preprocess.py` | `backend/tests/test_preprocess.py` |
| **Arquitectura de Red** | `BioacousticEfficientNet` | `backend/poc/train.py` | `backend/tests/test_train.py` |
| **Función de Pérdida** | `FocalLoss` | `backend/poc/train.py` | `backend/tests/test_train.py` |
| **Pipeline de Entrenamiento** | `train_pipeline` | `backend/poc/train.py` | `backend/tests/test_train.py` |
| **Evaluación Test Set** | `run_evaluation` | `backend/poc/evaluate.py` | `backend/tests/test_evaluate.py` |
| **Benchmark Multicorrida** | `run_benchmark` | `backend/poc/benchmark.py` | `backend/tests/test_benchmark.py` |

---

## 7. Resumen de Trade-offs Técnicos

| Dimensión | Enfoque Anterior (`AudioCNN`) | Técnica Actual (`BioacousticEfficientNet`) | Justificación Técnica |
| :--- | :--- | :--- | :--- |
| **Representación** | 4 capas convolucionales planas | Backbone MBConv preentrenado (ImageNet) | Capacidad expresiva 12x superior; conexiones residuales. |
| **Extracción Espectral** | CPU con `librosa` (64 bandas) | GPU con `torchaudio` (128 bandas) | Aceleración 7x; mayor resolución en formantes bioacústicos. |
| **Rango de Frecuencias** | $0 - 11.025\text{ Hz}$ | $800 - 10.000\text{ Hz}$ | Eliminación de ruido infrasónico y frecuencias inertes. |
| **Función de Pérdida** | Cross-Entropy uniforme | Focal Loss ($\gamma = 2.0$) | Supresión de clases sumidero y priorización de clases solapadas. |
| **Consumo de Memoria** | ~1.1 GB VRAM | ~2.4 GB VRAM | Perfectamente viable en GPUs de entrada (RTX 2050 Mobile de 4 GB). |
| **Rendimiento Test** | 54.68% ± 2.67% Acc | **69.48% ± 4.23% Acc** ($N=5$) | Salto cualitativo comprobado estadísticamente en 15 especies. |
