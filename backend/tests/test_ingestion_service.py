import sys
from pathlib import Path
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone
import pytest

_BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))


def test_get_storage_status_connected():
    """Verifica que el servicio retorne el estado de conexión al bucket GCS."""
    from app.services.ingestion import IngestionService

    with patch("google.cloud.storage.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_bucket = MagicMock()
        mock_client.bucket.return_value = mock_bucket

        # Simular 2 blobs en el bucket
        blob1 = MagicMock(size=1024)
        blob2 = MagicMock(size=2048)
        mock_client.list_blobs.return_value = [blob1, blob2]

        service = IngestionService(bucket_name="test-bucket")
        status = service.get_storage_status()

        assert status["connected"] is True
        assert status["bucket"] == "test-bucket"
        assert status["total_objects"] == 2
        assert status["total_bytes"] == 3072


def test_list_datasets_empty_bucket():
    """Verifica que retorne lista vacía si no hay datasets en GCS."""
    from app.services.ingestion import IngestionService

    with patch("google.cloud.storage.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.list_blobs.return_value = []

        service = IngestionService(bucket_name="test-bucket")
        datasets = service.list_datasets()

        assert datasets == []


def test_list_datasets_two_level_hierarchy():
    """Verifica agrupación por dataset_name y extracción de clases: datasets/{dataset}/{class}/{audio}.wav"""
    from app.services.ingestion import IngestionService

    with patch("google.cloud.storage.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client

        now = datetime.now(timezone.utc)
        blob1 = MagicMock(name="datasets/AvesChilenas/Chucao/c1.wav", size=500000, updated=now)
        blob1.name = "datasets/AvesChilenas/Chucao/c1.wav"
        blob2 = MagicMock(name="datasets/AvesChilenas/Chucao/c2.wav", size=300000, updated=now)
        blob2.name = "datasets/AvesChilenas/Chucao/c2.wav"
        blob3 = MagicMock(name="datasets/AvesChilenas/Canastero/ca1.wav", size=400000, updated=now)
        blob3.name = "datasets/AvesChilenas/Canastero/ca1.wav"
        blob4 = MagicMock(name="datasets/MotoresAutos/Diesel/m1.wav", size=600000, updated=now)
        blob4.name = "datasets/MotoresAutos/Diesel/m1.wav"

        mock_client.list_blobs.return_value = [blob1, blob2, blob3, blob4]

        service = IngestionService(bucket_name="test-bucket")
        datasets = service.list_datasets()

        assert len(datasets) == 2
        names = [d["name"] for d in datasets]
        assert "AvesChilenas" in names
        assert "MotoresAutos" in names

        aves = next(d for d in datasets if d["name"] == "AvesChilenas")
        assert aves["file_count"] == 3
        assert aves["total_size_bytes"] == 1200000
        assert set(aves["classes"]) == {"Chucao", "Canastero"}
        assert aves["class_count"] == 2

        motores = next(d for d in datasets if d["name"] == "MotoresAutos")
        assert motores["file_count"] == 1
        assert motores["classes"] == ["Diesel"]
        assert motores["class_count"] == 1


def test_sync_dataset_only_new_files(tmp_path):
    """Verifica RF_02: descarga masiva sólo si son archivos nuevos o modificados."""
    from app.services.ingestion import IngestionService

    with patch("google.cloud.storage.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_bucket = MagicMock()
        mock_client.bucket.return_value = mock_bucket

        now = datetime.now(timezone.utc)
        
        # Blob 1: ya existe localmente con el mismo tamaño -> debe ignorarse
        blob1 = MagicMock()
        blob1.name = "datasets/Chucao/existing.wav"
        blob1.size = 100
        blob1.updated = now
        
        # Blob 2: nuevo -> debe descargarse
        blob2 = MagicMock()
        blob2.name = "datasets/Chucao/new_file.wav"
        blob2.size = 200
        blob2.updated = now
        
        mock_client.list_blobs.return_value = [blob1, blob2]

        local_dir = tmp_path / "raw"
        local_dataset = local_dir / "Chucao"
        local_dataset.mkdir(parents=True, exist_ok=True)
        # Crear existing.wav localmente con tamaño 100 bytes
        (local_dataset / "existing.wav").write_bytes(b"x" * 100)

        service = IngestionService(bucket_name="test-bucket", local_base_dir=local_dir)
        result = service.sync_dataset_to_local("Chucao")

        assert result["downloaded"] == 1
        assert result["skipped"] == 1
        assert result["failed"] == 0
        # blob2 debe haber llamado a download_to_filename
        blob2.download_to_filename.assert_called_once()
        blob1.download_to_filename.assert_not_called()


def test_upload_files_with_class_label():
    """Verifica que la subida construya la ruta de dos niveles datasets/{dataset}/{class}/{file}."""
    from app.services.ingestion import IngestionService

    with patch("google.cloud.storage.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_bucket = MagicMock()
        mock_client.bucket.return_value = mock_bucket
        mock_blob = MagicMock()
        mock_bucket.blob.return_value = mock_blob

        service = IngestionService(bucket_name="test-bucket")
        result = service.upload_files_to_gcs(
            files=[("audio1.wav", b"dummy")],
            dataset_name="AvesChilenas",
            class_label="Chucao",
        )

        assert result["uploaded"] == 1
        assert result["dataset"] == "AvesChilenas"
        assert result["class_label"] == "Chucao"
        mock_bucket.blob.assert_called_once_with("datasets/AvesChilenas/Chucao/audio1.wav")
        mock_blob.upload_from_string.assert_called_once()


def test_sync_dataset_with_db_persistence(tmp_path):
    """Verifica que sync_dataset_to_local persista registros en las tablas conjunto_datos y audio."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.database import Base
    from app.models.dataset import ConjuntoDatos, Audio
    from app.services.ingestion import IngestionService

    # Base de datos SQLite temporal en memoria
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    db = Session()

    with patch("google.cloud.storage.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client

        blob1 = MagicMock()
        blob1.name = "datasets/TestPersist/Chucao/audio1.wav"
        blob1.size = 200
        mock_client.list_blobs.return_value = [blob1]

        local_dir = tmp_path / "raw"
        service = IngestionService(bucket_name="test-bucket", local_base_dir=local_dir)
        res = service.sync_dataset_to_local("TestPersist", db=db)

        assert res["downloaded"] == 1
        assert res["db_persisted"] is True

        # Verificar que se creó el ConjuntoDatos
        ds_record = db.query(ConjuntoDatos).filter_by(nombre="TestPersist").first()
        assert ds_record is not None
        assert ds_record.estado == "sincronizado"
        assert ds_record.cantidad_audios == 1

        # Verificar que se creó el Audio
        audio_record = db.query(Audio).filter_by(nombre_archivo="audio1.wav").first()
        assert audio_record is not None
        assert audio_record.clase == "Chucao"
        assert audio_record.id_conjunto_datos == ds_record.id_conjunto_datos

    db.close()


def test_sync_dataset_with_preprocess_trigger(tmp_path):
    """Verifica que sync_dataset_to_local ejecute la extracción tensorial cuando preprocess=True (RF_03)."""
    from app.services.ingestion import IngestionService

    with patch("google.cloud.storage.Client") as mock_client_cls, \
         patch("app.services.ingestion.IngestionService.preprocess_dataset_to_tensors") as mock_prep:
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client

        blob1 = MagicMock()
        blob1.name = "datasets/ChucaoDS/Chucao/audio1.wav"
        blob1.size = 200
        mock_client.list_blobs.return_value = [blob1]

        mock_prep.return_value = {
            "processed": 1,
            "failed": 0,
            "tensors_dir": str(tmp_path / "processed"),
            "duration_seconds": 0.15,
        }

        local_dir = tmp_path / "raw"
        service = IngestionService(bucket_name="test-bucket", local_base_dir=local_dir)
        res = service.sync_dataset_to_local("ChucaoDS", preprocess=True)

        assert res["downloaded"] == 1
        assert res["preprocessed"] == 1
        mock_prep.assert_called_once_with("ChucaoDS")


