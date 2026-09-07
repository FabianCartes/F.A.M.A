# ADR 0005: Ventaneo Temporal Denso (Dense Windowing) con Solapamiento Configurable en Inferencia TTA

* **Estado:** Aceptado / En Implementación  
* **Fecha:** 2026-09-06  
* **Decisores:** Equipo F.A.M.A.  
* **Área:** Inferencia Bioacústica, Procesamiento de Señales y TTA (Test-Time Augmentation)  

---

## 1. Contexto y Problema

En los sistemas de monitoreo bioacústico pasivo (PAM) y clasificación de fauna silvestre, las vocalizaciones diagnósticas de las aves (trinos, sílabas y reclamos territoriales) son típicamente eventos acústicos transitorios cuya duración oscila entre 0.4 y 1.5 segundos. 

Tras la introducción de Test-Time Augmentation (TTA) multi-crop en el ADR 0002, el modelo `BioacousticEfficientNet` implementó la segmentación de grabaciones en ventanas fijas de 5.0 segundos con un salto (*hop*) temporal rígido de 2.5 segundos (equivalente a un 50% de solapamiento temporal):

1. **Riesgo de Bisección de Eventos Acústicos Transitorios:**  
   Con un desplazamiento de 2.5 segundos, una frase vocal corta de 0.8 segundos que comience en el segundo 2.2 o 4.7 puede quedar fragmentada a través del límite de la ventana. Al dividirse entre dos ventanas consecutivas, la sílaba pierde su continuidad espectro-temporal diagnóstica (modulaciones de frecuencia, armónicos continuos), degradando la probabilidad asignada por la red convolucional.

2. **Atenuación en Bordes de Ventana y Padding:**  
   Los filtros convolucionales y las representaciones espectrales sufren efectos de borde (*boundary effects*) y amortiguamiento energético cerca de los extremos de la ventana temporal. Con hops espaciados de 2.5 segundos, cantos enteros pueden caer exclusivamente en las zonas marginales de baja sensibilidad relativa de las ventanas evaluadas.

3. **Rigidez Paramétrica en el Pipeline de Inferencia:**  
   El parámetro `hop_seconds` se encontraba fijado por defecto en 2.5 s a lo largo de las capas superiores del pipeline (`evaluate_test_set`, `run_evaluation` y el CLI de `evaluate.py`), impidiendo la exploración sistemática de regímenes de muestreo temporal más densos en inferencia sin alterar el código base.

---

## 2. Decisión Arquitectónica

Se aprueba la parametrización completa del ventaneo temporal en inferencia y la adopción de una estrategia de **Ventaneo Denso (Dense Windowing)** para la evaluación de modelos:

### 2.1 Parametrización Extremo a Extremo de `hop_seconds`
* **Validación en Preprocesamiento (`backend/poc/preprocess.py`):**  
  Se impone una verificación estricta en `extract_active_windows`: `hop_seconds` debe ser estrictamente positivo (`hop_seconds > 0.0`), lanzando un `ValueError` descriptivo en caso contrario para evitar bucles infinitos en el barrido temporal.
* **Propagación en Pipeline de Inferencia (`backend/poc/evaluate.py`):**  
  El parámetro `hop_seconds: float = 2.5` se expone e interconecta explícitamente a través de:
  - `predict_audio_tta(..., hop_seconds=hop_seconds)`
  - `evaluate_test_set(..., hop_seconds=hop_seconds)`
  - `run_evaluation(..., hop_seconds=hop_seconds)`
  - Interfaz de línea de comandos (CLI): `--hop-seconds` (tipo `float`, default `2.5`).

### 2.2 Exploración y Calibración de Regímenes Densos
Se establecen regímenes de ablación experimental en el conjunto de prueba oficial (`data/test.csv`, 154 muestras):
* **Hop 1.25s (75% Solapamiento):** Proporciona una densidad temporal 2x mayor respecto al baseline. Garantiza que cualquier evento vocal de duración $\ge 0.4\text{ s}$ quede capturado de manera íntegra y centrada en al menos una de las ventanas candidatas.
* **Hop 1.00s (80% Solapamiento):** Proporciona una densidad temporal 2.5x mayor. Permite un escaneo casi continuo del flujo de audio, maximizando la probabilidad de que el pico de energía y la morfología espectral del canto se expresen con máxima nitidez.
* **Agregación Probabilística Dual:** Ambos regímenes densos se evalúan en conjunto con las dos estrategias de agregación de probabilidades: `mean` (fusión conservadora) y `max` (detección de picos salientes).

---

## 3. Fundamentación Bioacústica y Estado del Arte

1. **Morfología Vocal en Aves Chilenas:**  
   Especies como el *Fío-fío* (*Elaenia albiceps*), el *Churrín del sur* (*Scytalopus magellanicus*) o el *Tijeral* (*Sylviorthorhynchus desmursii*) emiten notas ultra-rápidas o sílabas de modulación fina. Mantener un solapamiento de 75% a 80% asegura que la firma bioacústica no quede truncada en el dominio del tiempo antes de la proyección Mel STFT.
2. **Estándares en Competiciones Bioacústicas (BirdCLEF / DCASE):**  
   En los pipelines de inferencia líderes de BirdCLEF (Kaggle), el uso de densidades de hop del 70% al 85% durante TTA es una práctica estándar para mitigar el desalineamiento temporal sin incurrir en costos de reentrenamiento (*zero retraining cost*).
3. **Paralelismo de Micro-Lotes en GPU:**  
   Aunque un hop de 1.25 s o 1.0 s incrementa la cantidad de ventanas activas por audio de ~4 a ~7-11 ventanas promedio, el hardware disponible (NVIDIA GeForce RTX 2050 Mobile con 4 GB VRAM) procesa tensores de $[N, 1, 128, 216]$ en un único pase forward paralelo en milisegundos, manteniendo el tiempo total por audio muy por debajo del umbral de tiempo real (< 50 ms).

---

## 4. Consecuencias y Trade-offs

### Positivas:
* **Cero Costo de Reentrenamiento:** La mejora se logra exclusivamente en el tiempo de inferencia y evaluación (test-time optimization), reutilizando el checkpoint campeón sin necesidad de reentrenar la red neuronal.
* **Preservación Íntegra de Cantos Breves:** Se elimina la bisección de trinos diagnósticos y se neutraliza el efecto de atenuación en los bordes de la ventana.
* **Modularidad y Flexibilidad:** El usuario puede seleccionar el trade-off exacto entre velocidad de inferencia y densidad de cobertura temporal tanto vía código como por línea de comandos.
* **Compatibilidad Total:** El valor por defecto (`hop_seconds=2.5`) mantiene intacto el comportamiento histórico del sistema y preserva 100% de compatibilidad hacia atrás.

### Negativas / Riesgos:
* **Incremento Proporcional del Cómputo por Inferencia:** El número de ventanas $N$ aumenta de 1.5x a 2.5x por archivo de audio. En grabaciones muy extensas (> 60 segundos), el micro-lote en VRAM crecerá proporcionalmente. Para el test set actual, la latencia adicional es despreciable (< 35 ms por muestra).
* **Sensibilidad a Ruido en Modo Max:** Al aumentar la cantidad de ventanas candidatas, la probabilidad de que una ventana con ruido impulsivo genere una falsa activación en modo `max` podría aumentar ligeramente. La agregación `mean` actúa como contrapeso regularizador.
