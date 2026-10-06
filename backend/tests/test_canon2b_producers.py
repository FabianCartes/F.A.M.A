"""Downloaded raw -> indexed derivative -> canonical reader, wholly synthetic."""
import hashlib
import io
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest
import soundfile as sf

from dataset_references import resolve_reference
from poc.download import run_download_pipeline
from poc.sanitize import sanitize_dataset
from training.pipelines.dataset import GenericAudioDataset
from training.schemas.config import AudioConfig


def test_downloaded_raw_to_processed_canonical_reader_without_repartition(tmp_path, monkeypatch):
    stream = io.BytesIO()
    sf.write(stream, np.full(8000, .25), 8000, format="WAV", subtype="PCM_16")
    original = stream.getvalue()
    session = MagicMock()
    downloads = []

    def get(url, **kwargs):
        response = MagicMock(status_code=200)
        response.__enter__.return_value = response
        if "/api/" in url:
            response.json.return_value = {"numPages": 1, "recordings": [
                {"id": "00042", "file": "https://fake/audio", "rec": "NA", "loc": "001", "q": "A"}]}
        else:
            downloads.append(url)
            response.iter_content.return_value = [original]
        return response

    session.get.side_effect = get
    monkeypatch.setattr("poc.download.requests.Session", lambda: session)
    raw = tmp_path / "physical-raw"
    processed = tmp_path / "physical-processed" / "processed_wav"
    roots = {"raw": raw, "processed": processed}
    index = tmp_path / "indices" / "raw.csv"
    frame = run_download_pipeline(data_dir=raw, metadata_index=index, api_key="fake",
                                   species_list=[("Chincol", "Fake species")])
    assert len(frame) == 1
    assert len(downloads) == 1
    row = frame.iloc[0]
    assert row["file_path"] == "chincol/00042.mp3"
    assert row["file_stage"] == "raw"
    assert resolve_reference(row["file_path"], row["file_stage"], roots).read_bytes() == original
    assert row["hash_archivo"] == hashlib.sha256(original).hexdigest()
    # Preserve historical split bytes; the producer must not invoke a splitter.
    for split in ("train", "val", "test"):
        (raw / f"{split}.csv").write_bytes(b"historical membership,00042\n")
    before = index.read_bytes()
    stats = sanitize_dataset(raw, processed, target_sr=22050, num_workers=1,
                             metadata_index=index, roots=roots)
    assert (stats["total"], stats["converted"], stats["failed"]) == (1, 1, 0)
    derived = pd.read_csv(processed / "metadata.csv", dtype=str, keep_default_na=False)
    source_fields = pd.read_csv(index, dtype=str, keep_default_na=False).iloc[0].to_dict()
    assert derived.iloc[0].to_dict() == {**source_fields, "file_path": "chincol/00042.wav", "file_stage": "processed"}
    assert index.read_bytes() == before
    for split in ("train", "val", "test"):
        assert (raw / f"{split}.csv").read_bytes() == b"historical membership,00042\n"
    derivative = resolve_reference("chincol/00042.wav", "processed", roots)
    assert hashlib.sha256(derivative.read_bytes()).hexdigest() != source_fields["hash_archivo"]
    dataset = GenericAudioDataset(derived, AudioConfig(target_sr=22050, duration_seconds=1),
                                  {"Chincol": 0}, roots=roots)
    waveform, label = dataset[0]
    assert waveform.mean().item() == pytest.approx(.25, abs=.001)
    assert label.item() == 0
    assert waveform.shape == (22050,)
