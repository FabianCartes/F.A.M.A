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

#### OE4: Construir los módulos de software 🟡 EN PROGRESO (~65%)
> *Construir los módulos de software encargados de la sincronización de archivos, preprocesamiento de características, la interfaz gráfica de validación local y el componente de captura de telemetría de errores para la mejora continua.*

| Módulo | Estado | Detalle |
|---|---|---|
| Sincronización GCS → Local | ⚠️ Parcial | Subida a GCS funciona (`upload_audio_to_gcp`), pero la **descarga masiva** (ingesta de datasets desde GCS al local) aún no está implementada como endpoint real |
| Preprocesamiento (espectrogramas) | ✅ Implementado | `poc/preprocess.py` con Librosa (Mel spectrograms, MFCC, RMS) |
| Interfaz gráfica (Dashboard) | ✅ Implementado | 4 vistas: Dashboard, Ingesta, Predicción, Entrenamiento |
| Predicción en tiempo real | ✅ Implementado | `/api/predict` con Super-Ensamble + Dense TTA |
| **Telemetría / Retroalimentación** | ❌ **No implementado** | El ciclo de feedback (RF_06) donde el investigador corrige predicciones erróneas **no tiene endpoint ni UI funcional** |

#### OE5: Evaluar rendimiento y viabilidad 🟡 EN PROGRESO (~50%)
> *Evaluar el rendimiento, la viabilidad y la efectividad del ciclo de re-entrenamiento del pipeline híbrido mediante pruebas de concepto, analizando la evolución de la precisión del modelo y el ahorro de costos frente a alternativas puramente en la nube.*

- ✅ Métricas documentadas (88.31% accuracy, 88.68% macro F1, 90.15% macro precision)
- ✅ PoC ejecutado con dataset real de 15 especies chilenas
- ✅ Factibilidad económica calculada (VAN en tesis)
- ⚠️ El **ciclo de re-entrenamiento** desde la interfaz web aún no está conectado al backend real

---

## 📊 Estado de los Requerimientos Funcionales

