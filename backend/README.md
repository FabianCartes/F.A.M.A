# F.A.M.A. — Backend de Servicios e Inferencia Acústica Multi-Dominio

Este directorio contiene el núcleo del backend de **F.A.M.A.**, implementado en **FastAPI**, que da soporte a los pipelines de inferencia y entrenamiento en PyTorch para bioacústica y acústica industrial automotriz, con persistencia en **PostgreSQL** y **Google Cloud Storage**.

---

## 1. Requisitos Previos

- **Python 3.12+**
- **PostgreSQL 15+** en ejecución local o accesible vía red.
- Llave de cuenta de servicio de Google Cloud (`.json`) para operaciones de persistencia e ingesta en Cloud Storage.

---

## 2. Puesta en Marcha Rápida

### 1. Crear y activar el entorno virtual
```bash
# En Windows (PowerShell):
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# En Linux / macOS:
python3 -m venv .venv
source .venv/bin/activate
```

### 2. Instalar dependencias
```bash
pip install -r requirements.txt
```

### 3. Configurar variables de entorno (`.env`)
Copia la plantilla `.env.example`:
```bash
cp .env.example .env
```
Edita `.env` con tus credenciales locales:
```ini
# Base de datos PostgreSQL
DATABASE_URL=postgresql://postgres:tu_password@localhost:5432/fama_db

# Google Cloud Storage (Persistencia e Ingesta)
GOOGLE_APPLICATION_CREDENTIALS=tu_llave_servicio.json
GCP_KEY_PATH=tu_llave_servicio.json
GCS_BUCKET_NAME=fama-audio-records-2026

# Xeno-canto (opcional para recolección de bioacústica)
XC_API_KEY=tu_api_key
```

### 4. Crear la Base de Datos en PostgreSQL
Asegúrate de que PostgreSQL esté corriendo y crea la base de datos `fama_db`:
```bash
psql -U postgres -h localhost -c "CREATE DATABASE fama_db;"
```
*(Las tablas se crearán automáticamente al iniciar la aplicación).*

---

## 3. Suite de Pruebas Automatizadas (TDD)

El backend cuenta con una cobertura integral bajo TDD (174 pruebas unitarias e integrales):
```bash
pytest tests/ -v
```

---

## 4. Iniciar el Servidor de Desarrollo

```bash
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

- **Swagger UI:** [http://localhost:8000/docs](http://localhost:8000/docs)
- **ReDoc:** [http://localhost:8000/redoc](http://localhost:8000/redoc)

---

## 5. Endpoints Principales de la API

- `GET /`: Comprobación del estado del servicio.
- `GET /health`: Liveness probe operacional.
- `GET /api/models`: Catálogo de modelos registrados y metadatos de arquitectura.
- `POST /api/predict?model_id={id}`: Inferencia multi-dominio. Procesa el audio con filtros físicos (RMS y Planitud Espectral), HPSS y votación calibrada, subiendo el registro a Google Cloud Storage y guardando los resultados en PostgreSQL.
- `GET /api/dashboard/stats`: Estadísticas globales y métricas de los dos modelos campeones.
- `GET /api/ingestion/datasets`: Listado de datasets en el Data Lake y local.
- `POST /api/ingestion/sync`: Sincronización asíncrona bidireccional con Google Cloud Storage.
- `POST /api/training/train`: Inicio y orquestación de entrenamientos (individuales o tríadas completas).
