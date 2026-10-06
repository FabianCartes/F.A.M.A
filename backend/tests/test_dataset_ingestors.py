import tempfile
from pathlib import Path
import pandas as pd
import numpy as np
import soundfile as sf
import pytest

from training.datasets.base import DatasetIngestor, AudioRecordingMetadata
from training.datasets.local_folder import LocalFolderPAMIngestor
from training.datasets.xenocanto import XenoCantoIngestor
from dataset_references import resolve_reference


def test_xenocanto_reads_explicit_reference(tmp_path):
    (tmp_path / "birds").mkdir()
    audio = tmp_path / "birds/42.mp3"
    audio.write_bytes(b"original")
    csv_path = tmp_path / "metadata.csv"
    pd.DataFrame([dict(nombre_archivo="not-a-lookup.mp3", file_path="birds/42.mp3",
                       file_stage="raw", clase="Bird", recordist="author", xc_id="42",
                       hash_archivo="digest")]).to_csv(csv_path, index=False)
    row = XenoCantoIngestor(csv_path, tmp_path).ingest().iloc[0]
    assert row["file_path"] == "birds/42.mp3"
    assert row["file_stage"] == "raw"
    assert resolve_reference(row["file_path"], row["file_stage"], {"raw": tmp_path}) == audio
    assert (row["clase"], row["recordist"], row["source_id"], row["hash_archivo"]) == (
        "Bird", "author", "42", "digest")


def test_local_canonical_csv_preserves_labels_identity_and_provenance(tmp_path):
    sf.write(tmp_path / "recording.wav", np.full(800, .1, dtype=np.float32), 8000)
    metadata = AudioRecordingMetadata(nombre_archivo="recording.wav", file_path="recording.wav",
                                      file_stage="raw", clase="Primary", labels=["Primary", "Secondary"],
                                      source_id="0042", recordist="station", hash_archivo="knownhash",
                                      extra_metadata={"sensor": "PAM"})
    csv_path = tmp_path / "index.csv"
    pd.DataFrame([metadata.model_dump()]).to_csv(csv_path, index=False)
    row = LocalFolderPAMIngestor(tmp_path, csv_path).ingest().iloc[0]
    assert row["labels"] == ["Primary", "Secondary"]
    assert row["source_id"] == "0042"
    assert row["recordist"] == "station"
    assert row["hash_archivo"] == "knownhash"
    assert row["extra_metadata"] == {"sensor": "PAM"}


@pytest.mark.parametrize("fields", [
    {}, {"file_path": "birds/a.wav"}, {"file_path": "", "file_stage": "raw"},
    {"file_path": "../birds/a.wav", "file_stage": "raw"},
    {"file_path": "birds/missing.wav", "file_stage": "raw"},
    {"file_path": "birds/a.wav", "file_stage": "processed"},
    {"file_path": "birds/a.wav", "file_stage": "unknown"},
])
def test_index_importers_never_fallback_to_filename(tmp_path, fields):
    (tmp_path / "birds").mkdir()
    (tmp_path / "birds/a.wav").write_bytes(b"known original")
    csv_path = tmp_path / "index.csv"
    pd.DataFrame([dict(nombre_archivo="a.wav", clase="Bird", recordist="author", **fields)]).to_csv(csv_path, index=False)
    for importer in (XenoCantoIngestor(csv_path, tmp_path),
                     LocalFolderPAMIngestor(tmp_path, annotations_csv=csv_path)):
        with pytest.raises(ValueError):
            importer.ingest()


def test_importers_reject_processed_link_as_raw_root(tmp_path):
    processed = tmp_path / "processed"
    processed.mkdir()
    (processed / "a.wav").write_bytes(b"derived")
    alias = tmp_path / "raw"
    alias.symlink_to(processed, target_is_directory=True)
    csv_path = tmp_path / "index.csv"
    pd.DataFrame([dict(nombre_archivo="a.wav", file_path="a.wav", file_stage="raw",
                       clase="Bird", recordist="author")]).to_csv(csv_path, index=False)
    for importer in (XenoCantoIngestor(csv_path, alias), LocalFolderPAMIngestor(alias)):
        with pytest.raises(ValueError, match="symlink|physical"):
            importer.ingest()


def test_discovery_excludes_linked_directories_but_blocks_linked_audio(tmp_path):
    root = tmp_path / "raw"
    root.mkdir()
    outside = tmp_path / "derived"
    outside.mkdir()
    (outside / "a.wav").write_bytes(b"derived")
    (root / "processed_wav").symlink_to(outside, target_is_directory=True)
    assert LocalFolderPAMIngestor(root).ingest().empty
    (root / "a.wav").symlink_to(outside / "a.wav")
    with pytest.raises(ValueError, match="symlink"):
        LocalFolderPAMIngestor(root).ingest()


@pytest.mark.parametrize("count", [0, 2])
def test_pam_filename_import_requires_unique_match(tmp_path, count):
    for index in range(count):
        folder = tmp_path / str(index)
        folder.mkdir()
        (folder / "a.wav").write_bytes(b"fixture")
    csv_path = tmp_path / "annotations.csv"
    pd.DataFrame([dict(filename="a.wav", species="Bird")]).to_csv(csv_path, index=False)
    with pytest.raises(ValueError, match="exactly one"):
        LocalFolderPAMIngestor(tmp_path, csv_path, input_mode="pam_filename").ingest()


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
    required_cols = ["nombre_archivo", "file_path", "file_stage", "clase", "labels", "recordist", "duracion_segundos"]
    for col in required_cols:
        assert col in df.columns

    assert set(df["file_stage"]) == {"raw"}
    assert set(df["file_path"]) == {"chucao/audio1.wav", "chucao/audio2.wav", "zorzal/audio3.wav"}
    for row in df.to_dict("records"):
        assert resolve_reference(row["file_path"], row["file_stage"], {"raw": temp_audio_dir}).is_file()
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
            input_mode="pam_filename",
        )
        df = ingestor.ingest()

        assert len(df) == 1
        row = df.iloc[0]
        assert row["nombre_archivo"] == "pam_rec_001.wav"
        assert row["recordist"] == "sensor_station_01"
        assert len(row["labels"]) == 2
        assert "Batrachyla leptopus" in row["labels"]
        assert "Pleurodema thaul" in row["labels"]
