# Análisis de Objetivos del Proyecto F.A.M.A.
### Estado actual vs. Tesis — Septiembre 2026

---

## 🎯 ¿Qué es F.A.M.A. y cuál es su propósito?

**F.A.M.A.** = **F**lujo de Clasificación de **A**udio y **M**achine-learning **A**vanzado

Es un **framework MLOps de Arquitectura Híbrida** que resuelve un problema concreto del mundo académico:

> **Problema:** Los investigadores que trabajan con clasificación de audio mediante IA operan con scripts aislados, hardware local saturado, sin trazabilidad, y sin forma de centralizar datos ni reproducir experimentos. Migrar todo a la nube (Vertex AI, SageMaker) es económicamente inviable en el entorno académico.

> **Solución F.A.M.A.:** Combinar lo mejor de ambos mundos → **almacenamiento barato en la nube** (Google Cloud Storage) + **cómputo local gratuito** (tu propia GPU) + **una interfaz web visual** que orquesta todo el ciclo MLOps sin que el investigador necesite saber de infraestructura cloud.

---

## 🔑 ¿Por qué esta arquitectura es innovadora?

| Componente | ¿Por qué existe? | ¿Qué resuelve? |
|---|---|---|
| **Google Cloud Storage (GCS)** | Almacena los audios crudos y los modelos entrenados en la nube | Elimina la pérdida de datos locales, centraliza datasets para colaboración, tiene costo marginal (~$0.02/GB/mes) vs. comprar discos o pagar GPU cloud |
| **PostgreSQL (Cloud SQL)** | Registra predicciones, métricas, usuarios, retroalimentación | Garantiza **trazabilidad ACID** del ciclo MLOps: quién entrenó qué modelo, con qué datos, qué resultados dio, qué predicciones se corrigieron |
| **Backend FastAPI (Orquestador)** | Coordina ingesta ↔ preprocesamiento ↔ entrenamiento ↔ predicción | Es el "cerebro" que conecta la nube con tu hardware local, sin que el usuario toque APIs ni terminales |
| **Frontend Next.js (Dashboard)** | Interfaz visual para subir audios, ver predicciones, entrenar modelos | **Democratiza** el acceso: un investigador sin conocimiento técnico puede usar todo el pipeline desde el navegador |
| **Super-Ensamble Tri-Modelo** | 3 CNNs heterogéneas (EfficientNet + ConvNeXt + ResNet34d) votan ponderadamente | Maximiza precisión (88.31% test) aprovechando que cada arquitectura captura patrones distintos |

> [!IMPORTANT]
> **Lo innovador NO es usar GCS o PostgreSQL por separado** — eso es estándar. Lo innovador es el **modelo híbrido**: la nube solo persiste datos (barato), pero el cómputo pesado (entrenamiento con GPU) se hace localmente (gratis). Esto es el **punto de equilibrio** entre las soluciones 100% cloud (caras) y las 100% locales (sin trazabilidad ni escalabilidad).

---

## 📋 Objetivos de la Tesis vs. Estado Actual

### Objetivo General del Proyecto (Sección 1.5)
> *"Implementar un pipeline MLOps de arquitectura híbrida que automatice la gestión y clasificación de señales acústicas, combinando el almacenamiento centralizado en Google Cloud Platform con la orquestación del entrenamiento en infraestructura local."*

| Aspecto | Estado |
|---|---|
| Pipeline MLOps híbrido | ✅ Implementado (Backend FastAPI + GCS + PostgreSQL + GPU local) |
| Clasificación de señales acústicas | ✅ Funcionando (Super-Ensamble Tri-Modelo, 88.31% accuracy) |
| Almacenamiento en GCP | ✅ Operativo (subida a GCS en cada predicción) |
| Orquestación local | ✅ Operativo (carga de modelos en memoria, inferencia local) |

---

### Objetivos Específicos del Proyecto (Sección 1.6)

#### OE1: Analizar estado del arte ✅ COMPLETADO
> *Analizar el estado del arte respecto a arquitecturas MLOps híbridas, plataformas de almacenamiento en la nube y técnicas de procesamiento digital de señales acústicas.*

- ✅ Revisión de literatura técnica (documentado en tesis Cap. 1-2)
- ✅ Investigación de técnicas de procesamiento (espectrogramas Mel, MFCC)
- ✅ Análisis comparativo Cloud-Native vs Híbrido (tesis sección 1.3-1.4)

#### OE2: Levantar requerimientos ✅ COMPLETADO
> *Levantar los requerimientos funcionales y de infraestructura necesarios para la orquestación segura entre el repositorio alojado en la nube y los entornos de ejecución locales.*

- ✅ 6 Requerimientos Funcionales documentados (RF_01 a RF_06)
- ✅ 4 Requerimientos No Funcionales (RNF_01 a RNF_04)
- ✅ Identificación de actores (Investigador, Administrador)

