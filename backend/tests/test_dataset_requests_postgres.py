"""Concurrent requests/decisions through HTTP against ephemeral PostgreSQL."""
from concurrent.futures import ThreadPoolExecutor
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.database import get_db
from app.models.dataset import ConjuntoDatos
from app.models.user import Usuario
from app.routes.auth import router as auth_router
from app.routes.access import router as access_router, catalogue_router
from app.routes.security import router as security_router
from app.services.auth import hash_password
from app.schema import upgrade_schema
from tests.test_schema_migrations import database_url
from tests.test_web_sessions import login, ORIGIN, PASSWORD
from tests.http_security import configure_access_limits


def test_concurrent_duplicate_requests_and_decisions_create_one_grant_and_one_decision(database_url, monkeypatch):
    configure_access_limits(monkeypatch)
    monkeypatch.setenv('FAMA_WEB_ORIGIN', ORIGIN)
    assert upgrade_schema(database_url).code == 'schema_current'
    engine = create_engine(database_url)
    sessions = sessionmaker(bind=engine)
    with sessions() as db:
        for identifier, role in ((1, 'administrador'), (2, 'investigador')):
            db.add(Usuario(id=identifier, email=f'{role}@example.test', nombre_completo=role,
                           password_hash=hash_password(PASSWORD), rol=role, activo=True))
        db.add(ConjuntoDatos(id_conjunto_datos=10, nombre='Aves', ruta_gcp='datasets/Aves/'))
        db.commit()
    app = FastAPI()
    for router in (auth_router, access_router, catalogue_router, security_router):
        app.include_router(router)

    def database():
        with sessions() as db:
            yield db
    app.dependency_overrides[get_db] = database
    try:
        with TestClient(app, base_url=ORIGIN) as researcher, TestClient(app, base_url=ORIGIN) as admin:
            assert login(researcher).status_code == 200
            assert login(admin, 'administrador').status_code == 200

            def post(path, cookies, body=None):
                with TestClient(app, base_url=ORIGIN, cookies=cookies) as other:
                    response = other.post(path, json=body, headers={'Origin': ORIGIN})
                    return response.status_code, response.json()

            with ThreadPoolExecutor(max_workers=2) as workers:
                pending = list(workers.map(lambda _: post('/api/datasets/10/requests', researcher.cookies), range(2)))
                assert [code for code, _ in pending] == [200, 200]
                approved = list(workers.map(lambda _: post('/api/access/requests/2/10/decision', admin.cookies,
                                                            {'decision': 'approve'}), range(2)))
                assert [code for code, _ in approved] == [200, 200]
            assert admin.get('/api/access/requests?state=all').json()['total'] == 1
            assert admin.get('/api/access/users/2/datasets/10').json()['assigned'] is True
            events = admin.get('/api/security/audit').json()['events']
            actions = [item['action'] for item in events]
            assert actions.count('dataset.requested') == 1
            assert actions.count('dataset.request_approved') == 1
            assert actions.count('assignment.granted') == 1
    finally:
        engine.dispose()
