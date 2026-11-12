"""Joint evaluation attempts of a standard triad composition, through the public service."""
import pytest
from sqlalchemy.orm import sessionmaker

from app.models.dataset import ConjuntoDatos
from app.models.training import ModelEvaluation, Modelo
from app.services.triad_compositions import create_initial_composition, revise_weights
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


def test_weight_revision_does_not_inherit_reports(sessions):
    with sessions() as db:
        attempts = service(db)
        attempt = attempts.create(identity())
        attempts.start(attempt["id"])
        attempts.complete(attempt["id"], report())
        from app.models.triad_composition import TriadComposition
        revised = revise_weights(db, db.get(TriadComposition, 1), [.2, .3, .5], None)
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
