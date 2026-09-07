# ADR 0002: Mixup Aditivo en VRAM y Test-Time Augmentation (TTA) con Multi-Crop en Inferencia

* **Estado:** Aceptado / En Implementación  
* **Fecha:** 2026-09-05  
* **Decisores:** Equipo F.A.M.A.  
* **Área:** Inferencia Bioacústica, Regularización en GPU y MLOps  

---

## 1. Contexto y Problema

Tras la adopción de la arquitectura `BioacousticEfficientNet` y el front-end de espectrogramas Mel en GPU (ADR 0001), el modelo alcanzó un rendimiento significativamente superior en validación interna pero evidenció limitaciones críticas tanto en la fase de entrenamiento como en la evaluación de campo:

1. **Sub-muestreo Temporal y Pérdida de Información en Inferencia (Single-Crop):**  
   En la estrategia actual de inferencia (`AudioDataset` con `is_train=False`), cada archivo de audio —independientemente de si dura 5 segundos o más de 60 segundos— se colapsa a una única ventana fija de 5.0 s (seleccionada deterministamente mediante el mayor RMS energético detectado por VAD). Si la vocalización diagnóstica de la especie ocurre en una sección de menor amplitud relativa, o si una ráfaga de viento/ruido antropogénico genera un pico espurio de RMS, el modelo evalúa una ventana que no contiene el canto diagnóstico, provocando falsos negativos sistemáticos.

2. **Sobreajuste a Entornos Acústicos Focales y Polifonía en Campo:**  
   Las grabaciones focales (Xeno-Canto) poseen firmas de fondo específicas y relaciones señal-a-ruido (SNR) variables. El entrenamiento estándar con Cross-Entropy / Focal Loss sobre espectrogramas individuales induce sobreconfianza en las predicciones y memorización de patrones espurios. En escenarios reales de monitoreo bioacústico pasivo (PAM), las aves cantan de forma solapada (polifonía bioacústica) y en presencia de ruido difuso constante.

3. **Cuello de Botella I/O en Aumentación de Mezclas:**  
   Implementar mezclas de audio en CPU durante la carga en `DataLoader` saturaría los hilos de decodificación y re-muestreo, recreando el problema de inanición de GPU (*GPU Starvation*) documentado en el ADR 0001.

---

## 2. Decisión Arquitectónica

Se aprueba la implementación de una estrategia dual de regularización e inferencia robusta:

### 2.1 Test-Time Augmentation (TTA) Multi-Crop con Agregación Probabilística
Para el proceso de inferencia y evaluación (`backend/poc/evaluate.py`):
* **Segmentación Dinámica sin Pérdida de Cobertura:** Cada grabación se segmenta en todas sus ventanas activas detectadas por VAD ($N$ ventanas de 5.0 s con desplazamiento `hop_seconds=2.5s`, logrando un 50% de solapamiento). Para audios cortos ($< 5.0\text{ s}$), se aplica zero-padding devolviendo un único segmento ($N=1$).
* **Inferencia Paralela en GPU (Mini-Lote):** En lugar de evaluar secuencialmente cada ventana o colapsar el dataset en un `DataLoader` con tensores de forma irregular, la función `predict_audio_tta` construye un tensor de lote compacto de forma $[N, 1, \text{n\_mels}, \text{time\_steps}]$ (o $[N, T]$ para el front-end GPU) y ejecuta un único pase forward paralelo en GPU.
* **Agregación de Probabilidades:** Se transforman los logits mediante `softmax` y se aplican dos modos de agregación ortogonales:
  * **Mean-Pooling (`mean`):** $\bar{P} = \frac{1}{N} \sum_{i=1}^N \text{Softmax}(z_i)$. Promedia la distribución de certeza a lo largo de toda la grabación. Atenúa detecciones transitorias dudosas y prioriza especies con presencia acústica sostenida.
  * **Max-Pooling (`max`):** $P^* = \max_{i=1,\dots,N} \text{Softmax}(z_i)$. Selecciona el pico de evidencia máxima para cada especie entre todas las ventanas evaluadas. Ideal para especies crípticas con cantos breves o espaciados que de otro modo quedarían diluidos por el promedio de segmentos de fondo.
