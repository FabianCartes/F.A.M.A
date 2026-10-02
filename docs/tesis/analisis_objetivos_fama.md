# Análisis de Objetivos del Proyecto F.A.M.A.
### Estado del código vs. Tesis — Revisión documental del 2 de octubre de 2026

Esta revisión distingue **implementado** (código presente), **evidencia histórica** (resultados registrados en recibos) y **pendiente de validación** (comportamiento aún no acreditado en el entorno objetivo). No se ejecutaron pruebas, contenedores ni benchmarks durante esta revisión. Los pendientes se mantienen en [KANBAN.md](../KANBAN.md).

---

## ¿Qué es F.A.M.A. y cuál es su propósito?

**F.A.M.A.** = **F**lujo de Clasificación de **A**udio y **M**achine-learning **A**vanzado

Es un **framework MLOps de Arquitectura Híbrida** que resuelve un problema concreto del mundo académico:

> **Problema:** Los investigadores que trabajan con clasificación de audio mediante IA operan con scripts aislados, hardware local saturado, sin trazabilidad, y sin forma de centralizar datos ni reproducir experimentos. Migrar todo a la nube (Vertex AI, SageMaker) es económicamente inviable en el entorno académico.

> **Solución F.A.M.A.:** Combinar lo mejor de ambos mundos → **almacenamiento barato en la nube** (Google Cloud Storage) + **cómputo local gratuito** (tu propia GPU) + **una interfaz web visual** que orquesta todo el ciclo MLOps sin que el investigador necesite saber de infraestructura cloud.

---

## ¿Por qué esta arquitectura es innovadora?

| Componente | ¿Por qué existe? | ¿Qué resuelve? |
|---|---|---|
| **Google Cloud Storage (GCS)** | Almacena los audios crudos y los modelos entrenados en la nube | Elimina la pérdida de datos locales, centraliza datasets para colaboración, tiene costo marginal (~$0.02/GB/mes) vs. comprar discos o pagar GPU cloud |
| **PostgreSQL (Cloud SQL)** | Registra predicciones, métricas, usuarios, retroalimentación | Garantiza **trazabilidad ACID** del ciclo MLOps: quién entrenó qué modelo, con qué datos, qué resultados dio, qué predicciones se corrigieron |
| **Backend FastAPI (Orquestador)** | Coordina ingesta ↔ preprocesamiento ↔ entrenamiento ↔ predicción | Es el "cerebro" que conecta la nube con tu hardware local, sin que el usuario toque APIs ni terminales |
| **Frontend Next.js (Dashboard)** | Interfaz visual para subir audios, ver predicciones, entrenar modelos | **Democratiza** el acceso: un investigador sin conocimiento técnico puede usar todo el pipeline desde el navegador |
| **Super-Ensamble Tri-Modelo** | 3 CNNs heterogéneas (EfficientNet + ConvNeXt + ResNet34d) votan ponderadamente | Combina arquitecturas que capturan patrones distintos; el 88.31% de accuracy citado requiere consolidar su referencia experimental en OE5 |

> [!IMPORTANT]
> **Lo innovador NO es usar GCS o PostgreSQL por separado** — eso es estándar. Lo innovador es el **modelo híbrido**: la nube solo persiste datos (barato), pero el cómputo pesado (entrenamiento con GPU) se hace localmente (gratis). Esto es el **punto de equilibrio** entre las soluciones 100% cloud (caras) y las 100% locales (sin trazabilidad ni escalabilidad).

---

## Objetivos de la Tesis vs. Estado Actual

### Objetivo General del Proyecto (Sección 1.5)
> *"Implementar un pipeline MLOps de arquitectura híbrida que automatice la gestión y clasificación de señales acústicas, combinando el almacenamiento centralizado en Google Cloud Platform con la orquestación del entrenamiento en infraestructura local."*

| Aspecto | Estado |
|---|---|
| Pipeline MLOps híbrido | Componentes implementados (Backend FastAPI + GCS + PostgreSQL + cómputo local); validación integral del entorno pendiente |
| Clasificación de señales acústicas | Predictores y ensambles implementados; inferencia real documentada para un caso concreto en el [recibo de inferencia](../receipts/fase_inferencia_real_receipt.json) |
| Almacenamiento en GCP | Integración implementada; su disponibilidad y las transferencias dependen de credenciales, configuración y acceso al servicio |
| Orquestación local | Carga de modelos, inferencia y entrenamiento implementados; inventario de pesos y operación en contenedor con GPU pendientes de validación |

---

### Objetivos Específicos del Proyecto (Sección 1.6)

