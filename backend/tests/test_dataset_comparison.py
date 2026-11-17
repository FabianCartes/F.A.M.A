"""Local versus GCS content comparison through the public HTTP interface."""
import hashlib

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import main
from app.database import get_db
from app.models.dataset import Audio, ConjuntoDatos
from tests.http_security import administrator_http
from tests.test_ingestion_upload_integrity import upload_environment  # noqa: F401  (fixture)

DATASET = "AvesChilenas"
KEY = "Chucao/audio.wav"


def sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


class Scenario:
    def __init__(self, service, db, objects, client):
        self.service, self.db, self.objects, self.client = service, db, objects, client
        self.dataset = ConjuntoDatos(nombre=DATASET, ruta_gcp=f"gs://test-bucket/datasets/{DATASET}/",
                                     estado="subido", tamano_total_bytes=0, cantidad_audios=0)
        db.add(self.dataset)
        db.flush()

    def cloud(self, key, content):
        self.objects[f"datasets/{DATASET}/{key}"] = content

    def local(self, key, content):
        path = self.service.local_base_dir / DATASET / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    def register(self, key, content, fingerprint="auto"):
        clase, name = key.split("/")
        self.db.add(Audio(id_conjunto_datos=self.dataset.id_conjunto_datos, nombre_archivo=name,
                          ruta_gcp=f"{self.dataset.ruta_gcp}{key}", clase=clase, tamano_bytes=len(content),
                          hash_archivo=sha(content) if fingerprint == "auto" else fingerprint))
        self.db.commit()

    def compare(self, name=DATASET):
        return self.client.post(f"/api/ingestion/datasets/{name}/compare")


@pytest.fixture
def scenario(upload_environment, monkeypatch):  # noqa: F811
    service, db, objects = upload_environment
    monkeypatch.setattr(main, "ingestion_service", service)
    isolated = FastAPI()
    for route in main.app.routes:
        if getattr(route, "path", "").startswith("/api/ingestion/"):
            isolated.add_api_route(route.path, route.endpoint, methods=list(route.methods))
    isolated.dependency_overrides[get_db] = lambda: db
    with administrator_http(isolated), TestClient(isolated) as client:
        yield Scenario(service, db, objects, client)


def test_identical_content_matches_on_count_size_and_registered_fingerprints(scenario):
    content = b"RIFF-same-bytes"
    scenario.cloud(KEY, content)
    scenario.local(KEY, content)
    scenario.register(KEY, content)

    response = scenario.compare()

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "match"
    assert (body["local_count"], body["gcs_count"]) == (1, 1)
    assert (body["missing_local"], body["missing_gcs"], body["size_mismatch"],
            body["hash_mismatch"], body["hash_unverified"], body["hash_verified"]) == (0, 0, 0, 0, 0, 1)


def test_cloud_audio_absent_locally_is_reported_as_missing_local(scenario):
    scenario.cloud(KEY, b"one")
    scenario.cloud("Chucao/other.wav", b"two")
    scenario.local(KEY, b"one")
    scenario.register(KEY, b"one")

    body = scenario.compare().json()

    assert body["status"] == "differences"
    assert (body["local_count"], body["gcs_count"], body["missing_local"]) == (1, 2, 1)


def test_local_audio_absent_from_cloud_is_reported_as_missing_gcs(scenario):
    scenario.cloud(KEY, b"one")
    scenario.local(KEY, b"one")
    scenario.local("Chucao/extra.wav", b"extra")

    body = scenario.compare().json()

    assert body["status"] == "differences"
    assert body["missing_gcs"] == 1 and body["missing_local"] == 0


def test_different_size_is_reported_and_not_hashed_as_a_fingerprint_difference(scenario):
    scenario.cloud(KEY, b"cloud-longer-content")
    scenario.local(KEY, b"short")
    scenario.register(KEY, b"cloud-longer-content")

    body = scenario.compare().json()

    assert body["status"] == "differences"
    assert body["size_mismatch"] == 1 and body["hash_mismatch"] == 0


def test_same_size_with_different_registered_fingerprint_is_a_hash_mismatch(scenario):
    scenario.cloud(KEY, b"AAAA")
    scenario.local(KEY, b"BBBB")
    scenario.register(KEY, b"AAAA")

    body = scenario.compare().json()

    assert body["status"] == "differences"
    assert body["hash_mismatch"] == 1 and body["size_mismatch"] == 0 and body["hash_verified"] == 0


def test_null_registered_fingerprint_is_unverified_not_a_mismatch(scenario):
    scenario.cloud(KEY, b"AAAA")
    scenario.local(KEY, b"BBBB")
    scenario.register(KEY, b"AAAA", fingerprint=None)

    body = scenario.compare().json()

    assert body["status"] == "match"
    assert body["hash_unverified"] == 1 and body["hash_mismatch"] == 0 and body["hash_verified"] == 0


def test_dataset_without_cloud_audio_is_rejected_like_a_download(scenario):
    scenario.local(KEY, b"one")

    response = scenario.compare()

    assert response.status_code == 409
