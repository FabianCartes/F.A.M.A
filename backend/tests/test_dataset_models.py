import sys
from pathlib import Path
from datetime import datetime, timezone
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

_BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from unittest.mock import patch

with patch("dotenv.load_dotenv", return_value=False):
    from app.database import Base
from training.datasets.base import AudioRecordingMetadata
from pydantic import ValidationError


@pytest.mark.parametrize("stage", [None, "", "legacy", "RAW"])
def test_metadata_requires_explicit_stage(stage):
    fields = dict(nombre_archivo="bird.wav", file_path="birds/bird.wav",
                  clase="Bird", recordist="sensor")
    if stage is not None:
        fields["file_stage"] = stage
    with pytest.raises(ValidationError):
        AudioRecordingMetadata(**fields)


def test_metadata_serializes_relative_reference():
    record = AudioRecordingMetadata(nombre_archivo="bird.wav", file_path="birds/bird.wav",
                                    file_stage="raw", clase="Bird", recordist="sensor")
    assert record.model_dump()["file_stage"] == "raw"
    with pytest.raises(ValidationError):
        AudioRecordingMetadata(**{**record.model_dump(), "file_path": "/birds/bird.wav"})


@pytest.mark.parametrize("path", ["", ".", "../bird.wav", "birds//bird.wav", "birds/./bird.wav",
                                  "birds\\bird.wav", "file:bird.wav"])
def test_metadata_rejects_nonrelative_structural_paths(path):
    with pytest.raises(ValidationError):
        AudioRecordingMetadata(nombre_archivo="bird.wav", file_path=path, file_stage="raw",
                               clase="Bird", recordist="sensor")


def test_metadata_structure_does_not_claim_physical_validation():
    record = AudioRecordingMetadata(nombre_archivo="missing.wav", file_path="missing.wav",
                                    file_stage="processed", clase="Bird", recordist="sensor")
    assert record.model_dump()["file_path"] == "missing.wav"


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


def test_root_models_reexports_all_domain_entities():
    """Verifica que backend/models.py re-exporte todas las entidades del dominio para compatibilidad regresiva."""
    from models import (
        Prediccion,
        ConjuntoDatos,
        Audio,
        Modelo,
        MetricaEntrenamiento,
        Retroalimentacion,
        Usuario,
    )
    import models

    expected_entities = [
        "Prediccion",
        "ConjuntoDatos",
        "Audio",
        "Modelo",
        "MetricaEntrenamiento",
        "Retroalimentacion",
        "Usuario",
    ]
    for entity_name in expected_entities:
        assert hasattr(models, entity_name), f"models.py no re-exporta {entity_name}"
        entity_cls = getattr(models, entity_name)
        assert hasattr(entity_cls, "__tablename__"), f"{entity_name} no es una tabla SQLAlchemy válida"