#### OE1: Analizar estado del arte (Completado)
> *Analizar el estado del arte respecto a arquitecturas MLOps híbridas, plataformas de almacenamiento en la nube y técnicas de procesamiento digital de señales acústicas.*

- Revisión de literatura técnica (documentado en tesis Cap. 1-2)
- Investigación de técnicas de procesamiento (espectrogramas Mel, MFCC)
- Análisis comparativo Cloud-Native vs Híbrido (tesis sección 1.3-1.4)

#### OE2: Levantar requerimientos (Completado)
> *Levantar los requerimientos funcionales y de infraestructura necesarios para la orquestación segura entre el repositorio alojado en la nube y los entornos de ejecución locales.*

- 6 Requerimientos Funcionales documentados (RF_01 a RF_06)
- 4 Requerimientos No Funcionales (RNF_01 a RNF_04)
- Identificación de actores (Investigador, Administrador)

#### OE3: Diseñar la arquitectura (Completado)
> *Diseñar la arquitectura lógica y el modelo de flujo de datos del sistema, definiendo los puntos de integración, las responsabilidades de cada entorno y la estructura del ciclo de retroalimentación.*

- Diagramas UML (Casos de Uso, E-R, Modelo Relacional)
- Arquitectura de 3 capas (Presentación, Aplicación, Datos)
- Modelo de datos con 8 tablas normalizadas
- Diseño físico y lógico documentado

#### OE4: Construir los módulos de software (Implementación disponible; validación pendiente)
> *Construir los módulos de software encargados de la sincronización de archivos, preprocesamiento de características, la interfaz gráfica de validación local y el componente de captura de telemetría de errores para la mejora continua.*

| Módulo | Estado | Detalle |
|---|---|---|
| Sincronización GCS ↔ Local (Ingesta) | Implementado | Endpoints `/api/ingestion/status`, `/api/ingestion/datasets`, `/api/ingestion/sync` y carga masiva presentes; validación en el entorno objetivo y optimizaciones de gran volumen pendientes. |
| Preprocesamiento (espectrogramas) | Implementado | `poc/preprocess.py` y `GPUAudioFrontEnd` con aceleración CUDA (Mel spectrograms, RMS, Flatness). |
| Interfaz gráfica (Dashboard / Web App) | Implementado | 4 vistas interactivas conectadas a APIs reales: Dashboard, Ingesta, Predicción, Entrenamiento. |
| Predicción en tiempo real | Implementado; auditoría pendiente | `/api/predict`, catálogo `ModelRegistry` y predictores reales presentes. El endpoint maneja `ModelWeightsError` con HTTP 503, pero `EngineEnsemblePredictor` conserva ramas `mock_fallback`; no existe una garantía universal de fallo explícito ante pesos ausentes. |
| **Telemetría / Retroalimentación** | Captura y curación implementadas; E2E pendiente | `FeedbackService`, endpoints `/api/feedback`, captura en `PredictionView` y aprobación/rechazo en `IngestionView` presentes. El [recibo RF06](../receipts/fase_rf06_feedback_curation_receipt.json) documenta pruebas de esa fase, no el ciclo completo hasta un nuevo modelo reentrenado. |

#### OE5: Evaluar rendimiento y viabilidad (Evidencia experimental por consolidar)
> *Evaluar el rendimiento, la viabilidad y la efectividad del ciclo de re-entrenamiento del pipeline híbrido mediante pruebas de concepto, analizando la evolución de la precisión del modelo y el ahorro de costos frente a alternativas puramente en la nube.*

- Métricas citadas para consolidar con sus artefactos experimentales: 88.68% macro F1 bioacústica, 88.31% accuracy del Super-Ensamble y 81.16% accuracy de diagnóstico automotriz. Son métricas distintas; esta revisión no reejecutó los experimentos.
- PoC ejecutado con dataset real de 15 especies chilenas y 13 fallas mecánicas de motor
- Factibilidad económica calculada (VAN y ahorro frente a GPU cloud en tesis)
- Entrenamiento local conectado desde `TrainingView.tsx`: genera checkpoints `.pt` y acumula métricas por época. Al finalizar cada modelo, el worker inserta sus métricas en PostgreSQL y hace un commit; no persiste mediante un commit en cada época. Un error de persistencia provoca rollback y una advertencia, sin garantizar el registro del modelo ([training.py](../../backend/app/services/training.py)).
- Pendiente validar el ciclo completo de retroalimentación hasta reentrenamiento, el despliegue con GPU y la redacción final de OE4/OE5.

---

## Estado de los Requerimientos Funcionales

