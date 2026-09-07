# ADR 0009: Desplazamiento Tonal Espectral en GPU (Spectral Pitch Shift) como Data Augmentation Bioacústico

* **Estado:** Aceptado  
* **Fecha:** 2026-09-06  
* **Decisores:** Equipo F.A.M.A.  
* **Área:** Data Augmentation, GPU Preprocessing, Bioacústica, Deep Learning  

---

## 1. Contexto y Problema

En bioacústica aviar, los cantos y llamadas de individuos de una misma especie presentan variaciones naturales en su frecuencia fundamental ($f_0$) y estructura armónica de aproximadamente $\pm 1.0$ semitono. Estas variaciones se originan en diferencias morfológicas (tamaño corporal, masa de la siringe), dimorfismo sexual, edad y dialectos geográficos locales. 

Para dotar a los modelos neuronales de invarianza frente a estas variaciones tonales sin perder capacidad discriminante entre especies simpátricas, es necesario incorporar técnicas de desplazamiento tonal (*pitch shifting*). Sin embargo, el enfoque convencional presenta graves limitaciones:

1. **Inviabilidad Computacional del Phase Vocoder Clásico:**
   * El pitch shift tradicional opera sobre la forma de onda en el dominio temporal mediante STFT, escalado de frecuencia con phase vocoder e iSTFT (ej. `torchaudio.functional.pitch_shift` o `librosa.effects.pitch_shift`).
   * En benchmarks locales sobre GPU, este procedimiento consume ~180 ms por cada segmento de audio de 5 segundos.
   * Multiplicado por los cientos de lotes por época, el tiempo de entrenamiento se incrementaría de 4.5 minutos a más de 35 minutos por corrida de 35 épocas, destruyendo la agilidad del ciclo experimental.
   * Adicionalmente, el phase vocoder introduce artefactos de fase metálicos y robóticos que distorsionan los formantes biológicos reales.

2. **Propiedades Matemáticas del Banco de Filtros Mel:**
   * En la escala Mel, el mapeo de frecuencia lineal a perceptiva sigue una relación logarítmica:
     $$m = 2595 \log_{10}\left(1 + \frac{f}{700}\right)$$
   * Un cambio de tono relativo de $\Delta s$ semitonos corresponde a multiplicar las frecuencias por $2^{\Delta s / 12}$.
   * Debido a la compresión logarítmica de la escala Mel, una multiplicación en frecuencia lineal se traduce algebraicamente en un desplazamiento aditivo constante a lo largo de los bancos de filtros Mel:
     $$M_{\text{shifted}}(m, t) \approx M(m - \Delta m, t)$$
   * Por ende, un desplazamiento tonal bioacústicamente plausible ($\pm 1.0$ semitono) puede aproximarse de forma exacta y elegante como una traslación discreta de canales de frecuencia ($\Delta m \in \{-2, -1, +1, +2\}$) sobre el tensor Mel ya calculado en VRAM.

---

## 2. Decisión Arquitectónica

Se implementa la técnica de **Desplazamiento Tonal Espectral (*Spectral Pitch Shift*)** directamente en la capa de aumento de datos en GPU `GPUSpecAugment` (`backend/poc/preprocess.py`):

1. **Integración en `GPUSpecAugment`:**
   * Se incorporan los hiperparámetros `pitch_shift_max_bins: int = 2` y `pitch_shift_prob: float = 0.3`.
   * En cada pasada de entrenamiento (`self.training == True`), para cada muestra del lote, con probabilidad `pitch_shift_prob`, se muestrea estocásticamente un desplazamiento discreto no nulo $\Delta m \in [-\text{pitch\_shift\_max\_bins}, \dots, \text{pitch\_shift\_max\_bins}] \setminus \{0\}$.
   * La traslación se realiza mediante corte tensorial y concatenación con tensores de ceros (*zero-padding*) en el extremo correspondiente:
     * Si $\Delta m > 0$ (tono más agudo): se rellenan con ceros los primeros $\Delta m$ canales de baja frecuencia y se desplaza el espectro hacia frecuencias superiores:
       $$M_{\text{out}}[0:\Delta m, :] = 0, \quad M_{\text{out}}[\Delta m:F, :] = M[0:F-\Delta m, :]$$
     * Si $\Delta m < 0$ (tono más grave): se desplaza el espectro hacia frecuencias inferiores y se rellenan con ceros los últimos $|\Delta m|$ canales de alta frecuencia:
       $$M_{\text{out}}[0:F-|\Delta m|, :] = M[|\Delta m|:F, :], \quad M_{\text{out}}[F-|\Delta m|:F, :] = 0$$

2. **Aislamiento Estricto y No-Op Determinista en Evaluación:**
   * Cuando el módulo se encuentra en modo evaluación (`model.eval()`), la traslación espectral se desactiva de manera determinista e inmediata, garantizando que el tensor retornado sea idéntico al de entrada sin introducir dispersión ni estocasticidad en inferencia.

3. **Propagación a Pipeline de Entrenamiento:**
   * Se exponen los parámetros CLI `--pitch-shift-bins` y `--pitch-shift-prob` en `backend/poc/train.py`, instanciando `GPUSpecAugment` con estos valores durante la inicialización de `train_pipeline`.

---

## 3. Consecuencias y Trade-offs

### Positivas:
* **Latencia Cero en GPU (< 0.05 ms por batch):** Al operar directamente sobre el tensor en memoria VRAM mediante rebanado y concatenación out-of-place, no se requieren transformadas de Fourier inversas ni re-cálculos de espectrogramas, manteniendo inalterado el tiempo de entrenamiento de ~4.5 minutos por 35 épocas.
* **Preservación de Gradientes:** Las operaciones tensoriales son 100% derivables y conservan gradientes numéricamente estables y finitos para la optimización por descenso de gradiente (`.backward()`).
* **Mejora en Generalización Bioacústica:** Proporciona regularización efectiva frente a variaciones intraespecíficas de frecuencia, beneficiando especialmente a especies crípticas con llamadas breves y baja representación en el dataset (ej. *Scytalopus magellanicus* / Churrín del sur, *Scelorchilus rubecula* / Chucao).

### Negativas / Consideraciones:
* **Aproximación Discreta:** El desplazamiento está cuantizado al tamaño del bin Mel ($\approx 0.5$ semitonos por bin para $N_{\text{mel}}=128$), lo cual es suficientemente granular para modelar variaciones de tono natural pero no permite micro-afinaciones continuas arbitrarias.
