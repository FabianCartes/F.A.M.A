import sys
from types import SimpleNamespace
import wave
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

_BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from app.database import Base, get_db
from app.main import app
from app.models.prediction import Prediccion
from app.models.feedback import Retroalimentacion
from app.services.feedback import feedback_service
from app.services import storage


@pytest.fixture(autouse=True)
def fake_gcs(monkeypatch):
    class Client:
        def list_blobs(self, bucket_name, prefix):
            return [SimpleNamespace(name=f"{prefix}{label}/seed.wav")
                    for label in ("Chucao", "Churrín de la Mocha", "rayadito")]
        def bucket(self, name): return self
        def blob(self, key): return self
        def download_as_bytes(self): return b"real audio fixture"
        def upload_from_string(self, data, **kwargs): pass
    monkeypatch.setattr(storage.storage, "Client", Client)


@pytest.fixture
def test_db():
    """Create an isolated in-memory SQLite database session for tests."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = TestingSessionLocal()

    def override_get_db():
        session = TestingSessionLocal()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)
        app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def client(test_db):
    """FastAPI TestClient configured with test database."""
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def sample_prediction(test_db):
    """Fixture providing a persisted Prediccion entity."""
    pred = Prediccion(
        ruta_audio_prueba="audios_prueba/canto_zorzal.wav",
        etiqueta_predicha="Zorzal patagónico",
        confianza=0.88,
        modelo_id="super-ensemble-tri-model",
    )
    test_db.add(pred)
    test_db.commit()
    test_db.refresh(pred)
    return pred


def _create_dummy_wav(path: Path) -> None:
    """Helper to write a valid tiny WAV file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(22050)
        wf.writeframes(b"\x00\x00" * 2205)  # 0.1s of silence


def test_record_feedback_validation(client, test_db, sample_prediction, monkeypatch):
    """POST /api/feedback with fue_correcta=true persists validation in db and returns 200/201."""

    payload = {
        "id_prediccion": sample_prediction.id_prediccion,
        "fue_correcta": True,
    }
    response = client.post("/api/feedback", json=payload)

    assert response.status_code in (200, 201)
    data = response.json()
    assert data["id_prediccion"] == sample_prediction.id_prediccion
    assert data["fue_correcta"] is True
    assert data["procesado"] is False

    # Check persistence in database
    fb_record = test_db.query(Retroalimentacion).filter_by(id_prediccion=sample_prediction.id_prediccion).first()
    assert fb_record is not None
    assert fb_record.fue_correcta is True
    assert fb_record.etiqueta_corregida is None


def test_record_feedback_correction(client, test_db, sample_prediction, monkeypatch):
    """POST /api/feedback with fue_correcta=false and etiqueta_corregida persists correction."""

    payload = {
        "id_prediccion": sample_prediction.id_prediccion,
        "fue_correcta": False,
        "etiqueta_corregida": "Chucao",
    }
    response = client.post("/api/feedback", json=payload)

    assert response.status_code in (200, 201)
    data = response.json()
    assert data["id_prediccion"] == sample_prediction.id_prediccion
    assert data["fue_correcta"] is False
    assert data["etiqueta_corregida"] == "Chucao"
    assert data["procesado"] is False

    fb_record = test_db.query(Retroalimentacion).filter_by(id_prediccion=sample_prediction.id_prediccion).first()
    assert fb_record is not None
    assert fb_record.fue_correcta is False
    assert fb_record.etiqueta_corregida == "Chucao"


def test_record_feedback_missing_label_returns_422(client, sample_prediction):
    """POST /api/feedback with fue_correcta=false without etiqueta_corregida returns HTTP 422."""
    payload = {
        "id_prediccion": sample_prediction.id_prediccion,
        "fue_correcta": False,
    }
    response = client.post("/api/feedback", json=payload)
    assert response.status_code == 422


def test_record_feedback_nonexistent_prediction_returns_404(client):
    """POST /api/feedback with non-existent id_prediccion returns HTTP 404."""
    payload = {
        "id_prediccion": 999999,
        "fue_correcta": True,
    }
    response = client.post("/api/feedback", json=payload)
    assert response.status_code == 404