| RF | Descripción | Estado | Evidencia en código |
|---|---|---|---|
| **RF_01** | Autenticarse con Google Cloud Storage | Implementado; acceso operativo por validar | [`storage.py`](../../backend/app/services/storage.py) — Integración mediante credenciales IAM del entorno |
| **RF_02** | Sincronización masiva de datasets con la nube | Implementado; validación de gran volumen pendiente | [`ingestion.py`](../../backend/app/services/ingestion.py) — Endpoints `/api/ingestion/status`, `/datasets`, `/sync` |
| **RF_03** | Extraer características matemáticas (espectrogramas, MFCC) | Implementado; rendimiento por acreditar | [`poc/preprocess.py`](../../backend/poc/preprocess.py) y `GPUAudioFrontEnd` |
| **RF_04** | Entrenar la red neuronal localmente desde Dashboard | Implementado; validación integral pendiente | [`training.py`](../../backend/app/services/training.py) — Pipeline PyTorch, checkpoints `.pt` y persistencia de métricas al finalizar cada modelo |
| **RF_05** | Visualizar predicciones acústicas en tiempo real | Implementado; evidencia histórica de un caso | [`/api/predict`](../../backend/app/main.py), [`PredictionView.tsx`](../../frontend/components/views/PredictionView.tsx) y [recibo de inferencia](../receipts/fase_inferencia_real_receipt.json); auditoría de pesos/fallbacks pendiente |
| **RF_06** | Retroalimentar predicción errónea | Captura/curación implementadas; reentrenamiento E2E pendiente | [`feedback.py`](../../backend/app/services/feedback.py), `/api/feedback`, `PredictionView` e `IngestionView` (ADR 0013); [recibo de pruebas de captura/curación](../receipts/fase_rf06_feedback_curation_receipt.json) |

---

## Estado de los Requerimientos No Funcionales

| RNF | Descripción | Estado |
|---|---|---|
| **RNF_01** | Transformar audio a espectrograma en ≤ 2s | Frontend de audio implementado; falta consolidar un benchmark reproducible que acredite el umbral |
| **RNF_02** | Soportar datasets de hasta 50 GB sin OOM | Procesamiento por batches presente; capacidad de 50 GB pendiente de prueba documentada |
| **RNF_03** | Credenciales nunca hardcodeadas (leer de `.env`) | Configuración por entorno implementada, pero existen valores predeterminados en autenticación y Compose; endurecimiento pendiente |
| **RNF_04** | Predicción desplegada en pantalla en ≤ 3s | El recibo de inferencia registra 176.27 ms en un caso concreto; no acredita por sí solo el tiempo completo hasta pantalla ni una garantía general |

---

## Estado de las Actividades de Desarrollo (Tabla 6.17 de la tesis)

La columna de tesis conserva los valores citados de la Tabla 6.17. El estado del código no se expresa como porcentaje: no hay una metodología de medición de avance definida en este documento.

| # | Actividad | % Tesis citado | Estado según código y evidencia disponible |
|---|---|---|---|
| 1 | Levantamiento de requerimientos funcionales y no funcionales | 100% | Documentado; cumplimiento operativo diferenciado en las tablas RF/RNF |
| 2 | Análisis de factibilidad (técnica, operativa, económica) | 100% | Citado en la tesis; no revalidado en esta revisión de código |
| 3 | Especificación de Casos de Uso y Matriz de Trazabilidad | 100% | Documentado; actualización de estados pendiente |
| 4 | Diseño de Arquitectura de Software y Servicios Web | 100% | Diseño e implementación presentes; hardening pendiente |
| 5 | Diseño del Modelo Relacional y Entidad-Relación | 100% | Modelos implementados; registro extendido de pipeline sujeto a decisión |
| 6 | Diseño de Interfaz de Usuario (Guías de estilo y Mockups) | 100% | Vistas implementadas; mejoras de UI/UX abiertas en Kanban |
| 7 | **Desarrollo del prototipo del Backend (Orquestador FastAPI)** | 0% | Implementado; autorización de rutas sensibles pendiente |
| 8 | **Integración bidireccional con GCS y PostgreSQL** | 0% | Implementada; validación operativa y de gran volumen pendiente |
| 9 | **Desarrollo del Frontend interactivo (Dashboard)** | 0% | Cuatro vistas principales implementadas; backlog de producto abierto |
| 10 | **Integración de pipelines de entrenamiento local e IA** | 0% | Implementada; pesos, fallbacks y ejecución con GPU en contenedor por validar |
| 11 | **Pruebas de integración, telemetría y ciclo de retroalimentación** | 0% | Pruebas y recibos de alcance específico existentes; E2E hasta reentrenamiento pendiente |
| 12 | **Despliegue, manuales de usuario y documentación final** | 0% | Docker, autenticación y documentación presentes; despliegue integral/GPU, autorización y cierre de tesis pendientes |

