import tempfile
from pathlib import Path
import pandas as pd
import numpy as np
import soundfile as sf
import pytest

from training.datasets.base import DatasetIngestor, AudioRecordingMetadata
from training.datasets.local_folder import LocalFolderPAMIngestor


@pytest.fixture
def temp_audio_dir():
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        # Crear estructura por especies: species_a y species_b
        sp_a = root / "chucao"
        sp_b = root / "zorzal"
        sp_a.mkdir(parents=True)
        sp_b.mkdir(parents=True)

        sr = 22050
        audio_data = np.zeros(sr * 2, dtype=np.float32)

        sf.write(sp_a / "audio1.wav", audio_data, sr)
        sf.write(sp_a / "audio2.wav", audio_data, sr)
        sf.write(sp_b / "audio3.wav", audio_data, sr)

        yield root


def test_local_folder_ingestor_species_directories(temp_audio_dir):
    ingestor = LocalFolderPAMIngestor(source_dir=temp_audio_dir)
    df = ingestor.ingest()

    assert isinstance(df, pd.DataFrame)
    assert len(df) == 3

    # Verificar columnas canónicas obligatorias
    required_cols = ["nombre_archivo", "file_path", "clase", "labels", "recordist", "duracion_segundos"]
    for col in required_cols:
        assert col in df.columns

    clases = set(df["clase"].tolist())
    assert "chucao" in clases
    assert "zorzal" in clases
    # Asegurar que labels sea una lista con al menos la clase primaria
    for labels in df["labels"]:
        assert isinstance(labels, list)
        assert len(labels) >= 1


def test_local_folder_ingestor_soundscape_pam_annotations():
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        sr = 32000
        audio_data = np.zeros(sr * 3, dtype=np.float32)

        audio_file = root / "pam_rec_001.wav"
        sf.write(audio_file, audio_data, sr)

        # Crear archivo de anotaciones multi-etiqueta
        annotations_df = pd.DataFrame([
            {"filename": "pam_rec_001.wav", "species": "Batrachyla leptopus", "recordist": "sensor_station_01"},
            {"filename": "pam_rec_001.wav", "species": "Pleurodema thaul", "recordist": "sensor_station_01"},
        ])
        annotations_path = root / "annotations.csv"
        annotations_df.to_csv(annotations_path, index=False)

        ingestor = LocalFolderPAMIngestor(
            source_dir=root,
            annotations_csv=annotations_path,
        )
        df = ingestor.ingest()

        assert len(df) == 1
        row = df.iloc[0]
        assert row["nombre_archivo"] == "pam_rec_001.wav"
        assert row["recordist"] == "sensor_station_01"
        assert len(row["labels"]) == 2
        assert "Batrachyla leptopus" in row["labels"]
        assert "Pleurodema thaul" in row["labels"]
