# Informe Técnico: Paralelismo Productor-Consumidor (CPU + GPU) y Multiprocesamiento Seguro

**Proyecto:** Framework MLOps Híbrido para Clasificación de Audio (F.A.M.A.)  
**Fecha:** Septiembre 2026  
**Fase:** Iteración 3 - Desacoplamiento Concurrente y Paralelismo de Ingesta  
**Dominio:** 15 Especies de Aves de Chile (Dataset Xeno-canto v3)  
**Metodología:** TDD (*Test-Driven Development*) + Módulos Profundos  

---

## 1. Diagnóstico del Problema y Cuello de Botella Identificado

En las iteraciones previas del pipeline de entrenamiento local (`poc/train.py`), a pesar de contar con aceleración por hardware (`NVIDIA GeForce RTX 2050`), la GPU sufría de **inanición de cómputo (*GPU starvation*)**, manteniéndose ociosa más del 90% del tiempo.

### Causas Raíz Detectadas:
1. **Pipeline de Ingesta Secuencial Monohilo:**
   El cargador de datos `DataLoader` operaba con su configuración predeterminada `num_workers=0`. Esto obligaba a que un único hilo de CPU ejecutara secuencialmente el cálculo de detección de actividad vocal (VAD), data augmentation en forma de onda (pitch-shift y ruido) y la extracción del espectrograma Mel en `librosa` muestra a muestra, antes de entregar cada lote a la GPU.
2. **Transferencias Sincrónicas Bloqueantes:**
   La migración de memoria host a dispositivo se realizaba mediante `x_batch.to(device)` sin fijación de páginas de memoria (`pin_memory=False`), forzando al procesador a pausar la ejecución en cada paso de gradiente.

---

## 2. Escrutinio Arquitectónico y Prevención de Fallos Críticos

Durante la fase de revisión previa a la implementación, se detectaron tres anomalías severas asociadas al modelo de multiprocesamiento (`fork`) en entornos Linux:

### A. Ruptura de *Copy-on-Write (CoW)* y Riesgo de OOM
En Linux, al crear procesos hijos con `num_workers > 0`, la memoria virtual se comparte inicialmente sin coste físico. Sin embargo, la clase `AudioDataset` mutaba diccionarios internos en tiempo de ejecución (`self._windows_cache` y `self._cache` en `__getitem__`). Al escribir sobre memoria compartida en subprocesos, el kernel activa *Copy-on-Write*, duplicando las páginas físicas en la memoria privada (RSS) de cada worker y multiplicando el consumo de RAM hasta provocar potencialmente un fallo por falta de memoria (*Out Of Memory - OOM*).
- **Solución Implementada:** Se eliminó cualquier mutación de estado dentro de `__getitem__`, convirtiendo a `AudioDataset` en una estructura de solo lectura segura para concurrencia.

### B. Falla de Aleatoriedad en Data Augmentation (RNG Desincronizado)
PyTorch re-siembra automáticamente su generador de números pseudoaleatorios en los subprocesos, pero **no** re-siembra los módulos `random` estándar de Python ni `numpy.random`. Sin intervención, todos los workers heredaban la misma semilla del proceso padre, generando aumentaciones acústicas idénticas.
- **Solución Implementada:** Función de inicialización `seed_worker`:
  ```python
  def seed_worker(worker_id: int) -> None:
      worker_seed = torch.initial_seed() % (2**32)
      np.random.seed(worker_seed)
      random.seed(worker_seed)
      torch.set_num_threads(1)
  ```
  Esto garantiza independencia estadística entre hilos y restringe los hilos internos de álgebra lineal a 1 para evitar contención de CPU (*oversubscription*).

---

## 3. Arquitectura del Patrón Productor-Consumidor

La interacción entre el procesador de 12 hilos (**Intel Core i7-1255U**) y la tarjeta gráfica (**NVIDIA GeForce RTX 2050 con 4 GB VRAM**) se estructuró bajo un desacoplamiento estricto:

```
[ CPU: Intel Core i7-1255U (12 hilos) ]
 ├── Worker 0: Lectura MP3 + VAD + Pitch-Shift (RNG independiente)
 ├── Worker 1: Lectura MP3 + VAD + Pitch-Shift (RNG independiente)
 ├── Worker 2: Lectura MP3 + VAD + Pitch-Shift (RNG independiente)
 └── Worker 3: Lectura MP3 + VAD + Pitch-Shift (RNG independiente)
       │
       ▼ (Page-Locked Host RAM / pin_memory=True)
[ Transferencia DMA Asíncrona (non_blocking=True) ]
       │
       ▼
[ GPU: NVIDIA GeForce RTX 2050 (4 GB VRAM) ]
 └── Consumo continuo: Forward Pass + Loss + Backward Pass (Gradientes)
```