def test_get_pending_feedback(client, test_db, sample_prediction):
    """GET /api/feedback/pending returns list of uncurated feedback items with prediction metadata."""
    # Create two feedback records: one pending, one processed
    fb_pending = Retroalimentacion(
        id_prediccion=sample_prediction.id_prediccion,
        fue_correcta=False,
        etiqueta_corregida="Turca",
        procesado=False,
    )
    test_db.add(fb_pending)

    pred2 = Prediccion(
        ruta_audio_prueba="audios_prueba/test_processed.wav",
        etiqueta_predicha="Chincol",
        confianza=0.92,
        modelo_id="super-ensemble-tri-model",
    )
    test_db.add(pred2)
    test_db.commit()
    test_db.refresh(pred2)

    fb_processed = Retroalimentacion(
        id_prediccion=pred2.id_prediccion,
        fue_correcta=True,
        procesado=True,
    )
    test_db.add(fb_processed)
    test_db.commit()

    response = client.get("/api/feedback/pending")
    assert response.status_code == 200
    items = response.json()
    assert isinstance(items, list)
    assert len(items) == 1

    item = items[0]
    assert item["id_prediccion"] == sample_prediction.id_prediccion
    assert item["ruta_audio_prueba"] == sample_prediction.ruta_audio_prueba
    assert item["etiqueta_predicha"] == sample_prediction.etiqueta_predicha
    assert item["confianza"] == pytest.approx(sample_prediction.confianza, 0.01)
    assert item["etiqueta_corregida"] == "Turca"
    assert "fecha_retroalimentacion" in item


def test_approve_feedback(client, test_db, tmp_path, monkeypatch):
    """POST /api/feedback/{id}/approve marks procesado=True, places audio in dataset, updates metadata.csv."""
    # Setup temporary dataset directory
    raw_dir = tmp_path / "data" / "raw"
    dataset_dir = raw_dir / "AvesChilenas"
    dataset_dir.mkdir(parents=True, exist_ok=True)
    metadata_file = dataset_dir / "metadata.csv"
    metadata_file.write_text("nombre_archivo,clase,frecuencia_muestreo,duracion_segundos,tamano_bytes,hash_archivo,xc_id,recordist,licencia,pais,localidad,lat,lon,calidad\n")

    # Create dummy source audio file
    source_audio = tmp_path / "audios_prueba" / "canto_test_approve.wav"
    _create_dummy_wav(source_audio)

    monkeypatch.setattr(feedback_service, "raw_data_dir", raw_dir)

    # Persist prediction and feedback
    pred = Prediccion(
        ruta_audio_prueba="raw_audios/0123456789abcdef0123456789abcdef.wav",
        etiqueta_predicha="Rayadito",
        dataset_name="AvesChilenas",
        confianza=0.72,
        modelo_id="super-ensemble-tri-model",
    )
    test_db.add(pred)
    test_db.commit()
    test_db.refresh(pred)

    fb = Retroalimentacion(
        id_prediccion=pred.id_prediccion,
        fue_correcta=False,
        etiqueta_corregida="Chucao",
        procesado=False,
    )
    test_db.add(fb)
    test_db.commit()
    test_db.refresh(fb)

    response = client.post(f"/api/feedback/{fb.id_retroalimentacion}/approve?dataset_name=AvesChilenas")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "approved"
    assert "destination_path" in data
    expected_filename = f"chucao_fb_{fb.id_retroalimentacion}.wav"
    assert data.get("filename") == expected_filename

    # Verify database state
    test_db.refresh(fb)
    assert fb.procesado is True

    # Verify destination audio exists with canonical naming
    expected_audio = dataset_dir / "Chucao" / expected_filename
    assert expected_audio.exists()

    # Verify metadata.csv was updated
    metadata_content = metadata_file.read_text()
    assert expected_filename in metadata_content
    assert "Chucao" in metadata_content


