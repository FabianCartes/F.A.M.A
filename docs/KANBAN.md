# Tablero Kanban - Proyecto F.A.M.A

Tablero de seguimiento del ciclo de vida del proyecto **F.A.M.A** (*Flujo de Clasificación de Audio y Machine-learning Avanzado*). Diseñado para coordinar tareas entre el equipo de desarrollo, investigación y agentes.

**Revisión documental: 2 de octubre de 2026.** Las tareas completadas indican implementación presente, no validación integral del despliegue. Los recibos aportan evidencia histórica de alcance específico; no se ejecutaron pruebas ni Docker durante esta revisión. El estado y sus límites se detallan en [análisis de objetivos](tesis/analisis_objetivos_fama.md).

---

## ⏳ En Progreso (In Progress)

- [ ] **Auditoría y Aprovisionamiento de Pesos Preentrenados:** Verificar checkpoints reales (`.pt`/`.pth`) en el entorno local/contenedor y el comportamiento de cada predictor ante pesos ausentes o fallos de carga/inferencia. `EngineEnsemblePredictor` conserva ramas `mock_fallback`; HTTP 503 ante `ModelWeightsError` no cubre todos los casos. El [recibo de inferencia](receipts/fase_inferencia_real_receipt.json) acredita un caso histórico, no la disponibilidad de todos los pesos.
- [ ] **Consistencia de Entorno Docker:** Validar construcción, arranque, healthchecks y ejecución integral del stack con dependencias científicas (`torch`, `torchaudio`, `librosa`) y GPU NVIDIA real. Compose/Dockerfiles están implementados; el [recibo de operación Docker](receipts/fase1_operacion_red_docker_receipt.json) no acredita la ejecución completa con GPU.
- [ ] **Documentación de Tesis (OE4 / OE5):** Completar redacción final y consolidar métricas con sus artefactos experimentales, distinguiendo 88.31% accuracy de 88.68% macro F1. Manuales, ADRs y recibos existentes no equivalen al cierre de la tesis.

---

## 📋 Backlog (Pendientes y Próximas Mejoras)

### Frontend & UI / UX
- [ ] **Ruta Inicial Predeterminada:** Configurar `DashboardView` como la vista inicial por defecto al abrir la aplicación.
- [ ] **Consistencia de Sidebar:** Unificar el icono para colapsar/compactar la barra lateral en escritorio con el utilizado en la versión mobile.
- [ ] **Tablas Responsive, Búsqueda y Paginación:**
  - Optimizar el diseño de todas las tablas para adaptabilidad móvil/responsive.
  - Implementar paginación en tablas de datos.
  - Integrar barra de búsqueda y filtrado en tablas.
- [ ] **Buscador en Selector de Modelos (`PredictionView.tsx`):** Añadir barra de búsqueda predictiva en la barra/selector de modelos para inferencia.
- [ ] **Visualización de Ensambles (`TrainingView.tsx`):** Corregir y habilitar la visualización y composición de los ensambles en la vista de entrenamiento.
- [ ] **Gestión de Modelos Guardados (`TrainingView.tsx`):** Incorporar acciones completas para renombrar y eliminar checkpoints/modelos en la lista existente.
- [ ] **Ajustes en Gráficos de Métricas de Entrenamiento:**
  - Agregar etiquetas claras a los ejes X (Épocas / Steps) e Y (Pérdida / Precisión).
  - Reducir el grosor de las líneas de curvas para mejorar legibilidad técnica.
- [ ] **Control de Navegación de Logs en Ejecución:**
  - Permitir scroll libre hacia arriba para inspeccionar logs anteriores sin forzar auto-scroll.
  - Agregar botón de anclaje rápido ("scroll to bottom") para descender al último log recibido.