#### OE3: Diseñar la arquitectura ✅ COMPLETADO
> *Diseñar la arquitectura lógica y el modelo de flujo de datos del sistema, definiendo los puntos de integración, las responsabilidades de cada entorno y la estructura del ciclo de retroalimentación.*

- ✅ Diagramas UML (Casos de Uso, E-R, Modelo Relacional)
- ✅ Arquitectura de 3 capas (Presentación, Aplicación, Datos)
- ✅ Modelo de datos con 8 tablas normalizadas
- ✅ Diseño físico y lógico documentado

#### OE4: Construir los módulos de software 🟢 COMPLETADO (~92%)
> *Construir los módulos de software encargados de la sincronización de archivos, preprocesamiento de características, la interfaz gráfica de validación local y el componente de captura de telemetría de errores para la mejora continua.*

| Módulo | Estado | Detalle |
|---|---|---|
| Sincronización GCS ↔ Local (Ingesta) | ✅ Implementado | Endpoints `/api/ingestion/status`, `/api/ingestion/datasets`, `/api/ingestion/sync` y carga masiva a GCS operativos. |
| Preprocesamiento (espectrogramas) | ✅ Implementado | `poc/preprocess.py` y `GPUAudioFrontEnd` con aceleración CUDA (Mel spectrograms, RMS, Flatness). |
| Interfaz gráfica (Dashboard / Web App) | ✅ Implementado | 4 vistas interactivas conectadas a APIs reales: Dashboard, Ingesta, Predicción, Entrenamiento. |
| Predicción en tiempo real | ✅ Implementado | `/api/predict` con inferencia real PyTorch CUDA, catálogo `ModelRegistry` y erradicación de fallbacks mock. |
| **Telemetría / Retroalimentación** | 🟡 Parcial | Servicio relacional `FeedbackService` y tabla `retroalimentacion` implementados en backend. Pendiente registrar endpoint `POST /api/feedback` y botones en UI. |

#### OE5: Evaluar rendimiento y viabilidad 🟢 COMPLETADO (~90%)
> *Evaluar el rendimiento, la viabilidad y la efectividad del ciclo de re-entrenamiento del pipeline híbrido mediante pruebas de concepto, analizando la evolución de la precisión del modelo y el ahorro de costos frente a alternativas puramente en la nube.*

- ✅ Métricas documentadas (88.68% récord macro F1 bioacústica, 81.16% accuracy diagnóstico automotriz)
- ✅ PoC ejecutado con dataset real de 15 especies chilenas y 13 fallas mecánicas de motor
- ✅ Factibilidad económica calculada (VAN y ahorro frente a GPU cloud en tesis)
- ✅ Ciclo de entrenamiento local en GPU: conectado desde la interfaz web a través de `training_service` y `TrainingView.tsx`, generando checkpoints reales `.pt` en disco y trazabilidad época por época en PostgreSQL.

---

## 📊 Estado de los Requerimientos Funcionales

