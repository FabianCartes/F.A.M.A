"""Checkpoint backup/recovery through authenticated HTTP and a fake external GCS SDK."""
import hashlib
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from google.api_core.exceptions import NotFound, PreconditionFailed

from app import main
from app.models.dataset import ConjuntoDatos
from app.models.dataset_access import AsignacionDataset
from app.models.training import Modelo
from app.services import training
from tests.test_web_sessions import web, login, ORIGIN


class Cloud:
    def __init__(self):
        self.objects = {}
        self.failure = None
        self.corrupt_download = False

    def bucket(self, name):
        return self

    def blob(self, name, **kwargs):
        return Blob(self, name)

    def get_blob(self, name, **kwargs):
        if self.failure:
            raise self.failure
        return Blob(self, name) if name in self.objects else None


class Blob:
    def __init__(self, cloud, name):
        self.cloud, self.name = cloud, name
        self.generation = 17
        self.size = len(cloud.objects.get(name, b""))
        self.content_encoding = None

    def upload_from_filename(self, filename, *, if_generation_match, **kwargs):
        if self.cloud.failure:
            raise self.cloud.failure
        assert if_generation_match == 0  # Fake enforces GCS create-only semantics.
        if self.name in self.cloud.objects:
            raise PreconditionFailed("already exists")
        self.cloud.objects[self.name] = Path(filename).read_bytes()
        self.size = len(self.cloud.objects[self.name])

    def download_to_filename(self, filename, *, if_generation_match, **kwargs):
        if self.cloud.failure:
            raise self.cloud.failure
        assert if_generation_match == self.generation
        if self.name not in self.cloud.objects:
            raise NotFound("missing")
        data = self.cloud.objects[self.name]
        Path(filename).write_bytes(b"broken" if self.cloud.corrupt_download else data)


@pytest.fixture
def checkpoint_http(web, tmp_path, monkeypatch):
    client, sessions = web
    if hasattr(main, "checkpoint_router"):
        client.app.include_router(main.checkpoint_router)
    for route in main.app.routes:
        if getattr(route, 'path', '') == '/api/training/history':
            client.app.add_api_route(route.path, route.endpoint, methods=list(route.methods), dependencies=route.dependencies)
    root = tmp_path / "checkpoints"
    root.mkdir()
    monkeypatch.setattr(main, "training_service", training.TrainingService(root))
    from app.configuration import get_configuration, activate_configuration
    previous_configuration = get_configuration()
    activate_configuration(replace(previous_configuration, bucket_name="fixture"))
    from google.cloud import storage
    cloud = Cloud()
    monkeypatch.setattr(storage, "Client", lambda: cloud)
    content = b"registered checkpoint bytes\x00" * 500
    filename = "fama_sample_best.pt"
    (root / filename).write_bytes(content)
    with sessions() as db:
        db.add(ConjuntoDatos(id_conjunto_datos=10, nombre="Sample", ruta_gcp="gs://fixture/datasets/Sample/"))
        db.add(AsignacionDataset(id_usuario=2, id_conjunto_datos=10))
        db.add(Modelo(id_modelo=3, id_conjunto_datos=10, id_usuario=2, arquitectura="AudioCNN", epocas=1,
                      tasa_aprendizaje=0.001, tamano_lote=2, ruta_binario_gcp=f"models/{filename}",
                      hash_binario=hashlib.sha256(content).hexdigest(), tamano_bytes=len(content), activo=False))
        db.commit()
    assert login(client).status_code == 200
    try:
        yield SimpleNamespace(client=client, sessions=sessions, root=root, file=root / filename,
                              content=content, cloud=cloud)
    finally:
        activate_configuration(previous_configuration)


BASE = "/api/training/models/3/checkpoint"


def test_assigned_researcher_backs_up_and_recovers_exact_registered_weights(checkpoint_http):
    f = checkpoint_http
    initial = f.client.get(BASE)
    assert initial.status_code == 200, initial.text
    assert initial.json()["local"] == "valid"
    assert initial.json()["cloud"] == "missing"

    backed = f.client.post(BASE + "/backup", headers={"Origin": ORIGIN})
    assert backed.status_code == 200
    assert backed.json()["cloud"] == "available"
    assert backed.json()["transfer_verified"] is True
    f.file.unlink()  # Temporary test artifact, simulates loss of this node's copy.
    assert f.client.get(BASE).json()["local"] == "missing"

    restored = f.client.post(BASE + "/restore", headers={"Origin": ORIGIN})
    assert restored.status_code == 200, restored.text
    assert restored.json()["local"] == "valid"
    assert restored.json()["transfer_verified"] is True
    assert f.file.read_bytes() == f.content
    assert f.client.get('/api/training/history').json()['history'][0]['active'] is False


