# ADR 0014: Delimitación de Parámetros Configurables en Frontend bajo Principios de Deep Modules y Presets de Dominio

* **Estado:** Aceptado  
* **Fecha:** 2026-09-29  
* **Decisores:** Equipo F.A.M.A.  
* **Área:** Arquitectura de Software, UX/UI MLOps, Deep Learning, Procesamiento Digital de Señales (DSP)  

---

## 1. Contexto y Problema

La plataforma F.A.M.A. tiene como objetivo admitir el entrenamiento y la inferencia sobre diversos conjuntos de datos acústicos (bioacústica de aves, diagnóstico industrial de motores vehiculares, tos médica, etc.) permitiendo a los usuarios configurar hiperparámetros desde la interfaz gráfica web ([`TrainingView.tsx`](../../frontend/components/views/TrainingView.tsx)).

Al analizar la receta del modelo campeón de diagnóstico de motores (81.16% de exactitud y 80.33% Macro F1), se identifican múltiples variables críticas que intervienen en el rendimiento:
1. **Topología de Ensamble:** Ponderación calibrada de 3 arquitecturas heterogéneas (ResNet-34d 60%, PANNs-CNN14 30%, EfficientNet-B0 10%) con pooling GeM ($p = 3.0$).
2. **Procesamiento de Señal y DSP:** Separación de fuentes armónico-percusiva (HPSS de 3 canales), banco de 128 filtros Mel, $f_{\min} / f_{\max}$, $N_{\text{fft}} = 2048$, $\text{hop\_length} = 256$, tasa de muestreo a 32.000 Hz.
3. **Muestreo y Aumento de Datos:** Síntesis aditiva balanceada en energía RMS (`AdditiveCompoundSampler`), Mixup moderado ($\alpha = 0.2$), SpecAugment en GPU (`time_mask=16`, `freq_mask=8`).
4. **Optimización:** Optimizador AdamW, Cosine Annealing, tasa de aprendizaje nominal, regularización $L_2$ (`weight_decay = 0.01`), épocas de calentamiento (*warmup*).

Surge la disyuntiva de diseño: **¿Debe la interfaz de usuario en el frontend exponer cada una de estas variables como controles e inputs editables?**

---

## 2. Análisis de Riesgos y Anti-Patrones de la Sobre-Exposición

Intentar exponer todos los parámetros técnicos en la interfaz de usuario incurre en los siguientes anti-patrones de diseño de software:

### 2.1 Anti-patrón de Módulo Superficial (*Shallow Module*)
De acuerdo con los principios de diseño de software (John Ousterhout), un **módulo profundo (*Deep Module*)** provee una interfaz reducida y clara que oculta una complejidad interna considerable. Exponer decenas de entradas en el frontend transforma el subsistema en un **módulo superficial**:
* La interfaz se vuelve casi tan compleja como el código del backend.
* El frontend se acopla rígidamente a detalles internos de implementación del pipeline de PyTorch (como tensores de 3 canales en HPSS o clases de sampler del `DataLoader`).
* Cualquier refactorización interna del motor DSP o de aumento de datos quiebra la interfaz de usuario.

### 2.2 Síndrome de la Cabina de Avión (*Cockpit Overload*)
Obligar al usuario a interactuar con 30 o 40 entradas de formulario produce:
* Alta fricción cognitiva y parálisis por análisis.
* Imposibilidad de que usuarios no expertos en optimización estocástica y acústica física puedan entrenar un modelo exitosamente.

### 2.3 Riesgo de Combinaciones Inválidas o Destructivas (*Degenerate Configurations*)
Al desacoplar variables que tienen dependencias matemáticas estrictas entre sí, se incrementa exponencialmente la probabilidad de que el usuario configure combinaciones que impidan la convergencia o corrompan el entrenamiento:
* **Incompatibilidad DSP:** Seleccionar $f_{\max} > \text{target\_sr} / 2$ (violación del teorema de Nyquist-Shannon) o $\text{hop\_length} \ge n_{\text{fft}}$.
* **Desbalance de Warmup:** Configurar 5 épocas de warmup para un entrenamiento de 10 épocas, impidiendo que el scheduler *Cosine Annealing* descienda al valle de pérdida mínima.
* **Colisión de Augmentations:** Combinar síntesis aditiva agresiva con Mixup extremo ($\alpha > 1.0$), destruyendo la señal espectral por superposición excesiva de energía.

---

## 3. Decisión Arquitectónica: Modelo en Tres Capas

Se aprueba formalmente estructurar los parámetros del sistema en **tres capas de abstracción bien delimitadas**:

