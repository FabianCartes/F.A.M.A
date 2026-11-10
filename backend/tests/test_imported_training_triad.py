"""Imported triads through public admission and sequential CPU execution."""
import pickle
from copy import deepcopy

import pytest
from tests.http_security import cookie_headers, cookie_security

from tests.test_dataset_import_api import imports
from tests.test_imported_dataset_preparation import cohort, create
from tests.test_training_flow import training_env
from tests.test_api_training import client
from tests.test_imported_training_admission import authenticated


@pytest.fixture
def triad(cohort, training_env, tmp_path, monkeypatch):
    from app.services import training
    from app.services.imported_training_source import ImportedTrainingSource
    from training.imported_dataset_preparation import ImportedDatasetPreparation
    from scripts.migrate_imported_training_source import migrate_imported_sources
    runtime = training_env[0]
    monkeypatch.setattr(training, "SessionLocal", cohort[0].sessions)
    migrate_imported_sources(cohort[0].sessions.kw["bind"], writers_stopped=True)
    preparations = ImportedDatasetPreparation(cohort[0], tmp_path / "prepared-triad")
    models = []
    for duration, weight in ((0.5, 0.2), (0.75, 0.3), (1.0, 0.5)):
        profile = deepcopy(cohort[3])
        profile["audio"]["duration_seconds"] = duration
        changed = list(cohort)
        changed[3] = profile
        prepared = create(preparations, changed)
        models.append(dict(architecture="AudioCNN", weight=weight, epochs=1,
                           learning_rate=0.001, batch_size=2,
                           imported_prepared_version=prepared["version_id"]))
    runtime.imported_sources = ImportedTrainingSource(preparations)
    from app.services.imported_triad_records import ImportedTriadRecords
    from app.services.imported_triad_manifests import ImportedTriadManifests
    from app.services.imported_triad_evaluation import ImportedTriadEvaluation
    manifests = ImportedTriadManifests(tmp_path / 'triad-manifests')
    runtime.triad_records = ImportedTriadRecords(cohort[0].sessions, manifests,
        ImportedTriadEvaluation(cohort[0].sessions, manifests, runtime.imported_sources,
                                runtime.checkpoints_dir))
    return runtime, dict(dataset_name="", imported_dataset_id=cohort[5],
        snapshot_id=cohort[1]["id"], owner_id=1, models=models, seed=42), preparations


def test_three_preparations_admitted_as_serializable_ordered_sources(triad, training_env):
    from app.schemas.training import ModelEnsembleItem
    runtime, arguments, _ = triad
    arguments["models"] = [ModelEnsembleItem(**m) for m in arguments["models"]]
    result = runtime.start_training(**arguments)
    assert result["status"] == "started"
    config = pickle.loads(pickle.dumps(training_env[3].call_args.kwargs["args"][0]))
    assert [s["identity"]["preparation_version"] for s in config["component_sources"]] == [
        m.imported_prepared_version for m in arguments["models"]]
    assert [s["identity"]["profile"]["audio"]["duration_seconds"] for s in config["component_sources"]] == [0.5, 0.75, 1.0]
    assert runtime.current_source_owner == 1
    before = runtime.get_progress()
    with pytest.raises(RuntimeError, match="Ya existe"):
        runtime.start_training(**arguments)
    assert runtime.get_progress() == before
    assert training_env[3].call_count == 1


def test_http_triad_uses_existing_authenticated_start(triad, training_env, client, authenticated):
    from app.services import auth
    runtime, arguments, _ = triad
    body = {k: v for k, v in arguments.items() if k not in ("owner_id", "dataset_name")}
    assert client.post("/api/training/start", json=body).status_code == 401
    owner = cookie_headers(training_env[1], 1)
    response = client.post("/api/training/start", json=body, headers=owner)
    assert response.status_code == 200, response.text
    assert runtime.current_source_owner == 1
    assert len(training_env[3].call_args.kwargs["args"][0]["component_sources"]) == 3


