import pytest
from pathlib import Path
from app.schemas.model_info import ModelMetadata
from app.schemas.prediction import PredictionResult
from app.services.predictors.base import AudioPredictor
from app.services.registry import ModelRegistry, ModelNotFoundError


class FakeAudioPredictor(AudioPredictor):
    """Implementación fake de prueba para el contrato AudioPredictor."""

    def __init__(self, model_id: str, name: str, is_default: bool = False):
        self._meta = ModelMetadata(
            id=model_id,
            name=name,
            description="Fake predictor for unit tests",
            target_sr=22050,
            duration_seconds=5.0,
            classes=["Especie A", "Especie B"],
            is_default=is_default,
        )

    @property
    def has_weights(self) -> bool:
        return getattr(self, "has_weights_override", True)

    @property
    def metadata(self) -> ModelMetadata:
        self._meta.has_weights = self.has_weights
        return self._meta

    def predict(self, audio_file_path: Path) -> PredictionResult:
        return PredictionResult(clase="Especie A", confianza=0.95)


@pytest.mark.parametrize("name,path,expected", [
    ("AvesChilenas", "datasets/AvesChilenas/", "AvesChilenas"),
    ("Motores", "datasets/Motores/", "Motores"),
    ("Motores", "datasets/AvesChilenas/", None),
    ("Motores", "gs://other-bucket/datasets/Motores/", None),
    (None, None, None),
])
def test_db_registration_propagates_only_verified_storage_identity(tmp_path, monkeypatch, name, path, expected):
    from types import SimpleNamespace
    from unittest.mock import MagicMock
    from app.services.predictors import trained_predictor
    checkpoint = tmp_path / "trained.pt"
    checkpoint.write_bytes(b"isolated checkpoint fixture" * 500)
    model = SimpleNamespace(id_modelo=41, activo=False, arquitectura="fixture",
                            ruta_binario_gcp="models/trained.pt",
                            conjunto_datos=SimpleNamespace(nombre=name, ruta_gcp=path) if name else None)
    db = MagicMock()
    db.query.return_value.order_by.return_value.all.return_value = [model]
    captured = {}
    def factory(**kwargs):
        captured.update(kwargs)
        pred = FakeAudioPredictor(kwargs["model_id"], kwargs["name"])
        pred._meta = pred.metadata.model_copy(update={"dataset_name": kwargs.get("dataset_name")})
        return pred
    monkeypatch.setattr(trained_predictor, "TrainedModelPredictor", factory)
    registry = ModelRegistry()
    registry.register_from_db(db, tmp_path)
    assert "dataset_name" in captured
    assert registry.get("41").dataset_name == expected
    assert registry.list_models()[0].dataset_name == expected


def test_registry_register_and_get():
    registry = ModelRegistry()
    fake_predictor = FakeAudioPredictor(model_id="test-model-1", name="Test Model 1")

    registry.register(fake_predictor, is_default=True)

    # Obtener por ID exacto
    pred = registry.get("test-model-1")
    assert pred.model_id == "test-model-1"

    # Obtener sin ID (debe retornar el default)
    default_pred = registry.get(None)
    assert default_pred.model_id == "test-model-1"

    assert registry.get_default_model_id() == "test-model-1"


def test_registry_multiple_models_and_list():
    registry = ModelRegistry()
    m1 = FakeAudioPredictor(model_id="cnn", name="CNN Model", is_default=True)
    m2 = FakeAudioPredictor(model_id="ensemble", name="Ensemble Model")

    registry.register(m1, is_default=True)
    registry.register(m2, is_default=False)

    models = registry.list_models()
    assert len(models) == 2
    ids = [m.id for m in models]
    assert "cnn" in ids
    assert "ensemble" in ids


def test_registry_unknown_model_raises_model_not_found_error():
    registry = ModelRegistry()
    m1 = FakeAudioPredictor(model_id="cnn", name="CNN Model", is_default=True)
    registry.register(m1, is_default=True)

    with pytest.raises(ModelNotFoundError) as exc_info:
        registry.get("non-existent-model")

    assert "non-existent-model" in str(exc_info.value)


def test_registry_no_default_configured():
    registry = ModelRegistry()
    with pytest.raises(ModelNotFoundError):
        registry.get(None)


def test_get_model_registry_default_population(monkeypatch):
    from app.services import registry as module
    from app.services.predictors.cnn_predictor import AudioCNNPredictor
    from app.services.registry import get_model_registry
    monkeypatch.setattr(module, "_global_model_registry", None)
    monkeypatch.setattr(module, "discover_and_register_bundles", lambda *a: 0)
    monkeypatch.setattr(module, "discover_and_register_checkpoints", lambda *a: 0)
    monkeypatch.setattr(AudioCNNPredictor, "_load_checkpoint", lambda self: None)
    reg = get_model_registry()

    assert reg.has_model("chilean-birds-cnn")
    assert reg.has_model("chilean-birds-ensemble")
    assert reg.get_default_model_id() is not None

    cnn = reg.get("chilean-birds-cnn")
    assert cnn.model_id == "chilean-birds-cnn"
    assert cnn.dataset_name == "AvesChilenas"
    assert all(meta.dataset_name == "AvesChilenas" for meta in reg.list_models())

    default_model = reg.get(None)
    assert default_model.model_id == reg.get_default_model_id()


