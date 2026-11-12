"""Joint evaluation attempts of a standard triad composition, through the public service."""
import pytest
from sqlalchemy.orm import sessionmaker

from app.models.dataset import ConjuntoDatos
from app.models.training import ModelEvaluation, Modelo
from app.services.triad_compositions import create_initial_composition
from tests.schema_support import migrated_engine

HASHES = ("a" * 64, "b" * 64, "c" * 64)
CLASSES = ["b", "a"]


@pytest.fixture
def sessions():
    engine = migrated_engine()
    with engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
    factory = sessionmaker(bind=engine)
    with factory() as db:
        db.add_all([ConjuntoDatos(id_conjunto_datos=10, nombre="AvesChilenas", ruta_gcp="datasets/AvesChilenas"),
                    ConjuntoDatos(id_conjunto_datos=20, nombre="Motores", ruta_gcp="datasets/Motores")])
        for model_id, digest in zip((1, 2, 3), HASHES):
            db.add(Modelo(id_modelo=model_id, id_conjunto_datos=10, arquitectura=f"arch-{model_id}", epocas=1,
                          tasa_aprendizaje=0.001, tamano_lote=1, ruta_binario_gcp=f"models/{model_id}.pt",
                          hash_binario=digest))
        db.commit()
        create_initial_composition(db, job_id="job-a", dataset_id=10, partition_version="p1",
                                   components=[(1, .5), (2, .3), (3, .2)])
    yield factory
    engine.dispose()


def identity(split="val", **changes):
    from app.services.triad_evaluations import triad_ensemble_sha256
    values = dict(
        composition_id=1, composition_version=1, component_model_ids=[1, 2, 3],
        checkpoint_sha256s=list(HASHES), weights=[.5, .3, .2],
        schema_version=2, evaluator_version="recording-v1", dataset="AvesChilenas", split=split,
        manifest_sha256="d" * 64, classes=list(CLASSES), sample_count=2,
        predictor_config={"components": [{"architecture": "arch-1"}, {"architecture": "arch-2"},
                                         {"architecture": "arch-3"}]},
        preprocessing_config={"components": [{}, {}, {}]},
        aggregation_config={"unit": "recording"})
    values.update(changes)
    values.setdefault("checkpoint_sha256", triad_ensemble_sha256(
        values["checkpoint_sha256s"], values["weights"], values["classes"]))
    return values


def report(predicted=("b", "b")):
    from ml_core.classification_metrics import calculate_classification_report
    from app.services.recording_evaluator import REJECTION_LABEL
    return calculate_classification_report(["b", "a"], list(predicted), CLASSES, rejection_label=REJECTION_LABEL)


def service(db):
    from app.services.triad_evaluations import TriadEvaluationService
    return TriadEvaluationService(db)


def test_attempt_lifecycle_keeps_exact_composition_identity(sessions):
    with sessions() as db:
        attempts = service(db)
        created = attempts.create(identity())
        assert created["status"] == "pending" and created["report"] is None
        assert (created["composition_id"], created["composition_version"]) == (1, 1)
        assert created["component_model_ids"] == [1, 2, 3]
        assert created["checkpoint_sha256s"] == list(HASHES) and created["weights"] == [.5, .3, .2]
        # The ensemble digest covers every ordered checkpoint, not the first component's hash.
        assert created["checkpoint_sha256"] not in HASHES
        assert attempts.start(created["id"])["status"] == "running"
        done = attempts.complete(created["id"], report())
        assert done["status"] == "completed" and done["report"]["metrics"]["accuracy"] == .5
        assert done["finished_at"] is not None
        with pytest.raises(ValueError):
            attempts.start(created["id"])
    with sessions() as db:
        # Individual evaluation reports are untouched by composition attempts.
        assert db.query(ModelEvaluation).count() == 0


@pytest.mark.parametrize("changes", [
    {"weights": [.4, .4, .2]},
    {"composition_version": 2},
    {"component_model_ids": [2, 1, 3]},
    {"checkpoint_sha256s": ["e" * 64, HASHES[1], HASHES[2]]},
    {"dataset": "Motores"},
    {"checkpoint_sha256": HASHES[0]},
    {"composition_id": 99},
], ids=["weights", "version", "order", "checkpoint", "dataset", "first-hash", "missing"])
def test_identity_must_match_the_stored_composition(sessions, changes):
    with sessions() as db:
        with pytest.raises(ValueError):
            service(db).create(identity(**changes))
        assert service(db).latest_by_split([1]) == {}


