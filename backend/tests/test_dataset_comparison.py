"""Local versus GCS content comparison through the public HTTP interface.

Two levels: the inventory carries an automatic count + size check (no hashing),
and ``POST .../compare`` verifies the provider checksum of every common file.
"""
import base64
import hashlib
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import main
from app.database import get_db
from app.models.dataset import ConjuntoDatos
from app.services.ingestion import IngestionService
from tests.http_security import administrator_http
from tests.test_ingestion_upload_integrity import upload_environment  # noqa: F401  (fixture)

DATASET = "AvesChilenas"
KEY = "Chucao/audio.wav"


class FakeBlob(SimpleNamespace):
    pass


class FakeClient:
    """Lists the bucket objects with provider size and MD5, as GCS does."""

    def __init__(self, objects, without_checksum):
        self.objects, self.without_checksum = objects, without_checksum

    def list_blobs(self, bucket, prefix):
        return [FakeBlob(name=name, size=len(content), updated=None,
                         md5_hash=None if name in self.without_checksum else
                         base64.b64encode(hashlib.md5(content, usedforsecurity=False).digest()).decode(),
                         crc32c=None)
                for name, content in sorted(self.objects.items()) if name.startswith(prefix)]


class Scenario:
    def __init__(self, service, db, objects, client, without_checksum):
        self.service, self.db, self.objects, self.client = service, db, objects, client
        self.without_checksum = without_checksum
        self.dataset = ConjuntoDatos(nombre=DATASET, ruta_gcp=f"gs://test-bucket/datasets/{DATASET}/",
                                     estado="subido", tamano_total_bytes=0, cantidad_audios=0)
        db.add(self.dataset)
        db.commit()

    def cloud(self, key, content, checksum=True):
        self.objects[f"datasets/{DATASET}/{key}"] = content
        if not checksum:
            self.without_checksum.add(f"datasets/{DATASET}/{key}")

    def local(self, key, content):
        path = self.service.local_base_dir / DATASET / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    def verify(self, name=DATASET):
        return self.client.post(f"/api/ingestion/datasets/{name}/compare")

    def inventory_row(self):
        response = self.client.get("/api/ingestion/datasets")
        assert response.status_code == 200, response.text
        return next(item for item in response.json()["datasets"] if item["name"] == DATASET)


@pytest.fixture
def scenario(upload_environment, monkeypatch):  # noqa: F811
    service, db, objects = upload_environment
    without_checksum = set()
    monkeypatch.setattr(service, "_get_client", lambda: FakeClient(objects, without_checksum))
    monkeypatch.setattr(main, "ingestion_service", service)
    isolated = FastAPI()
    for route in main.app.routes:
        if getattr(route, "path", "").startswith("/api/ingestion/"):
            isolated.add_api_route(route.path, route.endpoint, methods=list(route.methods))
    isolated.dependency_overrides[get_db] = lambda: db
    with administrator_http(isolated), TestClient(isolated) as client:
        yield Scenario(service, db, objects, client, without_checksum)


def counts(body):
    return (body["matching"], body["missing_local"], body["only_local"],
            body["size_mismatch"], body["checksum_mismatch"], body["unverified"])


# --- explicit verification: provider checksum of every common file ---------------------------

def test_identical_content_is_verified_against_the_provider_checksum(scenario):
    scenario.cloud(KEY, b"RIFF-same-bytes")
    scenario.local(KEY, b"RIFF-same-bytes")

    response = scenario.verify()

    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["status"], body["level"]) == ("match", "checksum")
    assert (body["local_count"], body["gcs_count"]) == (1, 1)
    assert counts(body) == (1, 0, 0, 0, 0, 0)


def test_cloud_audio_absent_locally_is_reported_as_missing_local(scenario):
    scenario.cloud(KEY, b"one")
    scenario.cloud("Chucao/other.wav", b"two")
    scenario.local(KEY, b"one")

    body = scenario.verify().json()

    assert body["status"] == "differences"
    assert (body["local_count"], body["gcs_count"]) == (1, 2)
    assert counts(body) == (1, 1, 0, 0, 0, 0)


def test_local_audio_absent_from_cloud_is_reported_as_only_local(scenario):
    scenario.cloud(KEY, b"one")
    scenario.local(KEY, b"one")
    scenario.local("Chucao/extra.wav", b"extra")

    body = scenario.verify().json()

    assert body["status"] == "differences"
    assert counts(body) == (1, 0, 1, 0, 0, 0)


def test_different_size_is_a_size_mismatch_without_hashing(scenario, monkeypatch):
    scenario.cloud(KEY, b"cloud-longer-content")
    scenario.local(KEY, b"short")
    monkeypatch.setattr(IngestionService, "_matches_remote_content",
                        staticmethod(lambda path, blob: pytest.fail("size mismatch must not be hashed")))

    body = scenario.verify().json()

    assert body["status"] == "differences"
    assert counts(body) == (0, 0, 0, 1, 0, 0)


def test_same_size_with_different_md5_is_a_checksum_mismatch(scenario):
    scenario.cloud(KEY, b"AAAA")
    scenario.local(KEY, b"BBBB")

    body = scenario.verify().json()

    assert body["status"] == "differences"
    assert counts(body) == (0, 0, 0, 0, 1, 0)


def test_object_without_provider_checksum_is_unverified_not_different(scenario):
    scenario.cloud(KEY, b"AAAA", checksum=False)
    scenario.local(KEY, b"AAAA")

    body = scenario.verify().json()

    assert body["status"] == "match"
    assert counts(body) == (0, 0, 0, 0, 0, 1)


def test_dataset_without_cloud_audio_is_rejected_like_a_download(scenario):
    scenario.local(KEY, b"one")

    assert scenario.verify().status_code == 409


# --- automatic check carried by the inventory: count + size, never hashing --------------------

def test_inventory_row_matches_on_count_and_size_without_reading_file_content(scenario, monkeypatch):
    scenario.cloud(KEY, b"RIFF-same-bytes")
    scenario.local(KEY, b"RIFF-same-bytes")
    monkeypatch.setattr(IngestionService, "_matches_remote_content",
                        staticmethod(lambda path, blob: pytest.fail("the automatic check must not hash")))

    check = scenario.inventory_row()["content_check"]

    assert (check["status"], check["level"]) == ("match", "count_size")
    assert (check["local_count"], check["gcs_count"]) == (1, 1)
    assert counts(check) == (1, 0, 0, 0, 0, 0)


def test_inventory_row_reports_missing_only_local_and_size_differences(scenario):
    scenario.cloud(KEY, b"cloud-longer-content")
    scenario.cloud("Chucao/missing.wav", b"gone")
    scenario.local(KEY, b"short")
    scenario.local("Chucao/extra.wav", b"extra")

    check = scenario.inventory_row()["content_check"]

    assert check["status"] == "differences"
    assert counts(check) == (0, 1, 1, 1, 0, 0)


def test_inventory_row_keeps_its_existing_fields(scenario):
    scenario.cloud(KEY, b"one")
    scenario.local(KEY, b"one")

    row = scenario.inventory_row()

    assert (row["source"], row["gcs_file_count"], row["local_file_count"], row["file_count"]) == ("gcs", 1, 1, 1)
    assert row["sync_state"] == "comparison_pending"


def test_cloud_only_inventory_row_has_no_content_check(scenario):
    scenario.cloud(KEY, b"one")

    assert scenario.inventory_row().get("content_check") is None