---

## Hitos implementados y límites de validación

1. **RF_01 al RF_06:** Hay implementación de las funcionalidades descritas; el alcance de la validación varía por requisito y no permite declarar un cierre global al 100%.
2. **Ciclo de Retroalimentación Activa (RF_06 / ADR 0013):**
   - Captura inmediata de validación experta y corrección en [`PredictionView.tsx`](file:///home/kevin/Work/fama/frontend/components/views/PredictionView.tsx).
   - Registro pendiente en PostgreSQL (`procesado = False`) y subida a staging en GCS condicionada a localizar el audio y completar la transferencia; un fallo de subida puede quedar registrado sin impedir la captura del feedback.
   - Bandeja de curación semi-manual en [`IngestionView.tsx`](file:///home/kevin/Work/fama/frontend/components/views/IngestionView.tsx) para prevenir la contaminación del dataset (*Human-in-the-Loop MLOps*).
   - Notificación y badge reactivo en [`Sidebar.tsx`](file:///home/kevin/Work/fama/frontend/components/Sidebar.tsx).
   - [Recibo de captura y curación](../receipts/fase_rf06_feedback_curation_receipt.json) con resultados históricos de pruebas de esa fase. No acredita el E2E hasta reentrenamiento; aprobar una muestra no dispara automáticamente el entrenamiento.
3. **Infraestructura de despliegue y autenticación:**
   - `Dockerfile`, `docker-compose.yml`, healthchecks, autenticación JWT y `require_roles` presentes. El [recibo de operación Docker](../receipts/fase1_operacion_red_docker_receipt.json) documenta validaciones de configuración/rutas, no la ejecución integral con GPU.
   - Las rutas sensibles examinadas en `backend/app/main.py` no aplican dependencias de autenticación/roles. CORS, validación y tamaño de cargas, rate limiting y secretos predeterminados siguen pendientes de hardening.

---

## Resumen: Lo que YA logramos

| Logro | Impacto |
|---|---|
| **Super-Ensamble Tri-Modelo y Modelos Individuales** | Implementación presente; referencias experimentales de métricas por consolidar en OE5 |
| **Inferencia real GPU documentada** | El recibo registra una inferencia con EfficientNet-B0 y confianza 1.0 en una muestra; esa confianza no equivale a certeza diagnóstica ni accuracy general |
| **Manejo explícito de algunos fallos de pesos** | `ModelWeightsError` se traduce a HTTP 503; otras ramas conservan `mock_fallback` y requieren auditoría ([predictor de motores](../../backend/app/services/predictors/engine_ensemble_predictor.py)) |
| **Entrenamiento local implementado** | Orquestado desde `TrainingView.tsx`; guarda checkpoints y persiste métricas por época al finalizar cada modelo, con manejo de errores de base de datos |
| **Modelo relacional implementado** | Entidades de usuarios, predicciones, modelos, métricas, datasets, audios y feedback presentes; operación y persistencia dependen de la conexión a PostgreSQL |
| **Integración de ingesta con Google Cloud Storage** | Consulta, sincronización y subida implementadas; operación en el entorno objetivo por validar |
| **Captura y curación de feedback (RF_06)** | UI, endpoints y persistencia implementados; subida a staging condicional y validación E2E hasta reentrenamiento pendiente |
| **4 vistas principales implementadas** | Dashboard, Ingesta, Predicción y Entrenamiento con integración API; mejoras de producto abiertas en Kanban |
| **Pruebas automatizadas y recibos históricos** | Hay suites backend/frontend y resultados de alcance específico en los recibos; no se ejecutaron ni consolidaron en esta revisión para afirmar un total vigente |

### Evidencia y alcance de esta revisión

- [Recibo de inferencia](../receipts/fase_inferencia_real_receipt.json): caso individual y resultados de la suite ejecutada en esa fase.
- [Recibo RF06](../receipts/fase_rf06_feedback_curation_receipt.json): endpoints, captura y curación; no acredita el recorrido completo hasta un nuevo modelo.
- [Recibo de operación Docker](../receipts/fase1_operacion_red_docker_receipt.json): configuración y pruebas de alcance específico; no acredita operación integral con GPU.
- Código contrastado: [API](../../backend/app/main.py), [feedback](../../backend/app/services/feedback.py), [autenticación](../../backend/app/services/auth.py), [entrenamiento](../../backend/app/services/training.py) y [esquema de métricas](../../backend/app/models/training.py). Los resultados históricos no se suman como si correspondieran a una única ejecución actual.