@pytest.mark.parametrize("fail_second", [False, True])
def test_sequential_components_keep_own_profiles_and_failure_is_not_completion(
        triad, training_env, cohort, monkeypatch, fail_second):
    import torch
    from app.services import training
    runtime, arguments, _ = triad
    original = training.AudioCNN
    calls = []
    def constructor(*args, **kwargs):
        calls.append(1)
        if fail_second and len(calls) == 2:
            raise RuntimeError("Synthetic second component failure")
        return original(*args, **kwargs)
    monkeypatch.setattr(training, "AudioCNN", constructor)
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    class Inline:
        def __init__(self, target, args, **kwargs):
            self.target, self.args = target, args
        def start(self):
            self.target(*self.args)
    training_env[3].side_effect = Inline
    runtime.start_training(**arguments)
    progress = runtime.get_progress(owner_id=1)
    assert progress["status"] == ("failed" if fail_second else "completed"), progress
    with cohort[0].sessions() as db:
        history = runtime.get_history(db, owner_id=1)
        assert runtime.get_history(db, owner_id=2) == []
    if not fail_second:
        assert len(history) == 4
        composition = runtime.triad_records.read_admitted(1, progress['composition_model_id'])
        assert composition['model'].hash_binario == progress['composition_sha256']
        assert len(composition['pair_ids']) == 2
        history = [h for h in history if h['filename'] != progress['composition_sha256'] + '.json']
    assert len(history) == (1 if fail_second else 3)
    checkpoints = sorted((torch.load(runtime.checkpoints_dir / h["filename"], weights_only=True)
                          for h in history), key=lambda c: c["audio_config"]["duration_seconds"])
    assert [c["audio_config"]["duration_seconds"] for c in checkpoints] == ([0.5] if fail_second else [0.5, 0.75, 1.0])
    assert [c["ensemble_weight"] for c in checkpoints] == ([0.2] if fail_second else [0.2, 0.3, 0.5])
    for checkpoint, model in zip(checkpoints, arguments["models"]):
        assert checkpoint["imported_source"]["owner_id"] == 1
        assert checkpoint["imported_source"]["dataset_id"] == cohort[5]
        assert checkpoint["imported_source"]["preparation_version"] == model["imported_prepared_version"]
        assert checkpoint["epochs"] == 1
    assert all(not h["active"] and h["status"] == "standard_eval_completed" for h in history)
    assert len(progress["component_results"]) == len(history)
    assert progress["ensemble_available"] is (not fail_second)


@pytest.mark.parametrize("damage", ["partial", "mixed", "two", "negative", "nan", "sum", "zero", "foreign", "stale", "seed", "architecture", "audio", "window", "archived", "revision", "override"])
def test_invalid_triad_preserves_prior_state(triad, training_env, damage):
    from app.services.imported_training_source import ImportedSourceError
    runtime, arguments, _ = triad
    if damage == "partial":
        arguments["models"][1].pop("imported_prepared_version")
    elif damage == "mixed":
        arguments["imported_prepared_version"] = arguments["models"][0]["imported_prepared_version"]
    elif damage == "two":
        arguments["models"].pop()
    elif damage in ("negative", "nan", "sum", "zero"):
        values = {"negative": [-0.1, 0.6, 0.5], "nan": [float("nan"), 0.5, 0.5],
                  "sum": [0.2, 0.3, 0.4], "zero": [0, 0, 0]}[damage]
        for model, weight in zip(arguments["models"], values):
            model["weight"] = weight
    elif damage == "foreign":
        arguments["owner_id"] = 2
    elif damage == "stale":
        arguments["models"][1]["imported_prepared_version"] = "0" * 64
    elif damage == "seed":
        arguments["seed"] = 43
    elif damage == "audio":
        arguments["models"][1]["audio_config"] = {"duration_seconds": 2.0}
    elif damage == "window":
        arguments["models"][1]["windowing_config"] = {"hop_seconds": 0.25}
    elif damage == "override":
        arguments["models"][1]["owner_id"] = 2
    elif damage in ("archived", "revision"):
        from app.models.dataset_import import ImportedDataset
        with runtime.imported_sources.preparations.snapshots.sessions.begin() as db:
            dataset = db.get(ImportedDataset, arguments["imported_dataset_id"])
            if damage == "archived":
                dataset.archived = True
            else:
                dataset.revision += 1
    else:
        arguments["models"][1]["architecture"] = "ResNet-34d"
    before = runtime.get_progress()
    with pytest.raises((ImportedSourceError, ValueError)):
        runtime.start_training(**arguments)
    assert runtime.get_progress() == before
    training_env[3].assert_not_called()
    with runtime.imported_sources.preparations.snapshots.sessions() as db:
        assert runtime.get_history(db, owner_id=1) == []
