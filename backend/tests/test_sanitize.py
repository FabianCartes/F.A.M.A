import soundfile as sf
import numpy as np
import pytest
from pathlib import Path
from poc.sanitize import sanitize_audio_file, sanitize_dataset
from poc.train import AudioDataset
import pandas as pd


def test_sanitize_audio_file_converts_to_pcm16_wav(tmp_path):
    # Generar un audio sintético a 44100 Hz
    duration_s = 1.0
    orig_sr = 44100
    target_sr = 22050
    t = np.linspace(0, duration_s, int(orig_sr * duration_s), endpoint=False)
    sine = 0.5 * np.sin(2 * np.pi * 440 * t)
    
    src_file = tmp_path / "input.wav"
    dst_file = tmp_path / "output.wav"
    sf.write(str(src_file), sine, orig_sr)
    
    success = sanitize_audio_file(src_file, dst_file, target_sr=target_sr)
    assert success is True
    assert dst_file.exists()
    
    # Verificar formato PCM_16 y frecuencia de muestreo convertida
    info = sf.info(str(dst_file))
    assert info.samplerate == target_sr
    assert info.subtype == "PCM_16"
    assert info.channels == 1


def test_sanitize_audio_file_handles_corrupt_or_empty_input(tmp_path):
    empty_file = tmp_path / "corrupt.mp3"
    empty_file.write_bytes(b"NOT_AN_AUDIO_FILE")
    dst_file = tmp_path / "output.wav"
    
    success = sanitize_audio_file(empty_file, dst_file)
    assert success is False
    assert not dst_file.exists()


def test_sanitize_dataset_concurrency_and_structure(tmp_path):
    raw_dir = tmp_path / "raw"
    species_dir = raw_dir / "chincol"
    species_dir.mkdir(parents=True)
    
    # Crear dos archivos válidos
    t = np.linspace(0, 0.5, int(22050 * 0.5), endpoint=False)
    audio = 0.3 * np.sin(2 * np.pi * 440 * t)
    sf.write(str(species_dir / "1.wav"), audio, 22050)
    sf.write(str(species_dir / "2.wav"), audio, 22050)
    
    out_dir = tmp_path / "processed_wav"
    stats = sanitize_dataset(raw_dir, out_dir, target_sr=22050, num_workers=2)
    
    assert stats["total"] == 2
    assert stats["converted"] == 2
    assert stats["failed"] == 0
    assert (out_dir / "chincol" / "1.wav").exists()
    assert (out_dir / "chincol" / "2.wav").exists()


def test_audio_dataset_prefers_sanitized_wav_over_mp3(tmp_path):
    raw_dir = tmp_path / "raw"
    sp_dir = raw_dir / "chincol"
    sp_dir.mkdir(parents=True)
    
    t = np.linspace(0, 1.0, 22050, endpoint=False)
    audio = 0.2 * np.sin(2 * np.pi * 440 * t)
    
    # Crear tanto el mp3 como el wav saneado
    sf.write(str(sp_dir / "100.mp3"), audio, 22050)
    sf.write(str(sp_dir / "100.wav"), audio, 22050)
    
    df = pd.DataFrame([{"nombre_archivo": "100.mp3", "clase": "Chincol", "xc_id": "100"}])
    ds = AudioDataset(df, raw_dir, {"Chincol": 0})
    
    resolved = ds._resolve_file_path(df.iloc[0])
    assert resolved.suffix == ".wav"
