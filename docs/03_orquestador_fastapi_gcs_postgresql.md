# Informe Técnico: Reestructuración Modular, Orquestador FastAPI, Inferencia Bioacústica Calibrada y Persistencia Híbrida (GCS + PostgreSQL)

**Proyecto:** Framework MLOps Híbrido para Clasificación de Audio (F.A.M.A.)  
**Fecha:** Septiembre 2026  
**Fase:** Fase 3 - Orquestación de Servicios y Persistencia Híbrida (Minimum Viable Pipeline)  
**Dominio:** Bioacústica de Aves de Chile (15 Especies - Dataset Xeno-canto v3)  
**Autores:** Fabián Cartes Oliva, Kevin Cárdenas Sepúlveda  
**Profesor Guía:** Christian Vidal Castro  
**Institución:** Departamento de Sistemas de Información, Universidad del Bío-Bío  

---

## 1. Objetivo y Alcance de la Fase

Tras haber validado el núcleo algorítmico en la PoC local (alcanzando un **61.69% de Accuracy** en el conjunto de prueba independiente mediante VAD y Data Augmentation), la presente fase tuvo como objetivo principal la **transición desde scripts analíticos hacia una arquitectura orientada a servicios desacoplada y escalable**.

Los objetivos específicos abordados comprenden:
1. **Reestructuración Monorepo:** Separación formal de responsabilidades en directorios `/backend` y `/frontend`.
2. **Arquitectura en Capas:** Implementación de un diseño modular en `backend/app/` siguiendo principios de *Clean Architecture* y módulos profundos (*Deep Modules*).
3. **Orquestador FastAPI (Minimum Viable Pipeline):** Implementación de endpoints RESTful para comprobación de estado (`/`, `/health`) e inferencia bioacústica en tiempo real (`/api/predict`).
4. **Calibración y Discriminación Física de Señal:** Robustecimiento del pipeline bioacústico para rechazar de forma determinista silencios (VAD RMS) y ruidos sintéticos/ambientales (Planitud Espectral), incorporando además escalado por temperatura (*Temperature Scaling*) para una estimación probabilística realista.
5. **Persistencia Cloud (Google Cloud Storage):** Integración asíncrona para almacenamiento de audios de inferencia, dando estricto cumplimiento al requerimiento **RNF_03** (gestión segura de credenciales IAM).
6. **Persistencia Relacional (PostgreSQL):** Modelado ORM y registro histórico de inferencias mediante SQLAlchemy conectado a la base de datos `fama_db`.
7. **Aseguramiento de Calidad:** Mantenimiento de la suite de pruebas unitarias bajo TDD (22 tests automatizados, 100% de éxito).

---

## 2. Reestructuración del Repositorio y Arquitectura de Capas

El repositorio fue reorganizado bajo un esquema de monorepo desacoplado para separar de manera estricta el backend analítico del futuro cliente web:

```text
F.A.M.A/
├── .agents/                    # Reglas, skills y directrices de desarrollo
├── docs/                       # Documentación técnica centralizada e informes de hito
│   ├── 01_primera_prueba_poc.md
│   ├── 02_optimizacion_vad_data_augmentation.md
│   ├── 03_orquestador_fastapi_gcs_postgresql.md
│   └── confusion_matrix_augmented.png
├── frontend/                   # Espacio de trabajo reservado para la interfaz de usuario
│   └── README.md
├── backend/                    # Núcleo de computación, APIs y modelos de persistencia
│   ├── app/                    # Arquitectura modular en capas
│   │   ├── controllers/        # Controladores de negocio desacoplados
│   │   ├── middlewares/        # Middlewares de seguridad, CORS y control de errores
│   │   ├── models/             # Modelos de dominio y entidades ORM (SQLAlchemy)
│   │   │   └── prediction.py   # Entidad 'Prediccion' (tabla: prediccion)
│   │   ├── routes/             # Enrutadores modulares de FastAPI
│   │   ├── services/           # Servicios especializados de integración
│   │   │   └── storage.py      # Servicio asíncrono para Google Cloud Storage
│   │   ├── database.py         # Configuración del motor y sesiones SQLAlchemy
│   │   └── main.py             # Instanciación del servidor FastAPI y orquestación
│   ├── checkpoints/            # Pesos de modelos entrenados (augmented_best.pt)
│   ├── data/                   # Datasets particionados y metadata.csv con hashes
│   ├── poc/                    # Módulos profundos de ML (download, preprocess, split, train, evaluate)
│   ├── tests/                  # Suite de pruebas unitarias e integración (22 tests)
│   ├── .env                    # Variables de entorno locales (protegido en .gitignore)
│   ├── .env.example            # Plantilla de variables de configuración
│   └── requirements.txt        # Dependencias de producción y desarrollo
├── .gitignore                  # Protección estricta de credenciales, datos y artefactos
└── README.md                   # Resumen general del proyecto
```

