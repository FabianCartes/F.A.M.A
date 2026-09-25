import sys
from pathlib import Path
from datetime import datetime, timezone
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

_BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from app.database import Base


@pytest.fixture
def db_session():
    """Crea una base de datos SQLite en memoria para validar modelos sin alterar PostgreSQL."""
    engine = create_engine("sqlite:///:memory:")
    # Importar los modelos para que Base los registre
    from app.models.dataset import ConjuntoDatos, Audio
    from app.models.training import Modelo, MetricaEntrenamiento

    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


def test_modelo_creation(db_session):
    """Verifica la creación y persistencia del modelo según la Tabla 6.6 de la tesis."""
    from app.models.dataset import ConjuntoDatos
    from app.models.training import Modelo

    dataset = ConjuntoDatos(
        nombre="AvesChilenas_Train",
        ruta_gcp="gs://fama-audio-records-2026/datasets/AvesChilenas_Train/",
        estado="sincronizado",
    )
    db_session.add(dataset)
    db_session.commit()

    modelo = Modelo(
        id_conjunto_datos=dataset.id_conjunto_datos,
        clase_objetivo="15 Aves Chilenas",
        arquitectura="EfficientNet-B0",
        epocas=15,
        tasa_aprendizaje=0.001,
        tamano_lote=16,
        precision=86.75,
        perdida=0.452,
        ruta_binario_gcp="gs://fama-audio-records-2026/models/efficientnet_b0_best.pt",
        tamano_bytes=25000000,
        hash_binario="sha256_dummy_hash",
        activo=True,
        estado="entrenado",
    )
    db_session.add(modelo)
    db_session.commit()

    assert modelo.id_modelo is not None
    assert modelo.arquitectura == "EfficientNet-B0"
    assert modelo.precision == 86.75
    assert modelo.activo is True
    assert modelo.conjunto_datos.nombre == "AvesChilenas_Train"


def test_metrica_entrenamiento_cascade(db_session):
    """Verifica que las métricas por época (Tabla 6.7) se asocien y borren en cascada con el modelo."""
    from app.models.training import Modelo, MetricaEntrenamiento

    modelo = Modelo(
        clase_objetivo="15 Aves Chilenas",
        arquitectura="AudioCNN",
        epocas=2,
        tasa_aprendizaje=0.001,
        tamano_lote=32,
        ruta_binario_gcp="models/audiocnn.pt",
    )
    db_session.add(modelo)
    db_session.commit()

    m1 = MetricaEntrenamiento(
        id_modelo=modelo.id_modelo,
        epoca=1,
        precision=55.0,
        perdida=1.25,
        puntuacion_validacion=52.0,
        tiempo_epoca=14.2,
    )
    m2 = MetricaEntrenamiento(
        id_modelo=modelo.id_modelo,
        epoca=2,
        precision=68.5,
        perdida=0.88,
        puntuacion_validacion=65.0,
        tiempo_epoca=13.8,
    )
    db_session.add_all([m1, m2])
    db_session.commit()

    assert len(modelo.metricas) == 2
    assert modelo.metricas[0].epoca == 1
    assert modelo.metricas[1].precision == 68.5

    # Probar borrado en cascada
    db_session.delete(modelo)
    db_session.commit()

    metricas_restantes = db_session.query(MetricaEntrenamiento).filter_by(id_modelo=modelo.id_modelo).all()
    assert len(metricas_restantes) == 0
