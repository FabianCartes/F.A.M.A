# Centro de Documentación Técnica — F.A.M.A.

Repositorio documental del proyecto **F.A.M.A.** (*Framework MLOps Híbrido para Clasificación Acústica Multi-Dominio*), con aplicaciones en bioacústica y diagnóstico acústico de motores.

La documentación vigente se organiza por tipo de contenido. La documentación retirada (planes cerrados, traspasos, registros fechados y el tablero anterior) se conserva en [`historico/`](historico/README.md), junto con el [índice cronológico anterior](historico/indice-anterior.md).

## Estructura

```text
docs/
├── README.md        # Este índice
├── tesis/           # Memoria de título y análisis de objetivos
├── arquitectura/    # Diseño del sistema y glosario del dominio (CONTEXT.md)
├── manuales/        # Uso, instalación, despliegue y operación
├── modelos/         # Informes de modelos, experimentos y ensambles
├── limites/         # Límites matemáticos y físicos, problemas conocidos
├── adr/             # Decisiones arquitectónicas numeradas
├── receipts/        # Evidencia reproducible en JSON
├── images/          # Diagramas, capturas y matrices de confusión
└── historico/       # Documentación retirada, conservada como evidencia
```

## Índice por carpeta

### [`tesis/`](tesis/) — Memoria de título

Memoria formal del proyecto de título y análisis de sus objetivos.

- [`analisis_objetivos_fama.md`](tesis/analisis_objetivos_fama.md): Análisis de Objetivos del Proyecto F.A.M.A.
- [`memoria_proyecto_titulo_2026_1.md`](tesis/memoria_proyecto_titulo_2026_1.md): Memoria del proyecto de título 2026-1 ([PDF](tesis/memoria_proyecto_titulo_2026_1.pdf))

### [`arquitectura/`](arquitectura/) — Arquitectura

Diseño de sistemas, componentes, pipelines y arquitectura MLOps, junto con el glosario del dominio.

- [`04_saneamiento_y_transcodificacion_audio.md`](arquitectura/04_saneamiento_y_transcodificacion_audio.md): Informe Técnico: Saneamiento y Transcodificación Canónica de Audio (Data Hygiene)
- [`18_soporte_multimodelo_backend_rdd.md`](arquitectura/18_soporte_multimodelo_backend_rdd.md): Informe Técnico: Arquitectura Multi-Modelo Desacoplada (Strategy + Model Registry) y Aislamiento de Persistencia Cloud en Backend FastAPI (RDD)
- [`20_modelo_de_producto_despliegue_y_arquitectura_operativa.md`](arquitectura/20_modelo_de_producto_despliegue_y_arquitectura_operativa.md): 20. Modelo de Producto, Estrategia de Despliegue, Concurrencia y Arquitectura Operativa de F.A.M.A.
- [`22_arquitectura_universal_multidominio_y_limites_acusticos.md`](arquitectura/22_arquitectura_universal_multidominio_y_limites_acusticos.md): 22. Arquitectura Universal Multi-Dominio sin Código y Límites Físico-Computacionales de F.A.M.A.
- [`23_plan_correccion_pendientes_operacion.md`](arquitectura/23_plan_correccion_pendientes_operacion.md): 23. Plan de corrección de los pendientes operacionales 7–14
- [`CONTEXT.md`](arquitectura/CONTEXT.md): Glosario de F.A.M.A.

### [`manuales/`](manuales/) — Manuales

Instrucciones de uso, instalación, despliegue y operación.

