# 22. Arquitectura Universal Multi-Dominio sin Código y Límites Físico-Computacionales de F.A.M.A.

* **Fecha de Registro:** Septiembre 2026  
* **Área:** Arquitectura de Software, MLOps Híbrido, Procesamiento Digital de Señales Acústicas y Aprendizaje Estadístico  
* **Proyecto:** Framework MLOps Híbrido para Clasificación Acústica Multi-Dominio (F.A.M.A.)  
* **Documentos Base de Referencia:**  
  * Tesis de Grado: [`docs/VIDA_01_CINF_FINAL_PT_2026_1_CARTES.md`](./VIDA_01_CINF_FINAL_PT_2026_1_CARTES.md)  
  * Análisis de Objetivos: [`docs/analisis_objetivos_fama.md`](./analisis_objetivos_fama.md)  
  * Subsistema Modular de Entrenamiento: [`docs/19_subsistema_entrenamiento_modular_rdd.md`](./19_subsistema_entrenamiento_modular_rdd.md)  
  * Modelo de Producto y Operación: [`docs/20_modelo_de_producto_despliegue_y_arquitectura_operativa.md`](./20_modelo_de_producto_despliegue_y_arquitectura_operativa.md)  
  * Problema Conocido 02 (Límites de Generalización): [`docs/problemas_conocidos/02_limites_generalizacion_universal_y_conjunto_abierto.md`](./problemas_conocidos/02_limites_generalizacion_universal_y_conjunto_abierto.md)  

---

## 1. Resumen Ejecutivo y Motivación

El proyecto **F.A.M.A.** fue concebido como un framework MLOps híbrido capaz de entrenar modelos de alta precisión (como el Super-Ensamble Tri-Modelo con 88.68% Macro F1 en aves chilenas y 81.16% en diagnóstico de motores vehiculares) combinando almacenamiento centralizado en Google Cloud Storage con cómputo local acelerado por GPU.

A medida que el sistema madura hacia su versión de producción, surge una pregunta arquitectónica fundamental planteada por investigadores de diversas disciplinas:

> *¿Es posible que un investigador ingrese a la plataforma, cargue un conjunto de datos acústicos completamente nuevo (por ejemplo, tipos de tos humana o patologías respiratorias) y lo entrene desde la interfaz gráfica sin necesidad de modificar código fuente en el backend ni en el frontend?*

Este documento establece:
1. El **análisis de viabilidad y los límites físicos, matemáticos y computacionales** que gobiernan el procesamiento de audio con redes neuronales convolucionales 2D.
2. La demostración de por qué conjuntos de datos masivos (por ejemplo, 400 GB) son inviables para entrenamiento desde cero en infraestructura local móvil, junto con la alternativa industrial estándar (extracción de embeddings precomputados).
3. La **solución arquitectónica integral "No-Code / Zero-Touch"** para parametrizar dinámicamente cualquier conjunto de datos desde el navegador, desacoplando la física del audio del motor de entrenamiento.

---

## 2. Análisis de Viabilidad Computacional y Escala: El Caso de Datasets de 400 GB

Para evaluar la viabilidad de entrenar volúmenes masivos de datos (ej. 400 GB) en la estación local, se audita el hardware real del nodo de cómputo:

| Recurso de Hardware | Capacidad Física Real | Estado Operativo |
| :--- | :--- | :--- |
| **GPU Dedicada** | NVIDIA GeForce RTX 2050 Mobile | 4.096 MiB VRAM (4 GB GDDR6), 30W TGP |
| **Memoria RAM** | 16 GB DDR4/DDR5 | ~6 GB disponibles para buffers de usuario |
| **Almacenamiento Local** | Partición NVMe `/home` | **63 GB libres disponibles** |
| **Procesador (CPU)** | Intel Core i7-1255U | 10 núcleos (2P + 8E), 12 hilos, 15-28W TDP |

### 2.1 Cuello de Botella de Almacenamiento Local
* **Inviabilidad en Disco:** 400 GB de archivos de audio comprimidos no caben en una partición con 63 GB libres. Descargar el dataset completo al nodo provocaría de forma inmediata un fallo crítico de sistema por disco lleno (`ENOSPC`).
* **Inviabilidad de Espectrogramas en Caché:** Si los 400 GB de audio se preprocesaran a matrices NumPy de espectrogramas Mel cuantizados a punto flotante de 32 bits, el volumen resultante superaría los 80–120 GB, excediendo igualmente la capacidad del disco.
* **Inviabilidad de Streaming continuo desde GCS:** Si el DataLoader intentara transmitir muestras al vuelo desde el bucket mediante peticiones HTTP durante 35 épocas de entrenamiento:
  $$\text{Transferencia de Red} = 400\text{ GB} \times 35\text{ épocas} = 14.000\text{ GB } (14\text{ Terabytes})$$
  Esta carga saturaría el enlace institucional y la latencia de red provocaría inanición de la GPU (*GPU Starvation*), haciendo que el procesador gráfico permanezca más del 90% del tiempo inactivo esperando datos de entrada.

