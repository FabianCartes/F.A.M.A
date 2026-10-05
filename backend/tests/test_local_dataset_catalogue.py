"""Verified dataset associations through the HTTP catalogue and public registry."""
import pytest
from sqlalchemy.orm import Session

from app.models.dataset import ConjuntoDatos
from tests.test_api_model_catalogue import catalogue


def test_catalogue_exposes_persisted_canonical_local_dataset(catalogue, tmp_path):
    client, registry, persist, _ = catalogue
    dataset_dir = tmp_path / "data" / "raw" / "AvesChilenas"
    dataset_dir.mkdir(parents=True)
    persist(dataset=ConjuntoDatos(nombre="AvesChilenas", ruta_gcp=dataset_dir.as_uri()))

    response = client.get("/api/models")
    assert response.status_code == 200
    assert response.json()["publication_errors"] == []
    assert response.json()["models"][1]["dataset_name"] == "AvesChilenas"
    assert registry.get("11").dataset_name == "AvesChilenas"
    assert registry.get_default_model_id() == "selected"


def test_catalogue_rejects_dataset_symlink_escaping_raw_root(catalogue, tmp_path):
    client, registry, persist, _ = catalogue
    raw_root = tmp_path / "data" / "raw"
    raw_root.mkdir(parents=True)
    external = tmp_path / "external"
    external.mkdir()
    dataset_dir = raw_root / "AvesChilenas"
    dataset_dir.symlink_to(external, target_is_directory=True)
    persist(dataset=ConjuntoDatos(nombre="AvesChilenas", ruta_gcp=dataset_dir.as_uri()))

    response = client.get("/api/models")
    assert response.status_code == 200
    assert response.json()["publication_errors"] == []
    assert response.json()["models"][1]["dataset_name"] is None
    assert registry.get("11").metadata.dataset_name is None


@pytest.mark.parametrize("invalid", [
    "external", "mismatched_name", "traversal", "encoded_traversal",
    "encoded_separator", "double_encoded_traversal", "foreign_authority",
    "localhost_authority", "single_slash", "relative_uri", "query", "fragment",
    "leading_space", "control", "absolute_path", "missing_directory",
    "regular_file", "broken_symlink", "symlink_loop", "invalid_name",
])
def test_catalogue_keeps_unverified_local_associations_null(catalogue, tmp_path, invalid):
    client, registry, persist, _ = catalogue
    raw_root = tmp_path / "data" / "raw"
    dataset_dir = raw_root / "AvesChilenas"
    raw_root.mkdir(parents=True)
    external = tmp_path / "external" / "AvesChilenas"
    external.mkdir(parents=True)
    name = "AvesChilenas"
    uri = dataset_dir.as_uri()
    routes = {
        "external": external.as_uri(),
        "mismatched_name": (raw_root / "OtherDataset").as_uri(),
        "traversal": raw_root.as_uri() + "/../raw/AvesChilenas",
        "encoded_traversal": raw_root.as_uri() + "/%2e%2e/raw/AvesChilenas",
        "encoded_separator": raw_root.as_uri() + "%2fAvesChilenas",
        "double_encoded_traversal": raw_root.as_uri() + "/%252e%252e/raw/AvesChilenas",
        "foreign_authority": "file://foreign-host" + dataset_dir.as_posix(),
        "localhost_authority": "file://localhost" + dataset_dir.as_posix(),
        "single_slash": "file:" + dataset_dir.as_posix(),
        "relative_uri": "file://data/raw/AvesChilenas",
        "query": uri + "?source=local",
        "fragment": uri + "#local",
        "leading_space": " " + uri,
        "control": uri + "\n",
        "absolute_path": str(dataset_dir),
    }
    if invalid == "regular_file":
        dataset_dir.write_text("not a directory")
    elif invalid == "broken_symlink":
        dataset_dir.symlink_to(tmp_path / "absent", target_is_directory=True)
    elif invalid == "symlink_loop":
        dataset_dir.symlink_to(dataset_dir, target_is_directory=True)
    elif invalid != "missing_directory":
        dataset_dir.mkdir()
    if invalid == "mismatched_name":
        (raw_root / "OtherDataset").mkdir()
    if invalid == "invalid_name":
        name = "../AvesChilenas"
    persist(dataset=ConjuntoDatos(nombre=name, ruta_gcp=routes.get(invalid, uri)))

    response = client.get("/api/models")
    assert response.status_code == 200
    assert response.json()["publication_errors"] == []
    assert response.json()["models"][1]["dataset_name"] is None
    assert registry.get("11").metadata.dataset_name is None
    assert registry.get_default_model_id() == "selected"


@pytest.mark.parametrize("route_kind,expected", [
    ("local", "AvesChilenas"), ("local_trailing_slash", "AvesChilenas"),
    ("gcs_relative", "AvesChilenas"), ("gcs_relative_trailing", "AvesChilenas"),
    ("gcs_bucket", "AvesChilenas"), ("gcs_bucket_trailing", "AvesChilenas"),
    ("foreign_bucket", None), ("gcs_mismatched", None), ("no_relation", None),
])
@pytest.mark.parametrize("entrypoint", ["publish", "register"])
def test_public_registry_verifies_dataset_for_both_registration_paths(
    catalogue, tmp_path, route_kind, expected, entrypoint,
):
    from app.services import storage

    client, registry, persist, engine = catalogue
    dataset_dir = tmp_path / "data" / "raw" / "AvesChilenas"
    dataset_dir.mkdir(parents=True)
    routes = {
        "local": dataset_dir.as_uri(),
        "local_trailing_slash": dataset_dir.as_uri() + "/",
        "gcs_relative": "datasets/AvesChilenas",
        "gcs_relative_trailing": "datasets/AvesChilenas/",
        "gcs_bucket": f"gs://{storage.DEFAULT_BUCKET_NAME}/datasets/AvesChilenas",
        "gcs_bucket_trailing": f"gs://{storage.DEFAULT_BUCKET_NAME}/datasets/AvesChilenas/",
        "foreign_bucket": "gs://foreign-bucket/datasets/AvesChilenas",
        "gcs_mismatched": "datasets/OtherDataset",
    }
    dataset = (None if route_kind == "no_relation" else
               ConjuntoDatos(nombre="AvesChilenas", ruta_gcp=routes[route_kind]))
    checkpoint = persist(dataset=dataset, active=False)
    if entrypoint == "publish":
        response = client.get("/api/models")
        assert response.status_code == 200
        assert response.json()["publication_errors"] == []
    else:
        with Session(engine) as db:
            registry.register_from_db(db, checkpoints_root=checkpoint.parent)
    assert registry.get("11").dataset_name == expected
    assert registry.list_models()[1].dataset_name == expected
    assert registry.get_default_model_id() == "selected"