- [`acceso-web.md`](manuales/acceso-web.md): Acceso web a F.A.M.A.
- [`acceso_web_y_sliced_waves.md`](manuales/acceso_web_y_sliced_waves.md): Acceso web y SlicedWaves
- [`administracion_visual.md`](manuales/administracion_visual.md): Administración visual de cuentas y acceso
- [`asistente_primera_instalacion.md`](manuales/asistente_primera_instalacion.md): Asistente de primera instalación
- [`auditoria_y_limpieza_seguridad.md`](manuales/auditoria_y_limpieza_seguridad.md): Auditoría y limpieza de seguridad — backend
- [`autonomia_y_solicitudes_datasets.md`](manuales/autonomia_y_solicitudes_datasets.md): Autonomía investigadora y solicitudes de datasets
- [`base-integracion-local-fama-pruebas.md`](manuales/base-integracion-local-fama-pruebas.md): Base de integración local `fama_pruebas` (PostgreSQL 16.15 en Docker)
- [`bitacora_acceso_e_instalacion.md`](manuales/bitacora_acceso_e_instalacion.md): Bitácora de acceso, GCP e instalación de F.A.M.A.
- [`clases_de_audio_y_dashboard.md`](manuales/clases_de_audio_y_dashboard.md): Clases de audio y lectura del Dashboard
- [`conexiones_cloud_sql_y_gcs.md`](manuales/conexiones_cloud_sql_y_gcs.md): Conexiones Cloud SQL y GCS del nodo (etapa 5)
- [`contrato_referencias_dataset_canonicas.md`](manuales/contrato_referencias_dataset_canonicas.md): Operar índices con referencias canónicas por etapa
- [`diagnostico-publicacion-modelos.md`](manuales/diagnostico-publicacion-modelos.md): Diagnóstico de publicación de modelos
- [`directorios_persistentes_por_entorno.md`](manuales/directorios_persistentes_por_entorno.md): Directorios persistentes por entorno
- [`ejecucion_acotada_inferencia.md`](manuales/ejecucion_acotada_inferencia.md): Ejecución acotada de inferencia
- [`entorno-manual-entrenamiento.md`](manuales/entorno-manual-entrenamiento.md): Entorno principal del MVP: base conectada y acceso local
- [`estado_actual_y_pendientes.md`](manuales/estado_actual_y_pendientes.md): Estado actual y pendientes para retomar F.A.M.A.
- [`evaluacion-ensamble-motores.md`](manuales/evaluacion-ensamble-motores.md): Evaluación local del Super-Ensamble de motores servido
- [`evaluaciones-admitidas.md`](manuales/evaluaciones-admitidas.md): Evaluaciones admitidas en el catálogo
- [`feedback-datasets-importados.md`](manuales/feedback-datasets-importados.md): Incorporación revisada de feedback importado
- [`feedback-preparacion-siguiente-entrenamiento.md`](manuales/feedback-preparacion-siguiente-entrenamiento.md): Preparar el siguiente entrenamiento tras crecer un dataset
- [`flujo_revision_audios.md`](manuales/flujo_revision_audios.md): Revisar e incorporar audios
- [`fuentes-locales-frontend.md`](manuales/fuentes-locales-frontend.md): Fuentes locales del frontend
- [`gcs-mvp-local.md`](manuales/gcs-mvp-local.md): GCS conectado al MVP local
- [`gcs-sync-consumer.md`](manuales/gcs-sync-consumer.md): Consumidor exclusivo de sincronización GCS
- [`gestion_cuentas_y_recuperacion.md`](manuales/gestion_cuentas_y_recuperacion.md): Gestión de cuentas y recuperación — backend
- [`gpu-opcional-entrenamiento.md`](manuales/gpu-opcional-entrenamiento.md): GPU opcional para entrenamiento local
- [`guia_despliegue_operativo_docker.md`](manuales/guia_despliegue_operativo_docker.md): Guía de Despliegue Operativo Institucional con Docker
- [`identidad-checkpoint-prediccion.md`](manuales/identidad-checkpoint-prediccion.md): Interpretar la identidad del checkpoint en Predicción
- [`identidad_tecnica_oficial.md`](manuales/identidad_tecnica_oficial.md): Identidad técnica del nodo oficial
- [`importacion-datasets-zip.md`](manuales/importacion-datasets-zip.md): Importar datasets ZIP
- [`instalacion_segundo_nodo.md`](manuales/instalacion_segundo_nodo.md): Instalación de F.A.M.A. en un segundo nodo
- [`integracion-flujo-entrenamiento.md`](manuales/integracion-flujo-entrenamiento.md): Integración del flujo de entrenamiento en la carpeta principal
- [`limite_audio_inferencia.md`](manuales/limite_audio_inferencia.md): Límite de carga de audio para inferencia
- [`limites_login_y_recuperacion.md`](manuales/limites_login_y_recuperacion.md): Límites de login y recuperación — backend
- [`manual_usuario_plataforma.md`](manuales/manual_usuario_plataforma.md): Manual de Usuario y Operación de la Plataforma F.A.M.A.
- [`nombres-modelos.md`](manuales/nombres-modelos.md): Nombres de modelos en entrenamiento y predicción
- [`particiones_versionadas.md`](manuales/particiones_versionadas.md): Preparar y utilizar particiones versionadas
- [`permisos_aplicacion_postgresql.md`](manuales/permisos_aplicacion_postgresql.md): Permisos de aplicación en PostgreSQL de pruebas (etapa 6)
- [`permisos_recursos_asignados.md`](manuales/permisos_recursos_asignados.md): Permisos sobre recursos asignados
- [`plan_autonomia_investigador_y_catalogo.md`](manuales/plan_autonomia_investigador_y_catalogo.md): Ajustes para autonomía investigadora y solicitudes de datasets
- [`plan_instalacion_gcp_y_asistente.md`](manuales/plan_instalacion_gcp_y_asistente.md): Plan de implementación: Cloud SQL, GCS y primera instalación
- [`postgresql-entrenamiento-separado.md`](manuales/postgresql-entrenamiento-separado.md): PostgreSQL separado para entrenamiento importado
- [`prediccion-feedback-mvp.md`](manuales/prediccion-feedback-mvp.md): Predicción y feedback por asignación
- [`preflight-publicacion.md`](manuales/preflight-publicacion.md): Preflight de publicación de un modelo
- [`preparacion-automatica-dataset.md`](manuales/preparacion-automatica-dataset.md): Preparación automática del dataset — MVP
- [`preparacion_entorno_oficial.md`](manuales/preparacion_entorno_oficial.md): Preparación del entorno oficial
- [`preparacion_instalacion_y_migraciones.md`](manuales/preparacion_instalacion_y_migraciones.md): Preparación de instalación y migraciones (etapa 1)
- [`recuperacion_emergencia_administrador.md`](manuales/recuperacion_emergencia_administrador.md): Recuperación de emergencia del administrador
- [`reevaluacion-modelos.md`](manuales/reevaluacion-modelos.md): Reevaluación explícita de modelos MAIN
- [`respaldo_y_recuperacion_checkpoints.md`](manuales/respaldo_y_recuperacion_checkpoints.md): Respaldo y recuperación de checkpoints
- [`respaldo_y_restauracion_postgresql.md`](manuales/respaldo_y_restauracion_postgresql.md): Respaldo y restauración de PostgreSQL
- [`sesion-web-importados.md`](manuales/sesion-web-importados.md): Sesión web para recursos importados
- [`sesiones_web_y_acceso_administrado.md`](manuales/sesiones_web_y_acceso_administrado.md): Sesiones web y acceso administrado — implementación parcial
- [`trabajos-importacion-datasets.md`](manuales/trabajos-importacion-datasets.md): Trabajos locales de importación ZIP
- [`transferencias-datasets.md`](manuales/transferencias-datasets.md): Transferencias de datasets
- [`usuarios_postgresql_pruebas.md`](manuales/usuarios_postgresql_pruebas.md): Usuarios PostgreSQL de pruebas (etapa 4)
- [`validacion_mp3_y_curvas_entrenamiento.md`](manuales/validacion_mp3_y_curvas_entrenamiento.md): Subida de MP3 y rótulo de épocas del entrenamiento
- [`versiones-preparadas-dataset.md`](manuales/versiones-preparadas-dataset.md): Preparar y seleccionar una versión identificada del dataset
- [`worker-importacion-zip-local.md`](manuales/worker-importacion-zip-local.md): Worker local de importación ZIP — entorno principal del MVP

