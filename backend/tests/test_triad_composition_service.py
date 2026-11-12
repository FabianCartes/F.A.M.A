"""Composition creation and weight revision through the public service functions."""
import pytest
from sqlalchemy.orm import sessionmaker

from app.models.dataset import ConjuntoDatos
from app.models.training import Modelo
from app.models.triad_composition import TriadComposition
from app.models.user import Usuario
from app.services import triad_compositions as service
from app.services.triad_compositions import (
    TriadCompositionError, create_initial_composition,
    parse_triad_key,
)
from tests.schema_support import migrated_engine

HASH = "a" * 64


@pytest.fixture
def sessions():
    engine = migrated_engine()
    with engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
    factory = sessionmaker(bind=engine)
    with factory() as db:
        db.add(Usuario(id=2, email="investigador@example.test", password_hash="x",
                       nombre_completo="investigador", rol="investigador", activo=True))
        db.add_all([ConjuntoDatos(id_conjunto_datos=10, nombre="AvesChilenas", ruta_gcp="datasets/AvesChilenas"),
                    ConjuntoDatos(id_conjunto_datos=20, nombre="engine_diagnostics", ruta_gcp="datasets/engine_diagnostics")])
        for model_id, dataset_id, digest in ((1, 10, HASH), (2, 10, HASH), (3, 10, HASH),
                                             (4, 10, None), (5, 20, HASH)):
            db.add(Modelo(id_modelo=model_id, id_conjunto_datos=dataset_id, arquitectura="fixture", epocas=1,
                          tasa_aprendizaje=0.001, tamano_lote=1, ruta_binario_gcp=f"models/{model_id}.pt",
                          hash_binario=digest))
        db.commit()
    yield factory
    engine.dispose()


def initial(db, weights=(0.5, 0.3, 0.2), ids=(1, 2, 3), job_id="job-a", dataset_id=10):
    return create_initial_composition(db, job_id=job_id, dataset_id=dataset_id, partition_version="p1",
                                      components=list(zip(ids, weights)), author_id=None)


def rows(sessions):
    with sessions() as db:
        return [(r.id, r.job_id, r.version, r.previous_id, (r.first_weight, r.second_weight, r.third_weight))
                for r in db.query(TriadComposition).order_by(TriadComposition.id)]


def test_initial_composition_is_idempotent_per_job(sessions):
    with sessions() as db:
        first = initial(db)
        again = initial(db)
        assert again.id == first.id
        assert (first.version, first.previous_id, first.partition_version, first.dataset_id) == (1, None, "p1", 10)
        assert service.component_ids(first) == (1, 2, 3) and service.component_weights(first) == (0.5, 0.3, 0.2)
    assert len(rows(sessions)) == 1


@pytest.mark.parametrize("ids, dataset_id", [((1, 2, 4), 10), ((1, 2, 5), 10), ((1, 2, 99), 10), ((1, 2, 2), 10)],
                         ids=["no-hash", "other-dataset", "unknown-model", "repeated-model"])
def test_inadmissible_components_create_nothing(sessions, ids, dataset_id):
    with sessions() as db, pytest.raises(TriadCompositionError):
        initial(db, ids=ids, dataset_id=dataset_id)
    assert rows(sessions) == []


def test_ordinals_number_training_jobs_within_each_dataset(sessions):
    with sessions() as db:
        first = initial(db, job_id="job-a")
        second = initial(db, job_id="job-b", weights=(0.2, 0.3, 0.5))
        # A later stored version of job-a and another dataset's job keep their own numbering.
        db.add_all([
            TriadComposition(dataset_id=10, partition_version="p1", job_id="job-a", version=2, previous_id=first.id,
                             first_model_id=1, second_model_id=2, third_model_id=3, first_weight=.1,
                             second_weight=.1, third_weight=.8, created_at=first.created_at),
            TriadComposition(dataset_id=20, partition_version="p1", job_id="job-c", version=1,
                             first_model_id=1, second_model_id=2, third_model_id=3, first_weight=.1,
                             second_weight=.1, third_weight=.8, created_at=first.created_at),
        ])
        db.commit()
        assert service.triad_ordinals(db) == {first.id: 1, second.id: 2, 3: 1, 4: 1}


def test_display_name_identifies_dataset_ordinal_and_architectures():
    assert service.triad_display_name("Aves Chilenas", 2, ["EfficientNet-B0", "ConvNeXt-Nano", "ResNet-34d"]) == (
        "Aves Chilenas · Tríada 2 — EfficientNet-B0 + ConvNeXt-Nano + ResNet-34d")


@pytest.mark.parametrize("key, expected", [("fama_triad_7", 7), ("fama_triad_0", None), ("fama_triad_07", None),
                                           ("fama_triad_-1", None), ("fama_triad_x", None),
                                           ("fama_triad_99999999999", None), ("fama_trained_model_7", None),
                                           ("", None), (None, None)])
def test_catalogue_key_parsing_is_exact(key, expected):
    assert parse_triad_key(key) == expected