def test_model_metadata_reports_has_weights():
    registry = ModelRegistry()
    m_with_weights = FakeAudioPredictor(model_id="with-weights", name="Ready Model")
    m_without_weights = FakeAudioPredictor(model_id="no-weights", name="Empty Model")
    # Simular que no tiene pesos
    m_without_weights.has_weights_override = False

    registry.register(m_with_weights)
    registry.register(m_without_weights)

    models = registry.list_models()
    assert len(models) == 2
    for m in models:
        assert hasattr(m, "has_weights")


def test_registry_filter_models_only_with_weights():
    registry = ModelRegistry()
    m1 = FakeAudioPredictor(model_id="m1", name="Ready Model")
    m2 = FakeAudioPredictor(model_id="m2", name="No Weights Model")
    m2.has_weights_override = False

    registry.register(m1)
    registry.register(m2)

    ready_models = registry.list_models(only_with_weights=True)
    assert len(ready_models) == 1
    assert ready_models[0].id == "m1"


def test_registry_unregister():
    registry = ModelRegistry()
    m = FakeAudioPredictor(model_id="to-delete", name="Model To Delete")
    registry.register(m)
    assert registry.has_model("to-delete")

    removed = registry.unregister("to-delete")
    assert removed is True
    assert not registry.has_model("to-delete")


def test_registry_register_from_db_inactive_models_lazy_loaded(tmp_path):
    """
    Verifica que al registrar modelos desde la base de datos (register_from_db),
    los modelos no activos (is_default=False) se inicialicen con lazy_load=True,
    garantizando que su atributo model sea None para preservar RAM/VRAM.
    """
    import torch
    from unittest.mock import MagicMock
    from app.services.registry import ModelRegistry
    from app.services.predictors.trained_predictor import TrainedModelPredictor

    from poc.train import AudioCNN

    sample_model = AudioCNN(num_classes=2)
    state_dict = sample_model.state_dict()

    # Crear checkpoint sintético válido (> 10KB)
    ckpt_file = tmp_path / "fama_test_checkpoint_best.pt"
    torch.save(
        {
            "state_dict": state_dict,
            "architecture": "AudioCNN",
            "classes": ["Especie 1", "Especie 2"],
            "best_val_acc": 85.0,
            "padding": torch.zeros(5000),
        },
        ckpt_file,
    )
    assert ckpt_file.stat().st_size > 10000

    # Crear modelos mock: m_active y m_inactive
    m_active = MagicMock()
    m_active.id_modelo = 101
    m_active.arquitectura = "AudioCNN"
    m_active.activo = True
    m_active.ruta_binario_gcp = f"models/{ckpt_file.name}"
    m_active.conjunto_datos = None

    m_inactive = MagicMock()
    m_inactive.id_modelo = 102
    m_inactive.arquitectura = "AudioCNN"
    m_inactive.activo = False
    m_inactive.ruta_binario_gcp = f"models/{ckpt_file.name}"
    m_inactive.conjunto_datos = None

    mock_db = MagicMock()
    mock_db.query.return_value.order_by.return_value.all.return_value = [m_active, m_inactive]

    registry = ModelRegistry()
    registry.register_from_db(mock_db, checkpoints_root=tmp_path)

    active_pred = registry.get("fama_trained_model_101")
    inactive_pred = registry.get("fama_trained_model_102")

    assert isinstance(active_pred, TrainedModelPredictor)
    assert isinstance(inactive_pred, TrainedModelPredictor)
    assert active_pred.metadata.is_default is True
    assert inactive_pred.metadata.is_default is False

    # El modelo no activo debe tener lazy_load=True (model is None)
    assert inactive_pred.model is None


def test_discover_and_register_checkpoints_inactive_models_lazy_loaded(tmp_path):
    """
    Verifica que al descubrir checkpoints en disco sin BD activa,
    el primer checkpoint sea default (activo) y los subsiguientes sean lazy_loaded (model is None).
    """
    import torch
    import os
    from poc.train import AudioCNN
    from app.services.registry import ModelRegistry, discover_and_register_checkpoints
    from app.services.predictors.trained_predictor import TrainedModelPredictor

    sample_model = AudioCNN(num_classes=2)
    state_dict = sample_model.state_dict()

    # Crear dos checkpoints > 1MB
    payload = {
        "state_dict": state_dict,
        "architecture": "AudioCNN",
        "classes": ["Especie 1", "Especie 2"],
        "best_val_acc": 80.0,
        "padding": torch.zeros(300000),  # Aumenta el tamaño > 1MB
    }

    ckpt_path_1 = tmp_path / "fama_arch1_100_best.pt"
    ckpt_path_2 = tmp_path / "fama_arch2_200_best.pt"

    torch.save(payload, ckpt_path_1)
    torch.save(payload, ckpt_path_2)

    # Ajustar timestamps para garantizar orden determinista
    os.utime(ckpt_path_1, (2000, 2000))
    os.utime(ckpt_path_2, (1000, 1000))

    registry = ModelRegistry()
    count = discover_and_register_checkpoints(registry, checkpoints_root=tmp_path, db=None)
    assert count == 2

    # ckpt_path_1 es el más reciente -> default
    pred1 = registry.get(ckpt_path_1.stem)
    pred2 = registry.get(ckpt_path_2.stem)

    assert isinstance(pred1, TrainedModelPredictor)
    assert isinstance(pred2, TrainedModelPredictor)
    assert pred1.metadata.is_default is True
    assert pred2.metadata.is_default is False

    # El modelo no activo debe ser lazy_loaded (model is None)
    assert pred2.model is None