### 2.2 Cuello de Botella Térmico y Tiempo de Cómputo
* **Diferencia de Escala:** El dataset bioacústico actual de F.A.M.A. contiene ~1.300 archivos (~380 MB). Un dataset de 400 GB contiene entre **300.000 y 500.000 grabaciones**, lo que representa un factor de escala de aproximadamente $1.000\times$.
* **Restricción de VRAM:** Con 4 GB de VRAM, el tamaño de lote (*Batch Size*) admisible para arquitecturas modernas (ResNet-34d o EfficientNet-B0 con GeM Pooling) está acotado a $8$ o $16$ muestras para evitar desbordamiento de memoria (`CUDA Out of Memory`).
* **Cálculo de Tiempos de Entrenamiento:**
  1. A una tasa de procesamiento típica de 50 muestras por segundo (decodificación de audio, aumento de datos y paso hacia adelante/atrás):
     $$T_{\text{época}} = \frac{300.000\text{ muestras}}{50\text{ muestras/s}} = 6.000\text{ segundos} \approx 1,67\text{ horas por época}$$
  2. Para un régimen estándar de 35 épocas en un modelo individual:
     $$T_{\text{modelo}} = 35 \times 1,67\text{ h} \approx 58,5\text{ horas continuas } (\sim 2,5\text{ días ininterrumpidos})$$
  3. Para una **Tríada de Ensamble** (tres modelos heterogéneos entrenados secuencialmente):
     $$T_{\text{tríada}} \approx 175\text{ a }200\text{ horas continuas } (\mathbf{7\text{ a }8\text{ días al 100\% de carga}})$$
* **Riesgo Físico de Hardware:** Someter una GPU móvil de laptop (30W en chasis térmicamente restringido) a una carga sostenida del 100% durante más de una semana induce degradación por temperatura (*thermal throttling*) y riesgo de fallo de hardware.

### 2.3 La Solución Industrial: Extracción de Embeddings (Zero-Training Pesado)
Cuando el volumen supera los 20–50 GB en hardware modesto, la industria no entrena redes convolucionales completas desde cero. El paradigma correcto es:
1. **Paso Único de Inferencia (Feature Extraction):** Se utiliza un modelo fundacional preentrenado masivo (e.g. *Perch-v2* de Google Research, *BirdNET*, o *PANNs-CNN14* preentrenado en AudioSet). El audio pasa una sola vez por la red congelada.
2. **Generación de Embeddings:** Cada ventana temporal de audio se comprime en un vector latente de 1.024 o 1.280 números de punto flotante. Los 400 GB de audio crudo se reducen a una matriz de **~4 a 8 GB en memoria**.
3. **Clasificador Lineal Ligero (Head Tuning):** Se entrena una capa densa (MLP, regresión logística o clasificador de margen) sobre los vectores de características. El proceso converge en **10 a 15 minutos** utilizando CPU o GPU mínima, alcanzando una capacidad de generalización superior sin requerir días de cómputo.

---

## 3. Límites Teóricos y Matemáticos del Modelado Acústico con CNNs 2D

El enfoque de representar audio como una imagen de tiempo-frecuencia (espectrograma Mel) procesada por redes convolucionales (ResNet, EfficientNet, ConvNeXt) es sumamente efectivo, pero posee cuatro límites fundamentales:

```text
                           FRONTERA DE APLICABILIDAD DE F.A.M.A.
  ┌───────────────────────────────────────────────┬───────────────────────────────────────────────┐
  │         DOMINIOS APTOS PARA CNN 2D            │         LÍMITES / INCOMPATIBILIDAD            │
  ├───────────────────────────────────────────────┼───────────────────────────────────────────────┤
  │ • Eventos acústicos discretos (1 a 5 s).      │ • Habla continua y sintaxis larga (> 30 s).   │
  │ • Patrones de frecuencia discriminables.      │ • Dependencia estricta de fase de la onda.    │
  │ • Bioacústica (aves, anfibios, fauna).        │ • Ultrasonidos de muy alta frecuencia (>32k). │
  │ • Diagnóstico mecánico (motores, rodamientos).│ • Clasificación en conjunto abierto no acotado│
  │ • Acústica médica (tos, sibilancias pulmonar).│   (Alucinación de Softmax ante ruido nuevo).  │
  └───────────────────────────────────────────────┴───────────────────────────────────────────────┘
```