### Nueva Factoría Desacoplada: `build_dataloaders`
Siguiendo el principio de **Módulos Profundos**, la construcción de los flujos de datos se extrajo de scripts monolíticos hacia una factoría reutilizable:
- Expone una interfaz concisa (`train_df`, `val_df`, `raw_dir`, `label_to_idx`, `num_workers`, `pin_memory`).
- Activa memoria fijada de forma dinámica: `pin_memory = (device.type == "cuda")`.
- Mantiene los procesos de los workers vivos entre épocas (`persistent_workers=True`) para eliminar el costo de inicialización de subprocesos.

---

## 4. Validación Mediante TDD y Suite de Pruebas

El desarrollo se realizó bajo la metodología estricta **Test-Driven Development (TDD)**:
1. **Fase Roja:** Creación de `test_build_dataloaders_concurrency_and_seeding()` en `tests/test_train.py`, fallando por inexistencia de la factoría.
2. **Fase Verde:** Implementación de `seed_worker` y `build_dataloaders` junto a la inmutabilidad de `AudioDataset`.
3. **Fase Refactor:** Integración en `train_pipeline` y transferencias no bloqueantes en bucles de evaluación.

### Resultados de la Suite Automatizada:
* **Pruebas ejecutadas:** 23 tests unitarios e integrales en `tests/`.
* **Tasa de éxito:** 100% (23/23 aprobados).
* **Módulos cubiertos:** `download`, `preprocess`, `split`, `train`, `evaluate`.

---

## 5. Observabilidad y Monitoreo en Tiempo Real (tqdm)

Para resolver la incertidumbre visual durante la ejecución de lotes:
- Se integró `tqdm` dinámico en `train_one_epoch` configurado con `leave=False`.
- Muestra en vivo la época en curso (`Época [xx/xx]`), el porcentaje de progreso de lotes, la tasa de rendimiento (`it/s`), el tiempo estimado restante (ETA) y métricas dinámicas de pérdida y exactitud (`loss` y `acc`).
- La interfaz desacoplada admite `show_progress: bool` para silenciar la barra durante suites de pruebas automatizadas y activarla durante ejecuciones interactivas de producción.

---

---

## 6. Diagnóstico y Resolución del Fallo Crítico de Memoria (OOM-Killer por Pitch-Shift)

Durante las primeras pruebas de entrenamiento con 4 workers en `poc/train.py`, la terminal sufría un cierre forzoso abrupto (*crash*) sin traza de excepción en Python.

### Diagnóstico a Nivel de Sistema Operativo (`journalctl`)
El análisis de los registros del kernel de Linux reveló la causa de terminación:
```text
Out of memory: Killed process (python) total-vm:18944524kB, anon-rss:720512kB, file-rss:0kB, shmem-rss:0kB, UID:1000 pgtables:20000kB oom_score_adj:0
systemd[1]: app-foot.slice: Failed with result 'oom-kill'. Consumed 13.4G memory peak, 17.9G memory swap peak.
```
El kernel de Linux liquidó la jerarquía de procesos tras agotar **31.3 GB combinados de RAM física y Swap**.

### Causa Raíz: Explosión de Tablas de Filtros Sinc en `torchaudio.functional.pitch_shift`
1. Al pasar valores continuos en coma flotante a semitonos (`random.uniform(-1.5, 1.5)`), `torchaudio` en CPU invoca remuestreadores polifásicos sinc en C++ (`libsoxr` / resampler interno).
2. Cada valor flotante distinto exige aproximaciones racionales de alta precisión, instanciando matrices masivas de coeficientes sinc.
3. En pruebas de estrés aisladas, solo 5 muestras con `pitch_shift` continuo consumieron más de **8.1 GB de RAM privada por worker**, multiplicando el consumo por 4 workers hasta el colapso total del sistema.

### Solución Diseñada y Justificación Bioacústica
Se rediseñó la etapa de data augmentation en forma de onda sustituyendo `pitch_shift` por operaciones con complejidad espacial $O(1)$:

1. **Desplazamiento Temporal con Zero-Padding (*Time Shift*):**
   - *Por qué no usar `np.roll`:* El desplazamiento circular (`np.roll`) conecta el final de la grabación con el inicio, creando un escalón de amplitud artificial en los límites. Al aplicar la Transformada de Fourier (STFT), esa discontinuidad genera un "clic" espectral transitorio de banda ancha irreal que contamina el espectrograma.
   - *Implementación:* Desplazamiento lineal acotado ($\pm 0.5$ s) rellenando con ceros (*zero-padding*), simulando variaciones naturales en el instante en que el ave comienza su vocalización dentro de la ventana de detección.

