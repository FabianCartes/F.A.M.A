---
kanban-plugin: basic
kanban-source-of-truth: docs/KANBAN.md
---

## ⏳ En progreso

- [ ] **VERACIDAD — Implementado; verificación backend pendiente**<br>Historial/identidad veraces, incluida advertencia ante modelo ejecutado distinto; sin métricas/pesos/versiones sintéticos ni CPU por defecto; participantes solo con evidencia del resultado; contrato sin duración/SR supuestos; audio original canal 1 sin escaneo simulado. Frontend: 44 pruebas y lint focal PASS. Backend: corrección y pruebas escritas, runner bloqueado (`pytest` ausente). Sin navegador real/typecheck, despliegue ni commits. [[KANBAN#Veracidad de la vista de Predicción|Detalle y evidencia]]

## 🔍 En revisión / operación

- [ ] **DATASET — Despliegue y migración real**<br>Implementación y revisión cerradas; faltan migración/despliegue autorizados y comprobación en entorno real. [[KANBAN#Dataset vinculado a inferencia y validación visual|Detalle y límites]]
- [ ] **AUDIO — Verificación del flujo real de incorporación**<br>Código y revisión completados; queda validar manualmente inferencia, curación, GCS y copia local con entorno autorizado. [[KANBAN#Flujo de inferencia, validación e incorporación de audios|Detalle y límites]]
- [ ] **E2E — Evidencia automatizada del bucle**<br>Entrenamiento → inferencia → agregar al dataset operativo según el usuario. Pendiente evidencia automatizada completa hasta preparado y nuevo modelo; DATA-6 sigue abierto. No es una funcionalidad por implementar ni una ejecución E2E nueva. [[KANBAN#En Revisión / Pruebas (QA & Validation)|Criterio]]
- [ ] **TTA — Consistencia con y sin aumento en inferencia**<br>Evaluar audios con ruido de fondo variable. [[KANBAN#En Revisión / Pruebas (QA & Validation)|Criterio]]

## 📋 Pendiente

- [ ] **SUITE-3 — Ampliar baseline backend con aislamiento revisado**<br>Actual: 376 PASS focales, 5 deselecciones y payload de imports PASS aparte. Los 12/26 FAIL son antecedentes incompletos, no errores actuales confirmados. Ingestion real, spawn y módulos no revisados quedan separados. [[KANBAN#Suite backend actual y antecedentes globales — actualización del 15 de octubre de 2026|Resultados y límites]]

- [ ] **DATA-6 — Incorporar audios nuevos al preparado de entrenamiento**<br>El índice local y el preparado no coinciden; resolver regeneración/versionado y agrupación de feedback antes de afirmar que las nuevas incorporaciones entrenan el siguiente modelo. [[KANBAN#Flujo canónico de preparación y partición de datos|Hallazgos y criterios]]

- [ ] **REGIMEN-1 — Revisión completa del flujo de entrenamiento**<br>El flujo hace fine-tuning completo desde la época 1; el warmup de 3 épocas con backbone congelado que describen ADR 0001/0004/0007/0010 y `docs/modelos/05,07,09` no se ejecuta: `freeze_backbone()`/`unfreeze_backbone()` solo se invocan desde las pruebas. PANNs-CNN14 se entrena desde cero pese a la identidad AudioSet del recibo. Decidir dirección antes de corregir código o documentación. [[KANBAN#Régimen de entrenamiento y deriva entre documentación y código|Detalle, evidencia y límites]]

- [ ] **DATA-7 — Investigar duplicado exacto ajeno a feedback**<br>`Canastero/canastero_01.wav` y `Chucao/chucao_01.wav` comparten SHA-256; revisar procedencia y referencias antes de corregir. [[KANBAN#Flujo canónico de preparación y partición de datos|Detalle y límites]]

- [ ] **COLILARGA-2 — Diagnóstico del gate de ruido**<br>Requiere autorización separada: checkpoint exacto, centro y ventanas seleccionadas; bypass del filtro solo experimental, sin editar producción. El desenlace decide si el umbral está mal calibrado o si el audio no es clasificable. Calibrar con etiquetas antes de cambiar umbral. [[KANBAN#Investigación del rechazo de Colilarga|Evidencia y límites]]

- [ ] **Auditar pesos preentrenados**<br>Comprobar checkpoints reales y fallos/fallbacks de predictores. [[KANBAN#Flujo de inferencia, validación e incorporación de audios|Detalle]]
- [ ] **Validar el entorno Docker con GPU real**<br>Construcción, arranque, healthchecks y dependencias científicas. [[KANBAN#Flujo de inferencia, validación e incorporación de audios|Detalle]]
- [ ] **Cerrar documentación de tesis (OE4/OE5)**<br>Consolidar métricas y artefactos, distinguiendo accuracy de macro F1. [[KANBAN#Flujo de inferencia, validación e incorporación de audios|Detalle]]
- [ ] **Seguridad de subida de audio/WAV**<br>Validar contenido WAV real, entradas malformadas o peligrosas, saneamiento, límites de recursos y ausencia de residuos tras rechazos. [[KANBAN#Seguridad de la subida de archivos de audio|Detalle y criterios]]
- [ ] **Selector de modelos: catálogo y pesos disponibles**<br>No ofrecer modelos que no puedan ejecutar inferencia; diagnosticar API, registro y BD. [[KANBAN#Frontend & UI / UX|Detalle]]
- [ ] **Errores del frontend sin códigos HTTP visibles**<br>Explicar el resultado real, especialmente el duplicado 409 sin afirmar que el feedback finalizó. [[KANBAN#Frontend & UI / UX|Detalle]]
- [ ] **Vista de métricas de modelos**<br>Mostrar todas las métricas disponibles de los modelos. [[KANBAN#Frontend & UI / UX|Detalle]]
- [ ] **Descartar audio desde Predicción**<br>Agregar un botón para descartar el audio seleccionado en inferencia. [[KANBAN#Frontend & UI / UX|Detalle]]
- [ ] **Definir Dashboard como vista inicial**<br>[[KANBAN#Frontend & UI / UX|Detalle]]
- [ ] **Unificar icono de colapso del sidebar**<br>[[KANBAN#Frontend & UI / UX|Detalle]]
- [ ] **Hacer tablas responsive con búsqueda y paginación**<br>[[KANBAN#Frontend & UI / UX|Detalle]]
- [ ] **Añadir búsqueda al selector de modelos**<br>[[KANBAN#Frontend & UI / UX|Detalle]]
- [ ] **Habilitar visualización y composición de ensambles**<br>[[KANBAN#Frontend & UI / UX|Detalle]]
- [ ] **Completar gestión de modelos guardados**<br>Renombrar y eliminar checkpoints/modelos. [[KANBAN#Frontend & UI / UX|Detalle]]
- [ ] **Mejorar gráficos de métricas**<br>Etiquetar ejes y reducir grosor de curvas. [[KANBAN#Frontend & UI / UX|Detalle]]
- [ ] **Mejorar navegación de logs**<br>Permitir inspeccionar historial y volver al último log. [[KANBAN#Frontend & UI / UX|Detalle]]
- [ ] **Crear Centro de Conocimiento en HelpView**<br>[[KANBAN#Frontend & UI / UX|Detalle]]
- [ ] **Crear asistente para cargar datasets locales**<br>[[KANBAN#Frontend & UI / UX|Detalle]]
- [ ] **Permitir exportar modelos y bundles**<br>[[KANBAN#Frontend & UI / UX|Detalle]]
- [ ] **Auditar cobertura temporal del audio en inferencia**<br>Verificar truncamiento/relleno por predictor y definir ventanas o fragmentos, agregación y pruebas de inicio/medio/final. [[KANBAN#Backend & MLOps|Detalle y criterios]]
- [ ] **Mejorar sincronización bidireccional con GCS**<br>Chunks y sincronización delta para datasets grandes. [[KANBAN#Backend & MLOps|Detalle]]
- [ ] **Evaluar exportación ONNX/TensorRT**<br>[[KANBAN#Backend & MLOps|Detalle]]
- [ ] **Evaluar colas asíncronas para entrenamiento**<br>Celery/Redis fuera de FastAPI. [[KANBAN#Backend & MLOps|Detalle]]
- [ ] **Restringir orígenes CORS**<br>[[KANBAN#Seguridad & Hardening de Backend|Detalle]]
- [ ] **Aplicar autenticación/autorización a endpoints sensibles**<br>Revisar rutas y asignación de roles. [[KANBAN#Seguridad & Hardening de Backend|Detalle]]
- [ ] **Validar y sanear cargas de audio**<br>Tipos reales, tamaño máximo y entradas corruptas. [[KANBAN#Seguridad & Hardening de Backend|Detalle]]
- [ ] **Añadir rate limiting y endurecer secretos**<br>[[KANBAN#Seguridad & Hardening de Backend|Detalle]]
- [ ] **P2 — Resolver metadata.csv ausente en incorporación**<br>Crear índice válido o mantener la operación pendiente con error y reintento; diferido por decisión del usuario. [[KANBAN#Base de Datos & Mantenimiento|Detalle]]
- [ ] **Decidir si hace falta un registro extendido de pipeline**<br>Evaluar persistencia incremental y recuperación. [[KANBAN#Base de Datos & Mantenimiento|Detalle]]
- [ ] **Mitigar límites acústicos entre clases cercanas**<br>Evaluar calibración o thresholding adaptativo. [[KANBAN#Base de Datos & Mantenimiento|Detalle]]

## ✅ Completado

- [x] **CORRECCION-2 — Asociación nueva verificada; histórico sin conjeturas**<br>El modelo 14 registra el dataset en las predicciones nuevas. Las filas históricas sin procedencia se conservan NULL, sin backfill. [[KANBAN#Corrección de asociación de inferencia y controles compactos|Evidencia y límites]]

- [x] **LOCK-3–LOCK-4 — Conflicto histórico e incorporación local verificada**<br>Feedback 12 eliminado por limpieza, no aprobado. Cinco feedbacks locales con bytes/hash/WAV coherentes; 78 pruebas aisladas PASS. El 409 protege contra reincorporación; no acredita procedencia histórica ni inclusión en entrenamiento (DATA-6). [[KANBAN#Reparación puntual del bloqueo de aprobación feedback 12|Detalle y evidencia]]

- [x] **COLILARGA-1 — Investigación numérica del rechazo**<br>Centro de 5 s rechazado incluso sin compresión; la máscara altera continuidad (8/174 ventanas pasan sin compresión, 0/174 con tratamiento actual). No es solo volumen; sin inferencia ni validación de especie, no es un bug corregido. Experimento pendiente arriba. [[KANBAN#Investigación del rechazo de Colilarga|Detalle y evidencia]]

- [x] **MIG-1–MIG-4 — Metadatos de predicción**<br>Migración aplicada y una inferencia persistida/verificada. [[KANBAN#Migración operativa de metadatos de predicción|Detalle]]
- [x] **AVES-1–AVES-3 — Preparación de AvesChilenas**<br>Particiones publicadas y admitidas por el runtime; entrenamiento real pendiente por separado. [[KANBAN#Preparación operativa de AvesChilenas real|Detalle y límites]]
- [x] **DATA-1–DATA-5 — Preparación y partición canónica**<br>Splitter, preparación, entrenamiento/evaluación y documentación integrados. [[KANBAN#Flujo canónico de preparación y partición de datos|Detalle]]
- [x] **PERM-1–PERM-3 — Backend sin root y permisos**<br>Permisos y operación integrada verificados en el alcance registrado. [[KANBAN#Permisos del backend y ejecución sin root|Detalle y límites]]
- [x] **Nombre y fecha de carga en feedback**<br>Persistencia, API y presentación verificadas. [[KANBAN#Identificación de audios de retroalimentación por nombre original y carga|Detalle]]
- [x] **MODEL-1–MODEL-4 — Limpieza del catálogo de modelos**<br>Conservado y verificado el modelo #11; limpieza y catálogo comprobados. [[KANBAN#Limpieza de modelos experimentales — conservar #11 y ambos datasets|Detalle y límites]]
- [x] **CANON-1–CANON-6 — Referencias canónicas por etapa**<br>Productores, lectores y documentación integrados. [[KANBAN#Contrato canónico de referencias por etapa y retirada del runtime legacy|Detalle]]
- [x] **CLASE-1–CLASE-2 — Resolución de clases locales**<br>Asociaciones verificables y regresiones probadas. [[KANBAN#Resolución verificable de clases locales con catálogos mixtos|Detalle]]
- [x] **Incorporación local y sincronización GCS**<br>Cola recuperable, incorporación y controles de interfaz implementados; validación real pendiente arriba. [[KANBAN#Incorporación local de audios y sincronización recuperable con GCS|Detalle y límites]]
- [x] **MODELOS-1–MODELOS-3 — Publicación de modelos en Predicción**<br>Catálogo y refresco de UI implementados; despliegue pendiente por separado. [[KANBAN#Publicación de modelos entrenados en Predicción|Detalle y límites]]
- [x] **ENTRENAMIENTO-1–ENTRENAMIENTO-3 — Flujo verificable de entrenamiento**<br>Admisión, publicación de checkpoints y documentación completadas. [[KANBAN#Corrección verificable del flujo de entrenamiento|Detalle]]
- [x] **CORRECCION-1 y CORRECCION-3 — Controles compactos**<br>Ajuste visual verificado; la asociación funcional sigue pendiente arriba. [[KANBAN#Corrección de asociación de inferencia y controles compactos|Detalle]]
- [x] **DATASET-1–DATASET-3 — Dataset asociado a inferencia**<br>Implementación/revisión cerradas; despliegue y migración real siguen pendientes arriba. [[KANBAN#Dataset vinculado a inferencia y validación visual|Detalle y límites]]
- [x] **Flujo de inferencia y revisión de audios**<br>Implementación y revisión controlada completadas; falta la verificación operacional indicada arriba. [[KANBAN#Flujo de inferencia, validación e incorporación de audios|Detalle y límites]]
- [x] **Arquitectura & ML Core — Componentes base**<br>Ensambles, HPSS/ventaneo, Focal Loss/GeM y ADRs registrados. [[KANBAN#Arquitectura & ML Core|Detalle]]
- [x] **Backend — Componentes base**<br>FastAPI, persistencia, predictor modular y suite de tests implementados. [[KANBAN#Backend|Detalle]]
- [x] **Frontend — Componentes base**<br>SPA, dashboard, vistas operativas y curación de feedback implementados. [[KANBAN#Frontend|Detalle]]
