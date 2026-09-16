# Especificación: Ingesta de Datos y Pipeline Genérico de Audio

**Dominio:** `dataset-ingestion-and-pipeline`  
**Cambio:** `2026-09-15-modular-training-subsystem`  
**Estado:** Especificado  

---

## 1. Declaración de Requisitos (RFC 2119)

### 1.1 Ingesta y Normalización de Metadatos
* **REQ-ING-01:** El sistema DEBE proveer una interfaz abstracta `DatasetIngestor` con un método público `ingest(destination_dir: Path, force_refresh: bool = False) -> pd.DataFrame`.
* **REQ-ING-02:** Todo ingestor DEBE retornar un `pd.DataFrame` normalizado que contenga como mínimo las columnas canónicas: `nombre_archivo`, `file_path`, `clase`, `labels` (lista de strings), `recordist` y `duracion_segundos`.
* **REQ-ING-03:** El adaptador `LocalFolderPAMIngestor` DEBE descubrir recursivamente audios en disco y soportar tanto organización por carpetas de especie como archivos de anotaciones multi-etiqueta (soundscapes PAM).
* **REQ-ING-04:** El adaptador `XenoCantoIngestor` DEBE extraer concurrentemente metadatos desde la API v3, mapear el autor de la grabación al campo canónico `recordist` y parsear llamadas concurrentes (`also`) a la lista `labels`.

### 1.2 Pipeline Acústico Parametrizable
* **REQ-PIPE-01:** `GenericAudioDataset` NO DEBE depender de constantes globales de preprocesamiento. La física de audio (tasa de muestreo, duración, hop) DEBE ser inyectada mediante un objeto inmutable `AudioSignalConfig`.
* **REQ-PIPE-02:** `GenericAudioDataset` DEBE operar de forma estrictamente determinista cuando `is_train=False`, garantizando que dos lecturas del mismo índice retornen exactamente los mismos tensores.
* **REQ-PIPE-03:** En modo single-label (`multilabel=False`), el dataset DEBE retornar un escalar entero `torch.long`. En modo multi-label (`multilabel=True`), DEBE retornar un vector binario float32 de dimensión `(num_classes,)`.
* **REQ-PIPE-04:** El pipeline DEBE soportar el modo de onda cruda (`return_raw_waveform=True`) para transferir tensores 1D a GPU y delegar la extracción Mel a `GPUAudioFrontEnd`.

### 1.3 Particionamiento Zero Recordist Leakage
* **REQ-SPLIT-01:** La partición entre Train, Val y Test DEBE garantizar intersección vacía de grabadores (`recordist`) para prevenir sobreajuste por sesgo acústico de dispositivo.
* **REQ-SPLIT-02:** En escenarios multi-etiqueta, el algoritmo DEBE preservar la distribución de co-ocurrencia de especies manteniendo el aislamiento estricto por grabador.

---

## 2. Escenarios de Comportamiento (Given / When / Then)

### Escenario 1: Ingesta de carpeta local con estructura de especies
```gherkin
Given un directorio con audios ubicados en subcarpetas "zorzal/audio1.wav" y "chucao/audio2.wav"
When se ejecuta LocalFolderPAMIngestor.ingest(directorio)
Then el DataFrame retornado contiene 2 filas
And la columna "clase" coincide con el nombre de la subcarpeta
And la columna "recordist" tiene un identificador no nulo
And la columna "labels" contiene al menos la especie de "clase"
```

### Escenario 2: Generación de onda de audio con tasa de muestreo arbitraria
```gherkin
Given un archivo de audio grabado originalmente a 44100 Hz
And un objeto AudioSignalConfig con target_sr=32000 y duration_seconds=3.0
When GenericAudioDataset carga el audio para entrenamiento
Then el tensor resultante tiene forma (96000,)
And el tipo de dato es torch.float32
And no se produce error de aliasing ni excepciones de tasa de muestreo
```

### Escenario 3: Determinismo en conjunto de validación y test
```gherkin
Given un GenericAudioDataset instanciado con is_train=False
When se consulta __getitem__(i) consecutivamente 5 veces sobre el mismo índice
Then las 5 ondas acústicas retornadas son bit a bit idénticas
And no se aplicó time shift, ruido gaussiano ni SpecAugment
```

### Escenario 4: Aislamiento estricto por grabador (Zero Recordist Leakage)
```gherkin
Given un DataFrame con 500 audios y 40 grabadores distintos
When se invoca el particionado estratificado agrupado (70% train, 15% val, 15% test)
Then la intersección de recordists entre Train y Test es un conjunto vacío
And la intersección de recordists entre Train y Val es un conjunto vacío
And la intersección de recordists entre Val y Test es un conjunto vacío
```
