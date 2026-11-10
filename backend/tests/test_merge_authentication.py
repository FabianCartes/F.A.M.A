"""Joined access through actual HTTP sessions; no remote services."""
import pytest
from tests.test_web_sessions import web, login, ORIGIN

def test_zip_uses_revocable_cookie_and_checks_mutation_origin(web, tmp_path):
    from app.routes.dataset_imports import router, get_import_service
    from app.services.dataset_imports import DatasetImports
    from app.services.dataset_zip import ImportLimits
    client, sessions = web
    client.app.include_router(router)
    client.app.dependency_overrides[get_import_service] = lambda: DatasetImports(tmp_path/"imports", limits=ImportLimits(free_bytes=1))
    base = "/api/ingestion/imports"
    assert client.get(base+"/limits").status_code == 401
    assert login(client).status_code == 200
    assert client.get(base+"/access").json()["authenticated"] is True
    assert client.get(base+"/limits").status_code == 200
    rejected = client.post(base, headers={"Origin":"https://foreign.test"}, json={"request_key":"external", "name":"Private"})
    assert rejected.status_code == 403
    created = client.post(base, headers={"Origin": ORIGIN}, json={"request_key":"owned", "name":"Private"})
    assert created.status_code == 200, created.text
    assert client.post("/api/auth/logout", headers={"Origin": ORIGIN}).status_code == 204
    assert client.get(base+"/limits").status_code == 401


def test_unsupported_zip_platform_stays_explicit_without_loading_posix_services():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.routes.import_capability import zip_router
    app = FastAPI()
    app.include_router(zip_router(supported=False))
    client = TestClient(app)
    status = client.get("/api/ingestion/imports/access")
    assert status.status_code == 200
    assert status.json()["available"] is False
    assert client.post("/api/ingestion/imports").status_code == 503