- [ ] **Implementar Centro de Conocimiento e interactividad (`HelpView.tsx`):** Crear la vista de ayuda propuesta en [`arquitectura/22_propuesta_vista_ayuda_y_centro_de_conocimiento.md`](file:///home/kevin/Work/fama/docs/arquitectura/22_propuesta_vista_ayuda_y_centro_de_conocimiento.md) con guías teóricas, conceptos de espectrogramas/HPSS y manuales de usuario integrados.
- [ ] **Asistente de Carga de Datasets Locales:** Construir un asistente (wizard/drag & drop) en `IngestionView.tsx` para subir lotes de audio crudo y estructurarlos automáticamente en clases para entrenamiento.
- [ ] **Exportación de Modelos:** Añadir descarga directa de artefactos compilados (`.pth`, bundles de inferencia) desde el historial de modelos.

### Backend & MLOps
- [ ] **Sincronización Bidireccional Robusta con GCS:** Optimizar la descarga por chunks y sincronización delta entre Google Cloud Storage y almacenamiento local para datasets de gran tamaño (>10 GB).
- [ ] **Exportación ONNX / TensorRT:** Evaluar exportación de modelos del ensamble a formatos optimizados para inferencia de baja latencia en entornos edge.
- [ ] **Gestión de Nodos y Colas Asíncronas (Celery / Redis):** Desacoplar entrenamientos masivos de larga duración a trabajadores independientes fuera del proceso FastAPI.

### Seguridad & Hardening de Backend
- [ ] **Restricción de Orígenes CORS:** Reemplazar el wildcard abierto (`allow_origins=["*"]`) por los dominios estrictos permitidos en producción/desarrollo.
- [ ] **Protección y Autenticación en Endpoints Sensibles:** Aplicar autenticación y autorización por roles a las rutas de entrenamiento, ingesta, feedback y acciones de modificación/eliminación; revisar también la política de registro y asignación de roles. JWT y `require_roles` existen, pero las rutas sensibles examinadas en `backend/app/main.py` no aplican esas dependencias.
- [ ] **Validación Estricta y Sanitización de Cargas de Audio:** Validar tipos MIME reales y límite máximo de tamaño de archivo (evitar DoS por carga de archivos gigantes o corrompidos).
- [ ] **Rate Limiting y Manejo Seguro de Secretos:** Implementar limitador de peticiones en rutas críticas y eliminar o bloquear valores de secretos predeterminados en entornos expuestos; existen valores de respaldo en autenticación JWT y Compose.

### Base de Datos & Mantenimiento
- [ ] **Registro Extendido de Pipeline (Condicional):** Decidir si se requiere una entidad independiente `registro_pipeline` y persistencia incremental/recuperación ante interrupciones. `MetricaEntrenamiento` y el guardado de métricas por época ya están implementados: el worker las inserta al finalizar cada modelo y hace un commit, no en cada época; los fallos de base de datos se registran con rollback y advertencia ([training.py](../backend/app/services/training.py)).
- [ ] **Mitigación de Límites Acústicos (Límite 01):** Evaluar técnicas de post-calibración o thresholding adaptativo para reducir la confusión en clases filogenéticamente cercanas (Tijeral vs Canastero, Chucao vs Turca).

---

## 🔍 En Revisión / Pruebas (QA & Validation)

- [ ] **Pruebas E2E del Bucle de Retroalimentación (*Human-in-the-Loop*):** Validar `PredictionView` ➡️ `POST /api/feedback` ➡️ `IngestionView` (curación) ➡️ muestra disponible en el dataset ➡️ entrenamiento ➡️ nuevo checkpoint/modelo. El [recibo RF06](receipts/fase_rf06_feedback_curation_receipt.json) documenta captura y curación, no esa cadena completa; aprobar una muestra no dispara automáticamente el entrenamiento.
- [ ] **Validación de Test-Time Augmentation (TTA):** Pruebas de consistencia de predicción con y sin TTA en audios con ruido de fondo variable.

---

## ✅ Completado (Done)

### Arquitectura & ML Core
- [x] **Super-Ensamble Tri-Modelo Heterogéneo:** Integración y calibración de pesos (EfficientNet-B0 55%, ConvNeXt-Nano 30%, ResNet-34d 15%).
- [x] **Pipeline de Audio Frontend HPSS:** Separación armónica-percusiva y ventaneo denso implementados en GPU/CPU.
- [x] **Pérdida Focal y GeM Pooling:** Implementación de Generalized Mean Pooling y función de pérdida Focal Loss para desbalance de clases bioacústicas.
- [x] **14 ADRs Registrados:** Decisiones arquitectónicas formales documentadas en [`docs/adr/`](file:///home/kevin/Work/fama/docs/adr/).

### Backend
- [x] **Servidor FastAPI Modular:** Enrutamiento REST completo para predicción, dashboard, ingesta, entrenamiento y feedback.
- [x] **Persistencia SQLAlchemy / PostgreSQL:** Modelos de datos para usuarios, datasets, predicciones, feedback y entrenamientos.
- [x] **Predictor Modular (Strategy Pattern):** Predictores dedicados para bundles, modelos entrenados y ensambles implementados; auditoría de pesos y comportamientos de fallback pendiente en «En Progreso».
- [x] **Suite de Tests Backend Implementada:** Pruebas unitarias e integración en `backend/tests/` para componentes críticos; resultados históricos en recibos, sin ejecución ni conteo vigente consolidados en esta revisión.

### Frontend
- [x] **Arquitectura SPA Next.js 19:** Configuración con App Router, TypeScript, Tailwind CSS v4 y Zod.
- [x] **Dashboard de Telemetría:** Monitoreo en tiempo real de GPU, VRAM, estado de salud y métricas de modelos.
- [x] **Vistas Operativas Principales:** `DashboardView`, `IngestionView`, `TrainingView` y `PredictionView` implementadas y conectadas a la API real.
- [x] **Curación Supervisada (Feedback UI):** Captura, revisión y aprobación/rechazo implementadas, con evidencia histórica en el recibo RF06; E2E hasta reentrenamiento pendiente en «En Revisión / Pruebas».