2. **Ganancia Aleatoria (*Random Gain*) y Preservación de SNR:**
   - *Consideración matemática:* En `preprocess.py`, la conversión a decibelios se normaliza respecto al pico máximo (`librosa.power_to_db(mel, ref=np.max)`). Aplicar una ganancia escalar a una señal aislada es cancelado matemáticamente por la normalización logarítmica relativa.
   - *Implementación:* El factor de ganancia ($[0.8, 1.2]$) se aplica **antes** de la inyección de ruido blanco gaussiano. De esta forma, la relación señal-ruido (*Signal-to-Noise Ratio - SNR*) varía de manera realista y no es anulada por el cálculo logarítmico del espectrograma.

### Resultados de Estabilidad y Rendimiento:
| Métrica | Con `pitch_shift` continuo | Con *Time Shift* + *Gain* | Mejora |
|---|---|---|---|
| **Latencia por muestra (CPU)** | 6.63 segundos | **129 milisegundos** | **51.4x más rápido** |
| **Consumo de Memoria (4 workers)** | 31.3 GB (OOM-Kill) | **1.0 GB estable** | **Fuga eliminada (97% ahorro)** |
| **Estabilidad de Terminal** | Crasheo forzoso | 100% Estable | Cero abortos |

---

## 7. Resultados Empíricos del Entrenamiento y Evaluación en Test Set

Tras resolver la fuga de memoria y estabilizar el pipeline concurrente, se completó el ciclo de 15 épocas de entrenamiento:

### Progresión de Épocas:
| Época | Train Loss | Train Acc | Val Loss | Val Acc | Checkpoint |
|:---:|:---:|:---:|:---:|:---:|:---:|
| **01/15** | 2.4346 | 20.43% | 2.2069 | 26.50% | `augmented_best.pt` |
| **02/15** | 2.0007 | 34.22% | 1.7964 | 41.03% | `augmented_best.pt` |
| **03/15** | 1.8638 | 39.68% | 1.8443 | 37.61% | - |
| **04/15** | 1.6716 | 44.81% | 1.4706 | 51.28% | `augmented_best.pt` |
| **05/15** | 1.7066 | 43.64% | 1.7910 | 46.15% | - |
| **06/15** | 1.5864 | 45.88% | 1.4672 | 50.43% | - |
| **07/15** | 1.5561 | 48.13% | 1.3803 | 55.56% | `augmented_best.pt` |
| **08/15** | 1.4801 | 50.80% | 1.2815 | 52.99% | - |
| **09/15** | 1.4977 | 51.87% | 1.2113 | 59.83% | `augmented_best.pt` |
| **10/15** | 1.4080 | 54.44% | 1.3674 | 53.85% | - |
| **11/15** | 1.4049 | 52.62% | 1.2939 | 58.12% | - |
| **12/15** | 1.3829 | 53.69% | **1.1790** | **64.96%** | **Mejor Checkpoint** |
| **13/15** | 1.3225 | 57.11% | 1.0934 | 64.96% | - |
| **14/15** | 1.2753 | 56.36% | 1.1681 | 53.85% | - |
| **15/15** | **1.2987** | **58.18%** | 1.1793 | 59.83% | - |

* **Hardware utilizado:** CPU Intel Core i7-1255U (4 workers paralelos). *Nota:* El entrenamiento se ejecutó en CPU debido a un bloqueo del bus PCIe de NVIDIA tras suspender el equipo.
* **Tiempo total:** ~19 minutos y 15 segundos (~77 segundos por época).

### Evaluación Oficial en Conjunto de Prueba (Test Set - 154 muestras):
La evaluación sobre grabaciones nunca vistas durante el entrenamiento arrojó:

* **Accuracy Final:** **57.14%** (el azar para 15 clases balanceadas es $\sim 6.67\%$)
* **Precision (macro):** **65.62%**
* **Recall (macro):** **59.74%**
* **F1-Score (macro):** **57.59%**
* **Matriz de Confusión:** Almacenada en `poc/confusion_matrix_augmented.png`.

---

## 8. Conclusiones y Próximos Pasos

1. **Eficiencia en Nodos Locales:** El pipeline híbrido maximiza el hardware disponible en la estación de trabajo, reduciendo los tiempos muertos y reduciendo el consumo de RAM a un nivel predecible y constante ($1.0$ GB plano vs $31.3$ GB colapsados por OOM).
2. **Estabilidad Concurrente y Bioacústica:** El aislamiento estricto de memoria, el control de semillas y las técnicas de aumentación espectralmente limpias (*Time Shift* con zero-padding y *Random Gain* previo al ruido) preservan la fidelidad de las vocalizaciones sin introducir artefactos numéricos.
3. **Paso Siguiente:** Avanzar hacia la higiene total de datos (saneamiento de archivos MP3 con advertencias de decodificación en C) y la integración de arquitecturas de vanguardia preentrenadas (*backbones* como EfficientNet-B0 o Google Perch).
