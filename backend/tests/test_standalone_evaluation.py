"""Retained bundle publication and evaluation do not depend on a training CLI."""
import hashlib
import json
import wave
from pathlib import Path

import numpy as np
import pytest
import torch

from app.services.predictors.bundle_predictor import BundleAudioPredictor
from app.services.recording_evaluator import LabelledRecording, RecordingEvaluator
from poc.train import AudioCNN
from training.exporters.bundle_exporter import BundleExporter
from training.schemas.config import ArchitectureConfig, AudioConfig, DatasetConfig, TrainingConfig


def test_exported_bundle_preserves_recording_reports_and_configuration_binding(tmp_path):
    config = TrainingConfig(
        experiment_id='bundle-evaluation', model_id='evaluated-bundle',
        model_name='Evaluated bundle', description='synthetic', epochs=1,
        batch_size=1, device='cpu', dataset_name='synthetic-birds',
        architecture=ArchitectureConfig(type='audio_cnn', pretrained=False),
        audio=AudioConfig(target_sr=22050, duration_seconds=1, n_mels=32,
                          n_fft=512, hop_length=256, f_min=100),
        dataset=DatasetConfig(metadata_csv=Path('unused.csv'), raw_dir=tmp_path),
    )
    model = AudioCNN(num_classes=1)
    stage = tmp_path / '.evaluated-bundle.provisional-test'
    bundle = BundleExporter.export(stage, model, config, ['bird'])
    digest = hashlib.sha256((bundle / 'weights.pt').read_bytes()).hexdigest()
    predictor = BundleAudioPredictor(bundle, device=torch.device('cpu'), lazy_load=False)
    effective = predictor.evaluation_config
    reports = {}
    for split in ('val', 'test'):
        audio = tmp_path / f'{split}.wav'
        waveform = (5000 * np.sin(2 * np.pi * 440 * np.arange(22050) / 22050)).astype('<i2')
        with wave.open(str(audio), 'wb') as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(22050)
            output.writeframes(waveform.tobytes())
        evaluator = RecordingEvaluator(
            [LabelledRecording(split, 'bird', audio, audio.name, 'raw')],
            predictor, dataset='synthetic-birds', split=split,
            checkpoint_sha256=digest, **effective,
        )
        reports[split] = {
            'provenance': evaluator.identity.model_dump(),
            'report': evaluator.evaluate(),
        }

    published = BundleExporter.publish_official(bundle, reports)
    manifest_path = published / 'manifest.json'
    manifest = json.loads(manifest_path.read_text())
    final = manifest['final_evaluations']
    assert set(final['reports']) == {'val', 'test'}
    assert final['weights_sha256'] == digest
    for split, entry in final['reports'].items():
        assert entry['report']['sample_count'] == 1
        assert entry['provenance']['checkpoint_sha256'] == digest
        assert entry['provenance']['split'] == split
        assert entry['provenance']['dataset'] == 'synthetic-birds'
        for key, value in effective.items():
            assert entry['provenance'][key] == value
    assert hashlib.sha256((published / 'weights.pt').read_bytes()).hexdigest() == digest
    reloaded = BundleAudioPredictor(published, device=torch.device('cpu'), lazy_load=False)
    assert reloaded.classes == ['bird']
    assert reloaded.evaluation_config == effective
    assert not bundle.exists()

    # Serialized reports must remain bound to the effective serving configuration.
    manifest['audio_specs']['target_sr'] = 16000
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match='effective bundle configuration'):
        BundleAudioPredictor(published, device=torch.device('cpu'))
