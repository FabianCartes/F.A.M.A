import pytest
from pathlib import Path
import tempfile
import numpy as np
import soundfile as sf
import torch
from torch import nn

from poc.preprocess import (
    GPUAudioFrontEnd,
    build_gpu_audio_frontend_contract,
    load_and_fix_length,
    validate_gpu_audio_frontend_contract,
)
from app.services.predictors import trained_predictor as predictor_module
from app.services.predictors.trained_predictor import (
    TrainedModelPredictor,
    ModelWeightsError,
)
from app.schemas.prediction import PredictionResult


CHECKPOINT_PATH = (
    Path(__file__).resolve().parent.parent
    / "checkpoints/fama_efficientnet_b0_1790539191_efficientnet_b0_best.pt"
)


def resolve_test_audio_path() -> Path:
    repo_root = Path(__file__).resolve().parent.parent.parent
    candidate_repo = repo_root / "audios_prueba" / "audio_prueba.wav"
    if candidate_repo.exists():
        return candidate_repo
    candidate_cwd = Path("audios_prueba/audio_prueba.wav").resolve()
    if candidate_cwd.exists():
        return candidate_cwd
    downloads = Path.home() / "Downloads" / "audio_prueba.wav"
    if downloads.exists():
        return downloads
    return candidate_repo


AUDIO_PRUEBA_PATH = resolve_test_audio_path()


def test_trained_predictor_lazy_loading_defers_model_instantiation():
    """
    Verifica que con lazy_load=True:
    1. predictor.model sea None tras la inicialización (ahorro crítico de RAM/VRAM).
    2. La metadata ligera (clases, arquitectura, métricas) esté poblada desde el checkpoint.
    3. Al llamar a predict(), el modelo PyTorch se instancie bajo demanda y clasifique.
    """
    if not CHECKPOINT_PATH.exists():
        pytest.skip(f"Checkpoint no disponible en {CHECKPOINT_PATH}")
    if not AUDIO_PRUEBA_PATH.exists():
        pytest.skip(f"Audio de prueba no disponible en {AUDIO_PRUEBA_PATH}")

    predictor = TrainedModelPredictor(checkpoint_path=CHECKPOINT_PATH, lazy_load=True)

    # Invariante 1: No debe cargar pesos en GPU/RAM en el constructor
    assert predictor.model is None

    # Invariante 2: Metadata ligera disponible de inmediato
    assert len(predictor.classes) == 15
    assert "Chucao" in predictor.classes
    assert predictor.architecture_name == "EfficientNet-B0"
    assert predictor.metadata.id == predictor.model_id
    assert predictor.metadata.classes == predictor.classes

    # Invariante 3: Inferencia bajo demanda instancia el modelo y predice
    result = predictor.predict(AUDIO_PRUEBA_PATH)
    assert predictor.model is not None
    assert isinstance(result, PredictionResult)
    assert result.clase == "Chucao"
    assert result.confianza >= 0.95


def test_trained_predictor_infers_real_audio():
    """
    Verifica que TrainedModelPredictor cargue el checkpoint entrenado en GPU
    y clasifique con alta confianza 'Chucao' en el audio real de prueba.
    """
    if not CHECKPOINT_PATH.exists():
        pytest.skip(f"Checkpoint no disponible en {CHECKPOINT_PATH}")
    if not AUDIO_PRUEBA_PATH.exists():
        pytest.skip(f"Audio de prueba no disponible en {AUDIO_PRUEBA_PATH}")

    predictor = TrainedModelPredictor(checkpoint_path=CHECKPOINT_PATH)
    assert predictor.model_id is not None
    assert len(predictor.classes) == 15
    assert "Chucao" in predictor.classes

    result = predictor.predict(AUDIO_PRUEBA_PATH)
    assert isinstance(result, PredictionResult)
    assert result.clase == "Chucao"
    assert result.confianza >= 0.95
    assert result.detalles is not None
    assert result.detalles.get("is_mock") is False
    assert result.detalles.get("checkpoint_name") == CHECKPOINT_PATH.name
    assert "device" in result.detalles
    assert result.detalles.get("latency_ms", 0) > 0