| RF | Descripción | Estado | Evidencia en código |
|---|---|---|---|
| **RF_01** | Autenticarse con Google Cloud Storage | ✅ | [`storage.py`](file:///c:/Users/fabia/Desktop/F.A.M.A/backend/app/services/storage.py) — Credenciales IAM vía `.env` (RNF_03) |
| **RF_02** | Descargar masivamente datasets desde la nube | ❌ | No existe endpoint de descarga/ingesta desde GCS al local |
| **RF_03** | Extraer características matemáticas (espectrogramas, MFCC) | ✅ | [`poc/preprocess.py`](file:///c:/Users/fabia/Desktop/F.A.M.A/backend/poc/preprocess.py) — Librosa |
| **RF_04** | Entrenar la red neuronal localmente | ⚠️ Parcial | [`poc/train.py`](file:///c:/Users/fabia/Desktop/F.A.M.A/backend/poc/train.py) existe como script, pero **no hay endpoint API** que lo invoque desde el Dashboard |
| **RF_05** | Visualizar predicciones acústicas en tiempo real | ✅ | [`/api/predict`](file:///c:/Users/fabia/Desktop/F.A.M.A/backend/app/main.py#L327-L428) + [`PredictionView.tsx`](file:///c:/Users/fabia/Desktop/F.A.M.A/frontend/components/views/PredictionView.tsx) |
| **RF_06** | Retroalimentar predicción errónea | ❌ | No existe endpoint `/api/feedback` ni UI de corrección |

---

## 📊 Estado de los Requerimientos No Funcionales

| RNF | Descripción | Estado |
|---|---|---|
| **RNF_01** | Transformar audio a espectrograma en ≤ 2s | ✅ Cumplido |
| **RNF_02** | Soportar datasets de hasta 50 GB sin OOM | ⚠️ No verificado formalmente |
| **RNF_03** | Credenciales nunca hardcodeadas (leer de `.env`) | ✅ Cumplido ([`.env`](file:///c:/Users/fabia/Desktop/F.A.M.A/backend/.env) + `GOOGLE_APPLICATION_CREDENTIALS`) |
| **RNF_04** | Predicción desplegada en pantalla en ≤ 3s | ✅ Cumplido (latencia medida en frontend) |

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
| 7 | **Desarrollo del prototipo del Backend (Orquestador FastAPI)** | 0% | 🟢 **~75%** |
| 8 | **Integración bidireccional con GCS y PostgreSQL** | 0% | 🟡 **~50%** |
| 9 | **Desarrollo del Frontend interactivo (Dashboard)** | 0% | 🟢 **~70%** |
| 10 | **Integración de pipelines de entrenamiento local e IA** | 0% | 🟡 **~40%** |
| 11 | **Pruebas de integración, telemetría y ciclo de retroalimentación** | 0% | 🔴 **~10%** |
| 12 | **Despliegue, manuales de usuario y documentación final** | 0% | 🔴 **~5%** |

---

## 🚧 Lo que FALTA por implementar (ordenado por prioridad)

### 🔴 Prioridad Alta (Requerimientos funcionales pendientes)

1. **RF_02 — Ingesta bidireccional GCS ↔ Local**
   - Endpoint `POST /api/ingest` que descargue datasets desde un bucket GCS al servidor local
   - Conectar la vista [`IngestionView.tsx`](file:///c:/Users/fabia/Desktop/F.A.M.A/frontend/components/views/IngestionView.tsx) (actualmente usa datos mock/simulados) con el backend real

2. **RF_04 — Entrenamiento desde el Dashboard**
   - Endpoint `POST /api/train` que invoque el pipeline de entrenamiento (`poc/train.py`) con hiperparámetros configurados desde el frontend
   - Conectar la vista [`TrainingView.tsx`](file:///c:/Users/fabia/Desktop/F.A.M.A/frontend/components/views/TrainingView.tsx) (actualmente es estática) con el backend real
   - Enviar métricas de entrenamiento (accuracy, loss por época) al frontend en tiempo real vía WebSocket o SSE

3. **RF_06 — Ciclo de retroalimentación (feedback loop)**
   - Endpoint `POST /api/feedback` que reciba `id_prediccion`, `fue_correcta`, `etiqueta_corregida`
   - UI en PredictionView para que el investigador confirme o corrija la predicción
   - Subir el audio corregido a GCS con nueva etiqueta para re-entrenamiento futuro
   - Tabla `retroalimentacion` en PostgreSQL (ya diseñada en tesis pero no implementada)

### 🟡 Prioridad Media

4. **Base de datos completa**
   - Actualmente solo existe la tabla `prediccion` en PostgreSQL
   - Faltan las tablas: `usuario`, `conjunto_datos`, `audio`, `modelo`, `metrica_entrenamiento`, `retroalimentacion`, `registro_pipeline`, `nodo_procesamiento`

5. **Dashboard conectado a datos reales**
   - [`DashboardView.tsx`](file:///c:/Users/fabia/Desktop/F.A.M.A/frontend/components/views/DashboardView.tsx) muestra KPIs hardcodeados → Conectar a `/api/model-info` y `/api/stats` reales

6. **Autenticación de usuarios (CU_SES_01)**
   - Login/registro con roles (Investigador/Administrador) — Caso de Uso del módulo de sesión

### 🟢 Prioridad Baja (Trabajo futuro / nice-to-have)

7. Gestión de nodos de procesamiento (CU_ADM_02)
8. Gestión de recursos cloud (CU_ADM_03)
9. Monitoreo de pipelines (CU_ADM_04)
10. Despliegue en producción y manuales de usuario

---

## ✅ Resumen: Lo que YA logramos

| Logro | Impacto |
|---|---|
| **Super-Ensamble Tri-Modelo** con 88.31% accuracy en 15 especies chilenas | Demuestra que la arquitectura híbrida produce modelos competitivos con hardware local |
| **Predicción end-to-end funcional** (upload audio → GCS → inferencia → PostgreSQL → resultado visual) | El flujo completo RF_05 está operativo |
| **Visualización de señal acústica** con oscilograma SVG, animación de barrido y playhead a 60 FPS | Interfaz de calidad profesional para validación en campo |
| **Persistencia dual** (GCS + PostgreSQL) en cada predicción | Trazabilidad real de cada inferencia |
| **Arquitectura por capas** (Controllers, Services, Models, Routes, Middlewares) | Backend mantenible y extensible |
| **4 vistas del Dashboard** implementadas con diseño dark mode profesional | Cumple los mockups de la tesis (Figuras 6.5-6.8) |

