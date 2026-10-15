"""The web service owns training; legacy Python entrypoints are retired."""
import pytest


@pytest.mark.parametrize('module,name', [
    ('poc.train', 'train_pipeline'),
    ('poc.benchmark', 'run_benchmark'),
    ('ml_core.train', 'train_pipeline'),
])
def test_legacy_training_import_is_unavailable(module, name, tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ImportError, match=name):
        exec(f'from {module} import {name}', {})
    output = capsys.readouterr()
    assert output.out == ''
    assert output.err == ''
    assert list(tmp_path.iterdir()) == []


def test_shared_model_and_loss_exports_remain_available():
    from ml_core.train import AudioCNN, BioacousticModel, FocalLoss, apply_mixup
    from poc import train

    assert AudioCNN is train.AudioCNN
    assert BioacousticModel is train.BioacousticModel
    assert FocalLoss is train.FocalLoss
    assert apply_mixup is train.apply_mixup
