"""Historical CNN weights exercised through public metadata and prediction, without mocks."""
import hashlib

import numpy as np
import pytest
import soundfile as sf
import torch

from app.services.predictors.trained_predictor import TrainedModelPredictor, ModelWeightsError
from poc.train import AudioCNN


@pytest.mark.parametrize('lazy_load', [False, True])
def test_untyped_historical_audio_cnn_predicts_using_its_real_weights(tmp_path, lazy_load):
    model = AudioCNN(num_classes=2)
    with torch.no_grad():
        for parameter in model.parameters():
            parameter.zero_()
        model.classifier[-1].bias.copy_(torch.tensor([5.0, -5.0]))
    checkpoint = tmp_path / 'arbitrary-historical-name.pt'
    torch.save({'model_state_dict':model.state_dict(), 'classes':['Positive', 'Negative'],
                'val_acc':75.0, 'epoch':14}, checkpoint)
    before = hashlib.sha256(checkpoint.read_bytes()).hexdigest()
    audio = tmp_path / 'tone.wav'
    sf.write(audio, 0.3 * np.sin(2 * np.pi * 440 * np.arange(16000, dtype=np.float32) / 8000), 8000)

    predictor = TrainedModelPredictor(checkpoint, lazy_load=lazy_load)
    assert 'AudioCNN' in predictor.metadata.description
    assert predictor.metadata.metrics['accuracy'] == 0.75
    result = predictor.predict(audio)

    assert result.clase == 'Positive'
    assert result.confianza > 0.99
    assert result.detalles['status'] == 'classified'
    assert hashlib.sha256(checkpoint.read_bytes()).hexdigest() == before


@pytest.mark.parametrize('difference', ['missing_weight', 'extra_weight', 'wrong_shape', 'declared_architecture'])
def test_incomplete_or_declared_different_weights_are_not_reinterpreted_as_historical_cnn(tmp_path, difference):
    state = AudioCNN(num_classes=2).state_dict()
    metadata = {}
    if difference == 'missing_weight':
        del state['features.0.weight']
    elif difference == 'extra_weight':
        state['unknown.weight'] = torch.ones(1)
    elif difference == 'wrong_shape':
        state['classifier.3.bias'] = torch.ones(3)
    else:
        metadata['architecture'] = 'EfficientNet-B0'
    checkpoint = tmp_path / 'baseline_best.pt'
    torch.save({'classes':['Positive', 'Negative'], 'model_state_dict':state, **metadata}, checkpoint)
    with pytest.raises(ModelWeightsError, match='Incompatibilidad'):
        TrainedModelPredictor(checkpoint)
