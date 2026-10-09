# Centro de Documentación Técnica — F.A.M.A.

Bienvenido al repositorio documental del proyecto **F.A.M.A.** (*Framework MLOps Híbrido para Clasificación Acústica Multi-Dominio*).

La documentación está organizada temáticamente en subdirectorios especializados para facilitar la navegación a evaluadores, investigadores y desarrolladores:

---

## Estructura del Repositorio Documental

```text
docs/
├── README.md                    # Vista general e índice documental
├── KANBAN.md                    # Tablero de seguimiento activo del proyecto
├── tesis/                       # Memoria de grado oficial y análisis de objetivos
├── modelos/                     # Informes experimentales, optimizaciones y ensambles
├── arquitectura/                # Diseño de sistemas, pipelines, MLOps y despliegue
├── limites/                     # Límites matemáticos, físicos y problemas conocidos
├── manuales/                    # Manual de usuario, revisión, despliegue e índices canónicos
├── adr/                         # Architectural Decision Records (ADR 0001 a 0020)
├── receipts/                    # Recibos técnicos reproducibles en formato JSON (RDD)
├── duplicados-exactos/           # Tarea acotada: admisión de feedback sin duplicados SHA-256
└── images/                      # Diagramas, matrices de confusión y gráficos vectoriales
```

---

## Índice Detallado por Carpeta

### Tarea acotada: duplicados exactos
* [`docs/duplicados-exactos/tasks.md`](./duplicados-exactos/tasks.md): Alcance, decisiones locales, checklist y evidencia TDD de aprobación de feedback sin duplicados SHA-256; revisión y commit pendientes del orquestador.

### 1. [`docs/tesis/`](./tesis/) — Tesis y Objetivos de Grado
* [`VIDA_01_CINF_FINAL_PT_2026_1_CARTES.md`](./tesis/VIDA_01_CINF_FINAL_PT_2026_1_CARTES.md) / [`.pdf`](./tesis/VIDA_01_CINF_FINAL_PT_2026_1_CARTES.pdf): Memoria formal de proyecto de título.
* [`analisis_objetivos_fama.md`](./tesis/analisis_objetivos_fama.md): Matriz de trazabilidad de los Objetivos Específicos (OE1 a OE5) y Requerimientos Funcionales (RF_01 a RF_06) vs. el código real.

### 2. [`docs/modelos/`](./modelos/) — Modelado Acústico y Experimentos
Informes técnicos de evolución de los modelos de Machine Learning (desde la PoC al 88.68% F1):
* [`01_primera_prueba_poc.md`](./modelos/01_primera_prueba_poc.md): PoC inicial con red convolucional plana AudioCNN.
* [`02_optimizacion_vad_data_augmentation.md`](./modelos/02_optimizacion_vad_data_augmentation.md): Filtro VAD por energía y aumentaciones básicas.
* [`03_optimizacion_paralela_cpu_gpu.md`](./modelos/03_optimizacion_paralela_cpu_gpu.md): Paralelización CPU/GPU en preprocesamiento.
* [`05_transfer_learning_efficientnet_frontend_gpu.md`](./modelos/05_transfer_learning_efficientnet_frontend_gpu.md): Adopción de EfficientNet-B0 con banco Mel en GPU.
* [`06_optimizacion_inferencia_tta_mixup_rdd.md`](./modelos/06_optimizacion_inferencia_tta_mixup_rdd.md): Regularización Mixup y Test-Time Augmentation (TTA).
* [`07_regimen_extendido_mixup_convergencia.md`](./modelos/07_regimen_extendido_mixup_convergencia.md): Régimen de entrenamiento extendido a 35 épocas.
* [`08_optimizacion_pipeline_gpu_frontend_rdd.md`](./modelos/08_optimizacion_pipeline_gpu_frontend_rdd.md): Pipeline tensorial completo en CUDA.
* [`09_gem_pooling_bioacustica_rdd.md`](./modelos/09_gem_pooling_bioacustica_rdd.md): Integración de Generalized Mean Pooling (GeM $p=3.0$).
* [`10_metodo_campeon_bioacustica_fama.md`](./modelos/10_metodo_campeon_bioacustica_fama.md): Consolidación del modelo individual campeón.
* [`11_ventaneo_denso_inferencia_rdd.md`](./modelos/11_ventaneo_denso_inferencia_rdd.md): Ventaneo denso con solapamiento en inferencia.
* [`12_ensemble_multimodelo_rdd.md`](./modelos/12_ensemble_multimodelo_rdd.md): Primer ensamble homogéneo ponderado.
* [`13_ensamble_heterogeneo_convnext_rdd.md`](./modelos/13_ensamble_heterogeneo_convnext_rdd.md): Ensamble heterogéneo incorporando ConvNeXt-Nano.
* [`14_pitch_shift_espectral_gpu_rdd.md`](./modelos/14_pitch_shift_espectral_gpu_rdd.md): Pitch shifting espectral en GPU.
* [`15_super_ensamble_tri_modelo_resnet34d_rdd.md`](./modelos/15_super_ensamble_tri_modelo_resnet34d_rdd.md): Incorporación de ResNet-34d.
* [`16_informe_maestro_super_ensamble_fama.md`](./modelos/16_informe_maestro_super_ensamble_fama.md): Informe maestro del Super-Ensamble Tri-Modelo (88.68% F1 récord).
* [`17_arquitectura_super_ensamble_y_modelos_preentrenados.md`](./modelos/17_arquitectura_super_ensamble_y_modelos_preentrenados.md): Fundamentación teórica de modelos preentrenados.
* [`fundamentacion_tecnica_efficientnet_focal_loss.md`](./modelos/fundamentacion_tecnica_efficientnet_focal_loss.md): Justificación matemática de Focal Loss y EfficientNet.
* [`informe_consolidado_diagnostico_acustico_motores.md`](./modelos/informe_consolidado_diagnostico_acustico_motores.md): Informe del ensamble industrial para fallas de motor (81.16% Acc).

