"""Administrative assignment inventory through HTTP and an isolated database."""
import pytest

from app.models.dataset import ConjuntoDatos
from app.routes.access import router
from tests.test_web_sessions import web, login, ORIGIN


@pytest.fixture
def catalogue(web):
    client, sessions = web
    client.app.include_router(router)
    with sessions() as db:
        db.add_all([
            ConjuntoDatos(id_conjunto_datos=10, nombre="AvesChilenas", ruta_gcp="datasets/AvesChilenas"),
            ConjuntoDatos(id_conjunto_datos=20, nombre="Otro dominio", ruta_gcp="datasets/Otro dominio"),
        ])
        db.commit()
    return client


def test_assignment_inventory_uses_registered_ids_and_current_grants(catalogue):
    client = catalogue
    path = "/api/access/users/2/datasets"
    assert client.get(path).status_code == 401
    assert login(client).status_code == 200
    assert client.get(path).status_code == 403
    assert login(client, "administrador").status_code == 200
    page = client.get(path + "?limit=1").json()
    assert page == {"user_id": 2, "datasets": [{"dataset_id": 10, "name": "AvesChilenas", "assigned": False}],
                    "total": 2, "limit": 1, "offset": 0}
    assert client.put(path + "/10", headers={"Origin": ORIGIN}).status_code == 200
    assert client.get(path).json()["datasets"][0]["assigned"] is True
    assert client.delete(path + "/10", headers={"Origin": ORIGIN}).status_code == 204
    assert client.get(path).json()["datasets"][0]["assigned"] is False
    assert client.get(path + "?limit=1&offset=1").json()["datasets"] == [
        {"dataset_id": 20, "name": "Otro dominio", "assigned": False}]
    assert client.get(path).headers["cache-control"] == "no-store"
    assert client.get(path, headers={"Origin": "https://other.example.test"}).status_code == 403


@pytest.mark.parametrize("suffix,status", [("/999/datasets", 404), ("/2/datasets?limit=101", 422),
                                                   ("/2/datasets?offset=-1", 422)])
def test_assignment_inventory_rejects_unknown_users_and_invalid_pages(catalogue, suffix, status):
    assert login(catalogue, "administrador").status_code == 200
    assert catalogue.get("/api/access/users" + suffix).status_code == status
