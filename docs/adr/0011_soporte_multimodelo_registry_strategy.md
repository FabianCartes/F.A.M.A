# ADR 0011: Soporte Multi-Modelo en Backend mediante Strategy Pattern y Model Registry con Aislamiento de Persistencia Cloud

* **Estado:** Aceptado / En Implementación  
* **Fecha:** 2026-09-15  
* **Decisores:** Equipo F.A.M.A.  
* **Área:** Arquitectura de Software Backend, Inferencia Bioacústica, MLOps e Integración Cloud  

---

## 1. Contexto y Problema

Con la consolidación de la Fase 3 en el backend (orquestador FastAPI con subida a Google Cloud Storage y persistencia en PostgreSQL), la lógica de inferencia bioacústica quedó acoplada de forma monolítica en [`backend/app/main.py`](../../backend/app/main.py):

1. **Acoplamiento Rígido de Modelo:**  
   El servicio actual (`AudioPredictorService`) está atado de manera fija a `AudioCNN` y a los pesos de `augmented_best.pt` (61.69% accuracy), ignorando el catálogo de modelos de mayor rendimiento ya validados en el repositorio (como el Super-Ensamble Tri-Modelo de 88.68% F1 definido en el [ADR 0010](0010_tri_modelo_heterogeneo_resnet34d.md)).
2. **Inflexibilidad ante Futuros Dominios y Datasets:**  
   Como se identificó en el análisis de límites bioacústicos ([`docs/problemas_conocidos/02_limites_generalizacion_universal_y_conjunto_abierto.md`](../problemas_conocidos/02_limites_generalizacion_universal_y_conjunto_abierto.md)), el soporte de nuevos datasets (e.g. paisajes sonoros PAM a 32 kHz o clasificación multi-etiqueta) requiere desacoplar la física de preprocesamiento, la red neuronal y la función de decodificación/etiquetado.
3. **Restricción Crítica de Producción (GCP y Base de Datos):**  
   Cualquier refactorización para habilitar la selección de modelos debe garantizar **cero regresiones en la integración con Google Cloud Storage** (`upload_audio_to_gcp`) y mantener la retrocompatibilidad del endpoint `POST /api/predict`, permitiendo auditar qué modelo ejecutó cada inferencia en PostgreSQL.

---

## 2. Decisión Arquitectónica

Se aprueba la reestructuración del subsistema de predicción en `backend/app/` aplicando el patrón **Strategy** desacoplado mediante un **Model Registry (Catálogo en Memoria)**:

### 2.1 Interfaz Base del Módulo Profundo (`AudioPredictor`)
Se define una interfaz abstracta en `backend/app/services/predictors/base.py` que encapsula la tupla *preprocesamiento + modelo + decodificación*:

```python
class AudioPredictor(ABC):
    model_id: str
    metadata: ModelMetadata

    @abstractmethod
    def predict(self, audio_path: Path) -> PredictionResult:
        """Procesa el audio, ejecuta la inferencia y retorna clase, confianza y diagnósticos."""
        pass
```

Cada implementación concreta (`ChileanBirdsCNNPredictor`, `ChileanBirdsEnsemblePredictor`, y futuros modelos) gestiona internamente sus propios requisitos de frecuencia de muestreo ($22.050\text{ Hz}$ vs $32\text{ kHz}$), bancos Mel, funciones de activación (Softmax vs Sigmoid) y mapeo taxonómico.

### 2.2 Catálogo Centralizado (`ModelRegistry`)
Se crea un registro central en `backend/app/services/registry.py` responsable de:
* Registrar las instancias de predictores disponibles.
* Resolver el predictor adecuado a partir de un identificador `model_id`.
* Proveer un fallback determinista al modelo por defecto (`chilean-birds-cnn`) para mantener retrocompatibilidad total.
* Exponer los metadatos de modelos activos hacia la API.

### 2.3 Exposición HTTP Retrocompatible y Descubrimiento de Modelos
* `POST /api/predict`: Acepta el parámetro opcional `model_id: Optional[str] = None`. Si no se provee, utiliza el modelo por defecto. El formato de respuesta JSON preserva los campos preexistentes (`filename`, `gcp_upload`, `db_id`, `clase`, `confianza`) e incluye `modelo_id`.
* `GET /api/models`: Nuevo endpoint para que clientes y el frontend descubran dinámicamente los modelos instalados, sus versiones y sus taxonomías.

### 2.4 Trazabilidad en Persistencia Relacional
Se extiende la entidad [`Prediccion`](../../backend/app/models/prediction.py) en SQLAlchemy agregando la columna opcional:
```python
modelo_id = Column(String(100), nullable=True, default="chilean-birds-cnn")
```
Esto permite auditar en la base de datos PostgreSQL qué red generó cada predicción histórica sin romper registros preexistentes.

### 2.5 Aislamiento de Persistencia Cloud (GCS)
El servicio [`upload_audio_to_gcp`](../../backend/app/services/storage.py) permanece estrictamente intacto. La subida a GCS se ejecuta de manera previa e independiente de la resolución del modelo en el registry, asegurando que un fallo o cambio de modelo no comprometa el almacenamiento en la nube.

---

## 3. Consecuencias y Trade-offs

### Positivas:
* **Extensibilidad Abierta (OCP):** Agregar un nuevo modelo (ej. ensamble o red PAM a 32 kHz) solo requiere crear una clase que implemente `AudioPredictor` y registrarla, sin tocar `main.py` ni las rutas existentes.
* **Cero Impacto en Producción GCP:** La capa de persistencia en la nube queda completamente aislada de la inferencia.
* **Módulos Profundos y Testabilidad:** El contrato de inferencia es unívoco y fácil de mockear en pruebas unitarias y de integración.

### Negativas / Consideraciones:
* **Gestión de Memoria VRAM/RAM:** Registrar múltiples modelos simultáneos en el mismo proceso de FastAPI requiere controlar que la suma de checkpoints no sature la memoria disponible del host.

---

## 4. Metodología de Implementación: TDD + RDD (Receipt-Driven Development)

El desarrollo se ejecutará bajo **Test-Driven Development (TDD)** complementado con **Receipt-Driven Development (RDD)**:
* Cada fase requerirá pruebas en rojo antes del código de producción.
* La validación final generará un informe técnico de hito ([`docs/18_soporte_multimodelo_backend_rdd.md`](../18_soporte_multimodelo_backend_rdd.md)) con evidencia auditable (*receipts*): salida de `pytest` (100% pasando), pruebas de llamada HTTP (`curl`/`TestClient`) a `/api/models` y `/api/predict`, y verificación de inserción en base de datos.