### Límite 1: Modelado Secuencial Largo y Dependencia Sintáctica
* **Rango Óptimo:** Señales donde la identidad del evento está contenida en una firma espectral estacionaria o cuasi-estacionaria de corta duración (canto, zumbido, chasquido de válvula, golpe de tos).
* **El Límite:** Si la tarea requiere comprender relaciones causales de largo plazo, gramática o transcripción fonética continua (como el reconocimiento automático de voz tipo *Whisper*), las convoluciones locales 2D con ventaneo fijo colapsan. Dichas tareas demandan modelos autoregresivos basados en **Transformers / Conformer** con atención multi-cabeza temporal.

### Límite 2: Pérdida Irreversible de la Fase de la Señal
* **La Pérdida Matemática:** El espectrograma Mel se calcula tomando la magnitud al cuadrado de la Transformada de Fourier de Tiempo Corto (STFT):
  $$S(m, k) = |X(m, k)|^2$$
  La matriz descarta por completo el componente de fase $\phi(m, k) = \angle X(m, k)$.
* **El Límite:** Si la aplicación requiere discriminar la dirección tridimensional de la fuente sonora, la cancelación activa de ruido o la localización micro-espacial basada en diferencias interaurales de tiempo ($\mu\text{s}$), la información física se ha destruido en el preprocesamiento y la red no puede recuperarla.

### Límite 3: Frecuencia de Nyquist y Ultrasonidos
* **El Límite Físico:** De acuerdo con el teorema de muestreo de Nyquist-Shannon:
  $$f_{\text{máx}} \le \frac{f_s}{2}$$
  El pipeline de F.A.M.A. opera con frecuencias de muestreo estandarizadas de $22.050\text{ Hz}$ ($f_{\text{Nyquist}} = 11.025\text{ Hz}$) y $32.000\text{ Hz}$ ($f_{\text{Nyquist}} = 16.000\text{ Hz}$).
* **Consecuencia:** Señales de ecolocalización de murciélagos (40 a 120 kHz) o emisiones de cetáceos son completamente invisibles para este pipeline a menos que se escale la tasa de muestreo a 250–384 kHz, lo cual incrementa el tamaño de los tensores de forma prohibitiva para la memoria del sistema.

### Límite 4: El Colapso de la Función Softmax en Mundo Abierto (*Open-Set*)
* **La Patología:** Si la red se entrena con $K$ clases exclusivas mediante Softmax ($\sum P_i = 1.0$), cualquier sonido ajeno al vocabulario (e.g. un estornudo, un portazo o un ladrido frente a un modelo de tos) será forzado matemáticamente a asignarse a alguna de las clases conocidas con alta probabilidad aparente.
* **Mitigación Requerida:** La formulación debe permitir clases de rechazo (*background / unclassified*) o migrar a cabezas de clasificación multi-etiqueta independientes con sigmoide (`BCEWithLogitsLoss`).

---

## 4. Auditoría del Estado Actual en F.A.M.A.

Al contrastar la interfaz web y el backend en el estado actual del repositorio, se identifican las capacidades presentes y las brechas para soportar nuevos dominios sin tocar código:

