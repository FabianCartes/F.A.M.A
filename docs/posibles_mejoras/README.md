# Hoja de Ruta Técnica: Posibles Mejoras de Rendimiento y Arquitectura de Modelo

**Proyecto:** Framework MLOps Híbrido para Clasificación de Audio (F.A.M.A.)  
**Fecha:** Septiembre 2026  
**Área:** Escalabilidad, Arquitectura de Redes y Optimización de Cómputo  
**Estado:** Propuesta Técnica y Hoja de Ruta Futura  

---

## 1. Contexto Actual y Diagnóstico del Pipeline

Tras completar las cuatro primeras iteraciones del proyecto:
1. **Ingesta y Saneamiento:** Dataset 100% transcodificado a formato estándar WAV PCM 16-bit a 22.050 Hz (`data/processed_wav/`), eliminando las advertencias y fallas de decuantización en C de `libmpg123`.
2. **Multiprocesamiento Seguro:** Factoría concurrente `build_dataloaders` con aislamiento RNG (`seed_worker`), eliminación de Copy-on-Write y memoria fijada (`pin_memory`).
3. **Desempeño Actual:** El entrenamiento de 15 épocas se redujo de 19 minutos (en CPU) a **8.5 minutos en GPU** (~35 segundos por época).
4. **Límites Detectados:**
   * **Inanición de GPU (*GPU Starvation*):** La tarjeta gráfica computa un lote en 3–5 ms pero espera ~300 ms a que los workers de CPU calculen el espectrograma Mel en `librosa`.
   * **Techo de Capacidad del Modelo:** La red convolucional plana de 4 capas (`AudioCNN`) entrenada desde cero alcanza entre 50% y 65% de precisión, presentando variabilidad ante pequeñas fluctuaciones del conjunto de prueba (154 muestras).

A continuación se plantean las cuatro mejoras técnicas estructuradas para resolver estos cuellos de botella.

---

## 2. Propuesta 1: Aceleración de Espectrogramas en GPU (`torchaudio`)

### Problema:
Actualmente, cada worker de CPU ejecuta en tiempo de ejecución:
$$\text{Forma de onda (WAV)} \xrightarrow{\text{librosa.feature.melspectrogram}} \text{STFT} \xrightarrow{\text{Filtros Mel}} \text{power\_to\_db} \rightarrow \text{Tensor PyTorch}$$
Este cómputo matemático consume la mayor parte del tiempo de CPU por lote, forzando a la GPU a permanecer inactiva el 98% del tiempo.

### Solución Arquitectónica:
Mover la extracción del espectrograma Mel a la GPU como la primera capa diferenciable del modelo o al inicio del bucle de entrenamiento por lote:

```python
import torch
import torch.nn as nn
import torchaudio.transforms as T

class GPUAudioFrontEnd(nn.Module):
    def __init__(self, sample_rate=22050, n_fft=1024, hop_length=512, n_mels=64):
        super().__init__()
        self.mel_spectrogram = T.MelSpectrogram(
            sample_rate=sample_rate,
            n_fft=n_fft,
            hop_length=hop_length,
            n_mels=n_mels,
            power=2.0,
        )
        self.amplitude_to_db = T.AmplitudeToDB(top_db=80.0)

    def forward(self, waveform: torch.Tensor) -> torch.Tensor:
        # waveform: [Batch, Time] en GPU
        mel = self.mel_spectrogram(waveform)
        mel_db = self.amplitude_to_db(mel)
        # Normalización estandarizada por lote
        return mel_db.unsqueeze(1)  # [Batch, 1, Mel, Time]
```

### Trade-offs y Beneficios:
* **Beneficio:** La CPU únicamente realiza lectura I/O de archivos WAV y *Time Shift*. Las FFTs se calculan en paralelo masivo en los núcleos CUDA de la GPU.
* **Tiempo estimado por época:** Reducción de ~35 segundos a **~5 a 8 segundos por época** (aceleración de 4x a 7x).
* **Utilización de GPU:** Aumento del ciclo de trabajo de la GPU al 70%–90% continuo.

---

## 3. Propuesta 2: Migración a Backbones Preentrenados (*Transfer Learning*)

### Problema:
`AudioCNN` posee solo 4 capas convolucionales sin conexiones residuales ni mecanismos de atención, lo que impide capturar texturas espectrales complejas ni relaciones armónicas globales de cantos similares (ej. *Turca* vs *Chucao*).

### Solución Arquitectónica:
Adoptar un *backbone* estándar de visión/audio preentrenado como **EfficientNet-B0** mediante la biblioteca `timm`:

```python
import timm
import torch.nn as nn

class BioacousticEfficientNet(nn.Module):
    def __init__(self, num_classes=15, pretrained=True, in_chans=1, drop_rate=0.3):
        super().__init__()
        self.backbone = timm.create_model(
            "tf_efficientnet_b0_ns",
            pretrained=pretrained,
            in_chans=in_chans,
            drop_rate=drop_rate,
        )
        in_features = self.backbone.classifier.in_features
        self.backbone.classifier = nn.Sequential(
            nn.Dropout(drop_rate),
            nn.Linear(in_features, num_classes)
        )

    def forward(self, x):
        return self.backbone(x)
```

