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

    def list_blobs(self, bucket, *, prefix="", **kwargs):
        if self.failure:
            raise self.failure
        self.listings = getattr(self, "listings", 0) + 1
        return [Blob(self, name) for name in self.objects if name.startswith(prefix)]


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


SYNC = BASE + '/sync'
STATUS = '/api/training/models/checkpoints/sync-status'


def sync(client):
    return client.post(SYNC, headers={'Origin': ORIGIN})


def test_sync_uploads_a_missing_cloud_copy_after_verifying_it(checkpoint_http):
    f = checkpoint_http
    response = sync(f.client)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body['action'] == 'uploaded'
    assert (body['local'], body['cloud'], body['transfer_verified']) == ('valid', 'available', True)
    assert list(f.cloud.objects.values()) == [f.content]


def test_sync_restores_a_missing_local_copy(checkpoint_http):
    f = checkpoint_http
    assert sync(f.client).status_code == 200
    f.file.unlink()  # Temporary test artifact, simulates loss of this node's copy.
    response = sync(f.client)
    assert response.status_code == 200, response.text
    assert response.json()['action'] == 'restored'
    assert response.json()['local'] == 'valid'
    assert f.file.read_bytes() == f.content


def test_sync_reports_already_synced_copies_without_writing(checkpoint_http):
    f = checkpoint_http
    assert sync(f.client).status_code == 200
    unchanged = f.file.stat().st_mtime_ns
    response = sync(f.client)
    assert response.status_code == 200
    assert response.json()['action'] == 'already_synced'
    assert response.json()['transfer_verified'] is True
    assert f.file.stat().st_mtime_ns == unchanged
    assert len(f.cloud.objects) == 1


def test_sync_checks_cloud_bytes_of_an_apparently_synced_copy(checkpoint_http):
    f = checkpoint_http
    assert sync(f.client).status_code == 200
    key = next(iter(f.cloud.objects))
    f.cloud.objects[key] = b'X' * len(f.content)
    response = sync(f.client)
    assert response.status_code == 409
    assert 'SHA-256' in response.json()['detail']
    assert f.file.read_bytes() == f.content


def test_sync_without_any_copy_fails_with_its_reason(checkpoint_http):
    f = checkpoint_http
    f.file.unlink()
    response = sync(f.client)
    assert response.status_code == 409
    assert response.json()['detail'] == 'No hay copia local ni respaldo en GCS de este checkpoint; no se puede sincronizar.'
    assert not f.file.exists() and not f.cloud.objects


def test_sync_never_replaces_a_conflicting_local_file(checkpoint_http):
    f = checkpoint_http
    f.file.write_bytes(b'preserve this different checkpoint')
    response = sync(f.client)
    assert response.status_code == 409
    assert 'conflicto' in response.json()['detail']
    assert f.file.read_bytes() == b'preserve this different checkpoint'
    assert not f.cloud.objects


def test_sync_reports_a_conflicting_cloud_object(checkpoint_http):
    f = checkpoint_http
    f.cloud.objects['models/checkpoints/sha256/' + hashlib.sha256(f.content).hexdigest() + '.pt'] = b'short'
    response = sync(f.client)
    assert response.status_code == 409
    assert 'GCS' in response.json()['detail']
    assert f.cloud.objects and f.file.read_bytes() == f.content


def test_sync_is_sanitized_when_cloud_is_unavailable_and_requires_origin(checkpoint_http):
    f = checkpoint_http
    assert f.client.post(SYNC, headers={'Origin': 'https://evil.example.test'}).status_code == 403
    f.cloud.failure = RuntimeError('private SQL or credential detail')
    response = sync(f.client)
    assert response.status_code == 503
    assert 'private' not in response.text


def test_sync_status_lists_synced_state_with_one_cloud_listing(checkpoint_http):
    f = checkpoint_http
    with f.sessions() as db:
        db.add(Modelo(id_modelo=4, id_conjunto_datos=10, id_usuario=2, arquitectura="AudioCNN", epocas=1,
                      tasa_aprendizaje=0.001, tamano_lote=2, ruta_binario_gcp="models/other.pt",
                      hash_binario='a' * 64, tamano_bytes=5, activo=False))
        db.commit()
    before = f.client.get(STATUS)
    assert before.status_code == 200, before.text
    assert before.json() == {'models': [{'model_id': 3, 'synced': False}, {'model_id': 4, 'synced': False}]}
    assert sync(f.client).status_code == 200
    f.cloud.listings = 0
    after = f.client.get(STATUS).json()['models']
    assert after == [{'model_id': 3, 'synced': True}, {'model_id': 4, 'synced': False}]
    assert f.cloud.listings == 1
    f.file.write_bytes(b'short')  # Size mismatch: not synced, no hashing in the batch check.
    assert f.client.get(STATUS).json()['models'][0]['synced'] is False


def test_sync_status_only_lists_accessible_models_and_sanitizes_failures(checkpoint_http):
    f = checkpoint_http
    f.cloud.failure = RuntimeError('private SQL or credential detail')
    failed = f.client.get(STATUS)
    assert failed.status_code == 503 and 'private' not in failed.text
    f.cloud.failure = None
    with f.sessions() as db:
        db.query(AsignacionDataset).delete()
        db.commit()
    assert f.client.get(STATUS).json() == {'models': []}
    f.client.cookies.clear()
    assert f.client.get(STATUS).status_code == 401
