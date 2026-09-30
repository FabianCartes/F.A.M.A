export interface ParameterExplanation {
  title: string;
  impact: string;
  usage: string;
  keyPoints: string[];
}

export const PARAMETER_EXPLANATIONS: Record<string, ParameterExplanation> = {
  // --- Audio Physics & Spectrogram Parameters ---
  target_sr: {
    title: "Frecuencia de Muestreo (Sample Rate)",
    impact:
      "Define el ancho de banda capturado y el límite de Nyquist (f_max <= SR/2), afectando directamente la resolución temporal y el consumo de memoria.",
    usage:
      "16 kHz para voz humana y tos; 22.05 kHz para aves y bioacústica; 32-44.1 kHz para maquinaria industrial y ultrasonidos.",
    keyPoints: [
      "Nyquist: frecuencias superiores a SR/2 sufrirán aliasing.",
      "Tasas más altas incrementan el tamaño del espectrograma y el uso de VRAM.",
    ],
  },
  duration_seconds: {
    title: "Duración de Ventana (Window Duration)",
    impact:
      "Determina la longitud temporal fija de cada segmento de audio suministrado a la red neuronal durante entrenamiento e inferencia.",
    usage:
      "1.5 - 2.0s para impactos mecánicos breves o tos; 5.0s para cantos bioacústicos complejos o monitoreo ambiental.",
    keyPoints: [
      "Audios más cortos que este valor se rellenan con silencio (padding).",
      "Audios más largos se fragmentan en múltiples ventanas.",
    ],
  },
  f_min: {
    title: "Frecuencia Mínima (f_min)",
    impact:
      "Filtra y descarta las frecuencias por debajo de este umbral en el banco de filtros Mel, eliminando componentes no informativos.",
    usage:
      "Elevar a 200 - 800 Hz para suprimir vibraciones mecánicas de soporte, viento o rumble de baja frecuencia.",
    keyPoints: [
      "0 - 50 Hz para señales con graves informativos.",
      "Evita que ruido subsónico domine la atención del espectrograma.",
    ],
  },
  f_max: {
    title: "Frecuencia Máxima (f_max)",
    impact:
      "Establece el límite superior del banco Mel, recortando frecuencias ultrasónicas o ruido de banda ancha irrelevante.",
    usage:
      "Ajustar al rango de la señal objetivo (ej. 8000 Hz para bioacústica general; 16000 Hz para chillidos industriales agudos).",
    keyPoints: [
      "Debe cumplir estrictamente f_max <= target_sr / 2.",
      "Enfoca los filtros Mel exclusivamente en la región con energía acústica útil.",
    ],
  },
  hop_seconds: {
    title: "Desplazamiento Temporal (Dense Windowing)",
    impact:
      "Controla el solapamiento entre ventanas consecutivas al evaluar audios de larga duración durante la inferencia.",
    usage:
      "0.5 - 1.0s para detección temporal de alta precisión; 2.5s para clasificaciones globales rápidas.",
    keyPoints: [
      "Un salto menor genera más ventanas por audio, elevando el costo computacional.",
      "Garantiza que eventos transitorios en los bordes de ventana no se pierdan.",
    ],
  },
  aggregation_mode: {
    title: "Modo de Agregación Temporal",
    impact:
      "Define la estrategia matemática para combinar las probabilidades predichas a lo largo de las múltiples ventanas de un audio.",
    usage:
      "Seleccionar 'max' para detectar eventos breves o anomalías súbitas; 'mean' para evaluar presencia sonora continua o dominante.",
    keyPoints: [
      "max: sensible a picos locales, ideal para alertas o llamados esporádicos.",
      "mean: robusto ante falsos positivos aislados, ideal para fondo acústico.",
    ],
  },
  gem_p: {
    title: "Exponente GeM (Generalized Mean Pooling)",
    impact:
      "Generaliza el pooling global entre promedio aritmético (p=1) y máximo estricto (p -> infinito), enfatizando regiones activas clave.",
    usage:
      "Configurar en 3.0 (estándar en audio) para focalizar eventos acústicos relevantes sin saturar gradientes.",
    keyPoints: [
      "p = 1 equivale a Average Pooling.",
      "p > 1 concentra la activación en patrones espectrales destacados.",
    ],
  },
  vad_threshold: {
    title: "Umbral de Actividad de Voz/Energía (VAD)",
    impact:
      "Filtra fragmentos de silencio o ruido de fondo que no alcancen el umbral de energía normalizado antes del procesamiento.",
    usage:
      "0.2 - 0.5 para descartar silencios en grabaciones de campo; 0.0 para desactivar y evaluar todo el audio sin descartes.",
    keyPoints: [
      "Reduce el tiempo de cómputo ignorando segmentos mudos.",
      "Umbrales muy altos pueden descartar eventos acústicos de baja amplitud.",
    ],
  },
  loss_type: {
    title: "Función de Pérdida (Loss Function)",
    impact:
      "Determina la función objetivo que penaliza las predicciones incorrectas y orienta la actualización de pesos en backpropagation.",
    usage:
      "'focal' para mitigar desbalance severo de clases; 'cross_entropy' para clasificación multiclase mutuamente excluyente y balanceada.",
    keyPoints: [
      "Focal Loss previene que las clases mayoritarias dominen el entrenamiento.",
      "BCE / Cross Entropy son óptimas con distribución equitativa de datos.",
    ],
  },
  focal_gamma: {
    title: "Factor Gamma Focal (Focal Gamma)",
    impact:
      "Modula el factor de enfoque en Focal Loss, reduciendo progresivamente la contribución de ejemplos fáciles y seguros.",
    usage:
      "2.0 es el valor de referencia estándar en clasificación de eventos acústicos desbalanceados.",
    keyPoints: [
      "gamma = 0 convierte la función en Cross Entropy tradicional.",
      "Valores más altos concentran el gradiente exclusivamente en casos ambiguos y difíciles.",
    ],
  },
  mixup: {
    title: "Aumento de Datos: Mixup",
    impact:
      "Combina pares aleatorios de espectrogramas y sus etiquetas en proporciones lineales continuas, suavizando fronteras de decisión.",
    usage:
      "Activar con probabilidad 0.3 - 0.5 en conjuntos de datos pequeños para prevenir sobreajuste y mejorar calibración.",
    keyPoints: [
      "Enseña al modelo a predecir incertidumbre proporcional ante mezclas sonoras.",
      "Evita que la red memorice ruido específico de fondo.",
    ],
  },
  pitch_shift: {
    title: "Aumento de Datos: Pitch Shift",
    impact:
      "Desplaza aleatoriamente el tono del audio hacia arriba o abajo en frecuencia sin modificar su duración temporal.",
    usage:
      "Activar en señales biológicas o de voz para simular variabilidad tímbrica entre individuos de una misma especie.",
    keyPoints: [
      "No recomendado en maquinaria donde frecuencias exactas corresponden a armónicos de rotación fija.",
      "Aumenta la robustez ante diferencias de resonancia física.",
    ],
  },

  // --- Model Hyperparameters ---
  learning_rate: {
    title: "Tasa de Aprendizaje (Learning Rate)",
    impact:
      "Escala el tamaño del paso de actualización de los parámetros de la red a lo largo del gradiente de la función de pérdida.",
    usage:
      "1e-3 a 3e-4 para arquitecturas preentrenadas con optimizador AdamW; reducir si la pérdida oscila o diverge.",
    keyPoints: [
      "Valores muy altos causan divergencia o inestabilidad numérica.",
      "Valores muy bajos provocan convergencia lenta o estancamiento en mínimos locales.",
    ],
  },
  weight_decay: {
    title: "Decaimiento de Pesos (Weight Decay / L2)",
    impact:
      "Aplica regularización L2 sobre los pesos desacoplada del gradiente en AdamW, restringiendo la magnitud de los parámetros.",
    usage:
      "0.01 a 0.1 en redes neuronales profundas (EfficientNet, ConvNeXt) para prevenir memorización de ruido.",
    keyPoints: [
      "En AdamW actúa como verdadero decaimiento de pesos, a diferencia de L2 en SGD.",
      "Valores excesivos restringen la capacidad representativa del modelo.",
    ],
  },
  epochs: {
    title: "Épocas de Entrenamiento (Epochs)",
    impact:
      "Cantidad de iteraciones completas que realiza el optimizador a través de todo el conjunto de entrenamiento.",
    usage:
      "10 - 35 épocas complementadas con decaimiento de tasa de aprendizaje y early stopping.",
    keyPoints: [
      "Pocas épocas derivan en underfitting (modelo no aprende patrones suficientes).",
      "Épocas excesivas aumentan el riesgo de overfitting si no hay suficiente regularización.",
    ],
  },
  batch_size: {
    title: "Tamaño de Lote (Batch Size)",
    impact:
      "Número de muestras de audio procesadas simultáneamente antes de calcular el gradiente y actualizar los pesos.",
    usage:
      "16 o 32 como balance ideal entre estabilidad de gradiente y consumo de VRAM en GPU.",
    keyPoints: [
      "Lotes grandes ofrecen gradientes más estables pero requieren mayor memoria GPU.",
      "Reducir a 8 o 4 si se experimentan errores CUDA Out of Memory (OOM).",
    ],
  },
  framework: {
    title: "Framework de Deep Learning",
    impact:
      "Motor computacional subyacente responsable del grafo de tensores, cálculo automático de gradientes y aceleración en hardware.",
    usage:
      "PyTorch como backend principal optimizado para pipelines de audio con soporte CUDA y Metal (MPS).",
    keyPoints: [
      "Garantiza ejecución paralela y cuantización eficiente.",
      "Compatible con librerías nativas como Torchaudio y PyTorch Lightning.",
    ],
  },
  architecture: {
    title: "Arquitectura de Red Neuronal",
    impact:
      "Estructura convolucional o residual que extrae mapas de características bidimensionales a partir del espectrograma Mel.",
    usage:
      "EfficientNet-B0 para eficiencia y bajo consumo; ConvNeXt-Nano o ResNet34d para mayor riqueza acústica.",
    keyPoints: [
      "Modelos preentrenados aceleran la convergencia aprovechando filtros genéricos.",
      "Modelos más pesados demandan más tiempo por época y mayor memoria.",
    ],
  },
  ensemble_size: {
    title: "Topología de Ensamble (Multi-Modelo)",
    impact:
      "Combina las salidas de múltiples modelos independientes mediante votación ponderada para reducir varianza y errores individuales.",
    usage:
      "1 Modelo para prototipado rápido; 2 (Dúo) o 3 (Tríada) para competencia o despliegue crítico en producción.",
    keyPoints: [
      "La suma de los pesos de los modelos del ensamble debe equivaler al 100%.",
      "Modelos con arquitecturas diversas complementan debilidades mutuas.",
    ],
  },
  early_stopping: {
    title: "Detención Temprana (Early Stopping)",
    impact:
      "Monitorea la pérdida de validación (Val Loss) y detiene el entrenamiento automáticamente cuando el modelo deja de mejorar, evitando sobreajuste y ahorrando cómputo.",
    usage:
      "Recomendado siempre activo (true) para producción y ensambles; desactivar solo si se desea forzar una exploración exhaustiva de todas las épocas.",
    keyPoints: [
      "Calcula una paciencia dinámica proporcional a las épocas (mínimo 5 épocas sin mejora).",
      "Restaura y preserva automáticamente el mejor punto de control (best checkpoint).",
    ],
  },
};