def test_approve_feedback_canonical_naming_accents_and_spaces(client, test_db, tmp_path, monkeypatch):
    """POST /api/feedback/{id}/approve generates canonical filename with normalized slug for accents and spaces."""
    raw_dir = tmp_path / "data" / "raw"
    dataset_dir = raw_dir / "AvesChilenas"
    dataset_dir.mkdir(parents=True, exist_ok=True)
    metadata_file = dataset_dir / "metadata.csv"
    metadata_file.write_text("nombre_archivo,clase,frecuencia_muestreo,duracion_segundos,tamano_bytes,hash_archivo,xc_id,recordist,licencia,pais,localidad,lat,lon,calidad\n")

    source_audio = tmp_path / "audios_prueba" / "canto_churrin.wav"
    _create_dummy_wav(source_audio)

    monkeypatch.setattr(feedback_service, "raw_data_dir", raw_dir)

    pred = Prediccion(
        ruta_audio_prueba="raw_audios/0123456789abcdef0123456789abcdef.wav",
        etiqueta_predicha="Chercán",
        dataset_name="AvesChilenas",
        confianza=0.65,
    )
    test_db.add(pred)
    test_db.commit()
    test_db.refresh(pred)

    fb = Retroalimentacion(
        id_prediccion=pred.id_prediccion,
        fue_correcta=False,
        etiqueta_corregida="Churrín de la Mocha",
        procesado=False,
    )
    test_db.add(fb)
    test_db.commit()
    test_db.refresh(fb)

    response = client.post(f"/api/feedback/{fb.id_retroalimentacion}/approve?dataset_name=AvesChilenas")
    assert response.status_code == 200
    data = response.json()
    expected_filename = f"churrin_de_la_mocha_fb_{fb.id_retroalimentacion}.wav"
    assert data.get("filename") == expected_filename

    expected_audio = dataset_dir / "Churrín de la Mocha" / expected_filename
    assert expected_audio.exists()
    assert expected_filename in metadata_file.read_text()


def test_reject_feedback(client, test_db, tmp_path, monkeypatch):
    """POST /api/feedback/{id}/reject marks procesado=True without altering raw datasets."""
    raw_dir = tmp_path / "data" / "raw"
    dataset_dir = raw_dir / "AvesChilenas"
    dataset_dir.mkdir(parents=True, exist_ok=True)
    metadata_file = dataset_dir / "metadata.csv"
    initial_metadata = "nombre_archivo,clase,frecuencia_muestreo,duracion_segundos,tamano_bytes,hash_archivo,xc_id,recordist,licencia,pais,localidad,lat,lon,calidad\n"
    metadata_file.write_text(initial_metadata)

    monkeypatch.setattr(feedback_service, "raw_data_dir", raw_dir)

    pred = Prediccion(
        ruta_audio_prueba="audios_prueba/canto_rejected.wav",
        etiqueta_predicha="Fío-fío",
        confianza=0.60,
    )
    test_db.add(pred)
    test_db.commit()
    test_db.refresh(pred)

    fb = Retroalimentacion(
        id_prediccion=pred.id_prediccion,
        fue_correcta=False,
        etiqueta_corregida="Chercán",
        procesado=False,
    )
    test_db.add(fb)
    test_db.commit()
    test_db.refresh(fb)

    response = client.post(f"/api/feedback/{fb.id_retroalimentacion}/reject")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "rejected"

    test_db.refresh(fb)
    assert fb.procesado is True

    # Verify metadata.csv was untouched
    assert metadata_file.read_text() == initial_metadata
    assert not (dataset_dir / "Chercán" / "canto_rejected.wav").exists()


def test_get_feedback_stats(client, test_db, monkeypatch):
    """GET /api/feedback/stats returns consolidated metrics including pending_curation_count."""
    pred1 = Prediccion(ruta_audio_prueba="a1.wav", etiqueta_predicha="Chucao", confianza=0.9)
    pred2 = Prediccion(ruta_audio_prueba="a2.wav", etiqueta_predicha="Rayadito", confianza=0.7)
    test_db.add_all([pred1, pred2])
    test_db.commit()

    fb1 = Retroalimentacion(id_prediccion=pred1.id_prediccion, fue_correcta=True, procesado=True)
    fb2 = Retroalimentacion(id_prediccion=pred2.id_prediccion, fue_correcta=False, etiqueta_corregida="Turca", procesado=False)
    test_db.add_all([fb1, fb2])
    test_db.commit()

    response = client.get("/api/feedback/stats")
    assert response.status_code == 200
    data = response.json()
    assert data["total_validated"] == 2
    assert data["correct_count"] == 1
    assert data["corrected_count"] == 1
    assert data["accuracy_rate"] == 50.0
    assert data["pending_curation_count"] == 1
    assert len(data["corrections_breakdown"]) == 1
    assert data["corrections_breakdown"][0]["species"] == "Turca"


def test_approve_nonexistent_feedback_returns_404(client):
    """POST /api/feedback/{id}/approve returns 404 for non-existent feedback."""
    response = client.post("/api/feedback/99999/approve?dataset_name=AvesChilenas")
    assert response.status_code == 404


def test_reject_nonexistent_feedback_returns_404(client):
    """POST /api/feedback/{id}/reject returns 404 for non-existent feedback."""
    response = client.post("/api/feedback/99999/reject")
    assert response.status_code == 404
