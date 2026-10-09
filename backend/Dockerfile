# ==============================================================================
# Dockerfile Backend F.A.M.A. (FastAPI + PyTorch)
# ==============================================================================
FROM python:3.12-slim

# Evitar prompts interactivos durante apt-get y asegurar buffering correcto de logs
ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Instalar dependencias de sistema requeridas para procesamiento bioacústico:
# - libsndfile1: lectura/escritura de audio (soundfile/librosa)
# - ffmpeg: decodificación y transcodificación de formatos de audio
# - build-essential, libpq-dev: compilación de extensiones y drivers PostgreSQL
# - curl: verificación de estado (healthcheck)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libsndfile1 \
    ffmpeg \
    curl \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copiar e instalar dependencias de Python primero para optimizar caché de capas Docker
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copiar el código fuente del backend
COPY . .

# Identidad segura por defecto; Compose utiliza la identidad numérica del host.
RUN groupadd --gid 10001 fama && \
    useradd --uid 10001 --gid 10001 --home-dir /home/fama --no-create-home fama && \
    install -d -o 10001 -g 10001 -m 0700 /home/fama && \
    mkdir -p /app/data /app/checkpoints && \
    chown 10001:10001 /app/data /app/checkpoints
ENV HOME=/home/fama
USER 10001:10001

# Argumento para URL de API con default para orquestación en red interna
ARG API_URL=http://backend:8000
ENV API_URL=${API_URL}

# Exponer el puerto del servidor API FastAPI
EXPOSE 8000

# Healthcheck interno del contenedor
HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Comando por defecto para iniciar FastAPI
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]

