# Benchmark local CPU controlado — protocolo del 15–16 de octubre de 2026

## Resultado y alcance

Se ejecutaron mediciones reales locales con autorización individual de entradas, recursos y repeticiones. **No se acredita cumplimiento global de RNF_01/RNF_04/RNF_02.** Se midió un caso de preprocesamiento y una ruta del predictor que terminó en filtro de ruido; no se midió forward neuronal efectivo, API/navegador, GPU, entrenamiento, exactitud/F1 ni 50 GB.

| Medición | Primera llamada | Mediana caliente (5) | Interpretación |
| --- | ---: | ---: | --- |
| `load_and_fix_length` + `extract_mel_spectrogram` por defecto, 64 bandas | 1,5526 s | 27,911 ms | Un audio real; tensor 64×216 finito. No incluye imports, guardado npy ni UI |
| Carga del checkpoint tras corregir formato | 124,838 ms | No repetida | Deserialización restringida, construcción y carga estricta de pesos en CPU |
| `TrainedModelPredictor.predict`, resultado `noise` | 1,0035 s | 33,568 ms | Incluye su lectura/preprocesamiento/filtros, **sin forward del clasificador** |

La primera llamada es primera de proceso/etapa, no disco frío: se habían leído hashes/cabecera. La etapa de preprocesamiento precedió al primer intento de carga; el último intento no repitió esa etapa independiente. No se comparan ni suman estas duraciones como si fueran un mismo pipeline. Cinco repeticiones no dan una garantía general ni percentiles robustos.

## Entradas y entorno autorizados

- Audio: `backend/data/raw/AvesChilenas/Canastero/15290.mp3`, 185405 bytes; cabecera observada de 44100 Hz, mono y 23,1734 s. El directorio no se toma aquí como verdad-terreno de calidad/especie.
- Checkpoint: `backend/checkpoints/efficientnet_gpu_pipeline_35e_best.pt`, 48822960 bytes; mismo artefacto en todos los intentos, sin explorar/cargar otros pesos.
- Windows 11, Python 3.12.10, PyTorch 2.14.0+cpu, NumPy 2.4.2, librosa 1.0.0, soundfile 0.14.0 y timm 1.0.29. CPU con 12 hilos lógicos/10 núcleos informados y 15,69 GiB de RAM total. No se modificaron dependencias.
- Dos hilos de cómputo, máximo 180 s por proceso autorizado, vigilancia RSS 1,5 GiB y aborto si RAM libre <2 GiB. Muestreo de 0,1 s: no es un límite duro del sistema operativo. No hubo aborto por presupuesto.
- Pico observado inicial ≈517 MiB; intento final ≈528 MiB, **no pico de inferencia neuronal completa**. Imports separados del primer proceso: 11,107 s; último proceso: 5,918 s. El monitor final duró 8,468 s en total.
- Red bloqueada en el proceso; deserialización forzada `weights_only=True`; CPU sin CUDA visible. Cachés y temporales propios aislados. No hubo BD/GCS reales, servicios arrancados/detenidos, entrenamiento ni activación.

El inventario previo autorizado de nombres/tamaños halló 1218 archivos en `backend/data` (5394314590 bytes, aproximadamente 5,02 GiB), no 50 GB. `nvidia-smi` no estaba en PATH ni en dos ubicaciones habituales; no se deduce de ello ausencia física de GPU. El runtime usado era CPU-only y no se ejecutó benchmark GPU. El primer intento de inventario falló por el wrapper de Python en Windows; se repitió con el ejecutable explícito, sin abrir contenidos durante ese inventario.

## Fallos conservados y corrección

1. [Intento inicial](../receipts/benchmark_local_cpu_20261015.json): preprocesamiento medido; carga fallida por `backbone.global_pool.p` ausente. Status failed, no latencia de inferencia válida. El filename conserva la etiqueta inicial del protocolo; las fechas UTC reales están en el JSON.
2. [Repetición autorizada](../receipts/benchmark_local_cpu_inference_20261016.json): respetar solo `pool_type` explícito no bastó; mismo fallo, conservado sin sobrescribir.
3. [Diagnóstico restringido](../receipts/checkpoint_compatibility_metadata_20261016.json): formato PoC con `model_type=efficientnet_b0`, `n_mels=128`, sin architecture/pool_type y sin claves de global_pool. No es un benchmark de latencia.
4. [Intento final autorizado](../receipts/benchmark_local_cpu_inference_validated_20261016.json): tras [ADR 0050](../adr/0050-compatibilidad-explicita-de-checkpoints-poc.md), carga avg estricta correcta y 128 bandas configuradas; la ruta devolvió `Ruido / Señal no biológica` antes de la red. `classifier_forward_observed=false`, latency de forward null y Mel de esa rama no observado. **Completed del protocolo no significa clasificación neuronal comprobada ni requisito de 3 s cumplido.**

Las pruebas sintéticas reprodujeron tanto el campo de pooling ignorado como el formato model_type y las bandas explícitas ignoradas. No se cambiaron thresholds ni se forzó una clase para obtener un tiempo favorable. El rechazo noise requiere evaluación con casos/etiquetas validados antes de considerarlo correcto o falso positivo.

## Preservación y reproducción

Los cuatro recibos incluyen autorización, presupuestos, versiones, fuentes exactas del worker/monitor y datos de estado; los benchmarks incluyen hashes de código. Audio y checkpoint conservaron SHA-256, tamaño y mtime entre antes/después; no se modificaron originales. La vigilancia solo podía detener el proceso propio. El código de instrumentación está preservado como dato en `reproduction`; no se instala como funcionalidad de aplicación ni se ejecuta al validar los recibos.

`tests/test_local_benchmark_receipts.py` valida coherencia de evidencia, muestras, medianas, presupuestos e historia de fallos sin volver a abrir activos ni repetir benchmarks. Cualquier nueva ejecución real, otro archivo, mayor carga, GPU/servicios o prueba de 50 GB requiere autorización nueva. Los recibos no deben sobrescribirse; no se promedian intentos fallidos con exitosos ni se oculta la rama medida.

## Lo que sigue pendiente

- Caso autorizado que atraviese realmente el forward y una evaluación con ground truth; no hay permiso para sustituir ahora el audio ni el checkpoint.
- Tiempo de usuario completo hasta pantalla (RF05/RNF04), cargas concurrentes y variación por duración/formato/hardware.
- Perfil acústico histórico completo/normalización/TTA, calidad y consolidación experimental de OE5; legacy_librosa es explícito, no certifica reproducción del entrenamiento original.
- Ensayo de dataset de 50 GB sin OOM y límites integrales de recursos/recepción. El inventario actual y una vigilancia de proceso pequeño no lo acreditan.
