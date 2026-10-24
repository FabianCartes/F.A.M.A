# Centro de Documentación Técnica — F.A.M.A.

**Nodo oficial iniciado, 24 de octubre:** [catálogo, pesos y arranque](./manuales/conciliacion_catalogo_y_pesos_oficiales.md) registra decisiones aplicadas, índices/versiones conservados, cuenta histórica recuperada, comprobación del navegador y pendientes institucionales. [ADR 0050](./adr/0050-declaracion-explicita-de-ensambles-por-instalacion.md) explica la declaración persistente de ensambles. [Recibo actual](./receipts/catalogo_oficial_publicado_20261024.json) conserva evidencias; [bucket](./images/catalogo_oficial_20261024.png) e [inventario visible](./images/datasets_oficiales_20261024.png) muestran el entorno real. Los recibos anteriores mantienen sus cortes históricos.

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
├── manuales/                    # Uso, estado para retomar, revisión y despliegue
├── adr/                         # Architectural Decision Records (ADR 0001 a 0049)
├── receipts/                    # Recibos técnicos reproducibles en formato JSON (RDD)
├── duplicados-exactos/           # Tarea acotada: admisión de feedback sin duplicados SHA-256
└── images/                      # Diagramas, matrices de confusión y gráficos vectoriales
```

---

## Índice Detallado por Carpeta

**Historia oficial confirmada y pesos preparados, 24 de octubre:** [conciliacion_catalogo_y_pesos_oficiales.md](./manuales/conciliacion_catalogo_y_pesos_oficiales.md) reúne comparación SQL, runtime, corrección de formato histórico, propuesta para cinco versiones de audio, respaldo posterior recuperado y decisiones pendientes. [traslado_historia_confirmado_y_pesos_20261024.json](./receipts/traslado_historia_confirmado_y_pesos_20261024.json) conserva evidencia y límites de pruebas. El perfil oficial permanece sin activar; los siguientes recibos conservan los cortes anteriores.


**Esquema oficial confirmado, 24 de octubre:** [esquema_oficial_y_traslado_preparado_20261024.json](./receipts/esquema_oficial_y_traslado_preparado_20261024.json) registra la ejecución del operador y la comprobación independiente del esquema real vacío, SQL/GCS y permisos. El [comando de copia de historia](./manuales/traslado_historia_y_adopcion.md#paso-inmediato-copiar-la-historia-al-esquema-oficial) pide el secreto del migrador únicamente en el terminal y compara con la huella del respaldo recuperado. Historia, conciliación de archivos y activación real siguen pendientes. Los recibos anteriores conservan sus cortes.

**Traslado de historia preparado, 24 de octubre:** [traslado_historia_y_adopcion.md](./manuales/traslado_historia_y_adopcion.md) explica la copia transaccional, adopción reanudable y comando inmediato del esquema oficial. [ADR 0049](./adr/0049-traslado-explicito-de-historia-y-adopcion-de-cuenta.md) registra la separación respecto del alta inicial y el tratamiento de historia/permisos. [traslado_historia_preparado_20261024.json](./receipts/traslado_historia_preparado_20261024.json) conserva pruebas, ensayo con respaldo real y límites. Aplicación remota y corte pendientes.

**Acceso SQL e identidad oficial, 24 de octubre:** [identidad_tecnica_oficial.md](./manuales/identidad_tecnica_oficial.md) documenta IAM/ADC, proxy y perfil ya comprobados. [respaldo_historico_postgresql18.md](./manuales/respaldo_historico_postgresql18.md) explica respaldo/recuperación de la base local no versionada y sus límites antes del traslado. [perfil_oficial_y_respaldo_historico_20261024.json](./receipts/perfil_oficial_y_respaldo_historico_20261024.json) registra conexiones, corrección DACL con 13 pruebas y recuperación PostgreSQL 18. Cortes previos: [ADC/proxy](./receipts/identidad_oficial_adc_proxy_20261024.json), [IAM](./receipts/identidad_oficial_iam_20261024.json), [acceso SQL](./receipts/acceso_sql_oficial_confirmado_20261024.json).

**Comprobación SQL oficial preparada, 24 de octubre:** [comprobacion_sql_oficial_preparada_20261024.json](./receipts/comprobacion_sql_oficial_preparada_20261024.json) registra confirmación humana de contraseñas asignadas, proxy cotejado y comprobador de logins/privilegios de solo lectura con 22 pruebas PostgreSQL aprobadas. [Comando para el operador](./manuales/preparacion_entorno_oficial.md#siguiente-paso-comprobar-acceso-desde-este-pc).

**Roles oficiales confirmados por el operador, 24 de octubre:** [roles_oficiales_operador_20261024.json](./receipts/roles_oficiales_operador_20261024.json) distingue ejecución SQL y resultado informados, presencia de usuarios observada por API y contraseñas/logins todavía pendientes. [Siguiente paso](./manuales/preparacion_entorno_oficial.md#siguiente-paso-asignar-contraseñas-sql).

**Seguimiento del selector oficial, 24 de octubre:** [seleccion_base_oficial_20261024.json](./receipts/seleccion_base_oficial_20261024.json) registra el reporte de consola y la nueva confirmación de existencia de `fama_oficial` por Cloud SQL; roles y conexión del operador pendientes.

**Preparación oficial en curso (23 de octubre):** uso inicial en este PC y posterior traslado universitario; inventario, diferencias y pasos en [preparacion_entorno_oficial.md](./manuales/preparacion_entorno_oficial.md). Base `fama_oficial` creada en la instancia elegida; [script de roles](../backend/scripts/preparar_roles_oficial.sql) preparado y probado, pendiente de ejecución remota. [Recibo](./receipts/preparacion_oficial_inventario_20261023.json). El perfil oficial todavía no se ha creado ni activado.

**Para retomar el proyecto:** [`manuales/estado_actual_y_pendientes.md`](./manuales/estado_actual_y_pendientes.md) separa correcciones, pendientes, acceso web y administración visual, benchmark CPU autorizado y comprobaciones SQL/GCS de pruebas. El asistente está implementado y probado de forma aislada; siguen la instalación real conjunta y la operación institucional (corte del 22 de octubre de 2026).

### Tarea acotada: duplicados exactos
* [`docs/duplicados-exactos/tasks.md`](./duplicados-exactos/tasks.md): Alcance, decisiones locales, checklist y evidencia TDD de aprobación de feedback sin duplicados SHA-256; revisión y commit pendientes del orquestador.

### 1. [`docs/tesis/`](./tesis/) — Tesis y Objetivos de Grado
* [`VIDA_01_CINF_FINAL_PT_2026_1_CARTES.md`](./tesis/VIDA_01_CINF_FINAL_PT_2026_1_CARTES.md) / [`.pdf`](./tesis/VIDA_01_CINF_FINAL_PT_2026_1_CARTES.pdf): Memoria formal de proyecto de título.
* [`analisis_objetivos_fama.md`](./tesis/analisis_objetivos_fama.md): Matriz de objetivos/RF/RNF con actualización acotada del 15 de octubre de 2026; distingue correcciones comprobadas, antecedentes históricos y objetivos operativos aún no acreditados.

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
* [`benchmark_local_cpu_20261016.md`](./modelos/benchmark_local_cpu_20261016.md): Mediciones reales CPU autorizadas de un audio/checkpoint; fallos de compatibilidad conservados, preprocesamiento medido y predictor detenido por filtro de ruido, sin acreditar forward, latencia hasta pantalla ni 50 GB.

### 3. [`docs/arquitectura/`](./arquitectura/) — Arquitectura de Software y MLOps
* [`CONTEXT.md`](./arquitectura/CONTEXT.md): Glosario de catálogo, disponibilidad/activación, inferencia/confianza, alta de administrador, metadatos y referencias experimentales históricas.
* [`03_orquestador_fastapi_gcs_postgresql.md`](./arquitectura/03_orquestador_fastapi_gcs_postgresql.md): Arquitectura del orquestador backend con FastAPI.
* [`04_saneamiento_y_transcodificacion_audio.md`](./arquitectura/04_saneamiento_y_transcodificacion_audio.md): Pipeline de saneamiento y normalización de audio crudo.
* [`18_soporte_multimodelo_backend_rdd.md`](./arquitectura/18_soporte_multimodelo_backend_rdd.md): Desacoplamiento de inferencia con Patrón Strategy y ModelRegistry.
* [`19_subsistema_entrenamiento_modular_rdd.md`](./arquitectura/19_subsistema_entrenamiento_modular_rdd.md): Subsistema modular de recetas YAML y exportación de bundles.
* [`20_modelo_de_producto_despliegue_y_arquitectura_operativa.md`](./arquitectura/20_modelo_de_producto_despliegue_y_arquitectura_operativa.md): Estrategia de producto on-premise, concurrencia y contenedores Docker.
* [`21_resumen_actualizacion_remota_y_nuevas_capacidades.md`](./arquitectura/21_resumen_actualizacion_remota_y_nuevas_capacidades.md): Resumen de integración remota y resolución de conflictos.
* [`22_arquitectura_universal_multidominio_y_limites_acusticos.md`](./arquitectura/22_arquitectura_universal_multidominio_y_limites_acusticos.md): Especificación de F.A.M.A. como motor No-Code para cualquier dataset y límites físicos/computacionales.
* [`22_propuesta_vista_ayuda_y_centro_de_conocimiento.md`](./arquitectura/22_propuesta_vista_ayuda_y_centro_de_conocimiento.md): Diseño y especificación del centro de conocimiento e interactividad en frontend.

### 4. [`docs/manuales/`](./manuales/) — Manuales y Guías Operativas
* [`bitacora_acceso_e_instalacion.md`](./manuales/bitacora_acceso_e_instalacion.md): Registro vivo del trabajo del operador y Codex: acceso/administración, preparación GCP y etapas 1–8, con evidencia, límites y siguiente paso. Se actualiza durante el recorrido guiado.
* [`preparacion_instalacion_y_migraciones.md`](./manuales/preparacion_instalacion_y_migraciones.md): Etapa 1; configuración persistente del servidor, entrada previa a SQL/ML, CLI Alembic explícita y validación aislada con PostgreSQL.
* [`usuarios_postgresql_pruebas.md`](./manuales/usuarios_postgresql_pruebas.md): Etapa 4; creación atómica de usuarios SQL separados para migración y aplicación, contraseñas mediante consola y cuatro comprobaciones locales de permisos/preservación.
* [`conexiones_cloud_sql_y_gcs.md`](./manuales/conexiones_cloud_sql_y_gcs.md): Etapa 5; configuración privada y conexiones SQL/GCS reales comprobadas desde Windows/Docker, alcance de las 50 pruebas y comando del operador para iniciar las migraciones de etapa 6.
* [`permisos_aplicacion_postgresql.md`](./manuales/permisos_aplicacion_postgresql.md): Etapa 6; permisos DML, versión en solo lectura, secuencias y comando del operador; comprobación real de esquema, transacciones SQL, objeto GCS y entrada ASGI todavía pendiente de asistente.
* [`asistente_primera_instalacion.md`](./manuales/asistente_primera_instalacion.md): Etapa 7; autorización temporal del operador, formularios, comprobaciones, primer administrador, cierre y reanudación. Pruebas y recorrido visual sintéticos; instalación real pendiente de etapa 8.
* [`plan_instalacion_gcp_y_asistente.md`](./manuales/plan_instalacion_gcp_y_asistente.md): Plan ordenado de preparación de Cloud SQL/GCS, configuración, migraciones y asistente inicial; responsabilidades del operador y desarrollo, criterios de cierre y puesta en servicio.
* [`administracion_visual.md`](./manuales/administracion_visual.md): Mi cuenta y administración de cuentas, asignaciones, recuperación, auditoría y limpieza; lectura paginada de IDs persistidos y límites de verificación aislada.
* [`plan_autonomia_investigador_y_catalogo.md`](./manuales/plan_autonomia_investigador_y_catalogo.md): Política aceptada, orden de implementación y avance; distingue código verificado de activación remota pendiente.
* [`autonomia_y_solicitudes_datasets.md`](./manuales/autonomia_y_solicitudes_datasets.md): Uso del inventario, subida, incorporación autónoma, catálogo y decisiones de acceso; actualización controlada `0003_autonomy`, capturas sintéticas y siguiente paso del operador.
* [`acceso_web_y_sliced_waves.md`](./manuales/acceso_web_y_sliced_waves.md): Login centrado, cookie de mismo origen, navegación protegida, recuperación por fragmento y SlicedWaves; pruebas simuladas y preparación manual todavía pendiente.
* [`auditoria_y_limpieza_seguridad.md`](./manuales/auditoria_y_limpieza_seguridad.md): Eventos mínimos de seguridad, lectura administrativa por cursor y limpieza transaccional por lotes con retención configurable; sin ejecución sobre BD real ni scheduler.
* [`limites_login_y_recuperacion.md`](./manuales/limites_login_y_recuperacion.md): Cuotas persistentes de admisión, clave HMAC/configuración, 429/Retry-After y límites de proxy/producción; sin configurar servicios reales.
* [`gestion_cuentas_y_recuperacion.md`](./manuales/gestion_cuentas_y_recuperacion.md): Contratos backend de cuentas, revocación, último administrador y recuperación administrada de un solo uso; remite a la interfaz vigente, sin envío real de correo.
* [`permisos_recursos_asignados.md`](./manuales/permisos_recursos_asignados.md): Asignaciones por administrador, política HTTP de recursos/trabajos, tratamiento conservador de historia sin asociación y límites previos al despliegue.
* [`sesiones_web_y_acceso_administrado.md`](./manuales/sesiones_web_y_acceso_administrado.md): Primer bloque backend de sesiones cookie revocables y registro exclusivo de administradores; configuración, evidencia aislada y permisos/UI/Cloud SQL todavía pendientes.
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

### Evidencia de instalación local
* [`instalacion_etapa1_postgresql_20261021.json`](./receipts/instalacion_etapa1_postgresql_20261021.json): Etapa 1 con PostgreSQL 16.15 efímero; migraciones, permisos, arranque y acceso web aislados, 34 pruebas finales y 149 de regresión; sin servicios GCP ni artefactos reales.
* [`instalacion_etapa4_roles_20261022.json`](./receipts/instalacion_etapa4_roles_20261022.json): Etapa 4; cuatro pruebas locales del script SQL, consultas GCP de lectura, usuarios remotos creados por el operador y login SQL de ambos desde el PC confirmado mediante captura del terminal.
* [`instalacion_etapa5_conexiones_20261022.json`](./receipts/instalacion_etapa5_conexiones_20261022.json): Etapa 5; 50 pruebas previas y diagnóstico nativo/Linux contra Cloud SQL y GCS reales con la configuración privada de aplicación. Evidencia previa a la migración de etapa 6 y limpieza de recursos Docker temporales.
* [`instalacion_etapa6_permisos_20261022.json`](./receipts/instalacion_etapa6_permisos_20261022.json): Etapa 6 verificada en los recursos de pruebas; regresión local previa de 25 casos y comprobaciones reales de esquema/permisos, CRUD/reversión/persistencia SQL, objeto GCS y limpieza. El asistente y stack completo siguen pendientes.
* [`instalacion_etapa7_asistente_20261022.json`](./receipts/instalacion_etapa7_asistente_20261022.json): Implementación del asistente con regresiones HTTP/CLI/formularios y recorrido visual sobre PostgreSQL desechable/GCS simulado; hashes y limpieza. La instalación remota real permanece pendiente.
* [`instalacion_etapa8_validacion_20261022.json`](./receipts/instalacion_etapa8_validacion_20261022.json): Recibo vivo de instalación real, acceso, recuperación y autonomía. Recorrido acotado investigador verificado hasta incorporación SQL/GCS; conserva los cortes anteriores y los límites pendientes de etapa 8, sin secretos.
* [`autonomia_datasets_implementacion_20261022.json`](./receipts/autonomia_datasets_implementacion_20261022.json): Recibo vivo de la implementación de autonomía: inventario/acciones, subida, incorporación y solicitudes; distingue pruebas aisladas de actualización del entorno real.
* [`recuperacion_admin_operador_20261023.json`](./receipts/recuperacion_admin_operador_20261023.json): Restablecimiento puntual autorizado por el operador de su cuenta administradora; contraseña verificada, sesión previa revocada y auditoría confirmada, sin registrar secretos.
* [`limite_login_120s_20261023.json`](./receipts/limite_login_120s_20261023.json): Ventana de login de 120 segundos: TDD, regresión aislada y activación real comprobadas tras migración y reinicio; conserva el corte inicial y la evidencia posterior.
* [`autonomia_activacion_real_20261023.json`](./receipts/autonomia_activacion_real_20261023.json): Migración del operador, permisos y procesos actualizados, sesión e interfaz reales, plazo de login activo y carga verificada de diez audios; conserva E8-04 y pendientes del recorrido investigador.
* [`autonomia_muestra_aves_20261023.json`](./receipts/autonomia_muestra_aves_20261023.json): Procedencia, clase, tamaño y SHA-256 de los diez audios elegidos para el dataset separado de pruebas; preservación de los originales y alcance funcional.
* [`autonomia_particiones_muestra_20261023.json`](./receipts/autonomia_particiones_muestra_20261023.json): Diez copias y tensores verificados; ocho audios de train y dos de validación, sin afirmación de independencia por grabador ni calidad científica.
* [`autonomia_recorrido_investigador_20261023.json`](./receipts/autonomia_recorrido_investigador_20261023.json): Recorrido real acotado de investigador, modelo, corrección e incorporación propia, once audios SQL/GCS, hashes, autoría, entorno aislado y límites.
* [`autonomia_entrenamiento_real_20261023.png`](./images/autonomia_entrenamiento_real_20261023.png) y [`autonomia_incorporacion_real_20261023.png`](./images/autonomia_incorporacion_real_20261023.png): Evidencia visual del entrenamiento funcional y de PostgreSQL/autoría/copia cloud confirmados. No representan calidad del modelo ni despliegue institucional.
* [`autonomia_historial_real_20261023.png`](./images/autonomia_historial_real_20261023.png): Historial con el nombre SQL de `FAMA_Prueba_Aves`, una época y el modelo propio guardado.
* [`instalacion_etapa7_comprobaciones_20261022.png`](./images/instalacion_etapa7_comprobaciones_20261022.png) y [`instalacion_etapa7_finalizada_20261022.png`](./images/instalacion_etapa7_finalizada_20261022.png): Capturas del recorrido sintético en navegador; no representan la configuración real del proyecto GCP.

### Evidencia de benchmark local controlado
* [`benchmark_local_cpu_20261015.json`](./receipts/benchmark_local_cpu_20261015.json): Intento inicial: preprocesamiento real medido, fallo de carga de pesos conservado.
* [`benchmark_local_cpu_inference_20261016.json`](./receipts/benchmark_local_cpu_inference_20261016.json): Repetición autorizada, mismo fallo de carga; no latencia de inferencia válida.
* [`checkpoint_compatibility_metadata_20261016.json`](./receipts/checkpoint_compatibility_metadata_20261016.json): Diagnóstico restringido de metadatos/tensores del único checkpoint autorizado; no benchmark.
* [`benchmark_local_cpu_inference_validated_20261016.json`](./receipts/benchmark_local_cpu_inference_validated_20261016.json): Carga corregida y ruta del predictor medida con filtro noise; no forward neuronal ni medición navegador/API.

### 6. [`docs/adr/`](./adr/) — Architectural Decision Records
Registro de las 43 decisiones de arquitectura fundamentales del sistema:
* [`ADR 0043`](./adr/0043-autonomia-investigadora-en-datasets-asignados.md): Autonomía completa del investigador en datasets asignados, incorporación humana sin permiso de curador adicional y solicitudes de acceso resueltas por administración.
* [`ADR 0042`](./adr/0042-autorizacion-y-finalizacion-reanudable-de-instalacion.md): Autorización inicial vinculada al nodo/origen y finalización reanudable con intención privada y bloqueo SQL, sin adoptar cuentas existentes.
* [`ADR 0040`](./adr/0040-configuracion-persistente-y-migraciones-explicitas.md): Estado de instalación independiente de disponibilidad, arranque ligero y migraciones privilegiadas explícitas con esquema congelado.
* [`ADR 0041`](./adr/0041-conexiones-cloud-explicitas-mediante-proxy.md): Conexión mediante proxy externo, selección explícita sin heredar la base local y diagnóstico de lectura independiente del esquema/finalización.
* [`ADR 0039`](./adr/0039-acceso-web-del-mismo-origen-y-fondo-aislado.md): Interfaz de acceso sin segundo sistema de identidad, confirmación de cookie, invalidación de vistas y fondo gráfico aislado del trabajo.
* [`ADR 0038`](./adr/0038-auditoria-minima-y-limpieza-transaccional-acotada.md): Auditoría de vocabulario cerrado vinculada a la transacción y limpieza explícita de expirados con revalidación de vigencia.
* [`ADR 0037`](./adr/0037-cuotas-persistentes-de-login-y-recuperacion.md): Presupuestos de admisión persistidos, reserva atómica multicuota y seudonimización HMAC, frente a límites en memoria o un servicio adicional.
* [`ADR 0036`](./adr/0036-gestion-de-cuentas-y-recuperacion-administrada.md): Mutaciones transaccionales de cuentas, protección concurrente del último administrador y recuperación administrada sin SMTP supuesto.
* [`ADR 0035`](./adr/0035-asignaciones-explicitas-y-propiedad-de-entrenamiento.md): Asignaciones explícitas, procedencia autorizante y propiedad de trabajos; activación administrativa separada y restricciones de historia desconocida.
* [`ADR 0034`](./adr/0034-sesiones-web-revocables-y-registro-administrado.md): Sesiones web revocables frente a JWT en navegador; alta administrada y transición parcial sin declarar cerrado el acceso global.
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
* [`ADR 0021`](./adr/0021-preprocesamiento-efectivo-en-checkpoints.md): Configuración acústica efectiva y perfil versionado en checkpoints web; inferencia coherente para nuevos artefactos y compatibilidad legacy explícita, sin reinterpretación de pesos históricos.
* [`ADR 0022`](./adr/0022-ficha-tecnica-sin-valores-inventados.md): Ficha técnica con metadatos explícitos del checkpoint, lectura mapeada y valores desconocidos sin presets fabricados; contrato backend/cliente/UI sin migraciones ni certificación de inferencia.
* [`ADR 0023`](./adr/0023-seleccion-con-pesos-confirmados.md): Entradas indisponibles visibles/deshabilitadas, selección con pesos confirmados y preflight HTTP antes de GCS; no cambia la política de inclusión ni certifica inferencia.
* [`ADR 0024`](./adr/0024-configuracion-explicita-de-autenticacion.md): Clave JWT y alta inicial sin defaults, indisponibilidad explícita y preservación de cuentas; política de creación por administradores acordada pero aún pendiente de aplicación.
* [`ADR 0025`](./adr/0025-configuracion-runtime-y-contexto-sin-credenciales.md): Configuración existente transmitida por Compose y JSON externos excluidos del contexto backend; prueba con cliente Docker/API simulada, sin imágenes ni servicios reales.
* [`ADR 0026`](./adr/0026-sincronizacion-por-contenido-y-publicacion-local.md): Sincronización por MD5/CRC32C, staging local y registros de transferencias aceptadas por URI completa; preservación previa y límites de atomicidad.
* [`ADR 0027`](./adr/0027-rutas-portables-y-confinadas-en-descarga.md): Componentes portables, jerarquía y confinamiento en descarga; extensión a nombres de subida y HTTP 422 sanitizado; límites de concurrencia y atomicidad de lotes.
* [`ADR 0028`](./adr/0028-resultados-parciales-en-subida-de-audios.md): Subida continúa por archivo y registra solo transferencias confirmadas; subida/sync distinguen completed/partial/failed y la UI informa fallos de etapa; sin rollback cloud ni atomicidad.
* [`ADR 0029`](./adr/0029-metadatos-acusticos-observados-y-lectura-registrada.md): Ingesta registra frecuencia/duración de cabecera o null, sin defaults ficticios; inspector existente devuelve metadatos registrados por URI, no certificación del objeto actual.
* [`ADR 0030`](./adr/0030-cargas-acusticas-validadas-y-acotadas.md): Subida valida WAV/MP3/FLAC/OGG por decodificación en bloques y limita contenidos a 64 MiB/archivo y 256 MiB/lote configurables; no acredita RNF de 50 GB ni protección integral de recepción.
* [`ADR 0031`](./adr/0031-dashboard-con-observaciones-y-origen-explicito.md): Dashboard sin métricas/eventos ficticios, origen en último modelo registrado, desconocidos explícitos y referencias históricas separadas; GET sin cargar checkpoints ni alterar activación.
* [`ADR 0032`](./adr/0032-compatibilidad-explicita-de-checkpoints-poc.md): Predictor respeta pooling declarado, formato PoC model_type/avg y bandas Mel explícitas, preservando carga estricta y default del formato actual; sin reescribir artefactos.
* [`ADR 0033`](./adr/0033-estado-legacy-pasivo-y-ejecucion-atribuida.md): GET model-info observa registro/archivo/carga sin deserializar; ámbitos legacy diferenciados, métricas con origen y predicción atribuida al predictor invocado, sin activar ni fabricar componentes.

## Refinamiento de clases y Dashboard — 23 de octubre

* [`clases_de_audio_y_dashboard.md`](./manuales/clases_de_audio_y_dashboard.md): Uso del selector de clases, primera clase/nueva categoría, carga de métricas y gráfico con cero/una/varias épocas; variantes históricas y límites.
* [`validacion_mp3_y_curvas_entrenamiento.md`](./manuales/validacion_mp3_y_curvas_entrenamiento.md): Corrección de longitudes MP3 estimadas y total de épocas individual; reproducción, activación local y orden previo al corte oficial.
* [`mp3_y_curvas_entrenamiento_20261023.json`](./receipts/mp3_y_curvas_entrenamiento_20261023.json): Ciclos RED/GREEN, regresión de ingesta/gráficos, conservación de cinco originales y disponibilidad del runtime de pruebas.
* [`subida_clases_y_dashboard_20261023.json`](./receipts/subida_clases_y_dashboard_20261023.json): TDD, regresión focal, validación de tipos/lint, actualización de la copia frontend y observaciones reales sin aportes nuevos ni cambios backend.
* [`subida_selector_clases_20261023.png`](./images/subida_selector_clases_20261023.png) y [`dashboard_una_epoca_20261023.png`](./images/dashboard_una_epoca_20261023.png): Evidencia de selección de clase y del modelo real con una época visible.

## Particiones versionadas — 23 de octubre

* [`particiones_versionadas.md`](./manuales/particiones_versionadas.md): preparar, revisar y seleccionar versiones train/validación; procedencia, archivos excluidos, CSV históricos y límites operativos.
* [`ADR 0044`](./adr/0044-particiones-explicitas-y-manifiestos-inmutables.md): selección explícita, agrupación por procedencia y manifiestos locales inmutables conservados en checkpoints.
* [`particiones_versionadas_20261023.json`](./receipts/particiones_versionadas_20261023.json): TDD, regresión, publicación real de prueba, preservación de archivos/modelo y alcance sin escrituras GCS.
* [`particiones_versionadas_20261023.png`](./images/particiones_versionadas_20261023.png): versión de ocho audios de entrenamiento y dos de validación guardada y seleccionada en el navegador real.

## Respaldo y recuperación de checkpoints — 23 de octubre

* [`respaldo_y_recuperacion_checkpoints.md`](./manuales/respaldo_y_recuperacion_checkpoints.md): operaciones desde la ficha técnica, estados local/cloud, comprobación de bytes, conflictos y límites de recuperación.
* [`ADR 0045`](./adr/0045-respaldo-explicito-de-checkpoints-por-contenido.md): respaldo explícito por contenido, generaciones cloud y publicación local sin reemplazo, conservando la identidad SQL.
* [`respaldo_checkpoints_20261023.json`](./receipts/respaldo_checkpoints_20261023.json): TDD, regresión, respaldo real en `fama-pruebas` y recuperación verificada en un directorio separado, con diecisiete archivos originales intactos.
* [`respaldo_checkpoint_real_20261023.png`](./images/respaldo_checkpoint_real_20261023.png): ficha del modelo de prueba con respaldo confirmado por tamaño y SHA-256.

## Almacenamiento persistente por entorno — 23 de octubre

* [`directorios_persistentes_por_entorno.md`](./manuales/directorios_persistentes_por_entorno.md): perfil, estructura, CLI, lanzador nativo, traslado conservador, configuración Compose y límites operativos.
* [`ADR 0046`](./adr/0046-almacenamiento-persistente-vinculado-al-entorno.md): raíz vinculada al destino configurado, propiedad local exclusiva y resolución de archivos independiente del código.
* [`directorios_persistentes_20261023.json`](./receipts/directorios_persistentes_20261023.json): TDD, regresión y traslado real de 29 archivos con preservación de SQL, partición y checkpoint.
* [`runtime_persistente_pruebas_20261023.png`](./images/runtime_persistente_pruebas_20261023.png): copia local íntegra y respaldo disponible después del arranque desde el repositorio original.

## Respaldo y restauración PostgreSQL — 23 de octubre

* [`respaldo_y_restauracion_postgresql.md`](./manuales/respaldo_y_restauracion_postgresql.md): CLI, carpeta privada, instantánea, rechazo de destinos ocupados, permisos técnicos y límites de recuperación.
* [`ADR 0047`](./adr/0047-respaldo-logico-y-restauracion-sql-separada.md): archivo lógico verificable y restauración separada, sin adoptar automáticamente propietarios ni ACL del origen.
* [`respaldo_postgresql_20261023.json`](./receipts/respaldo_postgresql_20261023.json): TDD, regresión y copia real de `fama_pruebas` recuperada en PostgreSQL 16 local, con estado y archivos del origen conservados.

## Recuperación de emergencia del administrador — 23 de octubre

* [`recuperacion_emergencia_administrador.md`](./manuales/recuperacion_emergencia_administrador.md): inspección por ID/correo, confirmaciones, contraseña oculta, reactivación explícita, revocaciones y auditoría; autoridad local y límites.
* [`ADR 0048`](./adr/0048-recuperacion-local-de-administradores-existentes.md): recuperación del operador separada de una sesión web, transacción compartida y preservación del rol existente.
* [`recuperacion_emergencia_20261023.json`](./receipts/recuperacion_emergencia_20261023.json): pruebas PostgreSQL/CLI/HTTP, interfaz de auditoría e inspección real de solo lectura, sin cambiar la contraseña vigente.