def test_trained_predictor_fails_fast_when_checkpoint_missing():
    """
    Invariante crítica: Si los pesos no existen, debe fallar con error explícito.
    Está terminantemente prohibido retornar mocks silenciosos.
    """
    missing_path = Path("/tmp/non_existent_weights_12345.pt")
    with pytest.raises(ModelWeightsError):
        TrainedModelPredictor(checkpoint_path=missing_path)


def test_trained_predictor_fails_fast_when_checkpoint_corrupted(tmp_path):
    """
    Si el archivo de pesos está corrupto o es inválido, falla ruidosamente.
    """
    corrupt_ckpt = tmp_path / "corrupt_model.pt"
    corrupt_ckpt.write_bytes(b"THIS_IS_NOT_A_VALID_TORCH_STATE_DICT")
    with pytest.raises(ModelWeightsError):
        TrainedModelPredictor(checkpoint_path=corrupt_ckpt)


def test_trained_predictor_fails_fast_when_audio_missing():
    """
    Si el archivo de audio a clasificar no existe, lanza FileNotFoundError.
    """
    if not CHECKPOINT_PATH.exists():
        pytest.skip(f"Checkpoint no disponible en {CHECKPOINT_PATH}")

    predictor = TrainedModelPredictor(checkpoint_path=CHECKPOINT_PATH)
    with pytest.raises(FileNotFoundError):
        predictor.predict(Path("/tmp/non_existent_audio_sample_9999.wav"))


def test_trained_predictor_detects_silence():
    """
    Valida que el filtro acústico VAD de energía detecte silencio absoluto.
    """
    if not CHECKPOINT_PATH.exists():
        pytest.skip(f"Checkpoint no disponible en {CHECKPOINT_PATH}")

    predictor = TrainedModelPredictor(checkpoint_path=CHECKPOINT_PATH)
    sr = 22050
    samples = np.zeros(sr * 3, dtype=np.float32)
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        sf.write(tmp.name, samples, sr)
        tmp_path = Path(tmp.name)

    try:
        res = predictor.predict(tmp_path)
        assert res.clase == "Silencio / No detectado"
        assert res.confianza == 0.0
        assert res.detalles["status"] == "silence"
        assert res.detalles["is_mock"] is False
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


def _standard_payload(contract=None):
    payload = {
        "job_id": "synthetic-job",
        "dataset_id": 1,
        "dataset_name": "engine_diagnostics",
        "audio_config": None,
        "windowing_config": None,
        "architecture": "AudioCNN",
        "classes": ["tone", "other"],
        "state_dict": {"marker": torch.tensor(0.0)},
    }
    if contract is not None:
        payload["preprocessing_contract"] = contract
    return payload


def _frontend_contract():
    return {
        "version": 1,
        "implementation": "GPUAudioFrontEnd",
        "sample_rate": 16000,
        "duration_seconds": 0.5,
        "parameters": {
            "n_mels": 32,
            "n_fft": 256,
            "hop_length": 64,
            "f_min": 50.0,
            "f_max": 7000.0,
            "top_db": 80.0,
            "normalize": True,
            "top_db_scope": "per_sample",
        },
    }


def test_standard_checkpoint_prediction_matches_its_saved_frontend_contract(tmp_path, monkeypatch):
    contract = _frontend_contract()
    checkpoint = tmp_path / "standard.pt"
    torch.save(_standard_payload(contract), checkpoint)
    sample_rate = contract["sample_rate"]
    samples = np.arange(sample_rate, dtype=np.float32) / sample_rate
    waveform = (0.35 * np.sin(2 * np.pi * 440 * samples) +
                0.12 * np.sin(2 * np.pi * 880 * samples)).astype(np.float32)
    audio_path = tmp_path / "tone.wav"
    sf.write(audio_path, waveform, sample_rate)

    class InputProbe(nn.Module):
        def __init__(self, num_classes):
            super().__init__()
            self.marker = nn.Parameter(torch.tensor(0.0))
            self.observed = None

        def forward(self, inputs):
            self.observed = inputs.detach().cpu().clone()
            score = inputs.square().mean(dim=(1, 2, 3)) + self.marker
            return torch.stack((score, -score), dim=1)

    monkeypatch.setattr(predictor_module, "AudioCNN", InputProbe)
    predictor = TrainedModelPredictor(checkpoint, lazy_load=True)
    result = predictor.predict(audio_path)

    fixed_waveform = predictor_module.load_and_fix_length(
        audio_path, target_sr=contract["sample_rate"],
        duration_seconds=contract["duration_seconds"],
    )
    params = contract["parameters"]
    expected = GPUAudioFrontEnd(
        sample_rate=contract["sample_rate"],
        n_mels=params["n_mels"], n_fft=params["n_fft"],
        hop_length=params["hop_length"], f_min=params["f_min"],
        f_max=params["f_max"], top_db=params["top_db"],
        normalize=params["normalize"], top_db_scope=params["top_db_scope"],
    )(torch.from_numpy(fixed_waveform).unsqueeze(0))

    assert result.clase == "tone"
    torch.testing.assert_close(predictor.model.observed, expected, rtol=0, atol=0)