### Estrategia de Entrenamiento:
1. **Fase 1 (Warmup / Frozen Backbone):** Congelar pesos del extractor y entrenar solo el clasificador lineal durante 3 épocas ($\text{lr} = 1\times 10^{-3}$).
2. **Fase 2 (Fine-Tuning con Discriminative LR):** Descongelar capas profundas con tasa de aprendizaje reducida ($\text{lr} = 1\times 10^{-4}$) y optimizador AdamW con decaimiento de peso (*Weight Decay*).

### Trade-offs y Beneficios:
* **Beneficio:** Filtros con capacidad de extracción rica de bordes, patrones y armónicos formados en millones de imágenes/espectrogramas.
* **Métricas proyectadas:** Superar el **80% - 85% de exactitud y F1-Score macro** en el conjunto de prueba.
* **Costo computacional:** Requiere ~1.5 GB de VRAM (dentro de los 4 GB disponibles en la RTX 2050).

---

## 4. Propuesta 3: Representaciones Bioacústicas Especializadas (Google Perch / BirdNET)

### Problema:
Las redes de visión estándar no fueron optimizadas originalmente para acústica ambiental ni discriminación ornitológica.

### Solución Arquitectónica:
Utilizar modelos de fundación bioacústica:
* **Google Perch (Agi):** Modelo entrenado en más de 10.000 especies de aves globales utilizando arquitecturas Conformer/EfficientNet. Genera vectores de incrustación (*embeddings*) de 1.280 dimensiones cada 5 segundos de audio.
* **Esquema de Inferencia e Ingesta:**
  1. Extraer los *embeddings* de los 1.206 audios una sola vez y guardarlos en disco (en formato NumPy o HDF5).
  2. Entrenar una cabeza clasificadora ligera (MLP o Regresión Logística) sobre los embeddings en **menos de 30 segundos**.

```
[ Audio WAV (22.05 kHz) ]
         │
         ▼
[ Google Perch Backbone (Pre-trained) ]
         │
         ▼ (Vector denso de 1280 floats)
[ Clasificador Denso: Linear(1280, 256) -> ReLU -> Linear(256, 15) ]
         │
         ▼
[ Predicción de Especie ]
```

### Trade-offs y Beneficios:
* **Beneficio:** Robustez extrema ante ruido de viento, lluvia y solapamiento de especies.
* **Tiempo de entrenamiento:** Prácticamente instantáneo (solo se optimiza un clasificador lineal pequeño).
* **Dependencias:** Requiere `tensorflow-hub` o `onnxruntime` para ejecutar el modelo Perch base.

---

## 5. Propuesta 4: Detección de Eventos Sonoros (SED) y Regularización Avanzada

### Problema:
En grabaciones largas (30–60 segundos), el ave puede cantar solo durante 2 segundos y el resto ser silencio o ruido de fondo. El muestreo VAD actual corta ventanas estáticas de 5 segundos, arriesgando incluir ventanas donde el canto quedó en el borde.

### Solución Arquitectónica:
1. **Sound Event Detection (SED) con Pooling de Atención:** La red predice probabilidades a nivel de trama temporal (*frame-level*) y las agrega mediante atención débilmente supervisada:
   $$P(\text{clase}) = \frac{\sum_t w_t \cdot y_t}{\sum_t w_t}$$
2. **Data Augmentation con MixUp:**
   Mezclar dos espectrogramas con una proporción $\lambda \sim \text{Beta}(\alpha, \alpha)$:
   $$\tilde{x} = \lambda x_i + (1 - \lambda) x_j, \quad \tilde{y} = \lambda y_i + (1 - \lambda) y_j$$
   Obliga a la red a no sobreajustarse a amplitudes absolutas y enseña a distinguir especies coexistentes.
3. **Focal Loss:** Penaliza con mayor peso los ejemplos difíciles y las clases con menor número de grabaciones en el split.

---

## 6. Cuadro Comparativo y Priorización de Implementación

| Propuesta | Complejidad de Implementación | Impacto en Velocidad | Impacto en Precisión (F1) | Prioridad Recomendada |
|---|:---:|:---:|:---:|:---:|
| **1. Espectrogramas en GPU (`torchaudio`)** | Baja | **Muy Alto (4x - 7x más veloz)** | Neutral | **Inmediata (Iteración 5)** |
| **2. Backbone EfficientNet-B0 (`timm`)** | Media | Neutral (~35s/época) | **Muy Alto (+25% a +35% F1)** | **Inmediata (Iteración 5)** |
| **3. Embeddings Google Perch / BirdNET** | Media-Alta | **Extremo (entrenamiento en segundos)** | **SOTA (>85% F1)** | **Medio Plazo (Iteración 6)** |
| **4. Arquitectura SED + MixUp** | Alta | Leve disminución | **Alto (en grabaciones continuas)** | **Largo Plazo** |

---

## 7. Conclusión

El pipeline actual en `fama` cuenta con bases sólidas: datos saneados, multiprocesamiento libre de fugas de memoria y suite de pruebas integral. 

La ruta natural más eficiente para el proyecto es la combinación de la **Propuesta 1 (Espectrogramas en GPU)** y la **Propuesta 2 (EfficientNet-B0)**, lo que permitirá entrenar un modelo de clase mundial en menos de 3 minutos por corrida completa en la estación de trabajo local.
