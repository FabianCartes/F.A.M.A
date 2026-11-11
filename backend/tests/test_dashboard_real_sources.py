"""Dashboard cards backed by persisted records and bounded probes, never fixed values."""
from datetime import datetime, timezone, timedelta

import pytest

from app.models.dataset import ConjuntoDatos
from app.models.training import Modelo, ModelEvaluation
from app.models.triad_composition import TriadComposition
from app.services.dashboard import DashboardService
from tests.test_dashboard_truthful_stats import dashboard_environment  # noqa: F401

NOW = datetime(2026, 11, 11, tzinfo=timezone.utc)


def model(db, id_, dataset, arch, precision, sha="a"):
    db.add(Modelo(id_modelo=id_, id_conjunto_datos=dataset, arquitectura=arch, epocas=3,
                  tasa_aprendizaje=0.001, tamano_lote=4, precision=precision,
                  ruta_binario_gcp=f"models/m{id_}.pt", hash_binario=sha * 64, fecha_entrenamiento=NOW + timedelta(minutes=id_)))


def evaluation(db, model_id, accuracy, f1, *, split="test", sha="a", status="completed"):
    db.add(ModelEvaluation(id_modelo=model_id, schema_version=1, evaluator_version="v1", checkpoint_sha256=sha * 64,
                           dataset="d", split=split, manifest_sha256="b" * 64, classes=["x"], predictor_config={},
                           preprocessing_config={}, aggregation_config={}, sample_count=10,
                           report={"metrics": {"accuracy": accuracy, "f1_macro": f1}} if status == "completed" else None,
                           status=status, created_at=NOW,
                           started_at=NOW if status != "pending" else None,
                           finished_at=NOW if status == "completed" else None))


@pytest.fixture
def records(dashboard_environment):
    service, db = dashboard_environment
    db.add_all([ConjuntoDatos(id_conjunto_datos=1, nombre="AvesChilenas", ruta_gcp="gs://b/AvesChilenas/"),
                ConjuntoDatos(id_conjunto_datos=2, nombre="Motores", ruta_gcp="gs://b/Motores/")])
    model(db, 1, 1, "EfficientNet-B0", 70.0)
    model(db, 2, 1, "ResNet", 90.0, sha="c")
    model(db, 3, 1, "PANNs", 60.0)
    model(db, 4, 2, "ResNet", 55.5)
    model(db, 5, 2, "ImportedTriad", 99.0)
    db.flush()
    evaluation(db, 1, 0.8831, 0.8868)            # Held-out test evaluation of the current weights.
    evaluation(db, 2, 0.95, 0.94, sha="z")       # Evaluated other weights: not admitted.
    evaluation(db, 3, 0.99, 0.99, split="val")   # Validation split is not the held-out result.
    db.commit()
    return service, db


def test_best_model_per_dataset_prefers_held_out_evaluation_of_current_weights(records):
    service, db = records
    best = service.get_stats(db=db)["best_models"]

    assert [item["dataset_name"] for item in best] == ["AvesChilenas", "Motores"]
    birds, engines = best
    assert (birds["model_id"], birds["architecture"], birds["source"]) == (1, "EfficientNet-B0", "test_evaluation")
    assert (birds["accuracy"], birds["macro_f1"]) == (88.31, 88.68)
    assert (engines["model_id"], engines["accuracy"], engines["macro_f1"], engines["source"]) == (
        4, 55.5, None, "training_validation")
    assert "domain_champions" not in service.get_stats(db=db)


def test_best_models_respect_dataset_access(records):
    service, db = records

    class OnlyEngines:
        def query(self, entity):
            query = db.query(entity)
            column = {Modelo: Modelo.id_conjunto_datos, ConjuntoDatos: ConjuntoDatos.id_conjunto_datos,
                      TriadComposition: TriadComposition.dataset_id}.get(entity)
            return query.filter(column == 2) if column is not None else query.filter(False)

    best = service.get_stats(db=db, access=OnlyEngines())["best_models"]
    assert [item["dataset_name"] for item in best] == ["Motores"]


def test_super_ensemble_reports_the_default_or_latest_triad_with_members(records, monkeypatch):
    service, db = records
    common = dict(dataset_id=1, job_id="job", first_model_id=1, second_model_id=2, third_model_id=3,
                  first_weight=0.55, second_weight=0.30, third_weight=0.15)
    db.add_all([TriadComposition(id=7, version=1, created_at=NOW, activo=True, **common),
                TriadComposition(id=8, version=2, previous_id=7, created_at=NOW + timedelta(hours=1), **common)])
    db.commit()
    from app.services import registry
    monkeypatch.setattr(registry, "_global_model_registry", type("R", (), {"has_model": lambda self, key: key == "fama_triad_7"})())

    ensemble = service.get_stats(db=db)["super_ensemble"]

    assert ensemble["composition_id"] == 7  # The default triad wins over a newer revision.
    assert (ensemble["dataset_name"], ensemble["version"], ensemble["default"]) == ("AvesChilenas", 1, True)
    assert ensemble["ready"] is True
    assert ensemble["active_mode"] == "triad"
    assert [(m["name"], m["weight"], m["accuracy"]) for m in ensemble["models"]] == [
        ("EfficientNet-B0", 0.55, 70.0), ("ResNet", 0.30, 90.0), ("PANNs", 0.15, 60.0)]


def test_super_ensemble_without_triads_or_registry_is_not_invented(records, monkeypatch):
    service, db = records
    from app.services import registry
    monkeypatch.setattr(registry, "_global_model_registry", None)
    ensemble = service.get_stats(db=db)["super_ensemble"]
    assert ensemble == {"ready": None, "active_mode": "none", "composition_id": None, "dataset_name": None,
                        "version": None, "default": False, "models": []}


@pytest.mark.parametrize("probe,expected", [
    ({"ok": True, "code": "storage_read_connected"}, "connected"),
    ({"ok": False, "code": "storage_forbidden"}, "unavailable"),
    ({"ok": False, "code": "storage_configuration_missing"}, "unknown"),
])
def test_storage_health_comes_from_a_cached_bounded_probe(dashboard_environment, probe, expected):
    _, db = dashboard_environment
    calls = []
    clock = [0.0]
    service = DashboardService(storage_probe=lambda: calls.append(1) or probe, clock=lambda: clock[0])

    assert service.get_stats(db=db)["system_health"]["storage"] == expected
    assert service.get_stats(db=db)["system_health"]["storage"] == expected
    assert len(calls) == 1  # Dashboard polls every 15 s; the probe is cached.
    clock[0] = 61.0
    service.get_stats(db=db)
    assert len(calls) == 2


def test_failing_storage_probe_is_reported_unavailable(dashboard_environment):
    _, db = dashboard_environment
    def broken():
        raise RuntimeError("private credential detail")
    stats = DashboardService(storage_probe=broken).get_stats(db=db)
    assert stats["system_health"]["storage"] == "unavailable"