@pytest.mark.parametrize("contract", [
    None,
    {"version": 999, "implementation": "GPUAudioFrontEnd"},
    {
        **_frontend_contract(),
        "parameters": {**_frontend_contract()["parameters"], "top_db": -1.0},
    },
    {
        **_frontend_contract(),
        "parameters": {**_frontend_contract()["parameters"], "top_db_scope": "batch"},
    },
])
def test_standard_checkpoint_rejects_missing_invalid_or_unsupported_frontend_contract(
    tmp_path, contract
):
    checkpoint = tmp_path / "standard.pt"
    torch.save(_standard_payload(contract), checkpoint)

    with pytest.raises(ModelWeightsError, match="preprocessing|contract|checkpoint"):
        TrainedModelPredictor(checkpoint, lazy_load=True)


def test_standard_checkpoint_rejects_v1_contract_missing_top_db_scope(tmp_path):
    contract = _frontend_contract()
    del contract["parameters"]["top_db_scope"]
    checkpoint = tmp_path / "standard-missing-top-db-scope.pt"
    torch.save(_standard_payload(contract), checkpoint)

    with pytest.raises(ModelWeightsError, match="preprocessing|contract|checkpoint"):
        TrainedModelPredictor(checkpoint, lazy_load=True)


def test_historical_nonstandard_checkpoint_keeps_legacy_inference(tmp_path, monkeypatch):
    checkpoint = tmp_path / "historical.pt"
    torch.save({
        "architecture": "AudioCNN",
        "classes": ["tone", "other"],
        "state_dict": {"marker": torch.tensor(0.0)},
    }, checkpoint)
    sample_rate = predictor_module.TARGET_SR
    samples = np.arange(sample_rate, dtype=np.float32) / sample_rate
    audio_path = tmp_path / "historical-tone.wav"
    sf.write(audio_path, 0.35 * np.sin(2 * np.pi * 440 * samples), sample_rate)

    class InputProbe(nn.Module):
        def __init__(self, num_classes):
            super().__init__()
            self.marker = nn.Parameter(torch.tensor(0.0))
            self.observed = None

        def forward(self, inputs):
            self.observed = inputs.detach().cpu().clone()
            score = inputs.square().mean(dim=(1, 2, 3)) + self.marker
            return torch.stack((score, -score), dim=1)

    monkeypatch.setattr(predictor_module, "AudioCNN", InputProbe)
    predictor = TrainedModelPredictor(checkpoint, lazy_load=True)
    result = predictor.predict(audio_path)
    waveform = predictor_module.load_and_fix_length(
        audio_path, target_sr=sample_rate, duration_seconds=predictor_module.DURATION_SECONDS)
    mel = predictor_module.extract_mel_spectrogram(waveform, sr=sample_rate)
    expected = torch.from_numpy(mel).unsqueeze(0).unsqueeze(0)

    assert result.clase == "tone"
    torch.testing.assert_close(predictor.model.observed, expected, rtol=0, atol=0)


def test_gpu_audio_frontend_single_sample_matches_same_sample_in_batch():
    frontend = GPUAudioFrontEnd(
        sample_rate=16000, n_mels=16, n_fft=256, hop_length=64,
        f_min=50.0, f_max=7000.0,
    )
    time = torch.arange(2048, dtype=torch.float32) / 16000
    sample = torch.sin(2 * torch.pi * 440 * time)
    other_sample = torch.sin(2 * torch.pi * 880 * time)

    alone = frontend(sample)
    batched = frontend(torch.stack((other_sample, sample)))

    torch.testing.assert_close(alone, batched[1:2], rtol=1e-5, atol=1e-6)