### 3. [`docs/arquitectura/`](./arquitectura/) — Arquitectura de Software y MLOps
* [`03_orquestador_fastapi_gcs_postgresql.md`](./arquitectura/03_orquestador_fastapi_gcs_postgresql.md): Arquitectura del orquestador backend con FastAPI.
* [`04_saneamiento_y_transcodificacion_audio.md`](./arquitectura/04_saneamiento_y_transcodificacion_audio.md): Pipeline de saneamiento y normalización de audio crudo.
* [`18_soporte_multimodelo_backend_rdd.md`](./arquitectura/18_soporte_multimodelo_backend_rdd.md): Desacoplamiento de inferencia con Patrón Strategy y ModelRegistry.
* [`19_subsistema_entrenamiento_modular_rdd.md`](./arquitectura/19_subsistema_entrenamiento_modular_rdd.md): Subsistema modular de recetas YAML y exportación de bundles.
* [`20_modelo_de_producto_despliegue_y_arquitectura_operativa.md`](./arquitectura/20_modelo_de_producto_despliegue_y_arquitectura_operativa.md): Estrategia de producto on-premise, concurrencia y contenedores Docker.
* [`21_resumen_actualizacion_remota_y_nuevas_capacidades.md`](./arquitectura/21_resumen_actualizacion_remota_y_nuevas_capacidades.md): Resumen de integración remota y resolución de conflictos.
* [`22_arquitectura_universal_multidominio_y_limites_acusticos.md`](./arquitectura/22_arquitectura_universal_multidominio_y_limites_acusticos.md): Especificación de F.A.M.A. como motor No-Code para cualquier dataset y límites físicos/computacionales.
* [`22_propuesta_vista_ayuda_y_centro_de_conocimiento.md`](./arquitectura/22_propuesta_vista_ayuda_y_centro_de_conocimiento.md): Diseño y especificación del centro de conocimiento e interactividad en frontend.

