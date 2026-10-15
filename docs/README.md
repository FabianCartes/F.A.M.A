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
├── adr/                         # Architectural Decision Records (ADR 0001 a 0025)
├── receipts/                    # Recibos técnicos reproducibles en formato JSON (RDD)
├── duplicados-exactos/           # Tarea acotada: admisión de feedback sin duplicados SHA-256
└── images/                      # Diagramas, matrices de confusión y gráficos vectoriales
```

---

## Índice Detallado por Carpeta

* [`seguimiento-frontend-definitivo.md`](./seguimiento-frontend-definitivo.md): Contrato de preprocesamiento de nuevos checkpoints estándar, evidencia focal y límites antes de entrenar.

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
* [`publicacion-evaluaciones-coherentes.md`](./arquitectura/publicacion-evaluaciones-coherentes.md): Seguimiento de diagnóstico de publicación, par de evaluaciones aplicable, preflight y reversión; implementación y verificaciones por hitos.
* [`identidad-checkpoint-cargado.md`](./arquitectura/identidad-checkpoint-cargado.md): Contrato de identidad de carga, bloqueo de registros sin hash y evidencia de implementación; no implica atestación continua de tensores.
* [`03_orquestador_fastapi_gcs_postgresql.md`](./arquitectura/03_orquestador_fastapi_gcs_postgresql.md): Arquitectura del orquestador backend con FastAPI.
* [`04_saneamiento_y_transcodificacion_audio.md`](./arquitectura/04_saneamiento_y_transcodificacion_audio.md): Pipeline de saneamiento y normalización de audio crudo.
* [`18_soporte_multimodelo_backend_rdd.md`](./arquitectura/18_soporte_multimodelo_backend_rdd.md): Desacoplamiento de inferencia con Patrón Strategy y ModelRegistry.
* [`19_subsistema_entrenamiento_modular_rdd.md`](./arquitectura/19_subsistema_entrenamiento_modular_rdd.md): Informe histórico del subsistema modular de recetas YAML y exportación de bundles; no describe el flujo operativo vigente.
* [`limpieza-entrenamiento-legacy.md`](./arquitectura/limpieza-entrenamiento-legacy.md): Seguimiento de la retirada aprobada de herramientas legacy y revisión FastAPI.
* [`revision-fastapi.md`](./arquitectura/revision-fastapi.md): Revisión documental de patrones FastAPI, deuda de mantenibilidad y límites del worker de entrenamiento; propuestas no implementadas.
* [`20_modelo_de_producto_despliegue_y_arquitectura_operativa.md`](./arquitectura/20_modelo_de_producto_despliegue_y_arquitectura_operativa.md): Estrategia de producto on-premise, concurrencia y contenedores Docker.
* [`21_resumen_actualizacion_remota_y_nuevas_capacidades.md`](./arquitectura/21_resumen_actualizacion_remota_y_nuevas_capacidades.md): Informe histórico de integración remota; las recetas de entrenamiento descritas no son el flujo operativo vigente.
* [`22_arquitectura_universal_multidominio_y_limites_acusticos.md`](./arquitectura/22_arquitectura_universal_multidominio_y_limites_acusticos.md): Especificación de F.A.M.A. como motor No-Code para cualquier dataset y límites físicos/computacionales.
* [`22_propuesta_vista_ayuda_y_centro_de_conocimiento.md`](./arquitectura/22_propuesta_vista_ayuda_y_centro_de_conocimiento.md): Diseño y especificación del centro de conocimiento e interactividad en frontend.

### 4. [`docs/manuales/`](./manuales/) — Manuales y Guías Operativas
* [`recuperacion-modelo-14.md`](./manuales/recuperacion-modelo-14.md): Corrección del contrato de compatibilidad, reevaluación real del modelo 14, retirada de modelos 11–13 y comprobación HTTP/navegador del despliegue.
* [`consolidacion-worktrees.md`](./manuales/consolidacion-worktrees.md): Retirada de los 58 secundarios, recuperación de respaldos y entornos CUDA, integración spawn y verificaciones locales.
* [`evaluaciones-admitidas.md`](./manuales/evaluaciones-admitidas.md): Distingue el par val/test admitido por la guarda de los intentos y reportes históricos más recientes; documenta los límites de la evidencia.
* [`preflight-publicacion.md`](./manuales/preflight-publicacion.md): CLI explícito de publicación de solo lectura, identidad requerida y smoke separado de inferencia; SQLite nativo read-only y límites de verificación.
* [`diagnostico-publicacion-modelos.md`](./manuales/diagnostico-publicacion-modelos.md): Causas sanitizadas de rechazo y mensajes de catálogo vacío o indisponible; no modifica activación ni validación.
* [`fragmentacion-limpieza-legacy.md`](./manuales/fragmentacion-limpieza-legacy.md): Seguimiento de la división local autorizada del commit de limpieza, respaldo, verificaciones y límites de revisión nativa; sin publicación. [Evidencia de los cortes](./receipts/fragmentacion-limpieza-legacy.json).
* [`identidad-checkpoint-prediccion.md`](./manuales/identidad-checkpoint-prediccion.md): Interpretación de hashes de catálogo, carga e informe; bloqueo de modelos persistidos sin hash y límites operativos.
* [`integracion-flujo-entrenamiento.md`](./manuales/integracion-flujo-entrenamiento.md): Alcance, preservación y evidencia de integración local del flujo de entrenamiento; sin ejecución real ni cambios de activación.
* [`ejecucion_acotada_inferencia.md`](./manuales/ejecucion_acotada_inferencia.md): Plan aprobado, evidencia de admisión por proceso y ownership del predictor; ingreso, GCS y timeout pendientes.
* [`evaluacion-ensamble-motores.md`](./manuales/evaluacion-ensamble-motores.md): Evaluación local explícita del predictor servido de tres componentes; snapshots preparados, provenance compuesta y reporte no sobrescribible, sin BD ni publicación.
* [`reevaluacion-modelos.md`](./manuales/reevaluacion-modelos.md): Reevaluación MAIN con preflight y ejecución explícita append-only; incluye evidencia real EVAL-6B y sus límites de calidad.
* [`limite_audio_inferencia.md`](./manuales/limite_audio_inferencia.md): Límite WAV de 100 MiB, margen multipart del proxy, errores HTTP, evidencia aislada y activación con reconstrucción pendiente de autorización.
* [`contrato_referencias_dataset_canonicas.md`](./manuales/contrato_referencias_dataset_canonicas.md): Contrato relativo por etapa, raíces físicas, conversión offline dry-run y preservación; publicación, corte operativo y recuperación requieren autorización separada.
* [`manual_usuario_plataforma.md`](./manuales/manual_usuario_plataforma.md): Guía integral de operación para investigadores y administradores; incluye [admisión, procedencia y guardado del entrenamiento](./manuales/manual_usuario_plataforma.md#55-requisitos-de-la-fuente-local-y-procedencia) y siguiente comprobación autorizada; distingue [disponibilidad, activación y refresco de Predicción](./manuales/manual_usuario_plataforma.md#611-disponibilidad-del-catálogo-y-activación) de inferencia comprobada.
* [`flujo_revision_audios.md`](./manuales/flujo_revision_audios.md): Validación e incorporación local de audios, sincronización recuperable con GCS y [próximos pasos del operador](./manuales/flujo_revision_audios.md#próximos-pasos-del-operador); distingue hitos aceptados de auditorías actuales.
* [`fuentes-locales-frontend.md`](./manuales/fuentes-locales-frontend.md): Montserrat y Open Sans locales para Next.js, con licencias, procedencia de WOFF2 y evidencia de build.
* [`guia_despliegue_operativo_docker.md`](./manuales/guia_despliegue_operativo_docker.md): Manual de instalación y despliegue institucional con Docker; incluye [arranque diario, reconstrucción explícita y espera de disponibilidad](./manuales/guia_despliegue_operativo_docker.md#7-puesta-en-marcha-y-scripts-de-automatización).

### 5. [`docs/limites/`](./limites/) — Límites Matemáticos y Problemas Conocidos
* [`01_solapamiento_de_clases_bioacusticas.md`](./limites/01_solapamiento_de_clases_bioacusticas.md): Análisis del solapamiento espectral y confusión entre especies hermanas.
* [`02_limites_generalizacion_universal_y_conjunto_abierto.md`](./limites/02_limites_generalizacion_universal_y_conjunto_abierto.md): Límites teóricos de la generalización a 10.000 especies y reconocimiento en conjunto abierto.
* [`03_mejoras_posibles_modelo_prediccion.md`](./limites/03_mejoras_posibles_modelo_prediccion.md): Roadmap de mejoras futuras más allá del 88.68% F1.
* [`04_limitacion_subida_directorios_completos_data_lake.md`](./limites/04_limitacion_subida_directorios_completos_data_lake.md): Limitaciones de I/O en la ingesta masiva hacia GCS.
* [`05_restriccion_formato_audio_y_captura_microfono.md`](./limites/05_restriccion_formato_audio_y_captura_microfono.md): Restricción estricta de formato PCM .wav y pipeline de captura por micrófono web.

### Evidencia operacional

* [`receipts/backend-suite-current-baseline.json`](./receipts/backend-suite-current-baseline.json): Baseline focal posterior a las limpiezas: 320 + 56 pruebas aprobadas, cinco deselecciones y probe de imports separado; comandos, hashes y límites frente a los conteos globales históricos de 12/26 fallos.

* [`receipts/lock4-incorporacion-audit.json`](./receipts/lock4-incorporacion-audit.json): Auditoría local de cinco incorporaciones de feedback, duplicados WAV y 78 pruebas aisladas de incorporación/deduplicación; límites históricos y seguimientos DATA-6/DATA-7.
* [`model14-recovery.json`](./receipts/model14-recovery.json): Identidades y resultados de limpieza, reevaluación, despliegue y verificación del modelo 14; distingue recuperación operativa de calidad del clasificador.
* [`worktree-consolidation.json`](./receipts/worktree-consolidation.json): Conteos de retirada, identidad del respaldo, comprobaciones y bloqueos de consolidación local.
* [`worktree-consolidation-final.json`](./receipts/worktree-consolidation-final.json): Cierre de los doce secundarios restantes y tres rutas de verificación; integridad de respaldos y conservación del estado de revisión.
* [`training-checks-inventory.json`](./receipts/training-checks-inventory.json): Inventario vigente de entradas protegidas por el runner aislado; independiente del baseline histórico.
* [`training-legacy-final-verification.json`](./receipts/training-legacy-final-verification.json): Verificación independiente del candidato final, incluido el retiro de orquestadores Python y reexportación: 297 pruebas aprobadas, stdout/stderr y selección aislada preservados; sin validación de servicios reales ni revisión nativa.
* [`training-legacy-independent-verification.json`](./receipts/training-legacy-independent-verification.json): Evidencia histórica del retiro inicial de CLI/entrenador legacy: 322 pruebas aprobadas; la salvedad de funciones Python todavía invocables fue resuelta posteriormente y no describe el candidato final.
* [`backend_permissions_integration.json`](./receipts/backend_permissions_integration.json): Verificación PERM-3 del servicio público de feedback en contenedor aislado; propietario y modos tras aprobaciones, reinicio y replay. Contexto mínimo, no prueba del despliegue completo ni autoridad de entrega.
* [`model-11-evaluation-migration.json`](./receipts/model-11-evaluation-migration.json): Historial inmutable de migración EVAL-6B: primera creación exitosa, segundo intento fallido y contexto de la corrección verificada.
* [`model-11-real-evaluation.json`](./receipts/model-11-real-evaluation.json): Informe inmutable de reevaluación real del modelo #11 (val/test); no certifica calidad ni autoriza activación.

### 6. [`docs/adr/`](./adr/) — Architectural Decision Records
Registro de las 25 decisiones de arquitectura fundamentales del sistema:
* [`ADR 0025`](./adr/0025-compatibilidad-semantica-evaluacion.md): Compatibilidad semántica explícita del predictor; hashes fuente diagnósticos y reevaluación obligatoria para pasar del contrato anterior.
* [`ADR 0024`](./adr/0024-entrenamiento-aislado-spawn.md): Aislamiento del entrenamiento, supervisión independiente del sondeo, conciliación de salida y límites de cancelación/persistencia.
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
* [`ADR 0023`](./adr/0023-identidad-checkpoint-cargado.md): Procedencia de carga vinculada a la instancia y bloqueo de modelos persistidos sin hash esperado; no atestación continua de tensores.
* [`ADR 0022`](./adr/0022-evaluaciones-finales-estandarizadas.md): EVAL-1 a EVAL-6B cerrados en sus alcances; #11 reevaluado en desarrollo con calidad no aprobada. No implica upgrade de tabla v1, API/browser desplegados ni aprobación/activación; backend global 12 FAIL/5 SKIP pendiente.
* [`ADR 0021`](./adr/0021-ejecucion-acotada-inferencia.md): Cupo y temporal conservados por el trabajo real del predictor tras cancelación HTTP; límites de GCS y cierre explícitos.
* [`ADR 0020`](./adr/0020-raices-fisicas-en-localizadores-publicos.md): Getters raw/processed y PathResolver conservan la escritura declarada; raíces con alias no soportadas para asociación canónica, sin validación física implícita ni migración de URIs.
