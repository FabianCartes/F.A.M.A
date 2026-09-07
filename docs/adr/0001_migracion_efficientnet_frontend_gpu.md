# ADR 0001: Migración a EfficientNet-B0, Front-End GPU de 128 Mel y Focal Loss

* **Estado:** Aceptado / En Implementación  
* **Fecha:** 2026-09-05  
* **Decisores:** Equipo F.A.M.A.  
* **Área:** Arquitectura de Redes, Ingesta Bioacústica y MLOps  

---

## 1. Contexto y Problema

El pipeline inicial de clasificación bioacústica de 15 especies de aves chilenas (PoC) alcanzó su techo estructural con la arquitectura plana de 4 capas convolucionales (`AudioCNN`):
1. **Límite de Capacidad y Solapamiento de Clases:** En un benchmark de 10 ejecuciones independientes, `AudioCNN` estancó su rendimiento en **$54.68\% \pm 2.67\%$ de Accuracy** y **$55.82\% \pm 3.00\%$ de F1-Score macro**, presentando colapso sistemático en especies acústicamente similares (*Fío-fío* a $22.50\%$ F1, *Tijeral* a $27.48\%$ F1) canibalizadas por especies emparentadas (*Canastero*, *Turca*) y clases sumidero (*Tordo*, *Zorzal*), tal como se documentó en `docs/problemas_conocidos/01_solapamiento_de_clases_bioacusticas.md`.
2. **Inanición de GPU (*GPU Starvation*):** La extracción de espectrogramas Mel en CPU vía `librosa` toma ~300 ms por lote mientras la GPU procesa en ~5 ms, alargando la época a ~35 segundos e infrautilizando la GPU dedicada (`NVIDIA RTX 2050`).
3. **Resolución Espectral Insuficiente:** 64 bandas Mel comprimen armónicos sutiles en frecuencias medias-altas ($>4\text{ kHz}$), impidiendo la separación de firmas bioacústicas complejas.

---

## 2. Decisión Arquitectónica

Se aprueba la transición a la **Iteración 5** bajo la tríada **ADR + TDD + RDD**, implementando las siguientes modificaciones:

1. **Front-End Diferenciable en GPU (`GPUAudioFrontEnd`):**
   * Migrar la extracción espectral de CPU (`librosa`) a GPU utilizando `torchaudio.transforms.MelSpectrogram` y `AmplitudeToDB`.
   * Parámetros: `n_mels=128`, `n_fft=1024`, `hop_length=512`, `f_min=800.0 Hz`, `f_max=10000.0 Hz`.
   * La CPU solo ejecuta operaciones ligeras de lectura I/O de archivos WAV y aumentaciones temporales en crudo.
2. **Backbone `BioacousticEfficientNet` vía `timm`:**
   * Adoptar `timm.create_model("efficientnet_b0", pretrained=True, in_chans=1)`.
   * Adaptar la cabeza de salida a 15 clases: `Linear(in_features, 15)` precedida por `Dropout(0.3)`.
   * Estrategia de entrenamiento en 2 fases:
     * *Fase 1 (Warmup - 3 épocas):* Backbone congelado optimizando únicamente el clasificador lineal ($\text{lr} = 1\times 10^{-3}$).
     * *Fase 2 (Fine-tuning - 12 épocas):* Descongelado global suave con optimizador `AdamW` ($\text{lr} = 1\times 10^{-4}$, weight decay $1\times 10^{-2}$).
3. **Función de Pérdida `FocalLoss`:**
   * Sustituir Cross-Entropy estándar por Focal Loss ($\gamma = 2.0$) para enfocar los gradientes en clases con solapamiento y mitigar el sesgo hacia clases sumidero.
4. **Spike Timeboxeado Diferido (Perch v2):**
   * Se aprueba un spike timeboxeado de 2–3 h para extraer embeddings de Perch v2 y medir la cota superior del espacio latente. Si la ganancia respecto a EfficientNet supera los 5 puntos porcentuales de F1, se evaluará la destilación *Student-Teacher*.

---

## 3. Consecuencias y Trade-offs

### Positivas:
* **Resolución del Solapamiento Bioacústico:** Los bloques *Squeeze-and-Excitation* (SE) recalibran la atención de frecuencias según el timbre específico del ave.
* **Aceleración Computacional Masiva:** Reducción del tiempo de época de ~35 s a **~6–8 s**, permitiendo ciclos de experimentación ágiles en hardware local.
* **Salto en Rendimiento:** Se proyecta alcanzar entre **80% y 85% de F1-Score macro** en el conjunto de prueba.
* **Stack 100% PyTorch:** Integración limpia sin dependencias invasivas.

### Negativas / Riesgos:
* **Mayor Consumo de VRAM:** Aumento de ~700 MB a ~1.2 GB – 1.5 GB de memoria de video (completamente manejable dentro de los 4 GB de la RTX 2050).
* **Dependencia Externa:** Incorporación de la biblioteca `timm` en `backend/requirements.txt`.
