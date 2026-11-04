"""Public synchronous preparation bridge with real owner identity and T1/T2."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.test_dataset_import_api import imports
from tests.test_imported_dataset_preparation import cohort
from app.models import web_session, access_quota, security_audit  # Register synthetic auth schema.


@pytest.fixture
def bridge(cohort, tmp_path, monkeypatch):
    from app.database import get_db
    from app.routes.imported_training import router, get_preparations
    from app.models.user import Usuario
    from app.services import auth
    from training.imported_dataset_preparation import ImportedDatasetPreparation
    from scripts.migrate_imported_training_source import migrate_imported_sources
    sessions = cohort[0].sessions
    migrate_imported_sources(sessions.kw['bind'], writers_stopped=True)
    monkeypatch.setattr(auth, 'SECRET_KEY', 'synthetic-preparation-signing-key-not-production-2026')
    with sessions() as db:
        for uid in (1, 2):
            db.add(Usuario(id=uid, email=f'owner{uid}@example.test', password_hash='unused',
                           nombre_completo='Synthetic', rol='investigador', activo=True))
        db.commit()
    preparations = ImportedDatasetPreparation(cohort[0], tmp_path / 'prepared-http')
    app = FastAPI()
    app.include_router(router)
    from app.routes.auth import router as auth_router
    app.include_router(auth_router)
    def database():
        with sessions() as db:
            yield db
    app.dependency_overrides[get_db] = database
    app.dependency_overrides[get_preparations] = lambda: preparations
    headers = lambda uid: {'Authorization': 'Bearer ' + auth.create_access_token({'sub': str(uid)})}
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client, headers, preparations


def test_completed_snapshot_members_preparation_roundtrip(bridge, cohort):
    client, headers, _ = bridge
    response = client.post('/api/training/imported/snapshots', headers=headers(1),
                           json={'dataset_id': cohort[5]})
    assert response.status_code == 201, response.text
    snapshot = response.json()
    assert snapshot['state'] == 'ready'
    assert 'owner_id' not in snapshot
    path = '/api/training/imported/snapshots/' + snapshot['id']
    assert client.get(path, headers=headers(1)).json() == snapshot
    members = client.get(path + '/members', headers=headers(1)).json()['members']
    assert len(members) == 6
    assert all(set(m) == {'member_id', 'class_name', 'original_path', 'size_bytes', 'sha256'} for m in members)
    mapping = [dict(member_id=m['member_id'], recording_id=m['original_path'],
                    group_id=m['original_path'].split('/')[-1]) for m in members]
    prepared = client.post(path + '/preparations', headers=headers(1), json={
        'mapping': mapping, 'provenance': {'source': 'synthetic annotations'},
        'seed': 42, 'profile': cohort[3]})
    assert prepared.status_code == 201, prepared.text
    manifest = prepared.json()
    assert manifest['state'] == 'ready'
    assert manifest['profile'] == cohort[3]
    assert manifest['warnings']
    assert manifest['class_to_index'] == {'ants': 0, 'zebra': 1}
    readback = client.get(path + '/preparations/' + manifest['version_id'], headers=headers(1))
    assert readback.json() == manifest


def test_auth_foreign_and_invalid_mapping_do_not_publish(bridge, cohort):
    client, headers, preparations = bridge
    path = '/api/training/imported/snapshots/' + cohort[1]['id']
    assert client.get(path + '/members').status_code == 401
    for suffix in ('', '/members', '/preparations/' + '0' * 64):
        foreign = client.get(path + suffix, headers=headers(2))
        missing = client.get('/api/training/imported/snapshots/' + '0' * 32 + suffix, headers=headers(2))
        assert foreign.status_code == missing.status_code == 404
        assert foreign.json() == missing.json()
    before = set(preparations.root.iterdir()) if preparations.root.exists() else set()
    response = client.post(path + '/preparations', headers=headers(1), json={
        'mapping': [], 'provenance': {'source': 'explicit'}, 'seed': 42, 'profile': cohort[3]})
    assert response.status_code == 422
    assert response.json()['detail']['code'] == 'invalid_mapping'
    for mapping, profile, code in ((cohort[2], {}, 'invalid_profile'),
            ([{**row, 'group_id':'one'} for row in cohort[2]], cohort[3], 'split_impossible')):
        response = client.post(path + '/preparations', headers=headers(1), json={
            'mapping':mapping, 'profile':profile, 'seed':42, 'provenance':{'source':'explicit'}})
        assert response.status_code == 422, response.text
        assert response.json()['detail']['code'] == code
    assert (set(preparations.root.iterdir()) if preparations.root.exists() else set()) == before
    assert client.post('/api/training/imported/snapshots', headers=headers(1),
        json={'dataset_id': cohort[5], 'owner_id': 2, 'root': '/untrusted'}).status_code == 422


@pytest.mark.parametrize('identity', ['inactive', 'negative', 'invalid'])
def test_non_real_or_inactive_principal_cannot_create_snapshot(bridge, cohort, identity):
    from app.models.user import Usuario
    client, headers, preparations = bridge
    with cohort[0].sessions() as db:
        if identity == 'inactive':
            db.get(Usuario, 1).activo = False
        elif identity == 'negative':
            db.add(Usuario(id=-1, email='negative@example.test', password_hash='unused',
                nombre_completo='Synthetic', rol='administrador', activo=True))
        db.commit()
    credential = headers(-1 if identity == 'negative' else 1)
    if identity == 'invalid':
        credential = {'Authorization': 'Bearer invalid'}
    before = set(preparations.snapshots.root.iterdir())
    response = client.post('/api/training/imported/snapshots', headers=credential, json={'dataset_id': cohort[5]})
    assert response.status_code == 401, response.text
    assert set(preparations.snapshots.root.iterdir()) == before


def test_oversized_json_is_rejected_before_snapshot_publication(bridge, cohort):
    client, headers, preparations = bridge
    before = set(preparations.snapshots.root.iterdir())
    response = client.post(
        '/api/training/imported/snapshots', headers={**headers(1), 'Content-Type': 'application/json'},
        content=b' ' * (8 * 1024 * 1024 + 1))
    assert response.status_code == 413, response.text
    assert set(preparations.snapshots.root.iterdir()) == before


def test_altered_snapshot_audio_never_reads_back_ready_preparation(bridge, cohort):
    client, headers, preparations = bridge
    from tests.test_imported_dataset_preparation import create
    manifest = create(preparations, cohort)
    member, _ = next(cohort[0].iter_verified(1, cohort[1]['id']))
    path = cohort[0].root / cohort[1]['id'] / member['member_id']
    path.chmod(0o600)  # Simulate privileged storage corruption of this private synthetic fixture.
    path.write_bytes(b'altered')
    response = client.get('/api/training/imported/snapshots/' + cohort[1]['id'] +
        '/preparations/' + manifest['version_id'], headers=headers(1))
    assert response.status_code == 404, response.text
    assert 'altered' not in response.text
    assert client.get('/api/training/imported/snapshots/' + cohort[1]['id'], headers=headers(1)).status_code == 404


def test_cookie_origin_and_conflicting_bearer_on_preparation_routes(bridge, cohort, monkeypatch):
    from app.models.user import Usuario
    from app.services.auth import hash_password
    client, headers, preparations = bridge
    monkeypatch.setenv('FAMA_WEB_ORIGIN', 'http://localhost:3000')
    monkeypatch.setenv('FAMA_ALLOW_INSECURE_LOOPBACK', '1')
    monkeypatch.setenv('FAMA_RATE_LIMIT_KEY', 'synthetic-rate-limit-key-for-isolated-tests-only')
    with cohort[0].sessions() as db:
        db.get(Usuario, 1).password_hash = hash_password('SyntheticPass123!')
        db.commit()
    assert client.post('/api/auth/web/login', headers={'Origin':'http://localhost:3000'}, json={'email':'owner1@example.test','password':'SyntheticPass123!'}).status_code == 200
    path='/api/training/imported/snapshots/' + cohort[1]['id'] + '/members'
    assert client.get(path).status_code == 200
    assert client.get(path, headers=headers(2)).status_code == 401
    assert client.get(path, headers={'Authorization':'Bearer invalid'}).status_code == 401
    assert client.get(path, headers=headers(1)).status_code == 200
    before=set(preparations.snapshots.root.iterdir())
    for origin in (None, 'https://foreign.example.test'):
        response=client.post('/api/training/imported/snapshots', headers={} if origin is None else {'Origin':origin}, json={'dataset_id':cohort[5]})
        assert response.status_code == 403, response.text
    assert set(preparations.snapshots.root.iterdir()) == before
    assert client.post('/api/training/imported/snapshots', headers={'Origin':'http://localhost:3000'},json={'dataset_id':cohort[5]}).status_code == 201


def test_malformed_snapshot_foreign_key_fails_before_write(bridge, cohort):
    from sqlalchemy import Table, Column, MetaData
    from app.models.training_snapshot import SnapshotMember
    client, headers, preparations=bridge
    engine=cohort[0].sessions.kw['bind']
    table=SnapshotMember.__table__
    table.drop(engine)
    malformed=Table(table.name,MetaData(),*[Column(c.name,c.type,primary_key=c.primary_key,nullable=c.nullable) for c in table.columns])
    malformed.create(engine)
    before=set(preparations.snapshots.root.iterdir())
    response=client.post('/api/training/imported/snapshots',headers=headers(1),json={'dataset_id':cohort[5]})
    assert response.status_code == 503, response.text
    assert set(preparations.snapshots.root.iterdir()) == before


def test_schema_missing_is_read_only_before_snapshot_creation(bridge, cohort):
    from app.models.imported_training_source import ImportedModelSource
    from sqlalchemy import event, inspect
    client, headers, preparations = bridge
    engine = cohort[0].sessions.kw['bind']
    ImportedModelSource.__table__.drop(engine)
    statements = []
    def record(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)
    event.listen(engine, 'before_cursor_execute', record)
    before = set(preparations.snapshots.root.iterdir())
    try:
        response = client.post('/api/training/imported/snapshots', headers=headers(1), json={'dataset_id': cohort[5]})
        assert response.status_code == 503, response.text
        assert response.json()['detail']['code'] == 'source_migration_required'
        assert not inspect(engine).has_table('imported_model_source')
        assert set(preparations.snapshots.root.iterdir()) == before
        assert not any(s.lstrip().upper().startswith(('CREATE ', 'INSERT ', 'UPDATE ', 'DELETE ', 'ALTER ')) for s in statements)
    finally:
        event.remove(engine, 'before_cursor_execute', record)
