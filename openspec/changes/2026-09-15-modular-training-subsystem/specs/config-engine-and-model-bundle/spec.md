# Especificación: Motor de Configuración y Empaquetado de Model Bundles

**Dominio:** `config-engine-and-model-bundle`  
**Cambio:** `2026-09-15-modular-training-subsystem`  
**Estado:** Especificado  

---

## 1. Declaración de Requisitos (RFC 2119)

### 1.1 Motor de Configuración (YAML / Pydantic)
* **REQ-CFG-01:** El sistema DEBE validar recetas de entrenamiento escritas en YAML utilizando el esquema Pydantic `TrainingConfig`.
* **REQ-CFG-02:** El esquema DEBE validar la coherencia de la física del audio: `n_fft >= hop_length`, `f_max > f_min` (cuando `f_max` esté definido) y que las proporciones de split sumen exactamente $1.0$.
* **REQ-CFG-03:** El esquema DEBE permitir configurar funciones de pérdida (`focal`, `cross_entropy`, `bce_with_logits`) y familias de arquitectura (`audio_cnn`, `timm_bioacoustic`, `ensemble`).

### 1.2 Formato y Exportación del Model Bundle
* **REQ-BND-01:** Al finalizar el entrenamiento, el componente `BundleExporter` DEBE empaquetar el modelo en una carpeta aislada bajo `checkpoints/<model_id>/`.
* **REQ-BND-02:** El bundle DEBE contener obligatoriamente los archivos `manifest.json` y `weights.pt` (o `weights.safetensors`).
* **REQ-BND-03:** `weights.pt` DEBE contener únicamente los tensores de pesos del modelo (`state_dict`), sin estados del optimizador ni buffers residuales de entrenamiento.
* **REQ-BND-04:** `manifest.json` DEBE ajustarse estrictamente al esquema Pydantic `ModelManifest`, incluyendo especificaciones de audio (`target_sr`, `duration_seconds`, `n_mels`, `n_fft`, `hop_length`), especificaciones de arquitectura (`architecture_family`, `backbone`, `pool_type`) y la lista ordenada de clases.

### 1.3 Auto-descubrimiento y Serving Dinámico
* **REQ-SRV-01:** El sistema DEBE proveer un adaptador `BundleAudioPredictor` que implemente la interfaz `AudioPredictor` leyendo de forma autónoma cualquier `manifest.json` válido.
* **REQ-SRV-02:** `ModelRegistry` DEBE ofrecer una función de descubrimiento (`discover_and_register_bundles(checkpoints_dir)`) que escanee los subdirectorios de checkpoints y registre automáticamente los bundles encontrados.
* **REQ-SRV-03:** Si un bundle presenta un manifiesto corrupto o incompleto, el registro DEBE emitir una advertencia en los logs y omitir dicho modelo sin interrumpir el arranque del servidor FastAPI ni afectar a los modelos sanos.

---

## 2. Escenarios de Comportamiento (Given / When / Then)

### Escenario 1: Validación estricta de receta YAML
```gherkin
Given un archivo YAML de receta con proporciones de split train=0.70, val=0.20, test=0.20 (suma 1.10)
When se parsea el archivo con TrainingConfig.from_yaml()
Then se produce un error de validación de Pydantic
And el mensaje indica claramente que las proporciones deben sumar 1.0
```

### Escenario 2: Exportación de Model Bundle autocontenido
```gherkin
Given un modelo entrenado, su receta TrainingConfig y métricas de evaluación
When BundleExporter.export(output_dir, model, config, metrics) es ejecutado
Then se crea el directorio "checkpoints/<model_id>/"
And existe el archivo "manifest.json" válido contra ModelManifest
And existe el archivo "weights.pt" conteniendo solo el state_dict de PyTorch
And existe una copia "training_recipe.yaml" para trazabilidad de linaje
```

### Escenario 3: Auto-descubrimiento en ModelRegistry sin código manual
```gherkin
Given una carpeta "checkpoints/anfibios_pam_v1/" con un bundle válido a 32 kHz
And un ModelRegistry inicializado en FastAPI
When se ejecuta discover_and_register_bundles("checkpoints/")
Then el registry contiene el modelo "anfibios_pam_v1"
And GET /api/models lista el modelo con target_sr=32000 y sus clases correspondientes
And POST /api/predict?model_id=anfibios_pam_v1 resuelve el BundleAudioPredictor y ejecuta la inferencia
```

### Escenario 4: Tolerancia a fallos ante bundles inválidos
```gherkin
Given una carpeta "checkpoints/bundle_danado/" con un manifest.json con sintaxis JSON rota
When el ModelRegistry escanea el directorio de checkpoints
Then se captura la excepción y se emite un log de advertencia
And los demás modelos válidos se registran exitosamente
And el servidor FastAPI inicia con código de salida 0
```