def test_a_stored_later_version_does_not_inherit_reports(sessions):
    with sessions() as db:
        attempts = service(db)
        attempt = attempts.create(identity())
        attempts.start(attempt["id"])
        attempts.complete(attempt["id"], report())
        from app.models.triad_composition import TriadComposition
        first = db.get(TriadComposition, 1)
        # Versions above 1 exist only from before weights were fixed at training (ADR 0082).
        revised = TriadComposition(
            dataset_id=first.dataset_id, partition_version=first.partition_version, job_id=first.job_id,
            version=2, previous_id=first.id, first_model_id=first.first_model_id,
            second_model_id=first.second_model_id, third_model_id=first.third_model_id,
            first_weight=.2, second_weight=.3, third_weight=.5, created_at=first.created_at)
        db.add(revised)
        db.commit()
        assert attempts.latest_by_split([1, revised.id]) == {1: {"val": attempts.read(attempt["id"])}}
        with pytest.raises(ValueError):
            # The previous version's identity cannot be attached to the revision.
            attempts.create(identity(composition_id=revised.id))


def test_failure_is_saved_and_later_attempt_preserves_earlier_reports(sessions):
    with sessions() as db:
        attempts = service(db)
        val = attempts.create(identity("val"))
        attempts.start(val["id"])
        attempts.complete(val["id"], report())
        test = attempts.create(identity("test"))
        failed = attempts.fail(test["id"], "Checkpoint cambió durante inferencia")
        assert failed["status"] == "failed" and failed["report"] is None
        with pytest.raises(ValueError):
            attempts.fail(val["id"], "late failure")
        with pytest.raises(ValueError):
            attempts.fail(test["id"], " ")
        latest = attempts.latest_by_split([1])[1]
        assert latest["val"]["status"] == "completed" and latest["test"]["status"] == "failed"


def test_report_must_match_attempt_identity(sessions):
    with sessions() as db:
        attempts = service(db)
        attempt = attempts.create(identity(sample_count=3))
        attempts.start(attempt["id"])
        with pytest.raises(ValueError):
            attempts.complete(attempt["id"], report())
        assert attempts.read(attempt["id"])["status"] == "running"


# --- Joint computation over synthetic checkpoints and recordings -------------------------