### 4. [`docs/manuales/`](./manuales/) — Manuales y Guías Operativas
* [`contrato_referencias_dataset_canonicas.md`](./manuales/contrato_referencias_dataset_canonicas.md): Contrato relativo por etapa, raíces físicas, conversión offline dry-run y preservación; publicación, corte operativo y recuperación requieren autorización separada.
* [`manual_usuario_plataforma.md`](./manuales/manual_usuario_plataforma.md): Guía integral de operación para investigadores y administradores; incluye [admisión, procedencia y guardado del entrenamiento](./manuales/manual_usuario_plataforma.md#55-requisitos-de-la-fuente-local-y-procedencia) y siguiente comprobación autorizada; distingue [disponibilidad, activación y refresco de Predicción](./manuales/manual_usuario_plataforma.md#611-disponibilidad-del-catálogo-y-activación) de inferencia comprobada.
* [`flujo_revision_audios.md`](./manuales/flujo_revision_audios.md): Validación e incorporación local de audios, sincronización recuperable con GCS y [próximos pasos del operador](./manuales/flujo_revision_audios.md#próximos-pasos-del-operador); distingue hitos aceptados de auditorías actuales.
* [`guia_despliegue_operativo_docker.md`](./manuales/guia_despliegue_operativo_docker.md): Manual de instalación y despliegue institucional con Docker; incluye [arranque diario, reconstrucción explícita y espera de disponibilidad](./manuales/guia_despliegue_operativo_docker.md#7-puesta-en-marcha-y-scripts-de-automatización).

### 5. [`docs/limites/`](./limites/) — Límites Matemáticos y Problemas Conocidos
* [`01_solapamiento_de_clases_bioacusticas.md`](./limites/01_solapamiento_de_clases_bioacusticas.md): Análisis del solapamiento espectral y confusión entre especies hermanas.
* [`02_limites_generalizacion_universal_y_conjunto_abierto.md`](./limites/02_limites_generalizacion_universal_y_conjunto_abierto.md): Límites teóricos de la generalización a 10.000 especies y reconocimiento en conjunto abierto.
* [`03_mejoras_posibles_modelo_prediccion.md`](./limites/03_mejoras_posibles_modelo_prediccion.md): Roadmap de mejoras futuras más allá del 88.68% F1.
* [`04_limitacion_subida_directorios_completos_data_lake.md`](./limites/04_limitacion_subida_directorios_completos_data_lake.md): Limitaciones de I/O en la ingesta masiva hacia GCS.
* [`05_restriccion_formato_audio_y_captura_microfono.md`](./limites/05_restriccion_formato_audio_y_captura_microfono.md): Restricción estricta de formato PCM .wav y pipeline de captura por micrófono web.

### Evidencia operacional de permisos
* [`backend_permissions_integration.json`](./receipts/backend_permissions_integration.json): Verificación PERM-3 del servicio público de feedback en contenedor aislado; propietario y modos tras aprobaciones, reinicio y replay. Contexto mínimo, no prueba del despliegue completo ni autoridad de entrega.

### 6. [`docs/adr/`](./adr/) — Architectural Decision Records
Registro de las 20 decisiones de arquitectura fundamentales del sistema:
* `ADR 0001`: Migración de AudioCNN a EfficientNet-B0.
* `ADR 0002`: Particionamiento Estratificado a Nivel de Grabador (Zero Leakage).
* `ADR 0003`: Adopción de Focal Loss frente a Cross-Entropy estándar.
* `ADR 0004`: Pipeline Espectral en GPU vs. CPU.
* `ADR 0005`: Adopción de Generalized Mean Pooling (GeM $p=3.0$).
* `ADR 0006`: Ventaneo Denso Solapado en Inferencia con TTA.
* `ADR 0007`: Ensamble Homogéneo de Checkpoints.
* `ADR 0008`: Ensamble Heterogéneo Tri-Familia (EfficientNet + ConvNeXt + ResNet).
* `ADR 0009`: Pitch Shifting Espectral Vectorizado en GPU.
* `ADR 0010`: Homogeneización de Hiperparámetros de la Tríada.
* `ADR 0011`: Soporte Multi-Modelo con Patrón Strategy y ModelRegistry.
* `ADR 0012`: Unificación de Fuente de Datos Raw.
* `ADR 0013`: Bucle de Retroalimentación Activa (RF_06) con Curación Semi-Manual Human-in-the-Loop.
* `ADR 0014`: Delimitación de Parámetros Configurables en Frontend bajo Principios de Deep Modules y Presets de Dominio.
* [`ADR 0015`](./adr/0015-fallos-explicitos-inferencia-y-validacion.md): Fallos explícitos de inferencia y validación aislada.
* [`ADR 0016`](./adr/0016-procedencia-y-persistencia-entrenamiento.md): Datasets soportados, procedencia verificable y finalización confirmada; límites entre checkpoints locales y BD, sin garantía de subida a GCS.
* [`ADR 0017`](./adr/0017-disponibilidad-y-activacion-modelos.md): Reconciliación del catálogo por solicitud y refresco predecible de Predicción; disponibilidad sin activación implícita ni garantía de inferencia.
* [`ADR 0018`](./adr/0018-incorporacion-local-y-sincronizacion-gcs.md): Incorporación local antes de GCS, intención recuperable y outbox durable; aceptación, acuse cloud y entrenamiento sin atomicidad distribuida ni reparación histórica implícita.
* [`ADR 0019`](./adr/0019-referencias-canonicas-por-etapa.md): Referencias relativas con etapa raw/processed obligatoria y raíces físicas explícitas; contrato compartido estricto, sin inferencia ni activación automática de productores/consumidores legacy.
* [`ADR 0020`](./adr/0020-raices-fisicas-en-localizadores-publicos.md): Getters raw/processed y PathResolver conservan la escritura declarada; raíces con alias no soportadas para asociación canónica, sin validación física implícita ni migración de URIs.