```
┌────────────────────────────────────────────────────────┐
│ Capa 1: Exposición Directa en UI (Hiperparámetros Clave)│
│ • Dataset, Arquitectura/Ensamble (1-3 modelos, sliders) │
│ • Learning Rate, Weight Decay (AdamW), Epochs, Batch   │
│ • Rango espectral y duración base (SR, sec, fmin, fmax)│
└────────────────────────────────────────────────────────┘
                           │
                           ▼
┌────────────────────────────────────────────────────────┐
│ Capa 2: Abstracción por Presets de Dominio (Smart)     │
│ • Botones de 1-clic: "Diagnóstico Industrial",         │
│   "Tos Médica", "Aves Chilenas".                       │
│ • Auto-calibran física acústica y regularización base. │
└────────────────────────────────────────────────────────┘
                           │
                           ▼
┌────────────────────────────────────────────────────────┐
│ Capa 3: Encapsulación Estricta en Backend (Deep Module)│
│ • HPSS (3 canales espectrales armónico/percusivo).     │
│ • AdditiveCompoundSampler (balance energético RMS).    │
│ • SpecAugment GPU (máscaras de tiempo/frecuencia).     │
│ • Warmup proporcional: max(1, floor(epochs * 0.08)).   │
└────────────────────────────────────────────────────────┘
```

### 3.1 Capa 1: Variables Expuestas en Frontend ([`TrainingView.tsx`](../../frontend/components/views/TrainingView.tsx))
Se exponen únicamente aquellos parámetros de alto nivel que un usuario necesita ajustar de forma explícita para evaluar diferentes regímenes de entrenamiento:
* **Topología:** Selección de 1, 2 o 3 modelos con sliders para balancear pesos del ensamble y selector individual de épocas por modelo (1 a 100).
* **Optimización Base:** `learning_rate`, `weight_decay` (regularización $L_2$ de AdamW), `epochs` global (para modelo individual) y `batch_size`.
* **Física Acústica Visible:** `target_sr`, `duration_seconds`, $f_{\min}$, $f_{\max}$, $n_{\text{mels}}$, $n_{\text{fft}}$ y $\text{hop\_length}$.
* **Regularización Seleccionable:** Tipo de función de pérdida (`cross_entropy` vs `focal`), $\gamma$ focal, y activación de Mixup / Pitch Shift.

### 3.2 Capa 2: Presets de Dominio (*Domain Presets*)
Para evitar la manipulación manual propensa a error de los parámetros acústicos, la interfaz provee presets contextuales:
* **Diagnóstico Industrial:** Aplica automáticamente 32.000 Hz, ventana corta de 1.5s, $f_{\max} = 16.000\text{ Hz}$, $N_{\text{fft}} = 2048$, y ensamble ResNet-34d + PANNs-CNN14.
* **Tos Médica:** Aplica 16.000 Hz, 2.0s, $f_{\max} = 4.000\text{ Hz}$, $N_{\text{fft}} = 1024$.
* **Bioacústica (Aves Chilenas):** Aplica 22.050 Hz, 5.0s, $f_{\max} = 10.000\text{ Hz}$, $N_{\text{fft}} = 2048$.

### 3.3 Capa 3: Variables Encapsuladas en Backend ([`training.py`](../../backend/app/services/training.py))
Las siguientes variables y mecanismos permanecen encapsulados bajo el capó sin exposición de inputs en la UI:
1. **Separación de Fuentes HPSS:** Se activa de forma determinista en el backend según el dataset y arquitectura seleccionados, abstrayendo la descomposición armónica-percusiva.
2. **Síntesis Aditiva RMS (`AdditiveCompoundSampler`):** Se gobierna automáticamente a nivel de `DataLoader` para datasets de diagnóstico que contienen fallas compuestas.
3. **SpecAugment GPU:** Se aplica automáticamente durante la fase de entrenamiento en GPU cuando se activa la regularización.
4. **Épocas de Calentamiento (*Warmup*):** En lugar de un input manual susceptible a descalibración, se calcula de forma proporcional al total de épocas:
   $$\text{warmup\_epochs} = \max\left(1, \left\lfloor \text{epochs} \times 0.08 \right\rfloor\right)$$

---

## 4. Consecuencias y Beneficios

* **Robustez Operativa:** Imposibilidad de que el usuario descalibre el pipeline DSP o cause divergencia numérica por combinaciones absurdas de parámetros.
* **Ergonomía y Velocidad:** El usuario puede entrenar nuevos conjuntos de datos en minutos ajustando 4 o 5 hiperparámetros fundamentales o haciendo clic en un preset.
* **Arquitectura Limpia y Mantenible:** Los contratos API (`Pydantic` en backend y `Zod` en frontend) permanecen compactos, estables y testeables mediante TDD.
* **Modo Avanzado / Extensibilidad:** Si un investigador requiere calibrar hiperparámetros profundos de HPSS o SpecAugment fuera de los defaults, lo realiza directamente mediante las recetas declarativas en YAML ([`backend/training/recipes/`](../../backend/training/recipes/)), preservando la separación entre la interfaz de producto y la investigación de bajo nivel.
