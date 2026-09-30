# Guía de Despliegue Operativo Institucional con Docker
### Manual Exhaustivo de Instalación, Configuración Cloud, Base de Datos y Resolución de Problemas
**Framework MLOps Híbrido para Clasificación Bioacústica y Diagnóstico Industrial (F.A.M.A.)**  
*Documentación Técnica Correspondiente a la Actividad 12 de la Tesis de Grado (Ingeniería Civil en Informática, Universidad del Bío-Bío)*

---

## 1. Introducción y Arquitectura de Contenedores

La presente guía detalla los procedimientos técnicos estandarizados para instalar, configurar y mantener en producción el sistema **F.A.M.A.** en infraestructuras institucionales (laboratorios de investigación, servidores departamentales o estaciones de trabajo universitarias).

Para eliminar por completo la "fricción de instalación" —uno de los mayores motivos de fracaso en despliegues de Machine Learning— F.A.M.A. adopta el estándar de empaquetado mediante **Contenedores Docker multi-etapa orquestados con Docker Compose**. Esto aísla las dependencias críticas del sistema operativo (Python 3.12, Node.js 20, CUDA Toolkit 12.4, PostgreSQL 16 y librerías de procesamiento de audio como `libsndfile` y `ffmpeg`), garantizando que la plataforma funcione de forma determinista y reproducible en cualquier servidor institucional equipado con aceleración gráfica NVIDIA.

```text
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                        ARQUITECTURA DE CONTENEDORES F.A.M.A.                           │
└────────────────────────────────────────────────────────────────────────────────────────┘

    [Red Externa / Intranet Universitaria]
                     │
         ┌───────────┴───────────┐
         │                       │ Puerto 3000: Web GUI
         │ Puerto 8000: API REST │
         ▼                       ▼
┌──────────────────┐    ┌──────────────────┐
│ fama-frontend    │    │ fama-backend     │◄────── NVIDIA Container Toolkit
│ Next.js 15 Stand.│    │ FastAPI + PyTorch│       (Acceso directo a GPU/CUDA)
│ (Puerto 3000)    │    │ (Puerto 8000)    │
└────────┬─────────┘    └────────┬─────────┘
         │                       │
         └───────────┬───────────┘
                     │ Red Puente Privada Docker: fama-network
                     ▼
         ┌───────────────────────┐
         │ fama-postgres         │
         │ PostgreSQL 16 Alpine  │
         │ (Puerto 5432)         │
         └───────────┬───────────┘
                     │
        ┌────────────┴────────────┐
        ▼                         ▼
┌───────────────────────┐ ┌───────────────────────┐
│ VOLÚMENES PERSISTENTES│ │ RECURSOS EXTERNOS GCP │
│ • postgres_data       │ │ • Google Cloud Storage│
│ • checkpoints_cache   │ │   (Bucket institucional)
│ • datasets_local      │ │ • Service Account IAM │
└───────────────────────┘ └───────────────────────┘
```

---

## 2. Requisitos de Sistema y Matriz de Compatibilidad

### 2.1. Especificaciones de Hardware

| Componente | Requisito Mínimo Institucional | Requisito Recomendado (Rendimiento Óptimo) |
| :--- | :--- | :--- |
| **Procesador (CPU)** | Intel Core i5 / AMD Ryzen 5 (4 núcleos, 8 hilos) | Intel Core i7 / AMD Ryzen 7 / Xeon (8+ núcleos, 16 hilos) |
| **Memoria RAM** | 16 GB DDR4 | 32 GB o 64 GB DDR4/DDR5 |
| **Tarjeta Gráfica (GPU)** | NVIDIA con arquitectura Pascal o superior (GTX 1060 6GB / GTX 1660) | NVIDIA RTX 3060 (12GB), RTX 4070 (12GB), RTX 3080/4080 o Tesla/A100 |
| **Memoria de Video (VRAM)**| 6 GB VRAM dedicados | 8 GB a 16 GB VRAM dedicados (Permite entrenar Tríadas completas) |
| **Almacenamiento** | 60 GB libres en SSD (SATA III) | 250 GB+ libres en SSD NVMe M.2 (Lectura secuencial > 2500 MB/s) |
| **Conexión de Red** | 100 Mbps Ethernet / Wi-Fi 5 | 1 Gbps Ethernet institucional (Baja latencia con Google Cloud) |

### 2.2. Especificaciones de Software y Controladores

* **Sistema Operativo del Host:**
  * **Linux:** Ubuntu 22.04 LTS o Ubuntu 24.04 LTS (x86_64).
  * **Windows:** Windows 10 Pro / Enterprise o Windows 11 (versión 22H2 o superior) con **WSL2** activado.