### [`modelos/`](modelos/) — Modelos

Informes de modelos, experimentos, métricas, optimizaciones y ensambles.

- [`01_primera_prueba_poc.md`](modelos/01_primera_prueba_poc.md): Informe Técnico: Primera Prueba de Concepto (PoC) Local de F.A.M.A.
- [`02_optimizacion_vad_data_augmentation.md`](modelos/02_optimizacion_vad_data_augmentation.md): Informe Técnico: Optimización Bioacústica con Ventaneo Múltiple (VAD) y Data Augmentation
- [`03_optimizacion_paralela_cpu_gpu.md`](modelos/03_optimizacion_paralela_cpu_gpu.md): Informe Técnico: Paralelismo Productor-Consumidor (CPU + GPU) y Multiprocesamiento Seguro
- [`05_transfer_learning_efficientnet_frontend_gpu.md`](modelos/05_transfer_learning_efficientnet_frontend_gpu.md): Informe Técnico: Transfer Learning con EfficientNet, Front-End en GPU y Mitigación del Solapamiento Bioacústico
- [`06_optimizacion_inferencia_tta_mixup_rdd.md`](modelos/06_optimizacion_inferencia_tta_mixup_rdd.md): Informe Técnico: Optimización de Inferencia con Test-Time Augmentation (TTA), Mixup en GPU y Matriz de Ablación RDD
- [`07_regimen_extendido_mixup_convergencia.md`](modelos/07_regimen_extendido_mixup_convergencia.md): Informe Técnico: Maduración de Mixup en Régimen Extendido (35 Épocas), Superación del 80% F1 y Precisión del 85%
- [`08_optimizacion_pipeline_gpu_frontend_rdd.md`](modelos/08_optimizacion_pipeline_gpu_frontend_rdd.md): Informe Técnico: Eliminación del Cuello de Botella de CPU, Pipeline GPU de Alto Rendimiento y Récord de 83.76% F1
- [`09_gem_pooling_bioacustica_rdd.md`](modelos/09_gem_pooling_bioacustica_rdd.md): Informe Técnico: Implementación de Generalized Mean Pooling (GeM) con Parámetro Entrenable en BioacousticEfficientNet (RDD)
- [`10_metodo_campeon_bioacustica_fama.md`](modelos/10_metodo_campeon_bioacustica_fama.md): Metodología y Arquitectura del Modelo Campeón F.A.M.A. (83.76% Macro F1)
- [`11_ventaneo_denso_inferencia_rdd.md`](modelos/11_ventaneo_denso_inferencia_rdd.md): Informe Técnico: Ventaneo Temporal Denso (Dense Windowing) en Inferencia TTA (RDD)
- [`12_ensemble_multimodelo_rdd.md`](modelos/12_ensemble_multimodelo_rdd.md): Informe Técnico: Ensamble Ponderado Multi-Modelo (Soft Voting + Late Fusion) en Inferencia TTA (RDD)
- [`13_ensamble_heterogeneo_convnext_rdd.md`](modelos/13_ensamble_heterogeneo_convnext_rdd.md): Informe Técnico: Ensamble Heterogéneo ConvNeXt-Nano + EfficientNet-B0 con Diversificación Inductiva (RDD)
- [`14_pitch_shift_espectral_gpu_rdd.md`](modelos/14_pitch_shift_espectral_gpu_rdd.md): Informe Técnico: Implementación de Pitch Shift Espectral en GPU y Reentrenamiento (RDD)
- [`15_super_ensamble_tri_modelo_resnet34d_rdd.md`](modelos/15_super_ensamble_tri_modelo_resnet34d_rdd.md): Reporte RDD: Super-Ensamble Tri-Modelo Heterogéneo (ConvNeXt + EfficientNet + ResNet34d)
- [`16_informe_maestro_super_ensamble_fama.md`](modelos/16_informe_maestro_super_ensamble_fama.md): Informe Maestro: Super-Ensamble Tri-Modelo Heterogéneo y Estado del Arte en Bioacústica F.A.M.A. (88.68% Macro F1)
- [`17_arquitectura_super_ensamble_y_modelos_preentrenados.md`](modelos/17_arquitectura_super_ensamble_y_modelos_preentrenados.md): 17. Arquitectura del Super-Ensamble Tri-Modelo, Familias Pre-entrenadas y Pipeline Bioacústico Optimizado
- [`benchmark_local_cpu_20261016.md`](modelos/benchmark_local_cpu_20261016.md): Benchmark local CPU controlado — protocolo del 15–16 de octubre de 2026
- [`fundamentacion_tecnica_efficientnet_focal_loss.md`](modelos/fundamentacion_tecnica_efficientnet_focal_loss.md): Documento Técnico: Fundamentos de la Técnica de Transfer Learning, Front-End GPU y Focal Loss
- [`informe_consolidado_diagnostico_acustico_motores.md`](modelos/informe_consolidado_diagnostico_acustico_motores.md): Informe Consolidado: Diagnóstico Acústico de Motores Vehiculares, Síntesis Física y Modelo Campeón