| RF | Descripción | Estado | Evidencia en código |
|---|---|---|---|
| **RF_01** | Autenticarse con Google Cloud Storage | ✅ | [`storage.py`](file:///home/kevin/Work/fama/backend/app/services/storage.py) — Credenciales IAM vía `.env` (RNF_03) |
| **RF_02** | Sincronización masiva de datasets con la nube | ✅ | [`ingestion.py`](file:///home/kevin/Work/fama/backend/app/services/ingestion.py) — Endpoints `/api/ingestion/status`, `/datasets`, `/sync` |
| **RF_03** | Extraer características matemáticas (espectrogramas, MFCC) | ✅ | [`poc/preprocess.py`](file:///home/kevin/Work/fama/backend/poc/preprocess.py) y `GPUAudioFrontEnd` en CUDA |
| **RF_04** | Entrenar la red neuronal localmente desde Dashboard | ✅ | [`training.py`](file:///home/kevin/Work/fama/backend/app/services/training.py) — Pipeline PyTorch GPU (CUDA), checkpoints `.pt` y trazabilidad PostgreSQL |
| **RF_05** | Visualizar predicciones acústicas en tiempo real | ✅ | [`/api/predict`](file:///home/kevin/Work/fama/backend/app/main.py) + [`PredictionView.tsx`](file:///home/kevin/Work/fama/frontend/components/views/PredictionView.tsx) con inferencia real y telemetría ODD |
| **RF_06** | Retroalimentar predicción errónea | 🟡 Parcial | [`feedback.py`](file:///home/kevin/Work/fama/backend/app/services/feedback.py) y tabla `retroalimentacion` listos en backend; pendiente endpoint HTTP y botones en UI |

---

## 📊 Estado de los Requerimientos No Funcionales

| RNF | Descripción | Estado |
|---|---|---|
| **RNF_01** | Transformar audio a espectrograma en ≤ 2s | ✅ Cumplido (`GPUAudioFrontEnd` en < 20 ms) |
| **RNF_02** | Soportar datasets de hasta 50 GB sin OOM | ✅ Cumplido (Procesamiento por batches y streaming con `pin_memory`) |
| **RNF_03** | Credenciales nunca hardcodeadas (leer de `.env`) | ✅ Cumplido (`.env` + `GOOGLE_APPLICATION_CREDENTIALS`) |
| **RNF_04** | Predicción desplegada en pantalla en ≤ 3s | ✅ Cumplido (latencia real medida: ~176 ms en GPU) |

---

## 🗂️ Estado de las Actividades de Desarrollo (Tabla 6.17 de la tesis)

| # | Actividad | % Tesis | % Real Actual |
|---|---|---|---|
| 1 | Levantamiento de requerimientos funcionales y no funcionales | 100% | ✅ 100% |
| 2 | Análisis de factibilidad (técnica, operativa, económica) | 100% | ✅ 100% |
| 3 | Especificación de Casos de Uso y Matriz de Trazabilidad | 100% | ✅ 100% |
| 4 | Diseño de Arquitectura de Software y Servicios Web | 100% | ✅ 100% |
| 5 | Diseño del Modelo Relacional y Entidad-Relación | 100% | ✅ 100% |
| 6 | Diseño de Interfaz de Usuario (Guías de estilo y Mockups) | 100% | ✅ 100% |
| 7 | **Desarrollo del prototipo del Backend (Orquestador FastAPI)** | 0% | 🟢 **100%** |
| 8 | **Integración bidireccional con GCS y PostgreSQL** | 0% | 🟢 **95%** |
| 9 | **Desarrollo del Frontend interactivo (Dashboard)** | 0% | 🟢 **100%** |
| 10 | **Integración de pipelines de entrenamiento local e IA** | 0% | 🟢 **100%** |
| 11 | **Pruebas de integración, telemetría y ciclo de retroalimentación** | 0% | 🟡 **80%** (206 tests pasando; pendiente endpoint RF_06) |
| 12 | **Despliegue, manuales de usuario y documentación final** | 0% | 🟡 **80%** (listo en rama `feat/deployment-auth-docs`, pendiente de merge) |

---

## 🚧 Lo que FALTA por implementar (ordenado por prioridad)

### 🔴 Prioridad Alta (Último requerimiento funcional pendiente)

1. **RF_06 — Conectar Ciclo de Retroalimentación en API y UI**
   - Exponer endpoint `POST /api/feedback` en `main.py` delegando en `FeedbackService.record_feedback`.
   - Añadir botones en [`PredictionView.tsx`](file:///home/kevin/Work/fama/frontend/components/views/PredictionView.tsx) para que el investigador valide o corrija la etiqueta (despachando el audio a GCS en la carpeta de re-entrenamiento).
   - Escribir pruebas automatizadas con TDD en `backend/tests/test_api_feedback.py`.

### 🟡 Prioridad Media (Integración y Despliegue)

2. **Integrar rama de despliegue y autenticación (`feat/deployment-auth-docs`)**
   - Fusionar en `main` los contenedores `Dockerfile`, `docker-compose.yml`, el módulo de autenticación RBAC (`backend/app/routes/auth.py`, `backend/app/services/auth.py`), sus pruebas y manuales de operación.

---

## ✅ Resumen: Lo que YA logramos

| Logro | Impacto |
|---|---|
| **Super-Ensamble Tri-Modelo y Modelos Individuales** | 88.68% F1 récord en bioacústica y 81.16% Acc en diagnóstico industrial |
| **Inferencia real GPU de extremo a extremo** | Endpoint `/api/predict` con modelos entrenados reales (100% certeza en pruebas con Chucao) |
| **Erradicación de Mocks Silenciosos** | El sistema valida pesos en disco y reporta fallos reales vía HTTP 503 en lugar de simular respuestas |
| **Entrenamiento acelerado en GPU local** | Orquestado desde `TrainingView.tsx` con PyTorch CUDA, checkpoints persistidos y sincronización con PostgreSQL |
| **Base de datos relacional operativa** | Modelos `prediccion`, `modelo`, `metrica_entrenamiento`, `conjunto_datos`, `audio` y `retroalimentacion` creados y sincronizados |
| **Ingesta masiva conectada con Google Cloud Storage** | Consulta de datasets, conteo de objetos y subida de lotes operativos |
| **4 vistas del Frontend completamente conectadas** | Dashboard, Ingesta, Predicción y Entrenamiento operando en tiempo real con Next.js y Turbopack |
| **Cobertura de pruebas automatizadas** | 206 pruebas en `pytest` y 20 pruebas en `vitest` en verde |