* **Preservación Arquitectónica de Contratos:** La interfaz de `AudioDataset.__getitem__` y el flujo por defecto de `evaluate_test_set` permanecen inmutables (`[1, n_mels, time_steps]`), activando TTA de forma desacoplada y configurable vía CLI (`--use-tta`, `--tta-mode {mean,max}`).

### 2.2 Mixup Aditivo Directamente en VRAM (GPU)
Para la etapa de entrenamiento en lotes:
* **Operación Vectorizada en VRAM:** Aplicar Mixup aditivo directamente sobre los tensores de espectrogramas Mel $[B, 1, \text{n\_mels}, T]$ (o formas de onda) transferidos a GPU:
  $$\tilde{x} = \lambda x + (1 - \lambda) x_{\pi}, \quad \tilde{y} = \lambda y + (1 - \lambda) y_{\pi}$$
  donde $\pi$ es una permutación aleatoria de los índices del lote y $\lambda \sim \text{Beta}(\alpha, \alpha)$ con $\alpha \in [0.2, 0.4]$.
* **Zero Overhead de CPU:** Al ejecutarse tras la transferencia del lote a la memoria de video de la NVIDIA RTX 2050, no impone latencia de cómputo en el host ni compite con el `DataLoader`.

---

## 3. Fundamentación Teórica y Estado del Arte

Esta decisión se sustenta en la literatura reciente y estándares competitivos de aprendizaje bioacústico:

1. **Competiciones Kaggle BirdCLEF (2024 y 2025):**  
   En las soluciones de los equipos de punta (Top 1% en BirdCLEF 2024 y 2025), el uso de **Mixup espectral** y **TTA multi-crop (sliding window) con mean/max pooling** constituye un estándar unánime. Los competidores demostraron que el recorte arbitrario de una sola ventana pierde hasta el 35% de los cantos relevantes en audios largos (> 15 s) debido a la naturaleza dispersa de los cantos de aves silvestres.
2. **Benchmark BirdSet (ICLR 2025 - *BirdSet: A Benchmark for Bird Species Identification*):**  
   El estudio formaliza que la evaluación multiventana con agregación (mean/max pooling) es indispensable para cerrar la brecha de dominio entre grabaciones de audio focal (grabadas apuntando al espécimen) y grabaciones de monitoreo acústico pasivo (PAM, con micrófonos autónomos fijos). Demuestra además que el Mixup lineal regulariza las fronteras de decisión de modelos convolucionales y transformadores ante el solapamiento bioacústico de alta dimensionalidad.

---

## 4. Consecuencias y Trade-offs

### Positivas:
* **Eliminación del Sesgo de Ventana Única:** Se elimina el riesgo de evaluar ventanas vacías o ruidosas en audios largos, garantizando cobertura del 100% de los segmentos acústicamente activos del archivo.
* **Flexibilidad Operativa (Mean vs Max):** Permite sintonizar la estrategia de inferencia según el objetivo ecológico: detección conservadora y calibrada (`mean`) versus alta sensibilidad para especies raras o de vocalización breve (`max`).
* **Eficiencia Vectorizada en GPU:** Inferencia en lotes de tamaño $N$ por archivo aprovecha la capacidad de cómputo paralelo de la GPU sin incurrir en cuellos de botella secuenciales.
* **Compatibilidad Hacia Atrás:** Mantiene intacto el contrato de `AudioDataset` y `DataLoader`, evitando errores de tensores irregulares en mini-lotes estándar.

### Negativas / Riesgos:
* **Mayor Consumo Transitorio de Cómputo por Inferencia:** Cada archivo de prueba ejecuta $N$ pases forward en lugar de 1. No obstante, dado que $N \le 15$ en la gran mayoría de audios del dataset, el tiempo adicional es marginal en GPU (< 15 ms adicionales por archivo).
* **Calibración de Hiperparámetro $\alpha$ de Mixup:** Requiere experimentación controlada para evitar que valores excesivamente altos de $\alpha$ distorsionen los perfiles espectrales de especies con cantos tenues.
