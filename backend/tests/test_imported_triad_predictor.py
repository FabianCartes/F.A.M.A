"""Synthetic public predictor contracts; neural construction is the only fake."""
import hashlib
import numpy as np
import pytest
import soundfile as sf
import torch
from app.services.predictors import trained_predictor as module
from app.services.predictors.trained_predictor import TrainedModelPredictor, ModelWeightsError


@pytest.fixture
def components(tmp_path, monkeypatch):
    class Neural(torch.nn.Module):
        def __init__(self, num_classes):
            super().__init__()
            self.logits = torch.nn.Parameter(torch.zeros(num_classes))
        def forward(self, inputs):
            return self.logits.unsqueeze(0)
    monkeypatch.setattr(module, 'AudioCNN', Neural)
    audio = tmp_path / 'tone.wav'
    t = np.arange(22050 * 5) / 22050
    sf.write(audio, .5 * np.sin(2 * np.pi * 1000 * t), 22050)
    def build(vectors, labels=None):
        predictors = []
        for i, vector in enumerate(vectors):
            path = tmp_path / f'{i}.pt'
            torch.save({'architecture': 'AudioCNN', 'classes': (labels or [['a','b','c']]*3)[i],
                        'state_dict': {'logits': torch.log(torch.tensor(vector))}}, path)
            predictors.append(TrainedModelPredictor(path, model_id=f'component-{i}', lazy_load=True,
                expected_checkpoint_sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
        return predictors, audio
    return build


def test_full_vectors_choose_nonwinning_class_and_keep_single_output(components):
    from app.services.predictors.imported_triad_predictor import ImportedTriadPredictor
    parts, audio = components([[.5,.4,.1],[.1,.4,.5],[.5,.4,.1]])
    triad = ImportedTriadPredictor(parts, [.25,.5,.25], ['a','b','c'], 'triad-v1')
    assert all(p.model is None for p in parts)
    result = triad.predict(audio)
    assert result.clase == 'b'
    assert result.confianza == pytest.approx(.4)
    assert result.detalles['probabilities'] == pytest.approx([.3,.4,.3])
    assert result.detalles['model_id'] == 'triad-v1'
    assert result.detalles['component_ids'] == ['component-0','component-1','component-2']
    assert result.detalles['weights'] == [.25,.5,.25]
    assert result.detalles['ensemble_count'] == 3
    assert all(p.architecture_name == 'AudioCNN' for p in parts)
    single = parts[0].predict(audio)
    assert single.clase == 'a' and single.confianza == .5
    assert 'probabilities' not in single.detalles
    vector = parts[0].predict_probabilities(audio)
    assert vector['classes'] == ['a','b','c']
    assert vector['probabilities'] == pytest.approx([.5,.4,.1])
    assert len(result.detalles['loaded_checkpoint_sha256s']) == 3
    assert triad.metadata.metrics is None


@pytest.mark.parametrize('weights', [[1.0000000005, 0, 0],
    [0.3333333335, 0.3333333335, 0.3333333335]], ids=['single-weight', 'equal-weights'])
def test_tolerance_weight_overflow_keeps_probabilities_bounded(components, weights):
    from app.services.predictors.imported_triad_predictor import ImportedTriadPredictor
    parts, audio = components([[1.0]] * 3, [['only']] * 3)
    triad = ImportedTriadPredictor(parts, weights, ['only'], 'tolerance-v1')
    metadata = triad.metadata.model_dump()
    result = triad.predict(audio)
    assert 0 <= result.confianza <= 1
    assert all(0 <= value <= 1 for value in result.detalles['probabilities'])
    assert result.confianza == 1.0
    assert result.detalles['probabilities'] == [1.0]
    assert result.clase == 'only'
    assert triad.weights == tuple(weights)
    assert result.detalles['weights'] == weights
    assert result.detalles['model_id'] == 'tolerance-v1'
    assert result.detalles['component_ids'] == ['component-0', 'component-1', 'component-2']
    assert result.detalles['classes'] == ['only']
    assert result.detalles['ensemble_count'] == 3
    assert all(part.model is not None for part in parts)
    assert result.detalles['loaded_checkpoint_sha256s'] == [
        part.metadata.loaded_checkpoint_sha256 for part in parts]
    assert triad.metadata.model_dump() == metadata


def test_vector_keeps_precision_lost_by_single_prediction(components):
    parts, audio = components([[.1234567,.654321,.2222223]]*3)
    vector = parts[0].predict_probabilities(audio)
    single = parts[0].predict(audio)
    assert single.confianza == .6543
    assert vector['probabilities'][1] == pytest.approx(.654321, abs=1e-7)
    assert vector['probabilities'][1] != single.confianza


@pytest.mark.parametrize('count', [0, 2, 4])
def test_requires_exactly_three_components(components, count):
    from app.services.predictors.imported_triad_predictor import ImportedTriadPredictor
    parts, _ = components([[.5,.4,.1]]*3)
    with pytest.raises(ModelWeightsError, match='three'):
        ImportedTriadPredictor((parts + parts)[:count], [1,0,0], ['a','b','c'], 'bad')


def test_permuted_labels_and_weight_order(components):
    from app.services.predictors.imported_triad_predictor import ImportedTriadPredictor
    parts, audio = components([[.6,.3,.1],[.6,.3,.1],[.6,.3,.1]],
                             [['a','b','c'],['c','a','b'],['b','c','a']])
    first = ImportedTriadPredictor(parts, [1,0,0], ['a','b','c'], 'first').predict(audio)
    second = ImportedTriadPredictor(parts, [0,1,0], ['a','b','c'], 'second').predict(audio)
    assert first.clase == 'a' and second.clase == 'c'
    assert second.detalles['probabilities'] == pytest.approx([.3,.1,.6])
    assert all(p.model is not None for p in parts)


@pytest.mark.parametrize('weights', [[1,0], [0,0,0], [-1,1,1], [1,1,1],
    [float('nan'),0,1], [float('inf'),0,0], [.5,.5,.00000001], [True,0,0]])
def test_invalid_weights(components, weights):
    from app.services.predictors.imported_triad_predictor import ImportedTriadPredictor
    parts, _ = components([[.5,.4,.1]]*3)
    with pytest.raises(ModelWeightsError, match='weights'):
        ImportedTriadPredictor(parts, weights, ['a','b','c'], 'bad')


@pytest.mark.parametrize('labels', [['a','b'], ['a','b','d'], ['a','a','c'], ['a','b','c','d']])
def test_incompatible_labels(components, labels):
    from app.services.predictors.imported_triad_predictor import ImportedTriadPredictor
    parts, _ = components([[.5,.4,.1]]*3)
    parts[1].classes = labels
    with pytest.raises(ModelWeightsError, match='labels'):
        ImportedTriadPredictor(parts, [1,0,0], ['a','b','c'], 'bad')


@pytest.mark.parametrize('vector', [[float('nan'),.5,.5], [float('inf'),0,0], [-.1,.5,.6]])
def test_nonfinite_neural_outputs_are_not_probabilities(components, vector):
    from app.services.predictors.imported_triad_predictor import ImportedTriadPredictor
    parts, audio = components([[.5,.4,.1], vector, [.5,.4,.1]])
    with pytest.raises(ModelWeightsError, match='probabilities'):
        ImportedTriadPredictor(parts, [1,0,0], ['a','b','c'], 'bad').predict(audio)


def test_zero_weight_failed_checkpoint_has_no_fallback(components):
    from app.services.predictors.imported_triad_predictor import ImportedTriadPredictor
    parts, audio = components([[.5,.4,.1]]*3)
    triad = ImportedTriadPredictor(parts, [1,0,0], ['a','b','c'], 'broken')
    parts[2].checkpoint_path.write_bytes(b'corruption')
    with pytest.raises(ModelWeightsError, match='SHA-256'):
        triad.predict(audio)


@pytest.mark.parametrize('reject', ['silence', 'noise'])
def test_silence_has_no_vector_and_preserves_single_reject(components, reject):
    from app.services.predictors.imported_triad_predictor import ImportedTriadPredictor
    parts, audio = components([[.5,.4,.1]]*3)
    waveform = (np.zeros(22050 * 5) if reject == 'silence' else
                np.random.default_rng(32).normal(0, .1, 22050 * 5))
    sf.write(audio, waveform, 22050)
    single = parts[0].predict(audio)
    assert single.clase == ('Silencio / No detectado' if reject == 'silence' else 'Ruido / Señal no biológica')
    assert single.confianza == 0 and single.detalles['status'] == reject
    from app.services.predictors.trained_predictor import ClassVectorUnavailable
    with pytest.raises(ClassVectorUnavailable, match=f'unavailable: {reject}') as failure:
        parts[0].predict_probabilities(audio)
    assert isinstance(failure.value, ModelWeightsError)
    assert failure.value.status == reject
    composed = ImportedTriadPredictor(parts, [1,0,0], ['a','b','c'], 'silent').predict(audio)
    assert composed.clase == single.clase and composed.confianza == 0
    assert composed.detalles['status'] == reject
    assert 'probabilities' not in composed.detalles
    # Fresh lazy instances must still inspect the later zero-weight component.
    from app.services.predictors.trained_predictor import TrainedModelPredictor
    parts = [TrainedModelPredictor(p.checkpoint_path, lazy_load=True,
        expected_checkpoint_sha256=p.expected_checkpoint_sha256) for p in parts]
    parts[2].checkpoint_path.write_bytes(b'corrupt even after an earlier reject')
    with pytest.raises(ModelWeightsError, match='SHA-256'):
        ImportedTriadPredictor(parts, [1,0,0], ['a','b','c'], 'silent').predict(audio)


@pytest.mark.parametrize('shape', [(2,3), (1,2), (1,3,1), (3,), (1,0)])
def test_malformed_neural_output_shape(components, shape):
    from app.services.predictors.imported_triad_predictor import ImportedTriadPredictor
    parts, audio = components([[.5,.4,.1]]*3)
    parts[1].load_weights()
    class WrongShape(torch.nn.Module):
        def forward(self, inputs):
            return torch.zeros(shape)
    parts[1].model = WrongShape()
    with pytest.raises(ModelWeightsError, match='probabilities'):
        ImportedTriadPredictor(parts, [1,0,0], ['a','b','c'], 'shape').predict(audio)
