"""Public producer/consumer contracts, using synthetic audio and declared roots only."""
from pathlib import Path
import numpy as np
import pandas as pd
import pytest
import soundfile as sf

from dataset_references import resolve_reference
from training.datasets.local_folder import LocalFolderPAMIngestor
from training.pipelines.dataset import GenericAudioDataset
from training.schemas.config import AudioConfig
from training.prepare_engine_data import prepare_engine_dataset


def write_audio(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(path, np.full(800, 0.25, dtype=np.float32), 8000)


def test_consumer_resolves_declared_roots_portably(tmp_path):
    for host in ("host_a", "host_b"):
        root = tmp_path / host
        write_audio(root / "Bird/recording_1.wav")
        frame = LocalFolderPAMIngestor(root).ingest()
        dataset = GenericAudioDataset(frame, AudioConfig(target_sr=8000, duration_seconds=.1),
                                      {"Bird": 0}, roots={"raw": root})
        waveform, label = dataset[0]
        assert waveform.shape == (800,)
        assert waveform.mean().item() == pytest.approx(.25, abs=.001)
        assert label.item() == 0
        assert frame.iloc[0]["file_path"] == "Bird/recording_1.wav"


@pytest.mark.parametrize("reference,stage", [("missing.wav", "raw"), ("../escape.wav", "raw"),
                                            ("Bird/a.wav", ""), ("Bird/a.wav", "unknown")])
def test_consumer_invalid_reference_fails_before_audio_loading(tmp_path, reference, stage):
    frame = pd.DataFrame([dict(file_path=reference, file_stage=stage, clase="Bird")])
    with pytest.raises(ValueError):
        dataset = GenericAudioDataset(frame, AudioConfig(), {"Bird": 0}, roots={"raw": tmp_path})
        dataset[0]


def test_consumer_uses_stage_not_extension_and_revalidates(tmp_path):
    raw = tmp_path / "raw"
    processed = tmp_path / "processed"
    write_audio(raw / "Bird/a.wav")
    write_audio(processed / "Bird/a.wav")
    sf.write(processed / "Bird/a.wav", np.full(800, .5, dtype=np.float32), 8000)
    frame = pd.DataFrame([dict(file_path="Bird/a.wav", file_stage="processed", clase="Bird")])
    dataset = GenericAudioDataset(frame, AudioConfig(target_sr=8000, duration_seconds=.1),
                                  {"Bird": 0}, roots={"raw": raw, "processed": processed})
    assert dataset[0][0].mean().item() == pytest.approx(.5, abs=.001)
    (processed / "Bird").rename(processed / "original")
    (processed / "Bird").symlink_to(processed / "original", target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        dataset[0]


def test_consumer_cannot_accept_absolute_persisted_rows(tmp_path):
    write_audio(tmp_path / "a.wav")
    frame = pd.DataFrame([dict(file_path=str(tmp_path / "a.wav"), file_stage="raw", clase="Bird")])
    with pytest.raises(ValueError):
        GenericAudioDataset(frame, AudioConfig(), {"Bird": 0}, roots={"raw": tmp_path})


def test_prepare_engine_rejects_linked_source(tmp_path):
    source = tmp_path / "source"
    write_audio(source / "Bird/a.wav")
    alias = tmp_path / "alias"
    alias.symlink_to(source, target_is_directory=True)
    with pytest.raises(ValueError, match="physical"):
        prepare_engine_dataset(alias)
    assert not list(source.glob("*_metadata.csv"))


def test_prepare_engine_persists_canonical_splits(tmp_path):
    source = tmp_path / "source"
    for clase in ("Healthy", "Fault"):
        for group in range(6):
            for segment in (1, 2):
                write_audio(source / clase / f"engine{group}_{segment}.wav")
    output = tmp_path / "splits"
    prepare_engine_dataset(source, output_dir=output)
    frames = [pd.read_csv(output / f"{split}_metadata.csv") for split in ("train", "val", "test")]
    assert sum(map(len, frames)) == 24
    groups = [set(frame["recordist"]) for frame in frames]
    assert not (groups[0] & groups[1] or groups[0] & groups[2] or groups[1] & groups[2])
    for frame in frames:
        assert set(frame["clase"]) == {"Healthy", "Fault"}
        assert set(frame["file_stage"]) == {"raw"}
        for row in frame.to_dict("records"):
            assert not Path(row["file_path"]).is_absolute()
            path = resolve_reference(row["file_path"], row["file_stage"], {"raw": source})
            assert path.stem == row["source_id"]
            assert row["recordist"].endswith(path.stem.rsplit("_", 1)[0])