### [`limites/`](limites/) — Límites

Límites matemáticos o físicos, restricciones y problemas conocidos.

- [`01_solapamiento_de_clases_bioacusticas.md`](limites/01_solapamiento_de_clases_bioacusticas.md): Problema Conocido 01: Solapamiento Acústico y Confusión Sistemática entre Clases
- [`02_limites_generalizacion_universal_y_conjunto_abierto.md`](limites/02_limites_generalizacion_universal_y_conjunto_abierto.md): Problema Conocido 02: Límites de la Generalización Universal, Brecha Focal-PAM y Reconocimiento en Conjunto Abierto
- [`03_mejoras_posibles_modelo_prediccion.md`](limites/03_mejoras_posibles_modelo_prediccion.md): Problema Conocido 03: Mejoras Posibles al Modelo de Predicción más allá del 88.68% F1
- [`04_limitacion_subida_directorios_completos_data_lake.md`](limites/04_limitacion_subida_directorios_completos_data_lake.md): Problema Conocido 04: Limitación en Subida Web de Directorios Jerárquicos y Datasets Completos a GCS
- [`05_restriccion_formato_audio_y_captura_microfono.md`](limites/05_restriccion_formato_audio_y_captura_microfono.md): Problema Conocido 05: Restricción Estricta de Formato PCM .WAV y Pipeline de Captura por Micrófono Web
- [`06_ruta_checkpoint_gcs_y_entrenamiento_sin_particion.md`](limites/06_ruta_checkpoint_gcs_y_entrenamiento_sin_particion.md): Problema Conocido 06: Ruta registrada del checkpoint en GCS y entrenamiento sin partición por API