@pytest.fixture
def triad(tmp_path, monkeypatch):
    """Three real trained checkpoints whose constant logits make each component's choice known."""
    import hashlib
    import numpy as np
    import soundfile as sf
    import torch
    from app.services.predictors import trained_predictor as module
    from app.services.predictors.trained_predictor import TrainedModelPredictor
    from app.services.predictors.triad_predictor import TriadPredictor
    from app.services.recording_evaluator import LabelledRecording

    class Neural(torch.nn.Module):
        def __init__(self, num_classes):
            super().__init__()
            self.logits = torch.nn.Parameter(torch.zeros(num_classes))

        def forward(self, inputs):
            return self.logits.unsqueeze(0)
    monkeypatch.setattr(module, "AudioCNN", Neural)
    t = np.arange(22050 * 5) / 22050

    def recording(name, label, split, silent=False):
        path = tmp_path / f"{name}.wav"
        sf.write(path, np.zeros_like(t) if silent else .5 * np.sin(2 * np.pi * 1000 * t), 22050)
        return LabelledRecording(name, label, path, f"raw/{name}.wav", "raw", f"group-{name}")

    def build(vectors, labels, weights, splits):
        engine = migrated_engine()
        factory = sessionmaker(bind=engine)
        paths = []
        with factory() as db:
            db.add(ConjuntoDatos(id_conjunto_datos=10, nombre="AvesChilenas", ruta_gcp="datasets/AvesChilenas"))
            for index, (vector, names) in enumerate(zip(vectors, labels), start=1):
                path = tmp_path / f"{index}.pt"
                torch.save({"architecture": "AudioCNN", "classes": names,
                            "state_dict": {"logits": torch.log(torch.tensor(vector))}}, path)
                paths.append(path)
                db.add(Modelo(id_modelo=index, id_conjunto_datos=10, arquitectura=f"arch-{index}", epocas=1,
                              tasa_aprendizaje=0.001, tamano_lote=1, ruta_binario_gcp=f"models/{index}.pt",
                              hash_binario=hashlib.sha256(path.read_bytes()).hexdigest()))
            db.commit()
            create_initial_composition(db, job_id="job-a", dataset_id=10, partition_version="p1",
                                       components=list(zip((1, 2, 3), weights)))
        components = [TrainedModelPredictor(path, model_id=str(index), lazy_load=True,
                                            expected_checkpoint_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
                      for index, path in enumerate(paths, start=1)]
        predictor = TriadPredictor(components, weights, ["a", "b"], "fama_triad_1")
        recordings = {split: tuple(recording(f"{split}-{i}", *spec) for i, spec in enumerate(specs))
                      for split, specs in splits.items()}
        return factory, predictor, paths, recordings
    return build


SPLITS = {"val": [("a", "val"), ("b", "val"), ("b", "val")], "test": [("b", "test"), ("a", "test")]}
CONFIGS = [({"architecture": f"arch-{i}"}, {"crop": "center"}, {"unit": "recording"}) for i in (1, 2, 3)]


def run(factory, predictor, paths, recordings):
    from app.services.triad_evaluations import evaluate_composition
    return evaluate_composition(factory, 1, predictor=predictor, checkpoint_paths=paths,
                                recordings=recordings, component_configs=CONFIGS)


def test_joint_accuracy_comes_from_the_weighted_vectors_not_averaged_accuracies(triad):
    weights = (.2, .2, .6)
    factory, predictor, paths, recordings = triad(
        [[.6, .4], [.6, .4], [.1, .9]], [["a", "b"]] * 3, weights, SPLITS)
    attempts = run(factory, predictor, paths, recordings)
    val = attempts["val"]
    assert val["status"] == "completed" and val["sample_count"] == 3
    # Fused vector .3/.7 picks "b" for every recording: 2 of 3 correct.
    assert val["report"]["metrics"]["accuracy"] == pytest.approx(2 / 3)
    individual = (1 / 3, 1 / 3, 2 / 3)
    assert val["report"]["metrics"]["accuracy"] != pytest.approx(sum(w * a for w, a in zip(weights, individual)))
    assert attempts["test"]["report"]["metrics"]["accuracy"] == pytest.approx(.5)
    assert val["weights"] == list(weights) and val["component_model_ids"] == [1, 2, 3]
    assert val["predictor_config"]["components"][2] == {"architecture": "arch-3"}
    with factory() as db:
        assert db.query(ModelEvaluation).count() == 0


def test_permuted_component_classes_and_zero_weight_keep_the_predictor_contract(triad):
    factory, predictor, paths, recordings = triad(
        [[.9, .1], [.9, .1], [.5, .5]], [["a", "b"], ["b", "a"], ["a", "b"]], (.4, .6, 0), SPLITS)
    # Component 2 reports "b" first, so aligned fusion is a=.42/b=.58 → "b" (2 of 3 correct);
    # positional fusion would give a=.9 → "a" (1 of 3).
    attempts = run(factory, predictor, paths, recordings)
    assert attempts["val"]["report"]["metrics"]["accuracy"] == pytest.approx(2 / 3)


def test_rejected_recordings_are_counted_as_rejections(triad):
    splits = {"val": [("a", "val", True), ("b", "val")], "test": [("b", "test"), ("a", "test")]}
    factory, predictor, paths, recordings = triad([[.1, .9]] * 3, [["a", "b"]] * 3, (.5, .3, .2), splits)
    report = run(factory, predictor, paths, recordings)["val"]["report"]
    assert report["rejection"]["count"] == 1 and report["metrics"]["accuracy"] == pytest.approx(.5)


def test_changed_checkpoint_is_refused_before_any_attempt(triad):
    factory, predictor, paths, recordings = triad([[.6, .4]] * 3, [["a", "b"]] * 3, (.5, .3, .2), SPLITS)
    paths[1].write_bytes(paths[1].read_bytes() + b"tampered")
    with pytest.raises(ValueError):
        run(factory, predictor, paths, recordings)
    with factory() as db:
        assert service(db).latest_by_split([1]) == {}


def test_mismatched_predictor_weights_are_refused(triad):
    from app.services.predictors.triad_predictor import TriadPredictor
    factory, predictor, paths, recordings = triad([[.6, .4]] * 3, [["a", "b"]] * 3, (.5, .3, .2), SPLITS)
    other = TriadPredictor(predictor.components, (.2, .3, .5), ["a", "b"], "fama_triad_1")
    with pytest.raises(ValueError):
        run(factory, other, paths, recordings)
    with factory() as db:
        assert service(db).latest_by_split([1]) == {}


def test_failure_during_inference_marks_attempts_failed_and_keeps_the_composition(triad):
    from app.models.triad_composition import TriadComposition
    factory, predictor, paths, recordings = triad([[.6, .4]] * 3, [["a", "b"]] * 3, (.5, .5, 0), SPLITS)

    class Breaking:
        """Corrupts the zero-weight checkpoint after admission, before the second split."""
        def __init__(self, inner):
            self.inner, self.classes, self.calls = inner, inner.classes, 0
            self.weights, self.components = inner.weights, inner.components

        def predict(self, path):
            self.calls += 1
            if self.calls == 4:
                paths[2].write_bytes(b"corrupted")
            return self.inner.predict(path)
    with pytest.raises(Exception):
        run(factory, Breaking(predictor), paths, recordings)
    with factory() as db:
        latest = service(db).latest_by_split([1])[1]
        assert latest["val"]["status"] == "completed"
        assert latest["test"]["status"] == "failed" and latest["test"]["error_reason"].strip()
        composition = db.get(TriadComposition, 1)
        assert (composition.version, composition.activo) == (1, False)
        assert [m.hash_binario is not None for m in db.query(Modelo).order_by(Modelo.id_modelo)] == [True] * 3