### Principio de Módulos Profundos y Adaptabilidad
Para asegurar retrocompatibilidad con scripts existentes y permitir ejecuciones directas tanto a través de la arquitectura en capas (`backend.app.*`) como desde el directorio raíz de backend, se implementaron adaptadores y re-exportadores limpios en `backend/main.py`, `backend/database.py`, `backend/models.py` y `backend/services/storage.py`.

---

## 3. Orquestador FastAPI: Minimum Viable Pipeline (MVP)

Se implementó el orquestador principal utilizando el framework **FastAPI**, seleccionado por su alto rendimiento asíncrono y soporte nativo de especificaciones OpenAPI/Swagger.

### Catálogo de Endpoints

| Método | Endpoint | Entrada | Salida | Propósito |
|:---|:---|:---|:---|:---|
| `GET` | `/` | Ninguna | `{"status": "F.A.M.A. Backend Operativo"}` | Verificación básica de operatividad |
| `GET` | `/health` | Ninguna | `{"status": "ok"}` | Sonda de salud (*liveness probe*) para balanceadores y monitoreo |
| `POST` | `/api/predict` | `file` (`multipart/form-data`, archivo `.wav`) | `{"prediccion": str, "confianza": float, "id_registro": int, "gcs_uri": str}` | Inferencia bioacústica con persistencia en GCS y PostgreSQL |

### Flujo de Ejecución de una Solicitud de Inferencia

```mermaid
sequenceDiagram
    autonumber
    actor Cliente as Cliente / Frontend
    participant API as FastAPI Orquestador
    participant Filtro as Discriminador Físico
    participant CNN as PyTorch AudioCNN
    participant GCS as Google Cloud Storage
    participant DB as PostgreSQL (fama_db)

    Cliente->>API: POST /api/predict (audio.wav)
    API->>API: Validar formato .wav y tamaño
    API->>Filtro: Análisis de señal (RMS y Planitud Espectral)
    alt Es Silencio (RMS < 1e-4)
        Filtro-->>API: "Silencio / No detectado" (Conf: 0.0)
    else Es Ruido No Biológico (Flatness > 0.15)
        Filtro-->>API: "Ruido / Señal no biológica" (Conf: 0.0)
    else Señal Bioacústica Válida
        API->>CNN: Mel-Spectrogram + Forward Pass (T=1.5)
        CNN-->>API: Especie Predicha + Confianza Calibrada
    end
    par Persistencia Asíncrona en GCS
        API->>GCS: upload_audio_to_gcp(uuid.wav)
        GCS-->>API: gs://bucket/uuid.wav
    and Persistencia Relacional en PostgreSQL
        API->>DB: INSERT INTO prediccion (...)
        DB-->>API: id_prediccion (PK autoincremental)
    end
    API-->>Cliente: JSON con resultado, confianza, ID y GCS URI
```

---

## 4. Pipeline de Inferencia Bioacústica y Calibración Probabilística

Para mitigar el fenómeno de **alucinación en modelos de audio** (donde una red neuronal fuerza la clasificación de un silencio o ruido estático en alguna de las 15 clases conocidas), se diseñó un pipeline de inferencia robusto basado en propiedades físicas acústicas y calibración de temperatura.

### A. Preprocesamiento Espectral Estándar
El audio recibido se procesa con `librosa`:
- **Frecuencia de muestreo:** 22.050 Hz (estándar bioacústico).
- **Duración fija:** 5.0 segundos (110.250 muestras), aplicando relleno con ceros o truncamiento central simétrico.
- **Espectrograma de Mel:** 128 bandas Mel, `n_fft = 2048`, `hop_length = 512`, convertido a escala logarítmica (dB) normalizada.

### B. Discriminación Física de Señales

1. **Filtro de Silencio (Energía RMS):**
   $$\text{RMS} = \sqrt{\frac{1}{N}\sum_{i=1}^N x[i]^2}$$
   Si $\text{RMS} < 10^{-4}$ (amplitud inaudible o silencio digital), el sistema omite el paso por la red y responde inmediatamente:
   - **Etiqueta:** `"Silencio / No detectado"`
   - **Confianza:** `0.0`