def test_gpu_audio_frontend_v1_db_cutoff_is_independent_per_sample():
    contract = build_gpu_audio_frontend_contract(
        sample_rate=16000, duration_seconds=0.5, n_mels=16, n_fft=256,
        hop_length=64, f_min=50.0, f_max=7000.0, top_db=20.0,
        normalize=False,
    )
    assert contract["parameters"]["top_db_scope"] == "per_sample"
    frontend = GPUAudioFrontEnd(
        sample_rate=contract["sample_rate"], **contract["parameters"]
    )
    time = torch.arange(2048, dtype=torch.float32) / 16000
    samples = torch.stack((
        0.9 * torch.sin(2 * torch.pi * 440 * time),
        0.001 * torch.sin(2 * torch.pi * 880 * time),
        torch.zeros_like(time),
    ))

    alone = torch.cat([frontend(sample) for sample in samples])
    heterogeneous_batch = frontend(samples)

    max_difference = (alone - heterogeneous_batch).abs().max().item()
    assert torch.allclose(alone, heterogeneous_batch, rtol=1e-5, atol=1e-6), (
        "per-sample dB cutoff changed with batch composition; "
        f"max_difference={max_difference}"
    )


def test_gpu_audio_frontend_rejects_incomplete_contract_and_keeps_batch_constructor_default():
    contract = _frontend_contract()
    contract["parameters"]["top_db"] = 20.0
    del contract["parameters"]["top_db_scope"]
    with pytest.raises(ValueError, match="contract"):
        validate_gpu_audio_frontend_contract(contract)

    frontend = GPUAudioFrontEnd(
        sample_rate=contract["sample_rate"], **contract["parameters"]
    )
    assert frontend.top_db_scope == "batch"
    time = torch.arange(2048, dtype=torch.float32) / 16000
    weak_signal = 0.001 * torch.sin(2 * torch.pi * 880 * time)
    strong_signal = 0.9 * torch.sin(2 * torch.pi * 440 * time)

    alone = frontend(weak_signal)
    heterogeneous_batch = frontend(torch.stack((strong_signal, weak_signal)))

    assert not torch.allclose(alone, heterogeneous_batch[1:2], rtol=1e-5, atol=1e-6)


def test_gpu_audio_frontend_produces_deterministic_finite_silence_output():
    frontend = GPUAudioFrontEnd(
        sample_rate=16000, n_mels=16, n_fft=256, hop_length=64,
        f_min=50.0, f_max=7000.0,
    )
    silence = torch.zeros(1024, dtype=torch.float32)

    first = frontend(silence)
    second = frontend(silence.clone())

    assert torch.isfinite(first).all()
    torch.testing.assert_close(first, second, rtol=0, atol=0)
    assert torch.count_nonzero(first) == 0


def test_gpu_audio_frontend_handles_short_padding_and_center_truncation():
    sample_rate = 16000
    duration_seconds = 0.5
    target_samples = int(sample_rate * duration_seconds)
    short_waveform = np.linspace(-0.5, 0.5, 1000, dtype=np.float32)
    padded_waveform = load_and_fix_length(
        short_waveform, target_sr=sample_rate, duration_seconds=duration_seconds,
        original_sr=sample_rate,
    )
    np.testing.assert_array_equal(padded_waveform[:len(short_waveform)], short_waveform)
    np.testing.assert_array_equal(padded_waveform[len(short_waveform):], 0.0)

    long_waveform = np.arange(target_samples + 2000, dtype=np.float32)
    truncated_waveform = load_and_fix_length(
        long_waveform, target_sr=sample_rate, duration_seconds=duration_seconds,
        original_sr=sample_rate,
    )
    crop_start = (len(long_waveform) - target_samples) // 2
    np.testing.assert_array_equal(
        truncated_waveform, long_waveform[crop_start:crop_start + target_samples]
    )

    frontend = GPUAudioFrontEnd(
        sample_rate=sample_rate, n_mels=16, n_fft=256, hop_length=64,
        f_min=50.0, f_max=7000.0,
    )
    padded_features = frontend(torch.from_numpy(padded_waveform))
    truncated_features = frontend(torch.from_numpy(truncated_waveform))

    assert padded_features.shape == truncated_features.shape
    assert torch.isfinite(padded_features).all()
    assert torch.isfinite(truncated_features).all()