* **Controlador Gráfico NVIDIA (Host):**
  * Versión del Driver NVIDIA ≥ 535.xx (Windows / Linux).
  * Soporte CUDA a nivel de driver ≥ 12.2.
* **Motor de Contenedores:**
  * **Docker Engine** v24.0 o superior + **Docker Compose v2** (v2.24+).
  * O bien **Docker Desktop** v4.28+ con soporte WSL2 y aceleración GPU habilitada.
* **NVIDIA Container Toolkit:** Requerido en entornos Linux para enlazar la GPU física con el runtime de Docker.

---

## 3. Instalación del Entorno Docker con Soporte GPU

### 3.1. Procedimiento en Windows (Docker Desktop + WSL2)

1. **Habilitación de Virtualización:**  
   Verifique en la BIOS/UEFI de la máquina que la tecnología de virtualización (Intel VT-x o AMD-V) se encuentre **habilitada**.
2. **Instalación de WSL2 (Windows Subsystem for Linux):**  
   Abra PowerShell como Administrador y ejecute:
   ```powershell
   wsl --install -d Ubuntu-22.04
   wsl --set-default-version 2
   ```
   Reinicie el computador si el instalador lo solicita.
3. **Instalación de Controladores NVIDIA en Windows:**  
   Descargue e instale el controlador más reciente desde el sitio oficial de NVIDIA (GeForce Game Ready o NVIDIA Studio Driver). En Windows con WSL2, los controladores de video instalados en el host se exponen de forma nativa a los subsistemas Linux sin necesidad de instalar controladores adicionales dentro de WSL2.
4. **Instalación de Docker Desktop:**  
   * Descargue Docker Desktop para Windows.
   * Durante la instalación, marque la casilla: *"Use WSL 2 instead of Hyper-V (recommended)"*.
5. **Configuración de Docker Desktop:**  
   * Abra Docker Desktop y diríjase a **Settings (icono de engranaje) > General**.
   * Asegúrese de que esté marcada la opción: *"Use the WSL 2 based engine"*.
   * En **Settings > Resources > WSL Integration**, active la casilla *"Enable integration with my default WSL distro"* y active el interruptor para `Ubuntu-22.04`.
   * Presione **Apply & Restart**.

### 3.2. Procedimiento en Linux (Ubuntu 22.04 / 24.04 LTS)

1. **Instalación de Controladores NVIDIA:**
   ```bash
   sudo apt update
   sudo apt install -y ubuntu-drivers-common
   sudo ubuntu-drivers autoinstall
   sudo reboot
   ```
   Verifique la instalación tras el reinicio ejecutando `nvidia-smi`.
2. **Instalación de Docker CE y Docker Compose:**
   ```bash
   # Remover paquetes antiguos conflictivos
   sudo apt remove -y docker docker-engine docker.io containerd runc

   # Configurar repositorio oficial de Docker
   sudo apt update
   sudo apt install -y ca-certificates curl gnupg lsb-release
   sudo install -m 0755 -d /etc/apt/keyrings
   curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
   sudo chmod a+r /etc/apt/keyrings/docker.gpg

   echo \
     "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
     $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

   sudo apt update
   sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

   # Permitir ejecución sin sudo
   sudo usermod -aG docker $USER
   ```
3. **Instalación y Configuración del NVIDIA Container Toolkit (Exclusivo para Host Linux):**

   > [!IMPORTANT]
   > **Requisito Exclusivo para Linux:** En Windows con WSL2, los controladores NVIDIA del host se exponen automáticamente a Docker Desktop. En sistemas Linux nativos, es **estrictamente obligatorio** instalar `nvidia-container-toolkit` y configurar el runtime en el daemon de Docker para que los contenedores puedan detectar la tarjeta física (como la RTX 2050). Si se omite, Docker arrojará `failed to discover GPU vendor from CDI: no known GPU vendor found` y el backend se degradará a modo CPU.

   * **En distribuciones basadas en Debian / Ubuntu:**
     ```bash
     curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
     curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | \
       sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
       sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list

     sudo apt update
     sudo apt install -y nvidia-container-toolkit

     # Configurar runtime de Docker y reiniciar el servicio
     sudo nvidia-ctk runtime configure --runtime=docker
     sudo systemctl restart docker
     ```

   * **En distribuciones basadas en Arch Linux / Manjaro:**
     ```bash
     # 1. Instalar el toolkit desde los repositorios oficiales
     sudo pacman -S nvidia-container-toolkit

     # 2. Registrar el runtime de NVIDIA en /etc/docker/daemon.json
     sudo nvidia-ctk runtime configure --runtime=docker

     # 3. Reiniciar el servicio de Docker
     sudo systemctl restart docker
     ```

   * **En el archivo `docker-compose.yml` del proyecto:**
     Asegúrese de mantener activa la reserva de GPU en el servicio `backend`:
     ```yaml
     deploy:
       resources:
         reservations:
           devices:
             - driver: nvidia
               count: all
               capabilities: [gpu]
     ```