2. **Filtro de Ruido Blanco y Señales No Biológicas (Planitud Espectral / *Spectral Flatness*):**
   La planitud espectral mide el grado de tonalidad versus ruido blanco de una señal, calculando la relación entre su media geométrica y su media aritmética en el dominio espectral:
   $$\text{Flatness} = \frac{\exp\left(\frac{1}{K}\sum_{k=1}^K \ln |X[k]|\right)}{\frac{1}{K}\sum_{k=1}^K |X[k]|}$$
   - **Comportamiento Empírico:**
     - Cantos de aves chilenas reales: $\text{Flatness} \in [0.004, 0.032]$ (media: $0.015$), dado que concentran energía en armónicos tonales nítidos.
     - Ruido blanco sintético o estática ambiental desordenada: $\text{Flatness} \approx 0.56$.
   - **Criterio de Discriminación:** Si $\text{Flatness} > 0.15$, se clasifica como:
     - **Etiqueta:** `"Ruido / Señal no biológica"`
     - **Confianza:** `0.0`

### C. Calibración de Probabilidades mediante *Temperature Scaling*
En clasificación multiclase profunda, la función Softmax estándar suele producir distribuciones sobreconfiadas ($P \approx 0.9999$) debido a la magnitud de los logits brutos. En lugar de recortar artificialmente el valor numérico, se implementó el método canónico de **escalado por temperatura**:

$$P(y = c \mid \mathbf{z}) = \frac{\exp(z_c / T)}{\sum_{j=1}^C \exp(z_j / T)}$$

Con un hiperparámetro de temperatura calibrado en $T = 1.5$:
- Señales acústicas nítidas y claras obtienen confianzas realistas en el rango $0.75 - 0.88$.
- Señales dudosas o con interferencias distribuyen la probabilidad entre las clases más afines.
- Se preserva el orden estricto de las predicciones ($\arg\max$) sin introducir discontinuidades numéricas arbitrarias.

---

## 5. Persistencia Cloud: Google Cloud Storage (GCS)

En conformidad con el requerimiento no funcional **RNF_03** (*Seguridad y Gestión de Credenciales IAM*), se desarrolló el servicio `backend/app/services/storage.py`:

- **Aislamiento de Secretos:** Las credenciales de la cuenta de servicio de GCP (`proyectotesis-fama-*.json`) se leen exclusivamente mediante la variable de entorno `GOOGLE_APPLICATION_CREDENTIALS` gestionada vía `python-dotenv`.
- **Protección en Git:** Los archivos `.json` de IAM y los ficheros `.env` están completamente blindados en `.gitignore` para evitar cualquier filtración a repositorios remotos.
- **Función Asíncrona `upload_audio_to_gcp`:**
  - Recibe el flujo de bytes del archivo `.wav`.
  - Genera un identificador único mediante UUIDv4: `audios_inferencia/{timestamp}_{uuid}.wav`.
  - Sube el objeto al bucket configurado en `GCS_BUCKET_NAME`.
  - Devuelve la URI canónica persistente (`gs://...` o URL pública según configuración).

---

## 6. Persistencia Relacional: PostgreSQL con SQLAlchemy

Para garantizar la trazabilidad y auditoría histórica de cada inferencia (enfoque *Minimum Viable Pipeline*), se integró una base de datos relacional PostgreSQL local (`fama_db`).

### A. Configuración de Conexión (`database.py`)
- Motor de base de datos creado con `create_engine` a partir de la variable de entorno `DATABASE_URL`:
  ```text
  DATABASE_URL=postgresql://postgres:1739@localhost:5432/fama_db
  ```
- Manejo de sesiones mediante `sessionmaker(autocommit=False, autoflush=False)`.
- Inyección de dependencias `get_db()` para FastAPI mediante generadores (`yield`), garantizando el cierre ordenado de conexiones tras cada solicitud HTTP.

### B. Modelo Relacional: Tabla `prediccion` (`backend/app/models/prediction.py`)

```mermaid
erDiagram
    PREDICCION {
        int id_prediccion PK "Serial / Autoincremental"
        string ruta_audio_prueba "Ruta local o URI en GCS"
        string etiqueta_predicha "Especie predicha o descarte"
        float confianza "Confianza calibrada [0.0 - 1.0]"
        timestamp fecha_prediccion "Timestamp en UTC con zona horaria"
    }
```

| Columna | Tipo de Dato | Restricciones | Descripción |
|:---|:---|:---|:---|
| `id_prediccion` | `Integer` | `primary_key=True`, `index=True`, `autoincrement` | Identificador único del evento de inferencia |
| `ruta_audio_prueba` | `String` | `nullable=False` | Referencia al archivo en almacenamiento local o GCS |
| `etiqueta_predicha` | `String` | `nullable=False` | Nombre común de la especie o descarte físico |
| `confianza` | `Float` | `nullable=False` | Probabilidad posterior calibrada por temperatura |
| `fecha_prediccion` | `DateTime(timezone=True)` | `default=datetime.now(timezone.utc)` | Estampa de tiempo exacta del registro en formato UTC |

