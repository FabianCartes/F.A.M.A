# F.A.M.A. — Backend de Servicios e Inferencia Bioacústica

Este directorio contiene el orquestador **FastAPI**, los modelos de Machine Learning (PyTorch), la integración de almacenamiento en la nube (**Google Cloud Storage**) y la persistencia en base de datos (**PostgreSQL**).

---

## 🛠️ Requisitos Previos

- **Python 3.12+**
- **PostgreSQL 15+** en ejecución local o accesible vía red.
- Llave de cuenta de servicio de Google Cloud (`.json`) para operaciones con GCS (opcional para pruebas sin almacenamiento cloud).

---

## 🚀 Puesta en Marcha Rápida

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

# Google Cloud Storage (RNF_03)
GOOGLE_APPLICATION_CREDENTIALS=tu_archivo_de_credenciales.json
GCS_BUCKET_NAME=tu-bucket-gcs

# Xeno-canto (opcional para descarga de dataset)
XC_API_KEY=tu_api_key
```

### 4. Crear la Base de Datos en PostgreSQL
Asegúrate de que PostgreSQL esté corriendo y crea la base de datos `fama_db`:
```bash
psql -U postgres -h localhost -c "CREATE DATABASE fama_db;"
```
*(Las tablas se crearán automáticamente al iniciar la aplicación).*

---

## 🧪 Ejecución de Pruebas Unitarias (TDD)

Para validar la suite completa de 22 pruebas automatizadas:
```bash
pytest tests/ -v
```

---

## 🌐 Iniciar el Servidor de Desarrollo

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

- **Swagger UI:** [http://localhost:8000/docs](http://localhost:8000/docs)
- **ReDoc:** [http://localhost:8000/redoc](http://localhost:8000/redoc)

---

## 📡 Endpoints Principales

- `GET /`: Comprobación del estado del servicio.
- `GET /health`: Liveness probe operacional.
- `POST /api/predict`: Endpoint principal. Recibe un archivo `.wav` (multipart/form-data), ejecuta la inferencia con discriminación física (RMS y Planitud Espectral), sube el archivo a Google Cloud Storage y persiste el resultado en la tabla `prediccion` de PostgreSQL.

Para detalles exhaustivos de arquitectura, consulta la documentación general en [`../docs/`](../docs/).
