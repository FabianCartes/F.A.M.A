# F.A.M.A. — Framework MLOps Híbrido para Clasificación Acústica Multi-Dominio

[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688.svg)](https://fastapi.tiangolo.com/)
[![Next.js](https://img.shields.io/badge/Next.js-14+-black.svg)](https://nextjs.org/)
[![PyTorch](https://img.shields.io/badge/PyTorch-2.1+-ee4c2c.svg)](https://pytorch.org/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16+-336791.svg)](https://www.postgresql.org/)
[![Google Cloud Storage](https://img.shields.io/badge/GCS-Persistence-4285F4.svg)](https://cloud.google.com/storage)
[![Tests](https://img.shields.io/badge/tests-174%20passed-success.svg)](backend/tests/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

> **Proyecto de Título / Tesis de Grado**  
> **Carrera:** Ingeniería Civil Informática  
> **Institución:** Universidad del Bío-Bío, Concepción, Chile  
> **Autores:** Fabián Cartes Oliva, Kevin Cárdenas Sepúlveda  
> **Profesor Guía:** Christian Vidal Castro  

---

## 1. Descripción General

**F.A.M.A.** es un framework MLOps híbrido de nivel productivo para el ciclo de vida integral de modelos de clasificación acústica. Desacopla la ingesta masiva de grabaciones, el preprocesamiento espectral y la orquestación de entrenamientos del consumo en inferencia de baja latencia con persistencia híbrida en la nube (**Google Cloud Storage**) y base de datos relacional (**PostgreSQL**).

El sistema opera bajo un enfoque **multi-dominio acústico**, soportando simultáneamente:
1. **Bioacústica (Aves Chilenas):** Monitoreo y clasificación de 15 especies de aves nativas y endémicas de Chile a partir de registros de campo de [Xeno-canto](https://xeno-canto.org/).
2. **Diagnóstico Industrial (Fallas de Motores):** Detección y diagnóstico temprano de 13 condiciones de falla mecánica automotriz mediante análisis espectral y separación armónico-percusiva.

---

## 2. Arquitectura del Sistema

```text
                                ARQUITECTURA GENERAL F.A.M.A.

         [ Frontend Next.js / TypeScript ]  <────  RESTful API / SSE  ────>  [ Orquestador FastAPI ]
         ├── Dashboard (Doble Campeón)                                      ├── Controladores Desacoplados
         ├── Ingesta (Sincronización GCS)                                   ├── Model Registry Dinámico
         ├── Entrenamiento (Orquestador Triadas)                            ├── Pipeline Acústico (HPSS + VAD)
         └── Predicción (Selector Multi-Dominio)                            └── Persistencia Híbrida
                                                                                      │
                 ┌────────────────────────────────────────────────────────────────────┴──────────────────────────┐
                 ▼                                                                                               ▼
    [ Capa de Almacenamiento Cloud ]                                                            [ Capa de Inferencia Tensorial ]
    ├── Google Cloud Storage (Bucket)                                                           ├── Tríada Bioacústica (22.05 kHz)
    │   ├── datasets/{dominio}/{clase}/*.wav                                                    │   ├── EfficientNet-B0
    │   └── audios_inferencia/{timestamp}.wav                                                   │   ├── ConvNeXt-Nano
    └── PostgreSQL (fama_db)                                                                    │   └── ResNet-34d
        ├── datasets, colecciones y audios                                                      └── Tríada Industrial (32.00 kHz)
        ├── historial_entrenamiento y checkpoints                                                   ├── ResNet-34d
        └── prediccion y métricas de calibración                                                    ├── EfficientNet-B0
                                                                                                    └── PANNs-CNN14 (AudioSet)
```

---

## 3. Dominios Soportados y Modelos Campeones

### A. Dominio Bioacústico — 15 Especies Chilenas
- **Parámetros acústicos:** Remuestreo a 22.050 Hz, ventana temporal de 5.0 s, 128 bandas Mel (100 Hz - 11.025 Hz).
- **Modelo Campeón:** Súper-Ensamble Trimodal con votación ponderada calibrada.
  - **EfficientNet-B0** (Peso: 0.35)
  - **ConvNeXt-Nano** (Peso: 0.35)
  - **ResNet-34d** (Peso: 0.30)
- **Rendimiento en conjunto de prueba (`test.csv`):**
  - **F1-Score Macro:** 88.68%
  - **Accuracy en Test:** 88.31%
- **Catálogo de especies:**
  *Zorzal patagónico, Rayadito, Chucao, Chercán, Tordo, Turca (endémica), Fío-fío, Chincol, Churrín de la Mocha, Churrín del sur, Picaflor chico, Canastero, Tijeral, Tapaculo (endémica), Colilarga.*

### B. Dominio Industrial — Diagnóstico de Fallas de Motor
- **Parámetros acústicos:** Remuestreo a 32.000 Hz, ventana temporal de 2.0 s, descomposición armónico-percusiva (HPSS) de 3 canales (Original, Armónico, Percusivo).
- **Modelo Campeón:** Ensamble Trimodal con optimización de márgenes y representación transferida.
  - **ResNet-34d** (Especialista en resonancias armónicas y transientes)
  - **EfficientNet-B0** (Representación espectro-temporal de alta resolución)
  - **PANNs-CNN14** (Preentrenado en AudioSet para acústica física)
- **Rendimiento validado:**
  - **Accuracy en Test:** 81.16%
  - **F1-Score Balanceado:** 81.44%
- **Catálogo de 13 condiciones y severidades:**
  - *Condición Normal (Línea Base / Operación Nominal)*
  - *Fallas de Encendido y Combustión (Misfire leve y severo, Fuga de Vacío, Desbalance)*
  - *Fallas Mecánicas y Válvulas (Cadena de Distribución, Luz de Válvulas, Picado de Biela)*
  - *Fallas de Auxiliares y Rodamientos (Tensor de Correa, Alternador, Bomba de Agua, Aire Acondicionado)*

---

## 4. Filtros Físicos Anti-Alucinación y Calibración

Para evitar falsos positivos en condiciones reales de campo o taller:
1. **Detector de Silencio Energético (RMS):** Si el valor RMS es inferior a $10^{-4}$, el registro se etiqueta como `"Silencio / No detectado"` sin consultar a la red neuronal.
2. **Detector de Ruido No Estructurado (Planitud Espectral):** Si la planitud espectral supera el umbral crítico ($> 0.15$), se clasifica como `"Ruido / Señal no acústica"`, evitando predicciones forzadas sobre viento o interferencia eléctrica.
3. **Calibración de Confianza (Temperature Scaling):** Calibración post-hoc ($T = 1.5$) sobre los logits que transforma puntuaciones sobreconfiadas en probabilidades continuas y confiables.

---

## 5. Módulos de la Plataforma Web (Frontend)

El frontend está desarrollado con Next.js 14, React y TypeScript, diseñado bajo una estética oscura profesional, sin emojis y utilizando iconos vectoriales SVG con etiquetas de estado:

1. **Dashboard:**
   - Visualización de KPIs globales y tarjetas dedicadas para los **Dos Modelos Campeones** (Bioacústica e Industrial).
   - Métricas de exactitud, F1-Score, tasa de certeza y latencia promedio.
   - Historial de actividad en tiempo real con distintivos de dominio `[Bioacústica]` y `[Industrial]`.
2. **Ingesta de Datos:**
   - Catálogo interactivo de datasets almacenados en el Data Lake (Google Cloud Storage) y almacenamiento local.
   - Modal de subida por lotes con asignación obligatoria de clase/categoría para mantener la jerarquía de entrenamiento.
   - Sincronización asíncrona bidireccional entre la nube y el servidor local.
3. **Entrenamiento:**
   - Configuración individual de hiperparámetros para las 5 arquitecturas base (`AudioCNN`, `EfficientNet-B0`, `ConvNeXt-Nano`, `ResNet-34d`, `PANNs-CNN14`).
   - Orquestador de **Tríada Completa (Ensamble)** adaptativo: selecciona automáticamente la canalización bioacústica o industrial según el dataset seleccionado.
   - Gráficos interactivos de evolución de pérdidas (*Loss*) y precisión por época.
4. **Predicción e Inferencia:**
   - Selector dinámico de modelos poblado en tiempo real desde el `ModelRegistry`.
   - Banner de especificaciones técnicas (frecuencia de muestreo, duración de ventana y número de clases).
   - Desglose de contribución porcentual por modelo individual dentro del ensamble.
   - Diagnósticos contextuales con niveles de severidad (`Operacional`, `Advertencia`, `Crítica`).

---

## 6. Estructura del Repositorio

```text
F.A.M.A/
├── backend/                    # Servidor de aplicaciones, APIs y pipelines de ML
│   ├── app/                    # Arquitectura modular FastAPI
│   │   ├── controllers/        # Lógica de aplicación y endpoints
│   │   ├── models/             # Modelos de base de datos relacionales (SQLAlchemy)
│   │   ├── routes/             # Enrutadores API (predict, training, ingestion, dashboard)
│   │   ├── schemas/            # Validación de contratos Pydantic
│   │   └── services/           # Servicios profundos (storage, ingestion, training, registry)
│   ├── checkpoints/            # Pesos de modelos entrenados (*.pt)
│   ├── data/                   # Índices locales, metadata y particiones de audio
│   ├── tests/                  # Suite de pruebas unitarias automatizadas (TDD)
│   ├── requirements.txt        # Dependencias de Python
│   └── .env.example            # Plantilla de variables de entorno
├── frontend/                   # Interfaz de usuario Next.js 14
│   ├── components/
│   │   ├── ui/                 # Componentes base del sistema de diseño
│   │   └── views/              # Vistas completas (Dashboard, Ingesta, Entrenamiento, Predicción)
│   ├── pages/                  # Rutas principales y puntos de entrada
│   └── package.json            # Dependencias de Node.js
├── docs/                       # Documentación técnica, ADRs y reportes científicos
├── .gitignore                  # Exclusión de claves, binarios y datos confidenciales
├── AGENTS.md                   # Directrices obligatorias de desarrollo y TDD
└── README.md                   # Esta documentación
```

---

## 7. Requisitos y Puesta en Marcha

### Requisitos Previos
- **Python 3.12+**
- **Node.js 18+** y **npm**
- **PostgreSQL 15+** en ejecución local o en red
- **Cuenta de Google Cloud** con Bucket de Cloud Storage y clave de Service Account (`.json`)

---

### Paso 1: Configurar el Backend

```bash
cd backend

# Crear y activar entorno virtual
python -m venv .venv
# En Windows:
.\.venv\Scripts\Activate.ps1
# En Linux/macOS:
source .venv/bin/activate

# Instalar dependencias
pip install -r requirements.txt

# Configurar variables de entorno
cp .env.example .env
```

Editar el archivo `backend/.env`:
```ini
DATABASE_URL=postgresql://postgres:tu_password@localhost:5432/fama_db
GOOGLE_APPLICATION_CREDENTIALS=tu_llave_servicio.json
GCP_KEY_PATH=tu_llave_servicio.json
GCS_BUCKET_NAME=fama-audio-records-2026
XC_API_KEY=tu_api_key_opcional
```

Crear la base de datos en PostgreSQL:
```bash
psql -U postgres -h localhost -c "CREATE DATABASE fama_db;"
```

Validar la suite de pruebas automatizadas:
```bash
pytest tests/ -v
```

Iniciar el backend en desarrollo:
```bash
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

---

### Paso 2: Configurar el Frontend

En una nueva terminal:
```bash
cd frontend

# Instalar dependencias
npm install

# Iniciar servidor de desarrollo
npm run dev
```

El panel estará disponible en [http://localhost:3000](http://localhost:3000) y la documentación de la API en [http://localhost:8000/docs](http://localhost:8000/docs).

---

## 8. Verificación y Calidad de Código (TDD)

El repositorio se rige estrictamente por la metodología **Test-Driven Development** (TDD) y tipado estricto:
- **Pruebas en Backend:** 174 pruebas unitarias e integrales aprobadas (`174 passed, 0 failed`).
- **Verificación en Frontend:** Compilación estricta sin errores de TypeScript (`npx tsc --noEmit` -> Código de salida 0).