def test_retries_preserve_cloud_and_existing_local_checkpoint(checkpoint_http):
    f = checkpoint_http
    for _ in range(2):
        assert f.client.post(BASE + '/backup', headers={'Origin': ORIGIN}).status_code == 200
    assert len(f.cloud.objects) == 1
    unchanged = f.file.stat().st_mtime_ns
    assert f.client.post(BASE + '/restore', headers={'Origin': ORIGIN}).status_code == 200
    assert f.file.stat().st_mtime_ns == unchanged


@pytest.mark.parametrize('action', ['backup', 'restore'])
def test_conflicting_local_file_is_never_replaced(checkpoint_http, action):
    f = checkpoint_http
    assert f.client.post(BASE + '/backup', headers={'Origin': ORIGIN}).status_code == 200
    f.file.write_bytes(b'preserve this different checkpoint')
    assert f.client.get(BASE).json()['local'] == 'conflict'
    assert f.client.post(BASE + '/' + action, headers={'Origin': ORIGIN}).status_code == 409
    assert f.file.read_bytes() == b'preserve this different checkpoint'


def test_cloud_bytes_are_checked_even_when_name_and_size_match(checkpoint_http):
    f = checkpoint_http
    assert f.client.post(BASE + '/backup', headers={'Origin': ORIGIN}).status_code == 200
    key = next(iter(f.cloud.objects))
    f.cloud.objects[key] = b'X' * len(f.content)
    assert f.client.get(BASE).json()['cloud'] == 'available'  # Status is metadata, not a downloaded hash.
    f.file.unlink()
    assert f.client.post(BASE + '/restore', headers={'Origin': ORIGIN}).status_code == 409
    assert not f.file.exists()
    assert not list(f.root.glob('.checkpoint-*'))


def test_failed_backup_verification_is_not_reported_as_success(checkpoint_http):
    f = checkpoint_http
    f.cloud.corrupt_download = True
    assert f.client.post(BASE + '/backup', headers={'Origin': ORIGIN}).status_code == 409
    assert f.file.read_bytes() == f.content
    assert not list(f.root.glob('.checkpoint-*'))


def test_unavailable_cloud_is_sanitized_and_allows_a_retry(checkpoint_http):
    f = checkpoint_http
    f.cloud.failure = RuntimeError('private SQL or credential detail')
    for action in ('', '/backup', '/restore'):
        response = f.client.get(BASE) if not action else f.client.post(BASE + action, headers={'Origin': ORIGIN})
        assert response.status_code == 503
        assert 'private' not in response.text
    f.cloud.failure = None
    assert f.client.post(BASE + '/backup', headers={'Origin': ORIGIN}).status_code == 200


def test_revoked_or_anonymous_identity_cannot_access_copies(checkpoint_http):
    f = checkpoint_http
    f.client.cookies.clear()
    assert f.client.get(BASE).status_code == 401
    assert login(f.client).status_code == 200
    with f.sessions() as db:
        db.query(AsignacionDataset).delete()
        db.commit()
    for action in ('', '/backup', '/restore'):
        response = f.client.get(BASE) if not action else f.client.post(BASE + action, headers={'Origin': ORIGIN})
        assert response.status_code == 404
    assert not f.cloud.objects


def test_foreign_origin_cannot_publish_or_restore(checkpoint_http):
    f = checkpoint_http
    for action in ('/backup', '/restore'):
        assert f.client.post(BASE + action, headers={'Origin': 'https://evil.example.test'}).status_code == 403
    assert not f.cloud.objects


@pytest.mark.parametrize('field,value', [
    ('hash_binario', None), ('tamano_bytes', 0),
    ('ruta_binario_gcp', 'models/../../outside.pt'), ('ruta_binario_gcp', 'gs://other/models/weights.pt'),
])
def test_unverifiable_or_escaping_identity_requires_operator_review(checkpoint_http, field, value):
    f = checkpoint_http
    with f.sessions() as db:
        setattr(db.get(Modelo, 3), field, value)
        db.commit()
    assert f.client.post(BASE + '/backup', headers={'Origin': ORIGIN}).status_code == 409
    assert not f.cloud.objects


def test_other_bucket_dataset_cannot_reuse_the_current_bucket(checkpoint_http):
    f = checkpoint_http
    with f.sessions() as db:
        db.get(ConjuntoDatos, 10).ruta_gcp = 'gs://official/datasets/Sample/'
        db.commit()
    assert f.client.get(BASE).status_code == 409
    assert not f.cloud.objects


def test_missing_remote_copy_does_not_create_a_local_checkpoint(checkpoint_http):
    f = checkpoint_http
    f.file.unlink()
    assert f.client.post(BASE + '/restore', headers={'Origin': ORIGIN}).status_code == 409
    assert not f.file.exists()
    assert not list(f.root.glob('.checkpoint-*'))


def test_existing_directory_at_checkpoint_path_is_preserved(checkpoint_http):
    f = checkpoint_http
    f.file.unlink()
    f.file.mkdir()
    assert f.client.post(BASE + '/restore', headers={'Origin': ORIGIN}).status_code == 409
    assert f.file.is_dir()