### 3.3. Prueba de Verificación de CUDA en Contenedor

Para verificar que Docker tiene acceso directo a la tarjeta gráfica antes de desplegar F.A.M.A., ejecute:
```bash
docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi
```
**Resultado esperado:** Debe desplegarse la tabla estándar de `nvidia-smi` indicando el nombre de su tarjeta NVIDIA (ej. *NVIDIA GeForce RTX 3060*), versión del driver y versión de CUDA. Si este comando falla, no continúe; revise la sección de Troubleshooting.

---

## 4. Configuración de Google Cloud Platform y Service Account

F.A.M.A. utiliza Google Cloud Storage como Data Lake institucional. **Ningún usuario final (alumno o investigador) debe gestionar cuentas de Google Cloud**. La institución crea una única Cuenta de Servicio centralizada con permisos controlados.

```mermaid
flowchart TD
    Console["Google Cloud Console\n(Administrador TI)"] --> Project["Proyecto GCP\nfama-bioacustica-ubb"]
    Project --> Bucket["Bucket GCS\nfama-bioacustica-storage\n(Región: Santiago)"]
    Project --> SA["Cuenta de Servicio IAM\nfama-orchestrator@..."]
    SA -- "Rol: Storage Object Admin" --> Bucket
    SA --> Key["Clave Privada JSON\nfama-gcs-credentials.json"]
    Key --> Mount["Montaje Seguro en Docker\n/app/credentials/gcs-key.json"]
    Mount --> Backend["FastAPI Backend\nGOOGLE_APPLICATION_CREDENTIALS"]
```

