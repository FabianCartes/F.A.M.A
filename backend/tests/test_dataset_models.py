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
    # Importar los modelos para que Base los conozca
    from app.models.dataset import ConjuntoDatos, Audio

    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


def test_conjunto_datos_creation(db_session):
    """Verifica que se pueda instanciar y guardar un ConjuntoDatos según Tabla 6.4 de la tesis."""
    from app.models.dataset import ConjuntoDatos

    dataset = ConjuntoDatos(
        nombre="AvesChilenas_Test",
        ruta_gcp="gs://fama-audio-records-2026/datasets/AvesChilenas_Test/",
        estado="sincronizado",
        tamano_total_bytes=1048576,
        cantidad_audios=10,
        finalidad="Entrenamiento bioacústico",
        base_licitud="Investigación académica",
    )
    db_session.add(dataset)
    db_session.commit()

    assert dataset.id_conjunto_datos is not None
    assert dataset.nombre == "AvesChilenas_Test"
    assert dataset.estado == "sincronizado"
    assert dataset.tamano_total_bytes == 1048576
    assert dataset.cantidad_audios == 10
    assert dataset.fecha_carga is not None


def test_audio_creation_and_cascade(db_session):
    """Verifica que se pueda registrar un Audio (Tabla 6.5) y que exista relación con ConjuntoDatos."""
    from app.models.dataset import ConjuntoDatos, Audio

    dataset = ConjuntoDatos(
        nombre="Chucao_DS",
        ruta_gcp="gs://fama-audio-records-2026/datasets/Chucao_DS/",
        estado="sincronizado",
    )
    db_session.add(dataset)
    db_session.commit()

    audio = Audio(
        id_conjunto_datos=dataset.id_conjunto_datos,
        nombre_archivo="chucao_01.wav",
        ruta_gcp="gs://fama-audio-records-2026/datasets/Chucao_DS/Chucao/chucao_01.wav",
        clase="Chucao",
        frecuencia_muestreo=22050,
        duracion_segundos=5.0,
        tamano_bytes=220500,
        hash_archivo="abc123md5hash",
    )
    db_session.add(audio)
    db_session.commit()

    assert audio.id_audio is not None
    assert audio.conjunto_datos.nombre == "Chucao_DS"
    assert len(dataset.audios) == 1
    assert dataset.audios[0].nombre_archivo == "chucao_01.wav"

    # Probar borrado en cascada (ON DELETE CASCADE)
    db_session.delete(dataset)
    db_session.commit()

    remaining_audio = db_session.query(Audio).filter_by(id_audio=audio.id_audio).first()
    assert remaining_audio is None