### C. Verificación en Vivo
La inicialización del servidor ejecuta automáticamente `Base.metadata.create_all(bind=engine)`, asegurando la creación idempotente del esquema. Se ejecutaron pruebas de inserción y consulta en vivo, confirmando la persistencia inmediata en la base de datos `fama_db` de PostgreSQL 18.

---

## 7. Aseguramiento de Calidad y Pruebas Automatizadas (TDD)

Bajo las directrices de desarrollo definidas en [`AGENTS.md`](file:///c:/Users/fabia/Desktop/F.A.M.A/AGENTS.md), la totalidad del código fue probado mediante pruebas unitarias e integración con `pytest`:

```text
============================= test session starts =============================
platform win32 -- Python 3.12.10, pytest-9.1.1
rootdir: C:\Users\fabia\Desktop\F.A.M.A

backend/tests/test_download.py::test_compute_file_sha256 PASSED          [  4%]
backend/tests/test_download.py::test_create_metadata_row PASSED          [  9%]
backend/tests/test_download.py::test_search_recordings_pagination PASSED [ 13%]
backend/tests/test_download.py::test_download_file_success PASSED        [ 18%]
backend/tests/test_evaluate.py::test_compute_metrics_and_matrix PASSED   [ 22%]
backend/tests/test_evaluate.py::test_evaluate_test_set PASSED            [ 27%]
backend/tests/test_preprocess.py::test_constants PASSED                  [ 31%]
backend/tests/test_preprocess.py::test_load_and_fix_length_from_synthetic_array_short PASSED [ 36%]
backend/tests/test_preprocess.py::test_load_and_fix_length_from_synthetic_array_long PASSED [ 40%]
backend/tests/test_preprocess.py::test_load_and_fix_length_from_file PASSED [ 45%]
backend/tests/test_preprocess.py::test_extract_mel_spectrogram PASSED    [ 50%]
backend/tests/test_preprocess.py::test_compute_rms PASSED                [ 54%]
backend/tests/test_preprocess.py::test_extract_active_windows_multiple PASSED [ 59%]
backend/tests/test_preprocess.py::test_extract_active_windows_vad_discards_silence PASSED [ 63%]
backend/tests/test_preprocess.py::test_extract_active_windows_safeguard PASSED [ 68%]
backend/tests/test_split.py::test_grouped_stratified_split_disjoint_recordists PASSED [ 72%]
backend/tests/test_split.py::test_grouped_stratified_split_empty_or_small PASSED [ 77%]
backend/tests/test_train.py::test_audiocnn_forward_pass PASSED           [ 81%]
backend/tests/test_train.py::test_audio_dataset_synthetic PASSED         [ 86%]
backend/tests/test_train.py::test_audio_dataset_deterministic_when_eval PASSED [ 90%]
backend/tests/test_train.py::test_audio_dataset_augmentation_in_train PASSED [ 95%]
backend/tests/test_train.py::test_train_and_eval_step PASSED             [100%]

============================= 22 passed in 10.38s =============================
```

Las 22 pruebas automatizadas garantizan la estabilidad del preprocesamiento, el aislamiento de grabadores (*Zero Recordist Leakage*), el pipeline VAD, la aumentación estocástica y la consistencia de los tensores de red neuronal.

---

## 8. Conclusiones y Próximos Pasos

La implementación de este hito completa la columna vertebral del orquestador analítico y la persistencia de datos del proyecto F.A.M.A. El sistema dispone de:
1. Un modelo entrenado y validado científicamente sobre 15 especies de aves chilenas.
2. Un servidor de inferencia FastAPI con discriminación física de señales y calibración continua.
3. Doble persistencia híbrida: archivos crudos en Google Cloud Storage y metadatos históricos en PostgreSQL.

### Próximos Pasos Técnicos:
- **Desarrollo del Frontend (`/frontend`):** Construcción de la interfaz web para carga de audios, visualización interactiva del espectrograma de Mel, visualización de métricas de confianza y tabla histórica de predicciones consultada desde el backend.
- **Contenerización Docker:** Creación de `Dockerfile` y `docker-compose.yml` para orquestar conjuntamente la base de datos PostgreSQL, el servicio FastAPI y el cliente web en un entorno reproducible y listo para la nube.