### 4.1. Creación del Bucket en Google Cloud Storage
1. Ingrese a la consola de Google Cloud: [https://console.cloud.google.com](https://console.cloud.google.com).
2. Cree un nuevo proyecto o seleccione uno existente (ejemplo: `fama-bioacustica-ubb`).
3. Vaya a **Cloud Storage > Buckets** y haga clic en **Crear**.
4. Ingrese los parámetros de configuración institucional:
   * **Nombre del Bucket:** Debe ser único a nivel global (ejemplo: `fama-bioacustica-storage-ubb`).
   * **Ubicación:** Seleccione `Region` y elija la zona geográfica más cercana al campus (por ejemplo, `southamerica-west1` Santiago de Chile para minimizar latencias a menos de 15 ms).
   * **Clase de almacenamiento por defecto:** `Standard` (permite lecturas y escrituras frecuentes a costo mínimo).
   * **Control de Acceso:** `Uniforme` (Recomendado por Google para seguridad IAM).
   * **Protección de datos:** Sin retención o con historial de versiones opcional.
5. Haga clic en **Crear**.

### 4.2. Creación de la Cuenta de Servicio (Service Account)
1. En el menú de navegación, diríjase a **IAM y administración > Cuentas de servicio**.
2. Haga clic en **Crear cuenta de servicio**:
   * **Nombre de la cuenta de servicio:** `fama-orchestrator`
   * **ID de la cuenta de servicio:** `fama-orchestrator`
   * **Descripción:** *Cuenta de servicio institucional para orquestación de audios y datasets en F.A.M.A.*
3. Presione **Crear y continuar**.
4. En el paso de asignación de roles, asigne estrictamente el rol:
   * **Storage > Administrador de objetos de almacenamiento** (`roles/storage.objectAdmin`).
   > *Nota de Seguridad:* No asigne roles de Propietario (`Owner`) ni Editor global. El rol `Storage Object Admin` confiere únicamente permisos de lectura, creación y eliminación de blobs en Cloud Storage, cumpliendo el principio de menor privilegio.
5. Haga clic en **Continuar** y luego en **Listo**.

### 4.3. Generación y Resguardo de la Llave Criptográfica JSON
1. En la lista de Cuentas de Servicio, haga clic sobre la cuenta recién creada (`fama-orchestrator@...`).
2. Diríjase a la pestaña **Claves (Keys)**.
3. Haga clic en **Agregar clave > Crear clave nueva**.
4. Seleccione el tipo de clave **JSON** y presione **Crear**.
5. El navegador descargará automáticamente un archivo con nombre similar a `fama-bioacustica-ubb-d8f93a123456.json`.
6. **Renombrado y Protección:**
   * Renombre el archivo a: `fama-gcs-credentials.json`.
   * En el servidor institucional, guarde el archivo en el directorio seguro del proyecto:
     ```bash
     mkdir -p /home/usuario/fama/credentials
     mv ~/Descargas/fama-gcs-credentials.json /home/usuario/fama/credentials/
     chmod 600 /home/usuario/fama/credentials/fama-gcs-credentials.json
     ```

---

## 5. Configuración de PostgreSQL y Modelo de Datos Relacional

F.A.M.A. utiliza PostgreSQL como motor de base de datos relacional para registrar usuarios, datasets indexados, audios individuales, checkpoints entrenados, historial de inferencias y retroalimentación activa (`RF_06`).

### 5.1. Esquema Relacional de 8 Tablas Normalizadas

Al iniciar el contenedor del backend, SQLAlchemy ejecuta automáticamente el mapeo objeto-relacional (`Base.metadata.create_all`) generando de forma idempotente las 8 tablas oficiales:

```text
┌─────────────────────────┐       ┌─────────────────────────┐
│         usuario         │       │    nodo_procesamiento   │
├─────────────────────────┤       ├─────────────────────────┤
│ id_usuario (PK)         │       │ id_nodo (PK)            │
│ nombre_completo         │       │ nombre_nodo / ip_nodo   │
│ correo_institucional    │       │ estado_hardware         │
│ hash_contrasena         │       │ vram_total_mb           │
│ rol (Admin/Investigador)│       │ fecha_ultimo_ping       │
└────────────┬────────────┘       └─────────────────────────┘
             │
             ├──────────────────────────────────┐
             ▼                                  ▼
┌─────────────────────────┐       ┌─────────────────────────┐
│     conjunto_datos      │       │         modelo          │
├─────────────────────────┤       ├─────────────────────────┤
│ id_conjunto_datos (PK)  │       │ id_modelo (PK)          │
│ nombre_dataset          │       │ arquitectura            │
│ total_audios            │       │ ruta_checkpoint         │
│ estado_sincronizacion   │       │ exactitud_validacion    │
│ id_usuario_creador (FK) │       │ f1_macro / activo (bool)│
└────────────┬────────────┘       └─────────────┬───────────┘
             │                                  │
             ▼                                  ▼
┌─────────────────────────┐       ┌─────────────────────────┐
│          audio          │       │  metrica_entrenamiento  │
├─────────────────────────┤       ├─────────────────────────┤
│ id_audio (PK)           │       │ id_metrica (PK)         │
│ id_conjunto_datos (FK)  │       │ id_modelo (FK)          │
│ nombre_archivo          │       │ epoca / loss_entrenamiento
│ ruta_gcs / ruta_local   │       │ loss_validacion         │
│ etiqueta_clase / tensor │       │ exactitud_entrenamiento │
└─────────────────────────┘       └─────────────────────────┘
                                                │
             ┌──────────────────────────────────┘
             ▼
┌─────────────────────────┐       ┌─────────────────────────┐
│        prediccion       │       │    retroalimentacion    │
├─────────────────────────┤       ├─────────────────────────┤
│ id_prediccion (PK)      │◄──────┤ id_retroalimentacion(PK)│
│ ruta_audio_prueba       │       │ id_prediccion (FK, UQ)  │
│ etiqueta_predicha       │       │ id_usuario (FK)         │
│ confianza_calculada     │       │ fue_correcta (bool)     │
│ modelo_id / fecha_creac │       │ etiqueta_corregida      │
└─────────────────────────┘       └─────────────────────────┘
```

### 5.2. Opciones de Despliegue de Base de Datos
* **Modalidad Integrada (Contenedor Docker - Recomendada):**  
  El archivo `docker-compose.yml` aprovisiona automáticamente un contenedor `postgres:16-alpine` con almacenamiento persistente en un volumen Docker dedicado (`postgres_data`). No requiere ninguna intervención manual.
* **Modalidad Gestionada (Google Cloud SQL):**  
  Si la institución prefiere delegar el mantenimiento en la nube, basta con modificar la variable `DATABASE_URL` en el archivo `.env` apuntando a la IP pública o privada de la instancia de Cloud SQL:
  ```env
  DATABASE_URL=postgresql://fama_user:ClaveSegura123@10.128.0.5:5432/fama_db
  ```

---

## 6. Archivos Oficiales de Empaquetado Docker

A continuación se presentan las especificaciones exactas de los artefactos de compilación.

### 6.1. Dockerfile del Backend (`backend/Dockerfile`)

```dockerfile
# ============================================================================
# BACKEND DOCKERFILE - F.A.M.A. MLOps Platform
# Base oficial de NVIDIA CUDA 12.4 sobre Ubuntu 22.04 LTS
# ============================================================================
FROM nvidia/cuda:12.4.1-runtime-ubuntu22.04

# Configurar variables para ejecución no interactiva y optimización de Python
ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    LC_ALL=C.UTF-8 \
    LANG=C.UTF-8

# Instalar dependencias del sistema operativo y librerías acústicas
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.12 \
    python3.12-venv \
    python3.12-dev \
    python3-pip \
    build-essential \
    libsndfile1 \
    libsndfile1-dev \
    ffmpeg \
    sox \
    libsox-fmt-all \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Configurar alias de Python 3.12
RUN update-alternatives --install /usr/bin/python python /usr/bin/python3.12 1 \
    && update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.12 1

WORKDIR /app

# Actualizar gestor de paquetes pip
RUN python -m pip install --no-cache-dir --upgrade pip setuptools wheel

# Copiar dependencias de requerimientos
COPY requirements.txt /app/requirements.txt

# Instalar PyTorch oficial con aceleración CUDA 12.4
RUN python -m pip install --no-cache-dir \
    torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu124

# Instalar el resto de dependencias del framework
RUN python -m pip install --no-cache-dir -r requirements.txt

# Copiar el código fuente completo del backend
COPY . /app

# Crear directorios de trabajo para almacenamiento persistente y caché
RUN mkdir -p /app/data /app/checkpoints /app/audios_prueba /app/credentials

# Exponer el puerto del API FastAPI
EXPOSE 8000

# Comando de arranque del servidor Uvicorn con recarga optimizada
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
```

### 6.2. Dockerfile del Frontend (`frontend/Dockerfile`)

```dockerfile
# ============================================================================
# FRONTEND DOCKERFILE - F.A.M.A. MLOps Platform
# Compilación Multi-Etapa Optimizada con Node.js 20 Alpine
# ============================================================================

# ETAPA 1: Instalación de dependencias
FROM node:20-alpine AS deps
RUN apk add --no-cache libc6-compat
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

# ETAPA 2: Compilación de producción
FROM node:20-alpine AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . ./

# Desactivar telemetría de Next.js
ENV NEXT_TELEMETRY_DISABLED=1
ENV NODE_ENV=production

RUN npm run build

# ETAPA 3: Imagen final ligera para ejecución
FROM node:20-alpine AS runner
WORKDIR /app

ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1

RUN addgroup --system --gid 1001 nodejs && \
    adduser --system --uid 1001 nextjs

COPY --from=builder /app/public ./public
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static

USER nextjs

EXPOSE 3000
ENV PORT=3000
ENV HOSTNAME="0.0.0.0"

CMD ["node", "server.js"]
```

### 6.3. Orquestador Maestro (`docker-compose.yml`)

```yaml
version: "3.8"

services:
  # ==========================================================================
  # SERVICIO 1: BASE DE DATOS RELACIONAL POSTGRESQL 16
  # ==========================================================================
  db:
    image: postgres:16-alpine
    container_name: fama-db
    restart: unless-stopped
    environment:
      POSTGRES_USER: ${POSTGRES_USER:-postgres}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-postgres_seguro_2026}
      POSTGRES_DB: ${POSTGRES_DB:-fama_db}
    ports:
      - "${POSTGRES_PORT:-5432}:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER:-postgres} -d ${POSTGRES_DB:-fama_db}"]
      interval: 10s
      timeout: 5s
      retries: 5
    networks:
      - fama-network

  # ==========================================================================
  # SERVICIO 2: BACKEND ORQUESTADOR FASTAPI (CON ACELERACIÓN GPU NVIDIA)
  # ==========================================================================
  backend:
    build:
      context: ./backend
      dockerfile: Dockerfile
    container_name: fama-backend
    restart: unless-stopped
    depends_on:
      db:
        condition: service_healthy
    environment:
      DATABASE_URL: postgresql://${POSTGRES_USER:-postgres}:${POSTGRES_PASSWORD:-postgres_seguro_2026}@db:5432/${POSTGRES_DB:-fama_db}
      GCS_BUCKET_NAME: ${GCS_BUCKET_NAME:-fama-bioacustica-storage-ubb}
      GOOGLE_APPLICATION_CREDENTIALS: /app/credentials/fama-gcs-credentials.json
      GCP_KEY_PATH: /app/credentials/fama-gcs-credentials.json
      XC_API_KEY: ${XC_API_KEY:-}
      CORS_ALLOWED_ORIGINS: ${CORS_ALLOWED_ORIGINS:-http://localhost:3000,http://127.0.0.1:3000}
    ports:
      - "${BACKEND_PORT:-8000}:8000"
    volumes:
      - ./credentials/fama-gcs-credentials.json:/app/credentials/fama-gcs-credentials.json:ro
      - checkpoints_data:/app/checkpoints
      - datasets_data:/app/data
      - test_audios_data:/app/audios_prueba
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: all
              capabilities: [gpu]
    networks:
      - fama-network

  # ==========================================================================
  # SERVICIO 3: FRONTEND INTERACTIVO NEXT.JS (DASHBOARD)
  # ==========================================================================
  frontend:
    build:
      context: ./frontend
      dockerfile: Dockerfile
    container_name: fama-frontend
    restart: unless-stopped
    depends_on:
      - backend
    environment:
      NEXT_PUBLIC_API_URL: ${NEXT_PUBLIC_API_URL:-http://localhost:8000}
    ports:
      - "${FRONTEND_PORT:-3000}:3000"
    networks:
      - fama-network

# ============================================================================
# VOLÚMENES PERSISTENTES Y RED PRIVADA
# ============================================================================
volumes:
  postgres_data:
    name: fama_postgres_volume
  checkpoints_data:
    name: fama_checkpoints_volume
  datasets_data:
    name: fama_datasets_volume
  test_audios_data:
    name: fama_test_audios_volume

networks:
  fama-network:
    name: fama_internal_bridge
    driver: bridge
```

### 6.4. Archivo de Variables de Entorno (`.env.production`)

Cree un archivo `.env` en la raíz del proyecto junto al `docker-compose.yml`:

```env
# ============================================================================
# CONFIGURACIÓN OPERATIVA DE F.A.M.A. - PRODUCCIÓN
# ============================================================================

# 1. Base de Datos Relacional PostgreSQL
POSTGRES_USER=fama_admin
POSTGRES_PASSWORD=ClaveInstitucionalRobusta2026!
POSTGRES_DB=fama_db
POSTGRES_PORT=5432

# 2. Google Cloud Storage Data Lake
GCS_BUCKET_NAME=fama-bioacustica-storage-ubb
GOOGLE_APPLICATION_CREDENTIALS=/app/credentials/fama-gcs-credentials.json

# 3. Mapeo de Puertos Web
FRONTEND_PORT=3000
BACKEND_PORT=8000

# 4. URLs de Interconexión y CORS
# Si el acceso es por intranet institucional, use la IP del servidor (ej. http://192.168.1.100:8000)
NEXT_PUBLIC_API_URL=http://localhost:8000
CORS_ALLOWED_ORIGINS=http://localhost:3000,http://127.0.0.1:3000,http://192.168.1.100:3000
```

---

## 7. Puesta en Marcha y Scripts de Automatización

### 7.1. Procedimiento de Lanzamiento Estándar

1. **Clonar o Ubicar el Repositorio:**
   ```bash
   cd /home/usuario/fama
   ```
2. **Verificar que la Credencial de GCP esté en su Lugar:**
   ```bash
   ls -la credentials/fama-gcs-credentials.json
   ```
3. **Construir las Imágenes de Contenedores:**
   ```bash
   docker compose build
   ```
4. **Encender los Servicios en Segundo Plano:**
   ```bash
   docker compose up -d
   ```
5. **Inspeccionar el Estado de Salud de los Contenedores:**
   ```bash
   docker compose ps
   ```
   **Resultado esperado:**
   ```text
   NAME            IMAGE             COMMAND                  SERVICE    STATUS
   fama-db         postgres:16       "docker-entrypoint.s…"   db         Up (healthy)
   fama-backend    fama-backend      "uvicorn app.main:ap…"   backend    Up
   fama-frontend   fama-frontend     "node server.js"         frontend   Up
   ```
6. **Abrir el Sistema:** Abra el navegador en `http://localhost:3000` (o la IP asignada).

### 7.2. Scripts de Ejecución Rápida de Dos Clics

Para entregar al personal de laboratorio una experiencia completamente libre de terminales:

#### Script para Linux / macOS: `iniciar_fama.sh`
```bash
#!/bin/bash
echo "=========================================================="
echo "    INICIANDO FRAMEWORK MLOPS HÍBRIDO F.A.M.A. (UBB)     "
echo "=========================================================="

# Validar existencia de Docker
if ! command -v docker &> /dev/null; then
    echo "[ERROR] Docker no está instalado en este sistema."
    exit 1
fi

# Validar archivo de credenciales
if [ ! -f "./credentials/fama-gcs-credentials.json" ]; then
    echo "[AVISO] No se encontró ./credentials/fama-gcs-credentials.json."
    echo "Recuerde cargarlo en el asistente web de primer inicio (/setup)."
fi

# Levantar contenedores
docker compose up -d

echo ""
echo "[OK] Contenedores en ejecución exitosa."
echo "Acceda a la plataforma web ingresando a: http://localhost:3000"
echo "Para supervisar los logs en tiempo real ejecute: docker compose logs -f"
```

#### Script para Windows: `iniciar_fama.bat`
```batch
@echo off
title Iniciando F.A.M.A. MLOps Platform
echo ==========================================================
echo     INICIANDO FRAMEWORK MLOPS HÍBRIDO F.A.M.A. (UBB)     
echo ==========================================================

docker compose up -d
if %errorlevel% neq 0 (
    echo [ERROR] No se pudo iniciar Docker Compose. Verifique que Docker Desktop este abierto.
    pause
    exit /b %errorlevel%
)

echo.
echo [OK] Plataforma F.A.M.A. iniciada exitosamente.
echo Abriendo navegador en http://localhost:3000...
start http://localhost:3000
```

---

## 8. Redes, Mapeo de Puertos y Firewall Institucional

### 8.1. Matriz de Puertos y Tráfico de Red

| Puerto | Protocolo | Servicio | Exposición Requerida |
| :---: | :---: | :---: | :--- |
| **3000** | TCP / HTTP | Frontend (Next.js Dashboard) | **Pública / Intranet**: Accesible para todos los investigadores. |
| **8000** | TCP / HTTP | Backend (FastAPI / Swagger) | **Pública / Intranet**: Accesible para llamadas AJAX del navegador. |
| **5432** | TCP | PostgreSQL Database | **Solo Red Local / Bloqueado**: No exponer a Internet; uso interno. |
| **443** | TCP / HTTPS | Google Cloud Storage API | **Salida Externa (Outbound)**: Salida hacia `storage.googleapis.com`. |

### 8.2. Despliegue en Intranet Institucional (Red de Laboratorio)
Si el servidor corre en el Laboratorio de Sistemas de Información y se desea que cualquier estudiante en la Wi-Fi del campus acceda:
1. Asigne una dirección IP local fija a la máquina física (ejemplo: `192.168.1.100`).
2. Ajuste las reglas de cortafuegos en Linux (UFW):
   ```bash
   sudo ufw allow from 192.168.0.0/16 to any port 3000 proto tcp comment "FAMA Frontend"
   sudo ufw allow from 192.168.0.0/16 to any port 8000 proto tcp comment "FAMA Backend API"
   sudo ufw status
   ```
3. En el archivo `.env`, configure:
   ```env
   NEXT_PUBLIC_API_URL=http://192.168.1.100:8000
   CORS_ALLOWED_ORIGINS=http://192.168.1.100:3000,http://localhost:3000
   ```
4. Los alumnos accederán desde sus dispositivos tecleando `http://192.168.1.100:3000`.

### 8.3. Despliegue Seguro hacia Internet (Trabajo en Terreno)
Para permitir que biólogos en terreno clasifiquen audio desde teléfonos móviles en cualquier parte del mundo sin vulnerar la red universitaria:

* **Opción A (Recomendada): Cloudflare Tunnel (`cloudflared`):**
  * No requiere abrir puertos en el router del campus ni contratar una IP pública estática.
  * Cree un túnel en Cloudflare hacia `http://localhost:3000` y `http://localhost:8000`.
  * La plataforma queda disponible bajo un dominio seguro con HTTPS automático (ej. `https://fama.ubiobio.cl`).
* **Opción B: Proxy Inverso Nginx con Certbot:**
  * Configure Nginx en el host para terminar SSL en el puerto 443 y redirigir el tráfico hacia el puerto 3000 y 8000 de Docker.

---

## 9. Guía Exhaustiva de Resolución de Problemas (Troubleshooting)

### 9.1. Problema 1: PyTorch no detecta la GPU / Backend arranca en modo CPU Fallback
* **Síntoma:** Al consultar `/api/training/hardware` o ver la terminal, aparece: `CUDA disponible: False`.
* **Causa:** Docker no tiene acceso a los controladores NVIDIA del host, o el toolkit no está registrado en el daemon.
* **Diagnóstico y Solución:**
  1. En el host, verifique que `nvidia-smi` funcione.
  2. En Linux, verifique que el archivo `/etc/docker/daemon.json` contenga la configuración del runtime `nvidia`:
     ```json
     {
       "runtimes": {
         "nvidia": {
           "path": "nvidia-container-runtime",
           "runtimeArgs": []
         }
       }
     }
     ```
  3. Ejecute `sudo systemctl restart docker`.
  4. En `docker-compose.yml`, confirme que la directiva `deploy.resources.reservations.devices` esté presente.

---

### 9.2. Problema 2: Error Fatal `CUDA Out of Memory (OOM)` durante Entrenamientos
* **Síntoma:** El entrenamiento se interrumpe abruptamente con el mensaje: `RuntimeError: CUDA out of memory. Tried to allocate X.XX GiB`.
* **Causa:** El tamaño de batch (`batch_size`) excede la capacidad física de la VRAM, o existen modelos huérfanos residentes en memoria.
* **Diagnóstico y Solución:**
  1. **Reducir el Batch Size:** En la vista de Entrenamiento, baje el tamaño de lote de `16` a `8` o `4`.
  2. **Verificar Procesos Externos:** En el host, ejecute `nvidia-smi` y mate cualquier proceso ajeno que ocupe VRAM.
  3. **Reinicio Limpio del Backend:**
     ```bash
     docker compose restart backend
     ```
     FastAPI liberará toda la memoria retenida y volverá a cargar únicamente el modelo campeón.

---

### 9.3. Problema 3: Error de Autenticación con Google Cloud (`403 Forbidden` / `DefaultCredentialsError`)
* **Síntoma:** Al sincronizar datasets en Ingesta aparece: `Could not automatically determine credentials`.
* **Causa:** El contenedor no encuentra el archivo JSON montado, o la Service Account carece de permisos sobre el bucket.
* **Diagnóstico y Solución:**
  1. Compruebe que el archivo exista en el host en `./credentials/fama-gcs-credentials.json`.
  2. Ingrese al contenedor backend y verifique que el archivo esté montado:
     ```bash
     docker compose exec backend ls -la /app/credentials/fama-gcs-credentials.json
     ```
  3. Compruebe los permisos en Google Cloud Console: la Service Account debe tener el rol `Storage Object Admin` en el bucket especificado en `GCS_BUCKET_NAME`.

---

### 9.4. Problema 4: `Is the database running? Connection refused` al Arrancar
* **Síntoma:** El backend colapsa en bucle de reinicio con error de conexión a PostgreSQL.
* **Causa:** El backend intentó conectarse antes de que PostgreSQL finalizara su proceso de inicialización en disco.
* **Diagnóstico y Solución:**
  1. Verifique el estado de salud de la base de datos:
     ```bash
     docker compose ps db
     ```
  2. F.A.M.A. implementa una directiva de espera (`depends_on.db.condition: service_healthy`). Si la base de datos está corrupta, revise los logs:
     ```bash
     docker compose logs db
     ```
  3. Si es una instalación nueva y desea resetear la base de datos desde cero:
     ```bash
     docker compose down -v
     docker compose up -d
     ```
     *(¡Precaución! Esto purga las tablas locales de PostgreSQL; no afecta a los datos en GCS).*

---

### 9.5. Problema 5: Error de CORS al Conectar desde Otras Computadoras de la Red
* **Síntoma:** En la consola del navegador (F12) aparece: `Access to fetch at 'http://192.168.1.100:8000/api/...' from origin 'http://192.168.1.100:3000' has been blocked by CORS policy`.
* **Causa:** FastAPI tiene configurada una lista restrictiva de orígenes permitidos.
* **Diagnóstico y Solución:**
  * En el archivo `.env`, agregue la dirección IP exacta desde donde se carga el frontend a la variable `CORS_ALLOWED_ORIGINS`:
    ```env
    CORS_ALLOWED_ORIGINS=http://localhost:3000,http://192.168.1.100:3000
    ```
  * Reinicie el backend: `docker compose restart backend`.

---

### 9.6. Problema 6: Conflicto de Puertos en el Host (`Address already in use`)
* **Síntoma:** `Error response from daemon: driver failed programming external connectivity on endpoint fama-frontend: Bind for 0.0.0.0:3000 failed: port is already allocated`.
* **Causa:** Otro servicio del servidor (un servidor Apache, NodeJS, u otra instancia de PostgreSQL) está ocupando el puerto.
* **Diagnóstico y Solución:**
  1. Identifique el proceso en conflicto:
     * Linux: `sudo lsof -i :3000` o `sudo netstat -tulpn | grep 3000`
     * Windows: `netstat -ano | findstr :3000`
  2. Modifique el puerto en el archivo `.env` sin alterar el interior de los contenedores:
     ```env
     FRONTEND_PORT=3005
     BACKEND_PORT=8005
     ```
  3. Reinicie con `docker compose up -d`.

---

## 10. Mantenimiento Operativo y Respaldos

### 10.1. Respaldo y Restauración de la Base de Datos PostgreSQL

* **Generar Copia de Respaldo (.sql):**
  ```bash
  docker compose exec -t db pg_dump -U fama_admin -d fama_db > backup_fama_$(date +%Y%m%d_%H%M%S).sql
  ```
* **Restaurar Copia de Seguridad:**
  ```bash
  cat backup_fama_20260926_120000.sql | docker compose exec -T db psql -U fama_admin -d fama_db
  ```

### 10.2. Resguardo de Checkpoints de Modelos
Los modelos entrenados se guardan en el volumen persistente `checkpoints_data`. Para crear un archivo comprimido de respaldo:
```bash
docker run --rm -v fama_checkpoints_volume:/data -v $(pwd):/backup ubuntu tar czvf /backup/checkpoints_backup.tar.gz -C /data .
```

### 10.3. Actualización de Versiones de F.A.M.A.
Cuando se publiquen mejoras o parches en el repositorio oficial:
```bash
git pull origin main
docker compose build --no-cache
docker compose up -d
```
El volumen de PostgreSQL y los checkpoints locales se mantendrán intactos tras la actualización.
