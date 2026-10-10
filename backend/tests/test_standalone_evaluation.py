"""Official standalone publication evaluates the selected bundle per recording."""
import hashlib
import json
import wave
from pathlib import Path
import pandas as pd
import pytest
import torch
from torch import nn

from training.schemas.config import (
    ArchitectureConfig, AudioConfig, DatasetConfig, LossConfig, SplitConfig, TrainingConfig,
)
from training.trainers.standalone_trainer import GenericModelTrainer


def _wav(path, value=5000):
    with wave.open(str(path), 'wb') as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(22050)
        output.writeframes(value.to_bytes(2, 'little', signed=True) * 22050)
    return path


def _config():
    return TrainingConfig(
        experiment_id='eval4a', model_id='eval4a-model', model_name='EVAL4A',
        description='synthetic', epochs=2, batch_size=1, device='cpu',
        architecture=ArchitectureConfig(type='audio_cnn', pretrained=False),
        audio=AudioConfig(target_sr=22050, duration_seconds=1, n_mels=32,
                          n_fft=512, hop_length=256, f_min=100),
        loss=LossConfig(name='cross_entropy'),
        dataset=DatasetConfig(metadata_csv=Path('/not/read.csv'), raw_dir=Path('/not/read')),
        dataset_name='synthetic-birds',
        split=SplitConfig(),
    )


class TinyTrainingModel(nn.Module):
    def __init__(self):
        super().__init__()
        self.fc = nn.Linear(1, 1, bias=False)
        self.fc.weight.data.fill_(0)

    def forward(self, inputs):
        return self.fc(inputs.mean(dim=(1, 2, 3), keepdim=True).reshape(-1, 1))


def install_deterministic_training(monkeypatch):
    from torch.utils.data import TensorDataset

    monkeypatch.setattr(
        'training.trainers.standalone_trainer.GenericAudioDataset',
        lambda **kwargs: TensorDataset(torch.ones(1, 1, 1, 1), torch.zeros(1, dtype=torch.long)),
    )
    monkeypatch.setattr('training.trainers.standalone_trainer.GPUAudioFrontEnd',
                        lambda **kwargs: nn.Identity())
    monkeypatch.setattr('training.trainers.standalone_trainer.GPUSpecAugment',
                        lambda **kwargs: nn.Identity())
    monkeypatch.setattr('training.trainers.standalone_trainer.AudioCNN',
                        lambda **kwargs: TinyTrainingModel())
    monkeypatch.setattr('training.trainers.standalone_trainer.BioacousticModel',
                        lambda **kwargs: TinyTrainingModel())
    monkeypatch.setattr('poc.train.AudioCNN', lambda **kwargs: TinyTrainingModel())
    monkeypatch.setattr(torch.cuda, 'is_available', lambda: False)


def test_official_standalone_publishes_val_and_test_reports_for_selected_snapshot(tmp_path, monkeypatch):
    from app.services.predictors.bundle_predictor import BundleAudioPredictor
    roots = {'raw': tmp_path / 'raw'}
    roots['raw'].mkdir()
    frames = []
    for split in ('train', 'val', 'test'):
        path = _wav(roots['raw'] / f'{split}.wav')
        frames.append(pd.DataFrame([dict(file_path=path.name, file_stage='raw', clase='bird', id=split)]))

    # Exercise a real optimizer step while keeping only the network architecture
    # deterministic; export, public predictor and recording evaluation stay real.
    install_deterministic_training(monkeypatch)
    trainer = GenericModelTrainer(_config(), project_root=tmp_path)
    epochs = iter([0.9, 0.1])
    def evaluate_split(model, loader, frontend, criterion):
        try:
            score = next(epochs)
        except StopIteration:
            score = 0.0
        with torch.no_grad():
            model.fc.weight.fill_(score)
        return 1.0, 0.5, score
    monkeypatch.setattr(trainer, '_evaluate_split', evaluate_split)
    monkeypatch.setattr('training.trainers.standalone_trainer.BundleAudioPredictor', BundleAudioPredictor,
                        raising=False)

    path, metrics = trainer.train_and_export(*frames, tmp_path / 'bundles', roots=roots, verbose=False)
    manifest = json.loads((path / 'manifest.json').read_text())
    assert path.name == 'eval4a-model'
    assert path.is_dir()
    assert 'final_evaluations' in manifest
    final = manifest['final_evaluations']
    assert set(final['reports']) == {'val', 'test'}
    assert all(entry['report']['sample_count'] == 1 for entry in final['reports'].values())
    weight_hash = hashlib.sha256((path / 'weights.pt').read_bytes()).hexdigest()
    assert final['weights_sha256'] == weight_hash
    assert all(entry['provenance']['checkpoint_sha256'] == weight_hash
               for entry in final['reports'].values())
    assert metrics['best_val_f1_macro'] == 0.9
    assert metrics['legacy_metrics_scope'] == 'training_loop'
    predictor = BundleAudioPredictor(path, device=torch.device('cpu'), lazy_load=False)
    assert predictor.classes == ['bird']
    assert predictor.model.fc.weight.item() == pytest.approx(0.9)
    provenance = final['reports']['val']['provenance']
    effective = predictor.evaluation_config
    assert provenance['dataset'] == manifest['dataset_name'] == 'synthetic-birds'
    assert provenance['predictor_config'] == effective['predictor_config']
    assert provenance['preprocessing_config'] == effective['preprocessing_config']
    assert provenance['aggregation_config'] == effective['aggregation_config']

    # Loading revalidates the manifest/report binding after serialization too.
    manifest['audio_specs']['target_sr'] = 16000
    (path / 'manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match='effective bundle configuration'):
        BundleAudioPredictor(path, device=torch.device('cpu'))


def test_official_standalone_requires_explicit_dataset_name(tmp_path):
    config = _config().model_copy(update={'dataset_name': None})
    trainer = GenericModelTrainer(config, project_root=tmp_path)
    with pytest.raises(ValueError, match='explicit config.dataset_name'):
        trainer.train_and_export(pd.DataFrame(), pd.DataFrame(), pd.DataFrame(),
                                 tmp_path / 'bundles', roots={})
    assert not (tmp_path / 'bundles').exists()


def test_evaluation_failure_leaves_checkpoint_but_no_official_bundle(tmp_path, monkeypatch):
    from app.services.recording_evaluator import RecordingEvaluator

    roots = {'raw': tmp_path / 'raw'}
    roots['raw'].mkdir()
    rows = [pd.DataFrame([dict(file_path=f'{split}.wav', file_stage='raw', clase='bird', id=split)])
            for split in ('train', 'val', 'test')]
    for split in ('train', 'val', 'test'):
        _wav(roots['raw'] / f'{split}.wav')
    install_deterministic_training(monkeypatch)
    trainer = GenericModelTrainer(_config(), tmp_path)
    monkeypatch.setattr(trainer, '_evaluate_split', lambda *a: (0, 0, 1))
    monkeypatch.setattr(RecordingEvaluator, 'evaluate', lambda self: (_ for _ in ()).throw(RuntimeError('evaluation failed')))
    with pytest.raises(RuntimeError, match='evaluation failed'):
        trainer.train_and_export(*rows, tmp_path / 'bundles', roots=roots, verbose=False)
    root = tmp_path / 'bundles'
    assert not (root / 'eval4a-model').exists()
    assert list(root.glob('.eval4a-model.provisional-*'))
