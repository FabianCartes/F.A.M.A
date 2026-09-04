# F.A.M.A. — Framework MLOps Híbrido para Clasificación de Audio

[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/)
[![PyTorch](https://img.shields.io/badge/PyTorch-2.1+-ee4c2c.svg)](https://pytorch.org/)
[![Tests](https://img.shields.io/badge/tests-22%20passed-success.svg)](tests/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

> **Proyecto de Título / Tesis de Grado**  
> **Carrera:** Ingeniería Civil Informática  
> **Institución:** Universidad del Bío-Bío, Concepción, Chile  
> **Autores:** Fabián Cartes Oliva, Kevin Cárdenas Sepúlveda  
> **Profesor Guía:** Christian Vidal Castro  

---

## 📌 Descripción General

**F.A.M.A.** es un framework MLOps híbrido diseñado para el ciclo de vida completo de modelos de clasificación acústica. Permite desacoplar el procesamiento local de señales bioacústicas de la orquestación y el almacenamiento en la nube, optimizando el uso de recursos computacionales antes del despliegue en infraestructura cloud.

El dominio piloto seleccionado corresponde a la **clasificación bioacústica de 15 especies de aves comunes y endémicas de Chile**, utilizando grabaciones de campo de alta calidad (A y B) de la plataforma internacional [Xeno-canto](https://xeno-canto.org/).

---

## 🚀 Estado Actual del Proyecto: Prueba de Concepto (PoC) Validada

Actualmente se encuentra implementado y validado el **núcleo algorítmico local de Machine Learning**, estructurado bajo metodología estricta de **Test-Driven Development (TDD)** y arquitectura de **Módulos Profundos**:

```
                              PIPELINE BIOACÚSTICO F.A.M.A.
                              
 [ Xeno-canto v3 API ] ──> [ Descarga Concurrente ] ──> [ Catálogo data/metadata.csv ]
                                                                   │
                                                                   ▼
 [ Evaluación Test ] <── [ AudioCNN PyTorch ] <── [ Split Estratificado por Grabador ]
          │                    ▲                            (Zero Leakage)
          ▼                    │                                   │
 [ Matriz Confusión ]   [ Data Augmentation ]                      ▼
  (61.69% Test Acc)      - Pitch-shift                 [ Ventaneo Múltiple + VAD ]
                         - Ruido Gaussiano               - RMS relativo (top 25 dB)
                         - SpecAugment (Freq & Time)     - 5.0 s (22.050 Hz)
```

### 📊 Evolución de Métricas en Conjunto de Prueba (154 audios no vistos)

Ambas evaluaciones se ejecutaron sobre las **mismas 154 grabaciones del conjunto de prueba (`test.csv`)**, con estricto aislamiento por grabador (*Zero Recordist Leakage*) y evaluación 100% determinista:

| Métrica | Iteración 1: Baseline (Corte Estático 5s) | Iteración 2: Optimizado (VAD + Data Augmentation) | Impacto / Mejora |
|:---|:---:|:---:|:---:|
| **Accuracy en Test** | 44.16% | **61.69%** | **+17.53%** (vs. 6.67% azar) |
| **Precisión Macro** | 52.18% | **67.13%** | **+14.95%** |
| **Recall Macro** | 46.44% | **64.26%** | **+17.82%** |
| **F1-Score Macro** | 44.45% | **63.40%** | **+18.95%** |
| **Accuracy Validación** | 55.56% | **62.39%** | **+6.83%** |
| **Brecha Train-Test** | +29.07% *(Sobreajuste)* | **-1.73%** *(Generalización real)* | Regularización efectiva |

---

## 🦜 Especies Seleccionadas en el Dominio Piloto

Se catalogaron y descargaron **1.205 grabaciones** (calidad A y B) en `data/metadata.csv` respetando el esquema relacional de la tabla `audio` de la base de datos de F.A.M.A.:

1. **Zorzal patagónico** (*Turdus falcklandii*) — 174 audios
2. **Rayadito** (*Aphrastura spinicauda*) — 101 audios
3. **Chucao** (*Scelorchilus rubecula*) — 92 audios
4. **Chercán** (*Troglodytes aedon*) — 92 audios
5. **Tordo** (*Curaeus curaeus*) — 84 audios
6. **Turca** (*Pteroptochos megapodius*, *endémica*) — 76 audios
7. **Fío-fío** (*Elaenia chilensis*) — 76 audios
8. **Chincol** (*Zonotrichia capensis*) — 76 audios
9. **Churrín de la Mocha** (*Eugralla paradoxa*) — 75 audios
10. **Churrín del sur** (*Scytalopus magellanicus*) — 68 audios
11. **Picaflor chico** (*Sephanoides sephaniodes*) — 62 audios
12. **Canastero** (*Pseudasthenes humicola*) — 62 audios
13. **Tijeral** (*Leptasthenura aegithaloides*) — 59 audios
14. **Tapaculo** (*Scelorchilus albicollis*, *endémica*) — 57 audios
15. **Colilarga** (*Sylviorthorhynchus desmurii*) — 51 audios

---

## 📂 Estructura del Proyecto

El repositorio desacopla la arquitectura de servicios y Machine Learning (`backend/`) de la interfaz de usuario (`frontend/`):

```
F.A.M.A/
├── backend/                   # Backend en Python (FastAPI + Pipeline ML / PoC)
│   ├── app/                   # Aplicación FastAPI (arquitectura en capas)
│   │   ├── routes/            # Definición de endpoints HTTP
│   │   ├── controllers/       # Controladores y orquestación
│   │   ├── services/          # Servicios y lógica de negocio
│   │   ├── models/            # Modelos de dominio y persistencia
│   │   ├── middlewares/       # Middlewares de seguridad, CORS y logging
│   │   └── main.py            # Instancia de FastAPI con endpoint GET /health
│   ├── poc/                   # Módulos del pipeline bioacústico validado
│   │   ├── download.py        # Cliente API Xeno-canto v3 + cálculo SHA-256
│   │   ├── preprocess.py      # Remuestreo 22050Hz, Ventaneo VAD relativo y Mel-dB
│   │   ├── split.py           # Partición agrupada (Zero Recordist Leakage)
│   │   ├── train.py           # AudioDataset con caché RAM, AudioCNN, Data Augmentation
│   │   ├── evaluate.py        # Evaluación en Test Set y graficación de matriz
│   │   ├── confusion_matrix.png
│   │   └── confusion_matrix_augmented.png
│   ├── tests/                 # Suite de pruebas automatizadas (TDD)
│   ├── data/                  # Datasets locales y metadatos (ignorado en git)
│   ├── checkpoints/           # Pesos de modelos entrenados (ignorado en git)
│   ├── requirements.txt       # Dependencias de Python del backend
│   ├── .env.example           # Plantilla de variables de entorno
│   └── .env                   # Variables de entorno locales (ignorado en git)
├── frontend/                  # Aplicación Web Next.js (pendiente de inicialización)
│   └── README.md              # Documentación de reserva del frontend
├── docs/                      # Documentación académica y técnica
│   ├── VIDA_01_CINF_FINAL_PT_2026_1_CARTES.md  # Documento base de Anteproyecto
│   ├── 01_primera_prueba_poc.md               # Informe técnico Iteración 1
│   ├── 02_optimizacion_vad_data_augmentation.md # Informe técnico Iteración 2
│   ├── confusion_matrix_poc.png
│   └── confusion_matrix_augmented.png
├── .gitignore                 # Reglas de exclusión (backend/data/, frontend/.next/, etc.)
└── AGENTS.md                  # Directrices obligatorias de ingeniería y TDD
```

---

## 🛠️ Instalación y Configuración Local

### 1. Clonar el Repositorio
```bash
git clone https://github.com/FabianCartes/F.A.M.A.git
cd F.A.M.A
```

### 2. Configurar el Backend (Python 3.12)
```bash
cd backend

# En Windows (PowerShell)
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# En Linux / macOS
python3 -m venv .venv
source .venv/bin/activate

# Instalar dependencias
pip install -r requirements.txt
```

### 3. Configurar Variables de Entorno del Backend
Copia la plantilla y configura tu clave de API de Xeno-canto:
```bash
cp .env.example .env
```
Edita `.env`:
```ini
XC_API_KEY=tu_api_key_aqui
```

---

## 🧪 Ejecución del Backend, Pruebas y Pipeline

Desde el directorio `backend/`:

### 1. Iniciar Servidor de Desarrollo FastAPI
```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```
Verificar salud del servicio:
```bash
curl http://localhost:8000/health
# {"status": "ok"}
```

### 2. Ejecutar Suite Completa de Pruebas Unitarias (TDD)
```bash
python -m pytest tests/ -v
```

### 3. Ejecutar Pipeline Bioacústico (PoC)
```bash
# Descarga de audios
python -m poc.download

# Entrenamiento con VAD + Data Augmentation
python -m poc.train

# Evaluación en Test Set
python -m poc.evaluate --checkpoint checkpoints/augmented_best.pt --output poc/confusion_matrix_augmented.png
```

---

## 🗺️ Próximos Pasos en el Roadmap de F.A.M.A. v1.0

Una vez validado el núcleo de Machine Learning localmente, las siguientes fases de desarrollo corresponden a la arquitectura integral de la plataforma:

1. **Backend REST (FastAPI):** Endpoints orquestadores de ingesta, entrenamiento de modelos e inferencia bioacústica en tiempo real.
2. **Infraestructura Cloud:**
   - **Google Cloud Storage (GCS):** Almacenamiento distribuido de espectrogramas y grabaciones de campo.
   - **Cloud SQL (PostgreSQL):** Persistencia relacional de metadatos, usuarios, modelos y métricas de entrenamiento.
3. **Frontend (Next.js):** Panel de control interactivo para visualización de predicciones bioacústicas y gestión de pipelines.

