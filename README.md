# F.A.M.A. — Framework MLOps Híbrido para Clasificación de Audio

[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688.svg)](https://fastapi.tiangolo.com/)
[![PyTorch](https://img.shields.io/badge/PyTorch-2.1+-ee4c2c.svg)](https://pytorch.org/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16+-336791.svg)](https://www.postgresql.org/)
[![Google Cloud Storage](https://img.shields.io/badge/GCS-Persistence-4285F4.svg)](https://cloud.google.com/storage)
[![Tests](https://img.shields.io/badge/tests-22%20passed-success.svg)](backend/tests/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

> **Proyecto de Título / Tesis de Grado**  
> **Carrera:** Ingeniería Civil Informática  
> **Institución:** Universidad del Bío-Bío, Concepción, Chile  
> **Autores:** Fabián Cartes Oliva, Kevin Cárdenas Sepúlveda  
> **Profesor Guía:** Christian Vidal Castro  

---

## 📌 Descripción General

**F.A.M.A.** es un framework MLOps híbrido diseñado para el ciclo de vida completo de modelos de clasificación acústica. Desacopla el preprocesamiento local de señales bioacústicas de la orquestación y el almacenamiento en la nube, optimizando el uso de recursos computacionales antes del despliegue en infraestructura cloud.

El dominio piloto seleccionado corresponde a la **clasificación bioacústica de 15 especies de aves comunes y endémicas de Chile**, utilizando grabaciones de campo de alta calidad (A y B) de la plataforma internacional [Xeno-canto](https://xeno-canto.org/).

---

## 🚀 Estado Actual del Proyecto: Orquestador FastAPI & Persistencia Híbrida

El sistema ha superado con éxito la fase de PoC algorítmica y cuenta actualmente con un **Orquestador RESTful (FastAPI)** conectado a almacenamiento en la nube (**Google Cloud Storage**) y persistencia relacional (**PostgreSQL**), conformando el *Minimum Viable Pipeline* de la arquitectura híbrida:

```
                               ARQUITECTURA DEL SISTEMA F.A.M.A.
                               
      [ Cliente Web / Frontend ] ──( Multipart / Form-Data .wav )──┐
                                                                   ▼
                                                       [ Orquestador FastAPI ]
                                                                   │
                       ┌───────────────────────────────────────────┴───────────────────────────────────────────┐
                       ▼                                                                                       ▼
         [ Pipeline Bioacústico ]                                                                  [ Capa de Persistencia ]
                       │                                                                                       │
      ┌────────────────┴────────────────┐                                                  ┌───────────────────┴───────────────────┐
      ▼                                 ▼                                                  ▼                                       ▼
 [ Filtro Físico ]            [ Inferencia CNN PyTorch ]                           [ Google Cloud Storage ]                 [ PostgreSQL (fama_db) ]
 - RMS Silencio (< 1e-4)      - Checkpoint augmented_best.pt                       - Subida asíncrona (RNF_03)              - Tabla: prediccion
 - Planitud Espectral         - Mel-Spectrogram (128 bandas)                       - Bucket audios_inferencia               - ID, ruta, etiqueta,
   (Flatness > 0.15 = Ruido)  - Calibración Temperature Scaling (T=1.5)            - UUIDv4 único por archivo                 confianza calibrada, UTC
```

### 📊 Desempeño del Modelo de Inferencia (`augmented_best.pt`)

Evaluado sobre **154 grabaciones independientes de prueba (`test.csv`)** con estricto aislamiento por grabador (*Zero Recordist Leakage*):

| Métrica | Baseline PoC (Corte 5s) | Optimizado (VAD + Data Augmentation) | Impacto / Mejora |
|:---|:---:|:---:|:---:|
| **Accuracy en Test** | 44.16% | **61.69%** | **+17.53%** (vs. 6.67% azar) |
| **Precisión Macro** | 52.18% | **67.13%** | **+14.95%** |
| **Recall Macro** | 46.44% | **64.26%** | **+17.82%** |
| **F1-Score Macro** | 44.45% | **63.40%** | **+18.95%** |
| **Mejor Acc. Validación** | 55.56% | **62.39%** | **+6.83%** |

### 🛡️ Robustecimiento e Inferencia Anti-Alucinación

1. **Discriminación de Silencio (RMS):** Si $\text{RMS} < 10^{-4}$, el audio se descarta de inmediato como `"Silencio / No detectado"` (confianza $0.0$).
2. **Discriminación de Ruido Blanco (Planitud Espectral):** Si $\text{Flatness} > 0.15$, se clasifica como `"Ruido / Señal no biológica"` (confianza $0.0$), impidiendo que el ruido ambiental forzado sea clasificado erróneamente como un ave.
3. **Calibración por Temperatura (*Temperature Scaling*):** Aplicación de $T = 1.5$ sobre los logits para devolver probabilidades de confianza suaves y continuas, evitando sobreconfianzas artificiales de Softmax ($0.9999$).

---

## 🦜 Catálogo de Especies del Dominio Piloto

El dataset catalogado en `backend/data/metadata.csv` contiene **1.205 audios** con hash SHA-256 distribuido en 15 especies chilenas:

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

## 📂 Estructura del Repositorio

El proyecto sigue una estructura desacoplada de monorepo:

```text
F.A.M.A/
├── .agents/                    # Directrices de ingeniería de agentes y TDD
├── docs/                       # Informes técnicos de avance y documentación de arquitectura
│   ├── 01_primera_prueba_poc.md               # Informe PoC y validación de baseline
│   ├── 02_optimizacion_vad_data_augmentation.md # Informe optimización VAD y Data Augmentation
│   ├── 03_orquestador_fastapi_gcs_postgresql.md # Informe backend, GCS y PostgreSQL
│   ├── VIDA_01_CINF_FINAL_PT_2026_1_CARTES.md   # Anteproyecto formal de título
│   ├── confusion_matrix_poc.png
│   └── confusion_matrix_augmented.png
├── frontend/                   # Interfaz de usuario web (en desarrollo)
│   └── README.md
├── backend/                    # Núcleo de servicios, APIs y modelos de ML
│   ├── app/                    # Aplicación FastAPI estructurada en capas
│   │   ├── controllers/        # Controladores de negocio desacoplados
│   │   ├── middlewares/        # Middlewares de seguridad, CORS y control de errores
│   │   ├── models/             # Modelos ORM y esquemas relacionales
│   │   │   └── prediction.py   # Modelo 'Prediccion' (tabla: prediccion)
│   │   ├── routes/             # Enrutadores modulares de la API
│   │   ├── services/           # Servicios desacoplados de infraestructura
│   │   │   └── storage.py      # Servicio asíncrono para Google Cloud Storage
│   │   ├── database.py         # Configuración del motor y sesiones de SQLAlchemy
│   │   └── main.py             # Instancia principal de FastAPI y endpoints
│   ├── poc/                    # Módulos profundos del pipeline bioacústico
│   │   ├── download.py         # Descarga concurrente desde Xeno-canto v3 + SHA-256
│   │   ├── preprocess.py       # Remuestreo 22050Hz, VAD relativo (top 25 dB) y Mel-dB
│   │   ├── split.py            # Partición agrupada estratificada (Zero Recordist Leakage)
│   │   ├── train.py            # AudioCNN, SpecAugment, pitch-shift y entrenamiento PyTorch
│   │   └── evaluate.py         # Evaluación determinista y cálculo de métricas en Test
│   ├── tests/                  # Suite de pruebas unitarias automatizadas (TDD)
│   ├── checkpoints/            # Pesos entrenados (augmented_best.pt)
│   ├── data/                   # Metadata e índices de audio locales
│   ├── requirements.txt        # Dependencias de Python
│   ├── .env.example            # Plantilla de variables de entorno
│   ├── .env                    # Configuración local (ignorado en Git)
│   ├── main.py                 # Adaptador raíz para levantar el orquestador
│   └── database.py             # Adaptador raíz de base de datos
├── .gitignore                  # Protección estricta de llaves IAM, credenciales y datasets
└── README.md                   # Esta documentación
```

---

## 🛠️ Requisitos Previos e Instalación

### Requisitos del Sistema
- **Python 3.12+**
- **PostgreSQL 15+** instalado y en ejecución en `localhost:5432` (o accesible vía red/Docker).
- **Cuenta de Google Cloud (GCP)** con un bucket en Google Cloud Storage y llave JSON de cuenta de servicio (opcional para pruebas locales sin cloud).

---

### Paso a Paso para la Puesta en Marcha

#### 1. Clonar el Repositorio
```bash
git clone https://github.com/FabianCartes/F.A.M.A.git
cd F.A.M.A
```

#### 2. Configurar el Entorno Virtual de Python
```bash
cd backend

# En Windows (PowerShell)
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# En Linux / macOS
python3 -m venv .venv
source .venv/bin/activate

# Instalar dependencias requeridas
pip install -r requirements.txt
```

#### 3. Configurar la Base de Datos PostgreSQL
Asegúrate de que el servicio de PostgreSQL esté activo y crea la base de datos `fama_db`:

```bash
# Ejemplo usando psql (ingresa tu contraseña cuando sea requerida):
psql -U postgres -h localhost -c "CREATE DATABASE fama_db;"
```
*(Nota: Las tablas de la base de datos se crearán automáticamente al iniciar la aplicación FastAPI gracias a SQLAlchemy).*

#### 4. Configurar las Variables de Entorno (`.env`)
Copia la plantilla de configuración en `backend/.env`:
```bash
cp .env.example .env
```
Edita el archivo `backend/.env` con tus valores locales:
```ini
# Base de datos PostgreSQL
DATABASE_URL=postgresql://postgres:tu_password@localhost:5432/fama_db

# Google Cloud Storage (Persistencia Cloud - RNF_03)
# Coloca tu archivo JSON de cuenta de servicio dentro de /backend (protegido por .gitignore)
GOOGLE_APPLICATION_CREDENTIALS=backend/tu_llave_servicio.json
GCS_BUCKET_NAME=nombre-de-tu-bucket-gcs

# API de Xeno-canto (opcional para re-descargar datos)
XC_API_KEY=tu_api_key_aqui
```

> [!WARNING]
> **Seguridad (RNF_03):** Nunca subas archivos `.env` ni llaves `.json` de Google Cloud al repositorio. Ya están configurados en `.gitignore`.

---

## 🧪 Verificación y Pruebas Unitarias (TDD)

El proyecto sigue la metodología **Test-Driven Development**. Para verificar que todos los componentes (preprocesamiento, VAD, división de datos, modelo CNN, entrenamiento y evaluación) funcionan correctamente:

```bash
# Desde la carpeta backend/
pytest tests/ -v

# O desde la raíz del proyecto
pytest backend/tests/ -v
```
*(Resultado esperado: **22 passed** sin errores).*

---

## 🚀 Ejecución del Servidor FastAPI

### 1. Iniciar el Orquestador en Modo Desarrollo
Desde el directorio `backend/`:
```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```
O desde la raíz del proyecto:
```bash
uvicorn backend.app.main:app --reload --host 0.0.0.0 --port 8000
```

### 2. Documentación Interactiva Swagger / OpenAPI
Una vez iniciado el servidor, abre en tu navegador:
- **Swagger UI:** [http://localhost:8000/docs](http://localhost:8000/docs)
- **ReDoc:** [http://localhost:8000/redoc](http://localhost:8000/redoc)

---

## 📡 Catálogo de Endpoints y Ejemplos de Uso

### `GET /` — Comprobación de Servicio
```bash
curl -X GET http://localhost:8000/
```
**Respuesta:**
```json
{"status": "F.A.M.A. Backend Operativo"}
```

### `GET /health` — Liveness Probe / Salud
```bash
curl -X GET http://localhost:8000/health
```
**Respuesta:**
```json
{"status": "ok"}
```

### `POST /api/predict` — Inferencia Bioacústica
Envía un archivo `.wav` mediante `multipart/form-data`:

```bash
# En Linux / macOS / Git Bash
curl -X POST "http://localhost:8000/api/predict" \
     -H "accept: application/json" \
     -H "Content-Type: multipart/form-data" \
     -F "file=@ruta/a/tu/audio_muestra.wav"
```

```powershell
# En Windows (PowerShell)
Invoke-RestMethod -Uri "http://localhost:8000/api/predict" `
                  -Method Post `
                  -Form @{ file = Get-Item "ruta\a\tu\audio_muestra.wav" }
```

**Respuesta Exitosa (JSON):**
```json
{
  "prediccion": "Turdus falcklandii",
  "confianza": 0.8412,
  "id_registro": 1,
  "gcs_uri": "gs://mi-bucket-fama/audios_inferencia/20260904_120000_a1b2c3d4.wav"
}
```

**Respuesta ante Silencio o Ruido No Biológico:**
```json
{
  "prediccion": "Ruido / Señal no biológica",
  "confianza": 0.0,
  "id_registro": 2,
  "gcs_uri": null
}
```

---

## 📚 Documentación Técnica e Informes de Avance

Para profundizar en los fundamentos científicos, análisis matemáticos y decisiones de arquitectura del proyecto, consulta los informes en el directorio [`docs/`](docs/):

1. [**docs/01_primera_prueba_poc.md**](docs/01_primera_prueba_poc.md): PoC inicial, dataset de 15 especies y baseline en PyTorch (44.16% Acc).
2. [**docs/02_optimizacion_vad_data_augmentation.md**](docs/02_optimizacion_vad_data_augmentation.md): Segmentación VAD por energía relativa, SpecAugment y mejora sustancial a 61.69% Acc.
3. [**docs/03_orquestador_fastapi_gcs_postgresql.md**](docs/03_orquestador_fastapi_gcs_postgresql.md): Arquitectura en capas de FastAPI, discriminadores físicos de señal, calibración de confianza, persistencia en Google Cloud Storage y base de datos relacional PostgreSQL.
4. [**docs/VIDA_01_CINF_FINAL_PT_2026_1_CARTES.md**](docs/VIDA_01_CINF_FINAL_PT_2026_1_CARTES.md): Documento oficial de anteproyecto de titulación.

---

## 🗺️ Próximos Pasos en el Roadmap

1. **Frontend Web (`/frontend`):** Desarrollo del panel interactivo para carga y grabación de audios, visualizador espectral en tiempo real y vista histórica de inferencias.
2. **Contenerización Completa:** Empaquetado en contenedores Docker y orquestación con `docker-compose` (FastAPI + PostgreSQL + Frontend).
3. **CI/CD y MLOps Pipelines:** Automatización de re-entrenamiento continuo y versionado de modelos.