### [`adr/`](adr/) — Decisiones arquitectónicas

ADR numerados secuencialmente. Un ADR reemplazado conserva su ubicación y declara su estado.

- [`0001_migracion_efficientnet_frontend_gpu.md`](adr/0001_migracion_efficientnet_frontend_gpu.md): ADR 0001: Migración a EfficientNet-B0, Front-End GPU de 128 Mel y Focal Loss
- [`0002_mixup_gpu_tta_inferencia.md`](adr/0002_mixup_gpu_tta_inferencia.md): ADR 0002: Mixup Aditivo en VRAM y Test-Time Augmentation (TTA) con Multi-Crop en Inferencia
- [`0003_pipeline_datos_gpu_raw_waveform.md`](adr/0003_pipeline_datos_gpu_raw_waveform.md): ADR 0003: Pipeline de Datos en Ondas Crudas, Extracción Espectral en GPU y Portabilidad Acelerada Agnóstica
- [`0004_gem_pooling_bioacoustic_efficientnet.md`](adr/0004_gem_pooling_bioacoustic_efficientnet.md): ADR 0004: Generalized Mean Pooling (GeM) con Parámetro Entrenable en BioacousticEfficientNet
- [`0005_ventaneo_denso_hop_temporal.md`](adr/0005_ventaneo_denso_hop_temporal.md): ADR 0005: Ventaneo Temporal Denso (Dense Windowing) con Solapamiento Configurable en Inferencia TTA
- [`0006_ensemble_multimodelo_inferencia.md`](adr/0006_ensemble_multimodelo_inferencia.md): ADR 0006: Inferencia de Ensamble Ponderado Multi-Modelo (Soft Voting) con Diversidad Estructural
- [`0007_ensamble_heterogeneo_convnext_efficientnet.md`](adr/0007_ensamble_heterogeneo_convnext_efficientnet.md): ADR 0007: Ensamble Heterogéneo de ConvNeXt-Nano y EfficientNet-B0 con Diversificación de Sesgos Inductivos
- [`0008_calibracion_optima_pesos_ensamble_heterogeneo.md`](adr/0008_calibracion_optima_pesos_ensamble_heterogeneo.md): ADR 0008: Calibración Óptima de Pesos del Ensamble Heterogéneo y Micro-Batching de Memoria en Inferencia TTA
- [`0009_pitch_shift_espectral_gpu_augmentation.md`](adr/0009_pitch_shift_espectral_gpu_augmentation.md): ADR 0009: Desplazamiento Tonal Espectral en GPU (Spectral Pitch Shift) como Data Augmentation Bioacústico
- [`0010_tri_modelo_heterogeneo_resnet34d.md`](adr/0010_tri_modelo_heterogeneo_resnet34d.md): ADR 0010: Super-Ensamble Tri-Modelo Heterogéneo con ResNet34d, ConvNeXt-Nano y EfficientNet-B0 para Máxima Robustez Bioacústica
- [`0011_soporte_multimodelo_registry_strategy.md`](adr/0011_soporte_multimodelo_registry_strategy.md): ADR 0011: Soporte Multi-Modelo en Backend mediante Strategy Pattern y Model Registry con Aislamiento de Persistencia Cloud
- [`0012_unificacion_fuente_datos_raw.md`](adr/0012_unificacion_fuente_datos_raw.md): ADR 0012: Unificación de Almacenamiento de Datos Crudos (SSOT) en `backend/data/raw`
- [`0013_bucle_retroalimentacion_curacion_semi_manual_mlops.md`](adr/0013_bucle_retroalimentacion_curacion_semi_manual_mlops.md): ADR 0013: Bucle de Retroalimentación Activa (RF_06) con Curación Semi-Manual Human-in-the-Loop
- [`0014_delimitacion_hiperparametros_frontend_deep_modules.md`](adr/0014_delimitacion_hiperparametros_frontend_deep_modules.md): ADR 0014: Delimitación de Parámetros Configurables en Frontend bajo Principios de Deep Modules y Presets de Dominio
- [`0015-fallos-explicitos-inferencia-y-validacion.md`](adr/0015-fallos-explicitos-inferencia-y-validacion.md): ADR 0015: Fallos explícitos de inferencia y validación aislada
- [`0016-procedencia-y-persistencia-entrenamiento.md`](adr/0016-procedencia-y-persistencia-entrenamiento.md): ADR 0016: Procedencia y persistencia del entrenamiento
- [`0017-disponibilidad-y-activacion-modelos.md`](adr/0017-disponibilidad-y-activacion-modelos.md): ADR 0017: Disponibilidad y activación de modelos
- [`0018-incorporacion-local-y-sincronizacion-gcs.md`](adr/0018-incorporacion-local-y-sincronizacion-gcs.md): ADR 0018: Incorporación local y sincronización recuperable con GCS
- [`0019-referencias-canonicas-por-etapa.md`](adr/0019-referencias-canonicas-por-etapa.md): ADR 0019: Referencias canónicas por etapa con raíces físicas declaradas
- [`0020-raices-fisicas-en-localizadores-publicos.md`](adr/0020-raices-fisicas-en-localizadores-publicos.md): ADR 0020: Raíces físicas en los localizadores públicos de datasets
- [`0021-ejecucion-acotada-inferencia.md`](adr/0021-ejecucion-acotada-inferencia.md): ADR 0021: El trabajo real conserva el cupo de inferencia
- [`0022-evaluaciones-finales-estandarizadas.md`](adr/0022-evaluaciones-finales-estandarizadas.md): ADR 0022: Evaluaciones finales estandarizadas
- [`0023-identidad-checkpoint-cargado.md`](adr/0023-identidad-checkpoint-cargado.md): ADR 0023: Identidad del checkpoint cargado por el predictor
- [`0024-entrenamiento-aislado-spawn.md`](adr/0024-entrenamiento-aislado-spawn.md): ADR 0024: Entrenamiento aislado mediante spawn
- [`0025-compatibilidad-semantica-evaluacion.md`](adr/0025-compatibilidad-semantica-evaluacion.md): ADR 0025: Compatibilidad semántica del predictor evaluado
- [`0026-versiones-preparadas-y-procedencia-curada.md`](adr/0026-versiones-preparadas-y-procedencia-curada.md): ADR 0026: Identificar versiones preparadas y preservar la procedencia curada
- [`0027-importaciones-zip-privadas-locales.md`](adr/0027-importaciones-zip-privadas-locales.md): ADR 0027: Private local-first ZIP dataset imports
- [`0028-importacion-local-docker.md`](adr/0028-importacion-local-docker.md): ADR 0028: Excepción explícita de importación para Docker local
- [`0029-migracion-metadatos-importacion.md`](adr/0029-migracion-metadatos-importacion.md): Verified additive import-metadata migration before reader cutover
- [`0030-admision-durable-importaciones.md`](adr/0030-admision-durable-importaciones.md): ADR 0030: separar importaciones y trabajos con admisión transaccional
- [`0031-fenced-import-publication.md`](adr/0031-fenced-import-publication.md): Serialize import publication with lease recovery
- [`0032-durable-receipt-reservations.md`](adr/0032-durable-receipt-reservations.md): Reserve temporary receipt capacity separately from dataset storage
- [`0033-durable-import-chunks.md`](adr/0033-durable-import-chunks.md): Durable sequential chunks without a second archive copy
- [`0034-dataset-import-quotas.md`](adr/0034-dataset-import-quotas.md): Enforce unique dataset quotas inside fenced publication
- [`0035-contained-zip-validation.md`](adr/0035-contained-zip-validation.md): Contain ZIP and native audio processing before publication
- [`0036-recoverable-import-cleanup.md`](adr/0036-recoverable-import-cleanup.md): Recoverable staging cleanup independent of publication
- [`0037-immutable-dataset-revision-manifests.md`](adr/0037-immutable-dataset-revision-manifests.md): ADR 0037: Durable dataset revisions and immutable reconstruction manifests
- [`0038-complete-zip-exports-native-sessions.md`](adr/0038-complete-zip-exports-native-sessions.md): ADR 0038: Complete ZIP64 exports and renewable native download sessions
- [`0039-preprocesamiento-efectivo-en-checkpoints.md`](adr/0039-preprocesamiento-efectivo-en-checkpoints.md): ADR 0039: Preprocesamiento efectivo en checkpoints de entrenamiento web
- [`0040-ficha-tecnica-sin-valores-inventados.md`](adr/0040-ficha-tecnica-sin-valores-inventados.md): ADR 0040: Ficha técnica basada en datos explícitos, sin presets inventados
- [`0041-seleccion-con-pesos-confirmados.md`](adr/0041-seleccion-con-pesos-confirmados.md): ADR 0041: Selección con disponibilidad de pesos confirmada
- [`0042-configuracion-explicita-de-autenticacion.md`](adr/0042-configuracion-explicita-de-autenticacion.md): ADR 0042: Autenticación y alta inicial con configuración explícita
- [`0043-configuracion-runtime-y-contexto-sin-credenciales.md`](adr/0043-configuracion-runtime-y-contexto-sin-credenciales.md): ADR 0043: Configuración en runtime y contexto backend sin credenciales JSON
- [`0044-sincronizacion-por-contenido-y-publicacion-local.md`](adr/0044-sincronizacion-por-contenido-y-publicacion-local.md): ADR 0044: Sincronización por contenido y publicación local de transferencias completas
- [`0045-rutas-portables-y-confinadas-en-descarga.md`](adr/0045-rutas-portables-y-confinadas-en-descarga.md): ADR 0045: Rutas portables y confinadas en descarga de datasets
- [`0046-resultados-parciales-en-subida-de-audios.md`](adr/0046-resultados-parciales-en-subida-de-audios.md): ADR 0046: Resultados parciales en subida de audios
- [`0047-metadatos-acusticos-observados-y-lectura-registrada.md`](adr/0047-metadatos-acusticos-observados-y-lectura-registrada.md): ADR 0047: Metadatos acústicos observados y lectura registrada
- [`0048-cargas-acusticas-validadas-y-acotadas.md`](adr/0048-cargas-acusticas-validadas-y-acotadas.md): ADR 0048: Cargas acústicas validadas y acotadas
- [`0049-dashboard-con-observaciones-y-origen-explicito.md`](adr/0049-dashboard-con-observaciones-y-origen-explicito.md): ADR 0049: Dashboard con observaciones y origen explícito
- [`0050-compatibilidad-explicita-de-checkpoints-poc.md`](adr/0050-compatibilidad-explicita-de-checkpoints-poc.md): ADR 0050: Compatibilidad explícita de checkpoints PoC
- [`0051-estado-legacy-pasivo-y-ejecucion-atribuida.md`](adr/0051-estado-legacy-pasivo-y-ejecucion-atribuida.md): ADR 0051: Estado legacy pasivo y ejecución atribuida
- [`0052-sesiones-web-revocables-y-registro-administrado.md`](adr/0052-sesiones-web-revocables-y-registro-administrado.md): ADR 0052 — Sesiones web revocables y registro administrado
- [`0053-asignaciones-explicitas-y-propiedad-de-entrenamiento.md`](adr/0053-asignaciones-explicitas-y-propiedad-de-entrenamiento.md): ADR 0053 — Asignaciones explícitas y propiedad de entrenamiento
- [`0054-gestion-de-cuentas-y-recuperacion-administrada.md`](adr/0054-gestion-de-cuentas-y-recuperacion-administrada.md): ADR 0054 — Gestión de cuentas y recuperación administrada
- [`0055-cuotas-persistentes-de-login-y-recuperacion.md`](adr/0055-cuotas-persistentes-de-login-y-recuperacion.md): ADR 0055 — Cuotas persistentes de login y recuperación
- [`0056-auditoria-minima-y-limpieza-transaccional-acotada.md`](adr/0056-auditoria-minima-y-limpieza-transaccional-acotada.md): ADR 0056 — Auditoría mínima y limpieza transaccional acotada
- [`0057-acceso-web-del-mismo-origen-y-fondo-aislado.md`](adr/0057-acceso-web-del-mismo-origen-y-fondo-aislado.md): ADR 0057 — Acceso web del mismo origen y fondo aislado
- [`0058-configuracion-persistente-y-migraciones-explicitas.md`](adr/0058-configuracion-persistente-y-migraciones-explicitas.md): Configuración persistente y migraciones explícitas antes del arranque funcional
- [`0059-conexiones-cloud-explicitas-mediante-proxy.md`](adr/0059-conexiones-cloud-explicitas-mediante-proxy.md): Conexiones Cloud SQL explícitas mediante proxy externo
- [`0060-autorizacion-y-finalizacion-reanudable-de-instalacion.md`](adr/0060-autorizacion-y-finalizacion-reanudable-de-instalacion.md): Autorización del nodo y finalización reanudable de primera instalación
- [`0061-autonomia-investigadora-en-datasets-asignados.md`](adr/0061-autonomia-investigadora-en-datasets-asignados.md): ADR 0061: Autonomía investigadora en datasets asignados
- [`0062-particiones-explicitas-y-manifiestos-inmutables.md`](adr/0062-particiones-explicitas-y-manifiestos-inmutables.md): ADR 0062: Particiones explícitas y manifiestos inmutables
- [`0063-respaldo-explicito-de-checkpoints-por-contenido.md`](adr/0063-respaldo-explicito-de-checkpoints-por-contenido.md): ADR 0063: Respaldo explícito de checkpoints por contenido
- [`0064-almacenamiento-persistente-vinculado-al-entorno.md`](adr/0064-almacenamiento-persistente-vinculado-al-entorno.md): ADR 0064: Almacenamiento persistente vinculado al entorno
- [`0065-respaldo-logico-y-restauracion-sql-separada.md`](adr/0065-respaldo-logico-y-restauracion-sql-separada.md): ADR 0065: Respaldo lógico y restauración SQL separada
- [`0066-recuperacion-local-de-administradores-existentes.md`](adr/0066-recuperacion-local-de-administradores-existentes.md): ADR 0066: Recuperación local de administradores existentes
- [`0067-traslado-explicito-de-historia-y-adopcion-de-cuenta.md`](adr/0067-traslado-explicito-de-historia-y-adopcion-de-cuenta.md): Traslado explícito de historia y adopción de una cuenta existente
- [`0068-declaracion-explicita-de-ensambles-por-instalacion.md`](adr/0068-declaracion-explicita-de-ensambles-por-instalacion.md): Declaración explícita de ensambles por instalación
- [`0069-integracion-de-acceso-evaluacion-y-datasets.md`](adr/0069-integracion-de-acceso-evaluacion-y-datasets.md): ADR 0069: Integrar acceso, evaluación y datasets entre ramas
- [`0070-revision-0005-y-composicion-versionada-de-triadas.md`](adr/0070-revision-0005-y-composicion-versionada-de-triadas.md): ADR 0070: Revisión 0005 y composición versionada de tríadas estándar
- [`0071-preparacion-local-de-datasets-importados.md`](adr/0071-preparacion-local-de-datasets-importados.md): ADR 0071: Preparación local de datasets importados con grupos explícitos
- [`0072-procedencia-durable-de-entrenamiento-importado.md`](adr/0072-procedencia-durable-de-entrenamiento-importado.md): ADR 0072: Procedencia durable de entrenamiento importado sin identidad legacy ficticia
- [`0073-sesion-web-compatible-con-bearer-importados.md`](adr/0073-sesion-web-compatible-con-bearer-importados.md): Sesión web compatible con Bearer para recursos importados
- [`0074-postgresql-separado-para-bootstrap-de-entrenamiento.md`](adr/0074-postgresql-separado-para-bootstrap-de-entrenamiento.md): PostgreSQL separado para el bootstrap de entrenamiento
- [`0075-audio-local-privado-de-inferencia.md`](adr/0075-audio-local-privado-de-inferencia.md): Audio local privado para inferencia de modelos importados
- [`0076-identidad-inmutable-de-composiciones-importadas.md`](adr/0076-identidad-inmutable-de-composiciones-importadas.md): Identidad inmutable para composiciones de modelos importados
- [`0077-cache-de-hash-de-checkpoints-por-identidad-de-archivo.md`](adr/0077-cache-de-hash-de-checkpoints-por-identidad-de-archivo.md): Caché del hash de checkpoints por identidad de archivo
- [`0078-gcs-como-fuente-unica-y-publicacion-del-zip.md`](adr/0078-gcs-como-fuente-unica-y-publicacion-del-zip.md): ADR 0078: GCS como fuente única y publicación del ZIP en el catálogo compartido
- [`0079-descripcion-del-dataset-compartido.md`](adr/0079-descripcion-del-dataset-compartido.md): ADR 0079: Descripción del dataset compartido (revisión 0006)
- [`0080-reparto-incremental-y-origen-de-retroalimentacion-en-particiones.md`](adr/0080-reparto-incremental-y-origen-de-retroalimentacion-en-particiones.md): ADR 0080: Reparto incremental y origen de la retroalimentación en las particiones
- [`0081-intentos-de-evaluacion-conjunta-de-triadas.md`](adr/0081-intentos-de-evaluacion-conjunta-de-triadas.md): ADR 0081: Intentos de evaluación conjunta de composiciones de tríada
- [`0082-pesos-fijos-de-entrenamiento-en-triadas.md`](adr/0082-pesos-fijos-de-entrenamiento-en-triadas.md): ADR 0082: Pesos fijos de entrenamiento en tríadas estándar
- [`0083-retiro-del-super-ensamble-fijo.md`](adr/0083-retiro-del-super-ensamble-fijo.md): ADR 0083: Retiro del Super-Ensamble fijo y de su estado legacy

### [`receipts/`](receipts/) — Evidencia reproducible

Recibos JSON legibles por máquinas que registran comandos, resultados y límites de cada verificación. Los recibos son cortes históricos: no describen el estado actual del sistema ni ejecuciones nuevas.

### [`images/`](images/) — Imágenes

Diagramas, capturas de la aplicación y matrices de confusión enlazados desde los documentos anteriores.

### [`historico/`](historico/README.md) — Documentación retirada

Planes de implementación cerrados, traspasos, registros de integraciones fechadas y el tablero de seguimiento anterior. Se conservan como evidencia y contexto de decisiones; no describen necesariamente el comportamiento actual.