### 4.1 Lo que SÍ está implementado
1. **Interfaz de Hiperparámetros de Aprendizaje:** En [`TrainingView.tsx`](file:///home/kevin/Work/fama/frontend/components/views/TrainingView.tsx), el usuario puede seleccionar épocas, learning rate, batch size, arquitectura y alternar entre modelo individual o tríada de ensamble.
2. **Descubrimiento de Datasets:** El endpoint `GET /api/training/datasets` detecta automáticamente qué colecciones existen en la base de datos o en el almacenamiento local.
3. **Persistencia y Despliegue Dinámico:** Al concluir un entrenamiento, el modelo se empaqueta como bundle desacoplado (`weights.pt` + `manifest.json`) y se registra en tiempo de ejecución en el [`ModelRegistry`](file:///home/kevin/Work/fama/backend/app/services/registry.py) sin reiniciar el servidor.

### 4.2 Lo que FALTA para la operación "Zero-Touch"
Actualmente existe un acoplamiento implícito en [`backend/app/services/training.py`](file:///home/kevin/Work/fama/backend/app/services/training.py):
* Si el dataset seleccionado tiene por nombre `engine_diagnostics`, el backend inyecta los parámetros de motores automotrices ($f_s = 32\text{ kHz}$, ventana de 2.0 s, $f_{\text{min}} = 50\text{ Hz}$, $f_{\text{max}} = 16.000\text{ Hz}$).
* Para **cualquier otro nombre de dataset**, el backend asume por defecto los parámetros de **Aves Chilenas** ($f_s = 22.05\text{ kHz}$, ventana de 5.0 s, $f_{\text{min}} = 800\text{ Hz}$, $f_{\text{max}} = 10.000\text{ Hz}$).

> **Impacto Práctico:** Si un investigador sube hoy un dataset de **Tos Humana** (cuya energía acústica está entre 100 y 4.000 Hz con duración de 1 a 2 segundos), el backend recortaría las frecuencias graves esenciales por debajo de 800 Hz y rellenaría artificialmente 3 segundos de silencio en cada muestra, degradando drásticamente el modelo resultante.

---

## 5. Solución Arquitectónica Propuesta: Framework Multi-Dominio No-Code

Para permitir que F.A.M.A. entrene cualquier dataset acústico sin modificar una sola línea de código Python ni TypeScript en el futuro, se define la siguiente arquitectura desacoplada en cuatro capas:

```text
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                        CAPA 1: PRESENTACIÓN (TrainingView.tsx)                         │
│  • Selector de Presets de Dominio (Bioacústica / Industrial / Médico-Tos / Custom)    │
│  • Inputs de Física Espectral: Sample Rate, Duración (s), Fmin (Hz), Fmax (Hz), Mels   │
└───────────────────────────────────────────┬────────────────────────────────────────────┘
                                            │ HTTP POST /api/training/start
                                            │ (JSON con StartTrainingRequest + audio_config)
                                            ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                         CAPA 2: CONTRATOS API (Pydantic Schemas)                       │
│  • Validación estricta con AudioConfig (invariantes físicas: f_min < f_max <= fs/2)    │
│  • Inyección polimórfica en el servicio de entrenamiento                               │
└───────────────────────────────────────────┬────────────────────────────────────────────┘
                                            │
                                            ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                   CAPA 3: PIPELINE DE ENTRENAMIENTO (backend/training/)                │
│  • Ingestor lee subcarpetas como clases de forma automática (LocalFolderPAMIngestor)   │
│  • GenericAudioDataset aplica ventaneo y extracción Mel parametrizada por AudioConfig  │
│  • Head Classifier ajusta dinámicamente sus neuronas de salida: len(classes)          │
│  • Exportación atómica: weights.pt + manifest.json auto-descriptivo                    │
└───────────────────────────────────────────┬────────────────────────────────────────────┘
                                            │
                                            ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                       CAPA 4: SERVING DINÁMICO (ModelRegistry)                         │
│  • Autodescubrimiento del bundle generado en checkpoints/<model_id>/                   │
│  • BundleAudioPredictor reproduce la física exacta estipulada en manifest.json         │
│  • Inferencia inmediata disponible en GET /api/models y POST /api/predict              │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

### 5.1 Extensión del Contrato de la API (`StartTrainingRequest`)
Se incorpora el esquema `AudioConfig` dentro de la solicitud de entrenamiento:

```python
class AudioConfigSchema(BaseModel):
    sample_rate: int = Field(default=22050, ge=8000, le=48000)
    duration_seconds: float = Field(default=5.0, ge=0.5, le=30.0)
    f_min: float = Field(default=800.0, ge=0.0)
    f_max: float = Field(default=10000.0, ge=100.0)
    n_mels: int = Field(default=128, ge=32, le=256)

    @model_validator(mode="after")
    def validate_nyquist(self):
        nyquist = self.sample_rate / 2.0
        if self.f_max > nyquist:
            raise ValueError(f"f_max ({self.f_max}) no puede exceder Nyquist ({nyquist} Hz)")
        if self.f_min >= self.f_max:
            raise ValueError(f"f_min ({self.f_min}) debe ser menor que f_max ({self.f_max})")
        return self

class StartTrainingRequest(BaseModel):
    dataset_name: str
    architecture: str = "ResNet-34d"
    epochs: int = 15
    learning_rate: float = 0.0003
    batch_size: int = 16
    framework: str = "pytorch"
    is_tri_model: bool = False
    audio_config: Optional[AudioConfigSchema] = None
```

### 5.2 Catálogo de Presets en el Frontend
Para garantizar usabilidad sin sobrecargar al investigador con conceptos de procesamiento digital de señales, el frontend proporciona botones de un clic para autocompletar la configuración:

| Preset | Frecuencia de Muestreo | Ventana Temporal | Rango Espectral ($f_{\text{min}} - f_{\text{max}}$) | Bandas Mel | Casos de Uso |
| :--- | :---: | :---: | :---: | :---: | :--- |
| **Bioacústica (Aves/Fauna)** | $22.050\text{ Hz}$ | $5,0\text{ s}$ | $800\text{ Hz} - 10.000\text{ Hz}$ | 128 | Passeriformes, anfibios, fauna de bosque. |
| **Diagnóstico Industrial** | $32.000\text{ Hz}$ | $2,0\text{ s}$ | $50\text{ Hz} - 16.000\text{ Hz}$ | 128 | Motores, rodamientos, bombas, turbinas. |
| **Acústica Médica / Tos** | $16.000\text{ Hz}$ | $2,0\text{ s}$ | $50\text{ Hz} - 6.000\text{ Hz}$ | 128 | Tos seca/productiva, auscultación respiratoria. |
| **Voz / Comandos Cortos** | $16.000\text{ Hz}$ | $1,0\text{ s}$ | $100\text{ Hz} - 8.000\text{ Hz}$ | 80 | Detección de palabras clave (*Keyword Spotting*). |
| **Personalizado (*Custom*)** | *Manual* | *Manual* | *Manual* | *Manual* | Cualquier dominio acústico no contemplado. |

### 5.3 Ingesta Automática y Adaptación de la Red
1. **Detección Dinámica de Clases:** El servicio de ingesta analiza la estructura de carpetas `datasets/<dataset_name>/<clase>/*.wav`. El número de clases $K$ se infiere en tiempo de ejecución:
   $$K = \text{len}(\text{subcarpetas\_con\_audio})$$
2. **Reconfiguración del Head Classifier:** Al instanciar el modelo base en PyTorch (e.g. `timm.create_model("resnet34d")`), la capa clasificadora lineal final se reemplaza dinámicamente:
   ```python
   model.fc = nn.Linear(model.fc.in_features, num_classes)
   ```
3. **Generación del Manifiesto Auto-descriptivo:** Al finalizar el entrenamiento, el exportador genera el archivo `manifest.json`:
   ```json
   {
     "model_id": "human_cough_resnet34d_v1",
     "version": "1.0.0",
     "architecture": "resnet34d",
     "num_classes": 4,
     "classes": ["Tos Seca", "Tos Productiva", "Tos Convulsiva", "Normal"],
     "audio_config": {
       "sample_rate": 16000,
       "duration_seconds": 2.0,
       "f_min": 50.0,
       "f_max": 6000.0,
       "n_mels": 128
     },
     "metrics": {
       "val_f1_macro": 0.892,
       "val_accuracy": 0.901
     }
   }
   ```
4. **Carga Polimórfica en Inferencia:** Cuando un usuario realiza una predicción sobre este modelo en `/api/predict?model_id=human_cough_resnet34d_v1`, el `BundleAudioPredictor` lee el manifiesto, configura su propio preprocesador a 16 kHz y 2 segundos, procesa el audio y emite el diagnóstico con las etiquetas correspondientes sin requerir ninguna modificación de código.

---

## 6. Conclusiones y Relevancia para la Tesis de Grado

1. **Rigor Técnico frente a Soluciones Ilusorias:** Este documento demuestra formalmente por qué pretender procesar 400 GB de audio desde cero en una estación de trabajo local no es una limitación del software, sino una **imposibilidad física de almacenamiento, térmico y ancho de banda**, sustentando con fundamentos teóricos el uso de modelos fundacionales.
2. **Modularidad y Principio Abierto/Cerrado (OCP):** La arquitectura propuesta cumple con el principio *Open/Closed* de SOLID: el sistema está **abierto a la extensión** (nuevos dominios, aves, motores, tos, cetáceos) pero **cerrado a la modificación** (el código del backend y del frontend permanece inalterado).
3. **Defensa de Título de Grado:** Esta formalización consolida a F.A.M.A. no como un prototipo académico rígido, sino como un **Framework MLOps Híbrido de nivel productivo** con arquitectura modular profunda y fundamentación científica rigurosa.
